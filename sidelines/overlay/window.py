import ctypes
import ctypes.util
import os
import sys
import tempfile
import threading
import tkinter as tk

from intelligence.gemini import GeminiClient
from intelligence.key_frames import KeyFrameSelector
from intelligence.tts import TTSClient
from intelligence.video_compiler import compile_to_video

# ---------------------------------------------------------------------------
# macOS: make borderless windows accept keyboard input
# ---------------------------------------------------------------------------
_FOCUS_IMP_REF = None  # prevent garbage collection of ctypes callback


def _patch_tk_window_focus():
    """Override canBecomeKeyWindow on Tk's NSWindow subclass so borderless
    windows can receive keyboard events on macOS."""
    global _FOCUS_IMP_REF
    if sys.platform != "darwin":
        return
    try:
        libobjc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        libobjc.objc_getClass.argtypes = [ctypes.c_char_p]
        libobjc.objc_getClass.restype = ctypes.c_void_p
        libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
        libobjc.sel_registerName.restype = ctypes.c_void_p
        libobjc.class_replaceMethod.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
        ]
        libobjc.class_replaceMethod.restype = ctypes.c_void_p

        BOOL_IMP = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @BOOL_IMP
        def _yes(self, _cmd):
            return True

        _FOCUS_IMP_REF = _yes
        sel = libobjc.sel_registerName(b"canBecomeKeyWindow")

        for name in (b"TKWindow", b"NSWindow"):
            cls = libobjc.objc_getClass(name)
            if cls:
                libobjc.class_replaceMethod(cls, sel, _yes, b"B@:")
                print(f"[sidelines] Patched {name.decode()}.canBecomeKeyWindow")
                break
    except Exception as exc:
        print(f"[sidelines] canBecomeKeyWindow patch failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Windows: set always-on-top via Win32 API (more reliable than tkinter alone)
# ---------------------------------------------------------------------------
def _configure_windows_overlay(hwnd):
    """Push the window to topmost and remove it from the taskbar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes.wintypes

        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        ctypes.windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )

        # Remove taskbar button: set WS_EX_TOOLWINDOW, clear WS_EX_APPWINDOW
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW  = 0x00040000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

        print("[sidelines] Windows overlay configured: topmost + no taskbar")
    except Exception as exc:
        print(f"[sidelines] Windows overlay config warning: {exc}", file=sys.stderr)


class SidelinesOverlay:
    def __init__(self, frame_buffer, analyzer):
        self.frame_buffer = frame_buffer
        self.analyzer = analyzer
        self.last_response = ""
        self.native_window_id = None  # CGWindowID (mac) or HWND (win)

        self.key_frame_selector = KeyFrameSelector()
        self.gemini = GeminiClient()
        self.tts = TTSClient()

        # Theme colors
        self.bg = "#1e1e1e"
        self.input_bg = "#2d2d2d"
        self.text_color = "#e0e0e0"
        self.muted = "#9e9e9e"
        self.accent = "#8ab4f8"
        self.border = "#3c3c3c"

        # Tell Windows we handle DPI ourselves — must happen before Tk init
        if sys.platform == "win32":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()   # fallback
                except Exception:
                    pass

        self.root = tk.Tk()
        _patch_tk_window_focus()  # must run after Tk registers TKWindow
        self._build_window()

        # Resolve native window ID after the window is mapped
        self.root.after(500, self._resolve_and_register_window)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg=self.bg)

        width, height = 380, 560
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = screen_w - width - 20
        y = (screen_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # --- Title bar (top) ---
        header = tk.Frame(self.root, bg=self.bg, height=36)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header, text="Sidelines", font=("Helvetica", 13, "bold"),
            bg=self.bg, fg=self.text_color,
        ).pack(side=tk.LEFT, padx=12)

        close_btn = tk.Label(
            header, text="\u2715", font=("Helvetica", 13),
            bg=self.bg, fg=self.muted, cursor="hand2",
        )
        close_btn.pack(side=tk.RIGHT, padx=10)
        close_btn.bind("<Button-1>", lambda e: self._quit())

        header.bind("<ButtonPress-1>", self._start_drag)
        header.bind("<B1-Motion>", self._on_drag)

        # --- Input bar (bottom) — packed BEFORE response so it's never clipped ---
        input_container = tk.Frame(self.root, bg=self.input_bg, padx=12, pady=10)
        input_container.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(0, 12))

        # --- Separator (above input) ---
        tk.Frame(self.root, bg=self.border, height=1).pack(side=tk.BOTTOM, fill=tk.X, padx=16)

        # --- Response area (fills remaining space) ---
        response_frame = tk.Frame(self.root, bg=self.bg)
        response_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=16, pady=(4, 8))

        self.response_text = tk.Text(
            response_frame, wrap=tk.WORD, font=("Helvetica", 13),
            bg=self.bg, fg=self.text_color, relief=tk.FLAT,
            insertbackground=self.text_color,
            borderwidth=0, highlightthickness=0,
            padx=0, pady=4,
        )
        self.response_text.pack(fill=tk.BOTH, expand=True)
        self.response_text.insert("1.0", "Ask me anything about the game.")
        self.response_text.config(state=tk.DISABLED)

        self.input_field = tk.Entry(
            input_container, font=("Helvetica", 13),
            bg=self.input_bg, fg=self.text_color,
            insertbackground=self.text_color,
            relief=tk.FLAT, borderwidth=0,
        )
        self.input_field.pack(fill=tk.X, ipady=4)
        self.input_field.insert(0, "Ask anything")
        self.input_field.bind("<FocusIn>", self._clear_placeholder)
        self.input_field.bind("<FocusOut>", self._restore_placeholder)
        self.input_field.bind("<Return>", self._on_submit)
        self.input_field.bind("<Button-1>", self._focus_input)
        self.input_field.config(fg=self.muted)

        icons_row = tk.Frame(input_container, bg=self.input_bg)
        icons_row.pack(fill=tk.X, pady=(6, 0))

        self.speaker_btn = tk.Label(
            icons_row, text="\U0001F50A", font=("Helvetica", 14),
            bg=self.input_bg, fg=self.muted, cursor="hand2",
        )
        self.speaker_btn.pack(side=tk.LEFT)
        self.speaker_btn.bind("<Button-1>", self._on_speak)

        send_btn = tk.Label(
            icons_row, text="\u2191", font=("Helvetica", 16, "bold"),
            bg=self.accent, fg="#1e1e1e", cursor="hand2",
            padx=6, pady=1,
        )
        send_btn.pack(side=tk.RIGHT)
        send_btn.bind("<Button-1>", self._on_submit)

    # ------------------------------------------------------------------
    # Drag
    # ------------------------------------------------------------------

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------

    def _clear_placeholder(self, event):
        if self.input_field.get() == "Ask anything":
            self.input_field.delete(0, tk.END)
            self.input_field.config(fg=self.text_color)

    def _restore_placeholder(self, event):
        if not self.input_field.get().strip():
            self.input_field.insert(0, "Ask anything")
            self.input_field.config(fg=self.muted)

    def _set_response(self, text):
        self.response_text.config(state=tk.NORMAL)
        self.response_text.delete("1.0", tk.END)
        self.response_text.insert("1.0", text)
        self.response_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Submit / AI pipeline
    # ------------------------------------------------------------------

    def _on_submit(self, event):
        question = self.input_field.get().strip()
        if not question or question == "Ask anything":
            return
        self.input_field.delete(0, tk.END)
        self._set_response("Thinking...")
        threading.Thread(
            target=self._process_question, args=(question,), daemon=True
        ).start()

    def _process_question(self, question):
        video_path = None
        try:
            all_frames = self.frame_buffer.get_all_frames()
            key_frames = self.key_frame_selector.select(all_frames)

            if not key_frames:
                self.root.after(
                    0, self._set_response,
                    "No frames captured yet. Make sure screen recording permission is enabled.",
                )
                return

            # Compile key frames to a short video clip
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.close()
            video_path = tmp.name

            success = compile_to_video(key_frames, video_path)
            if not success:
                self.root.after(0, self._set_response, "Couldn't compile video clip. Try again.")
                return

            # Deduplicated OCR history for game context
            ocr_texts = [f.get("ocr_text", "") for f in all_frames if f.get("ocr_text")]
            seen, ocr_lines = set(), []
            for t in ocr_texts[-10:]:
                if t not in seen:
                    seen.add(t)
                    ocr_lines.append(t)
            ocr_history = "\n".join(ocr_lines)

            response = self.gemini.ask(video_path, question, ocr_history)
            self.last_response = response
            self.root.after(0, self._set_response, response)

        except Exception as e:
            self.root.after(0, self._set_response, f"Error: {e}")
        finally:
            if video_path:
                try:
                    os.unlink(video_path)
                except OSError:
                    pass

    def _on_speak(self, event):
        if self.last_response:
            threading.Thread(
                target=self.tts.speak, args=(self.last_response,), daemon=True
            ).start()

    def _focus_input(self, event):
        self.root.focus_force()
        self.input_field.focus_set()
        if sys.platform == "darwin":
            try:
                from AppKit import NSApp
                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # macOS overlay configuration
    # ------------------------------------------------------------------

    def _configure_macos_overlay(self):
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSApp, NSApplication
            NSApplication.sharedApplication()

            target = None
            for ns_win in NSApp.windows():
                if ns_win.windowNumber() == self.native_window_id:
                    target = ns_win
                    break

            if target is None:
                ns_windows = NSApp.windows()
                if not ns_windows:
                    self.root.after(200, self._configure_macos_overlay)
                    return
                target = ns_windows[0]

            target.setLevel_(1000)                 # above fullscreen apps
            target.setCollectionBehavior_(1 | 16 | 256)  # all spaces + fullscreen
            target.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            print("[sidelines] macOS overlay configured: fullscreen + keyboard focus")
        except Exception as exc:
            print(f"[sidelines] macOS overlay config warning: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Window ID resolution — platform-specific
    # ------------------------------------------------------------------

    def _resolve_and_register_window(self):
        if sys.platform == "darwin":
            self._resolve_macos()
        else:
            self._resolve_windows()

    def _resolve_macos(self):
        """Find this process's CGWindowID and register it with the frame buffer."""
        from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID

        pid = os.getpid()
        windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
        if windows:
            for w in windows:
                if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowNumber", 0) > 0:
                    self.native_window_id = w["kCGWindowNumber"]
                    self.frame_buffer.set_exclude_window(self.native_window_id)
                    print(f"[sidelines] Overlay CGWindowID: {self.native_window_id}")
                    self._configure_macos_overlay()
                    return
        self.root.after(200, self._resolve_macos)

    def _resolve_windows(self):
        """Find the HWND for this tkinter window and register it with the frame buffer."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()

            # Verify it belongs to our process
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != os.getpid():
                # Not our window yet — fall back to winfo_id which tkinter exposes
                hwnd = self.root.winfo_id()

            self.native_window_id = hwnd
            self.frame_buffer.set_exclude_window(hwnd)
            print(f"[sidelines] Overlay HWND: {hwnd:#010x}")
            _configure_windows_overlay(hwnd)
        except Exception as exc:
            print(f"[sidelines] HWND resolution warning: {exc}", file=sys.stderr)
            # Non-fatal — capture just won't black out the overlay region

    # ------------------------------------------------------------------

    def _quit(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()