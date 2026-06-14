import ctypes
import ctypes.util
import io
import os
import sys
import tempfile
import threading
import time
import tkinter as tk
import wave

from PIL import Image, ImageTk

from overlay import icons
from intelligence.gemini import GeminiClient
from intelligence.key_frames import KeyFrameSelector
from intelligence.stt import STTClient
from intelligence.video_compiler import compile_to_video

# ---------------------------------------------------------------------------
# macOS: make borderless windows accept keyboard input
# ---------------------------------------------------------------------------
_FOCUS_IMP_REF = None  # prevent garbage collection of ctypes callback


def _patch_tk_window_focus():
    """Override canBecomeKeyWindow and canBecomeMainWindow on Tk's NSWindow
    subclass so borderless windows can receive keyboard events on macOS."""
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

        for name in (b"TKWindow", b"NSWindow"):
            cls = libobjc.objc_getClass(name)
            if cls:
                for sel_name in (b"canBecomeKeyWindow", b"canBecomeMainWindow"):
                    sel = libobjc.sel_registerName(sel_name)
                    libobjc.class_replaceMethod(cls, sel, _yes, b"B@:")
                print(f"[sidelines] Patched {name.decode()}.canBecomeKeyWindow + canBecomeMainWindow")
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
        self.stt = STTClient()

        # Mic recording state
        self._mic_press_time = 0
        self._mic_timer = None
        self._recording = False
        self._audio_chunks = []
        self._audio_stream = None
        self._pyaudio_instance = None
        self._listening_anim_id = None
        self._mic_pulse_id = None

        # Pre-generate audio cue WAVs
        self._tone_start = icons.generate_tone(freq=880, duration_ms=80, volume=0.25)
        self._tone_stop = icons.generate_tone(freq=660, duration_ms=80, volume=0.25)

        # Theme colors — glassmorphism (Tailwind zinc palette)
        self.bg = "#18181b"          # zinc-900 panel (~88% opacity via -alpha)
        self.input_bg = "#0a0a0b"    # zinc-950 nested input surface
        self.tab_bg = "#18181b"      # zinc-900 left collapse tab
        self.text_color = "#FFFFFF"  # primary text / icons
        self.response_color = "#FFFFFF"  # assistant message text
        self.muted = "#a1a1aa"       # zinc-400 placeholder
        self.border = "#3a3a3f"      # ~10% white hairline on dark
        self.divider = "#2e2e32"     # subtle section separators

        self._imgs = {}              # keep PhotoImage refs alive
        self._collapsed = False
        self._animating = False

        # Helvetica Neue Thin (style 35). On macOS tkinter resolves
        # "Helvetica Neue Thin" / "HelveticaNeue-Thin" to the correct face.
        if sys.platform == "darwin":
            self.ui_font = "Helvetica Neue Thin"
        elif sys.platform == "win32":
            self.ui_font = "Segoe UI Light"
        else:
            self.ui_font = "Helvetica"

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

        # On macOS, make the window appear on all Spaces immediately.
        # This must happen early — before the user might switch Spaces.
        if sys.platform == "darwin":
            self.root.after(50, self._apply_macos_overlay_behavior)

        # Resolve native window ID after the window is mapped
        self.root.after(500, self._resolve_and_register_window)

        # Pump the OpenCV debug window from the main thread (required on macOS)
        self.root.after(3000, self._pump_debug_window)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    # window/content geometry constants
    WIDTH = 360       # mockup: w-[360px]
    HEIGHT = 480      # mockup: aspect-[3/4] -> 360 * 4/3
    PAD = 20          # outer gutter (p-5) between content and window edge
    STRIP = 24        # width of the collapsed strip (just the tab)
    SLIDE_MS = 280    # collapse / expand duration
    SLIDE_STEP = 16   # animation frame interval (~60fps)

    def _build_window(self):
        # Same on both platforms: borderless + topmost + translucent.
        # On macOS, canBecomeKeyWindow/canBecomeMainWindow patches
        # (applied above) allow keyboard input in borderless windows.
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.88)
        self.root.configure(bg=self.bg)

        width, height = self.WIDTH, self.HEIGHT
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = screen_w - width - 20
        y = (screen_h - height) // 2
        self._expanded_geometry = (width, height, x, y)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # --- Icon images (kept on self._imgs so they aren't GC'd) ---
        white = (255, 255, 255, 255)
        self._imgs["logo"] = ImageTk.PhotoImage(icons.brand_logo(22, color=white))
        self._imgs["mic"] = ImageTk.PhotoImage(icons.mic(20, color=white))
        self._imgs["mic_dim"] = ImageTk.PhotoImage(icons.mic(20, color=(161, 161, 170, 255)))  # zinc-400 pressed
        self._imgs["mic_red"] = ImageTk.PhotoImage(icons.mic(20, color=(255, 80, 80, 255)))
        self._imgs["mic_red_dim"] = ImageTk.PhotoImage(icons.mic(20, color=(180, 50, 50, 255)))  # pulse dim
        self._imgs["send"] = ImageTk.PhotoImage(icons.send(20, color=white))
        self._imgs["chev_left"] = ImageTk.PhotoImage(
            icons.chevron(16, "left", color=white))
        self._imgs["chev_right"] = ImageTk.PhotoImage(
            icons.chevron(16, "right", color=white))

        # --- Content holder (everything but the left tab) ---
        self.content = tk.Frame(self.root, bg=self.bg)
        self.content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        inner_w = width - 2 * self.PAD

        # --- Header: brand logo (left) + close (right) ---
        header = tk.Frame(self.content, bg=self.bg)
        header.pack(side=tk.TOP, fill=tk.X, padx=self.PAD, pady=(self.PAD, 4))

        logo_lbl = tk.Label(header, image=self._imgs["logo"], bg=self.bg)
        logo_lbl.pack(side=tk.LEFT)

        close_btn = tk.Label(
            header, text="\u2715", font=(self.ui_font, 15),
            bg=self.bg, fg=self.text_color,
        )
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind("<Button-1>", lambda e: self._quit())

        for w in (header, logo_lbl):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

        # --- Input bar (bottom) — packed BEFORE response so it's never clipped ---
        self._build_input(self.content, inner_w)

        # --- Message area: solid white rule + response text (no sparkle) ---
        # `message_frame` reserves the middle space (pushes the input to the
        # bottom); `msg_row` hugs the top so the accent bar matches text height
        # like the mockup's `items-start`.
        message_frame = tk.Frame(self.content, bg=self.bg)
        message_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                           padx=self.PAD, pady=(self.PAD, self.PAD))

        msg_row = tk.Frame(message_frame, bg=self.bg)
        msg_row.pack(side=tk.TOP, fill=tk.X, anchor=tk.N)

        # A fixed-width Frame stretches vertically (fill=Y) to the text height,
        # giving the mockup's `w-[2px] self-stretch` white indicator bar.
        accent_line = tk.Frame(msg_row, width=2, bg=self.text_color)
        accent_line.pack(side=tk.LEFT, fill=tk.Y, padx=(2, 12))
        accent_line.pack_propagate(False)

        self.response_text = tk.Text(
            msg_row, wrap=tk.WORD, font=(self.ui_font, 15),
            bg=self.bg, fg=self.response_color, relief=tk.FLAT,
            insertbackground=self.text_color,
            borderwidth=0, highlightthickness=0, height=2,
            padx=0, pady=0, spacing1=2, spacing2=5, spacing3=2,
        )
        self.response_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._resp_w = 0
        # Refit height whenever the wrap width actually changes (not on every
        # configure, which would loop as the height re-adjusts).
        self.response_text.bind(
            "<Configure>",
            lambda e: (e.width != self._resp_w) and (
                setattr(self, "_resp_w", e.width) or self._fit_response_height()),
        )
        self.response_text.insert(
            "1.0", "Hello! I'll guide you through any sport, just ask me anything!")
        self.response_text.config(state=tk.DISABLED)
        # Size the text box to its content once the window has a real width.
        self.root.after(80, self._fit_response_height)

        # --- Left collapse tab (overlays the left edge, vertically centered) ---
        # Mockup: h-10 w-6 rounded-l-md arrow tab on the panel's left edge.
        tab_w = self.STRIP - 6
        self.tab = tk.Canvas(
            self.root, width=tab_w, height=40,
            bg=self.bg, highlightthickness=0,
        )
        self._round_rect(self.tab, 1, 1, tab_w - 1, 39, 6,
                         fill=self.tab_bg, outline="")
        self._tab_chev = self.tab.create_image(
            tab_w / 2, 20, image=self._imgs["chev_left"])
        self.tab.place(x=2, rely=0.5, anchor=tk.W)
        self.tab.bind("<Button-1>", self._toggle_tab)

    def _build_input(self, parent, inner_w):
        """Rounded input box: text field on top, mic + send controls below.

        Mirrors the mockup's `rounded-xl bg-zinc-950/40 p-3 flex-col gap-3`.
        """
        h = 86             # p-3 (12) + field (~26) + gap-3 (12) + icons (~24) + p-3 (12)
        pad = 12           # p-3
        field_y = 28       # baseline of the text field row
        icon_row_y = h - 24  # baseline of the mic/send controls row
        c = tk.Canvas(parent, width=inner_w, height=h, bg=self.bg,
                      highlightthickness=0)
        c.pack(side=tk.BOTTOM, padx=self.PAD, pady=(0, self.PAD))
        self._round_rect(c, 1, 1, inner_w - 1, h - 1, 12,
                         fill=self.input_bg, outline=self.border, width=1)

        self.input_field = tk.Entry(
            c, font=(self.ui_font, 14),
            bg=self.input_bg, fg=self.muted,
            insertbackground=self.text_color,
            relief=tk.FLAT, borderwidth=0, highlightthickness=0,
        )
        c.create_window(pad + 4, field_y, anchor=tk.W, window=self.input_field,
                        width=inner_w - 2 * pad - 8)
        self.input_field.insert(0, "Ask Anything")
        self.input_field.bind("<FocusIn>", self._clear_placeholder)
        self.input_field.bind("<FocusOut>", self._restore_placeholder)
        self.input_field.bind("<Return>", self._on_submit)
        self.input_field.bind("<Button-1>", self._focus_input)

        # Controls row: mic (left) — hold to record voice.
        self._input_canvas = c
        self.speaker_btn = c.create_image(pad + 10, icon_row_y, image=self._imgs["mic"])
        c.tag_bind(self.speaker_btn, "<ButtonPress-1>", self._on_mic_press)
        c.tag_bind(self.speaker_btn, "<ButtonRelease-1>", self._on_mic_release)

        # "Hold to talk" hint
        self._mic_hint = c.create_text(
            pad + 28, icon_row_y, anchor=tk.W,
            text="Hold to talk", font=(self.ui_font, 10),
            fill="#71717a",  # zinc-500
        )

        send_item = c.create_image(inner_w - pad - 10, icon_row_y, image=self._imgs["send"])
        c.tag_bind(send_item, "<Button-1>", self._on_submit)

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
        """Draw a rounded rectangle on a canvas via a smoothed polygon."""
        pts = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return canvas.create_polygon(pts, smooth=True, **kwargs)

    # ------------------------------------------------------------------
    # Collapse tab
    # ------------------------------------------------------------------

    @staticmethod
    def _ease_in_out_cubic(t):
        """Smooth acceleration / deceleration (0..1 in, 0..1 out)."""
        if t < 0.5:
            return 4 * t * t * t
        return 1 - pow(-2 * t + 2, 3) / 2

    def _slide_window(self, start_w, end_w, right_edge, y, h, on_complete):
        """Animate width with the right edge pinned — panel slides in/out."""
        self._animating = True
        elapsed = 0

        def tick():
            nonlocal elapsed
            elapsed += self.SLIDE_STEP
            t = min(1.0, elapsed / self.SLIDE_MS)
            eased = self._ease_in_out_cubic(t)
            w = max(self.STRIP, int(start_w + (end_w - start_w) * eased))
            x = int(right_edge - w)
            self.root.geometry(f"{w}x{h}+{x}+{y}")

            if t < 1.0:
                self.root.after(self.SLIDE_STEP, tick)
            else:
                self.root.geometry(f"{end_w}x{h}+{int(right_edge - end_w)}+{y}")
                self._animating = False
                on_complete()

        tick()

    def _toggle_tab(self, event=None):
        if self._animating:
            return

        w, h, _, _ = self._expanded_geometry
        cur_x = self.root.winfo_x()
        cur_y = self.root.winfo_y()
        cur_w = self.root.winfo_width()
        right_edge = cur_x + cur_w

        if self._collapsed:
            self.tab.itemconfigure(self._tab_chev, image=self._imgs["chev_left"])
            # Re-pack content before sliding so text is visible during animation
            self.content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
            self._slide_window(
                cur_w, w, right_edge, cur_y, h,
                on_complete=self._finish_expand,
            )
        else:
            self.tab.itemconfigure(self._tab_chev, image=self._imgs["chev_right"])
            # Hide content before shrinking so layout doesn't fight the slide.
            if self.content.winfo_ismapped():
                self.content.pack_forget()
            self.root.update_idletasks()
            self.root.geometry(f"{cur_w}x{h}+{int(right_edge - cur_w)}+{cur_y}")
            self._slide_window(
                cur_w, self.STRIP, right_edge, cur_y, h,
                on_complete=self._finish_collapse,
            )

    def _finish_expand(self):
        self.content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self._collapsed = False

    def _finish_collapse(self):
        self._collapsed = True

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
        if self.input_field.get() == "Ask Anything":
            self.input_field.delete(0, tk.END)
            self.input_field.config(fg=self.text_color)

    def _restore_placeholder(self, event):
        if not self.input_field.get().strip():
            self.input_field.insert(0, "Ask Anything")
            self.input_field.config(fg=self.muted)

    def _set_response(self, text):
        self.response_text.config(state=tk.NORMAL)
        self.response_text.delete("1.0", tk.END)
        self.response_text.insert("1.0", text)
        self.response_text.config(state=tk.DISABLED)
        self._fit_response_height()

    def _fit_response_height(self):
        """Shrink/grow the response box to fit its wrapped content so the
        accent bar matches the text height (mockup's `items-start`)."""
        try:
            self.response_text.update_idletasks()
            lines = self.response_text.count("1.0", "end", "displaylines")[0]
            self.response_text.config(height=max(2, int(lines)))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Submit / AI pipeline
    # ------------------------------------------------------------------

    def _on_submit(self, event):
        question = self.input_field.get().strip()
        if not question or question == "Ask Anything":
            return
        # Brief send-icon flash: dim → restore after 150ms
        self._imgs["send_dim"] = self._imgs.get("send_dim") or ImageTk.PhotoImage(
            icons.send(20, color=(161, 161, 170, 255)))  # zinc-400
        send_item = self._input_canvas.find_all()[-1]  # send is the last canvas item
        self._input_canvas.itemconfigure(send_item, image=self._imgs["send_dim"])
        self.root.after(150, lambda: self._input_canvas.itemconfigure(
            send_item, image=self._imgs["send"]))
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

    # ------------------------------------------------------------------
    # Mic: hold-to-record
    # ------------------------------------------------------------------

    def _on_mic_press(self, event):
        self._mic_press_time = time.time()
        # Immediate visual feedback — dim icon shows the press registered
        self._input_canvas.itemconfigure(self.speaker_btn, image=self._imgs["mic_dim"])
        self._input_canvas.itemconfigure(self._mic_hint, text="Recording in...", fill="#a1a1aa")
        self._mic_timer = self.root.after(500, self._start_recording)

    def _on_mic_release(self, event):
        if self._recording:
            self._stop_recording()
        else:
            # Released before 500ms — cancel the pending timer
            if self._mic_timer is not None:
                self.root.after_cancel(self._mic_timer)
                self._mic_timer = None
            # Restore idle state
            self._input_canvas.itemconfigure(self.speaker_btn, image=self._imgs["mic"])
            self._input_canvas.itemconfigure(self._mic_hint, text="Hold to talk", fill="#71717a")

    def _start_recording(self):
        self._mic_timer = None
        try:
            import pyaudio
            self._pyaudio_instance = pyaudio.PyAudio()
            self._audio_chunks = []
            self._recording = True
            self._audio_stream = self._pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1024,
            )
            # Audio cue
            self._play_tone(self._tone_start)
            # Visual feedback: red mic, hide hint, animated "Listening"
            self._input_canvas.itemconfigure(self.speaker_btn, image=self._imgs["mic_red"])
            self._input_canvas.itemconfigure(self._mic_hint, text="")
            self.input_field.delete(0, tk.END)
            self.input_field.config(fg=self.text_color)
            self.input_field.insert(0, "Listening")
            self._animate_listening()
            self._pulse_mic()
            threading.Thread(target=self._record_loop, daemon=True).start()
            print("[sidelines] Recording started...")
        except Exception as e:
            print(f"[sidelines] Mic error: {e}")
            self._recording = False
            self._input_canvas.itemconfigure(self.speaker_btn, image=self._imgs["mic"])
            self._input_canvas.itemconfigure(self._mic_hint, text="Hold to talk", fill="#71717a")

    def _record_loop(self):
        while self._recording and self._audio_stream:
            try:
                data = self._audio_stream.read(1024, exception_on_overflow=False)
                self._audio_chunks.append(data)
            except Exception:
                break

    def _animate_listening(self, dots=0):
        """Cycle 'Listening' → 'Listening.' → 'Listening..' → 'Listening...'"""
        if not self._recording:
            return
        dots = (dots % 4)
        text = "Listening" + "." * dots
        self.input_field.delete(0, tk.END)
        self.input_field.config(fg=self.text_color)
        self.input_field.insert(0, text)
        self._listening_anim_id = self.root.after(400, self._animate_listening, dots + 1)

    def _pulse_mic(self, bright=True):
        """Alternate red mic brightness for a pulsing effect."""
        if not self._recording:
            return
        img = self._imgs["mic_red"] if bright else self._imgs["mic_red_dim"]
        self._input_canvas.itemconfigure(self.speaker_btn, image=img)
        self._mic_pulse_id = self.root.after(500, self._pulse_mic, not bright)

    def _play_tone(self, wav_bytes):
        """Play a short WAV tone non-blocking."""
        def _play():
            try:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.write(wav_bytes)
                tmp.close()
                if sys.platform == "darwin":
                    import subprocess
                    subprocess.run(["afplay", tmp.name], check=False)
                elif sys.platform == "win32":
                    import winsound
                    winsound.PlaySound(tmp.name, winsound.SND_FILENAME)
                os.unlink(tmp.name)
            except Exception:
                pass
        threading.Thread(target=_play, daemon=True).start()

    def _stop_recording(self):
        self._recording = False
        # Stop animations
        if self._listening_anim_id:
            self.root.after_cancel(self._listening_anim_id)
            self._listening_anim_id = None
        if self._mic_pulse_id:
            self.root.after_cancel(self._mic_pulse_id)
            self._mic_pulse_id = None
        # Audio cue
        self._play_tone(self._tone_stop)
        # Restore mic icon, hint, and input field
        self._input_canvas.itemconfigure(self.speaker_btn, image=self._imgs["mic"])
        self._input_canvas.itemconfigure(self._mic_hint, text="Hold to talk", fill="#71717a")
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "Ask Anything")
        self.input_field.config(fg=self.muted)

        if self._audio_stream:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except Exception:
                pass
            self._audio_stream = None
        if self._pyaudio_instance:
            try:
                self._pyaudio_instance.terminate()
            except Exception:
                pass
            self._pyaudio_instance = None

        if not self._audio_chunks:
            return

        print("[sidelines] Recording stopped, transcribing...")
        # Assemble WAV bytes
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(16000)
            wf.writeframes(b"".join(self._audio_chunks))
        wav_bytes = buf.getvalue()
        self._audio_chunks = []

        self._set_response("Listening...")
        threading.Thread(
            target=self._process_voice, args=(wav_bytes,), daemon=True
        ).start()

    def _process_voice(self, wav_bytes):
        try:
            text = self.stt.transcribe(wav_bytes)
            if text.strip():
                self.root.after(0, self._set_response, "Thinking...")
                self._process_question(text)
            else:
                self.root.after(0, self._set_response, "Couldn't hear that. Try again.")
        except Exception as e:
            self.root.after(0, self._set_response, f"Error: {e}")

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

    def _apply_macos_overlay_behavior(self):
        """Make the overlay appear on all Spaces, including over fullscreen apps.

        On macOS 26+, only NSPanel (not NSWindow) can overlay fullscreen apps.
        TKWindow inherits from NSWindow and can't do this alone.  We create an
        invisible NSPanel and attach the TKWindow as its child — the child
        window inherits the panel's Space behaviour and follows it everywhere.
        """
        try:
            from AppKit import (
                NSApp, NSApplication, NSPanel, NSWindowAbove,
                NSWindowStyleMaskBorderless,
                NSWindowStyleMaskNonactivatingPanel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
                NSWindowCollectionBehaviorStationary,
            )
            from Foundation import NSMakeRect
            NSApplication.sharedApplication()

            self.root.update_idletasks()

            # Find the TKWindow (the real tkinter window)
            tk_window = None
            for w in NSApp.windows():
                try:
                    if str(w.className()) == "TKWindow" and w.frame().size.width > 10:
                        tk_window = w
                        break
                except Exception:
                    continue
            if tk_window is None:
                self.root.after(100, self._apply_macos_overlay_behavior)
                return

            # Create a tiny invisible NSPanel — its only job is to carry the
            # TKWindow onto fullscreen Spaces via the child-window relationship.
            carrier = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 1, 1),
                NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
                2,  # NSBackingStoreBuffered
                False,
            )
            carrier.setLevel_(1000)
            carrier.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
                | NSWindowCollectionBehaviorStationary
            )
            carrier.setAlphaValue_(0.0)
            carrier.orderFront_(None)

            # Attach TKWindow as child — it inherits the panel's Space behaviour
            carrier.addChildWindow_ordered_(tk_window, NSWindowAbove)
            tk_window.setLevel_(1000)
            tk_window.setHasShadow_(True)

            # Rounded corners + subtle 15%-white border — pure presentation.
            self._round_macos_window(tk_window)

            NSApp.activateIgnoringOtherApps_(True)

            # Keep a reference so the carrier isn't garbage-collected
            self._carrier_panel = carrier

            print(f"[sidelines] macOS overlay: fullscreen=yes, "
                  f"level={tk_window.level()}, visible={tk_window.isVisible()}")
        except ImportError:
            print("[sidelines] AppKit unavailable — overlay won't appear over fullscreen apps",
                  file=sys.stderr)
        except Exception as exc:
            print(f"[sidelines] macOS overlay config warning: {exc}", file=sys.stderr)

    def _round_macos_window(self, tk_window):
        """Clip the window to rounded corners and draw a hairline white border.

        Makes the overlay read as a floating glass pill. Best-effort: any
        failure leaves the square window intact without affecting behaviour.
        """
        try:
            from AppKit import NSColor
            from Quartz import CGColorCreateGenericRGB

            # The window itself defaults to an opaque square background that
            # fills the full frame — its square corners show through behind the
            # rounded content layer. Make it non-opaque with a clear background
            # so the rounded content view is the only visible surface.
            tk_window.setOpaque_(False)
            tk_window.setBackgroundColor_(NSColor.clearColor())

            content = tk_window.contentView()
            content.setWantsLayer_(True)
            layer = content.layer()
            if layer is None:
                return
            layer.setCornerRadius_(16.0)
            layer.setMasksToBounds_(True)
            # 1px border at ~15% white opacity
            layer.setBorderWidth_(1.0)
            layer.setBorderColor_(CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.15))

            for sub in content.subviews():
                try:
                    sub.setWantsLayer_(True)
                    sub_layer = sub.layer()
                    if sub_layer is not None:
                        sub_layer.setCornerRadius_(16.0)
                        sub_layer.setMasksToBounds_(True)
                except Exception:
                    continue
        except Exception as exc:
            print(f"[sidelines] corner rounding skipped: {exc}", file=sys.stderr)

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
        from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID

        pid = os.getpid()
        windows = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)
        if windows:
            for w in windows:
                if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowNumber", 0) > 0:
                    self.native_window_id = w["kCGWindowNumber"]
                    self.frame_buffer.set_exclude_window(self.native_window_id)
                    print(f"[sidelines] Overlay CGWindowID: {self.native_window_id}")
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

    # ------------------------------------------------------------------
    # Debug window — tkinter Toplevel (works on macOS unlike cv2.imshow)
    # ------------------------------------------------------------------

    _debug_toplevel = None
    _debug_label = None
    _debug_photo = None  # prevent GC

    def _pump_debug_window(self):
        """Render the debug dashboard and display it in a tkinter Toplevel."""
        try:
            frame = self.analyzer.last_frame
            if frame is not None:
                import cv2
                combined = self.analyzer.render_debug(frame)
                if combined is not None:
                    # BGR -> RGB for PIL
                    rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb)
                    photo = ImageTk.PhotoImage(img)
                    self._debug_photo = photo  # prevent GC

                    if self._debug_toplevel is None or not self._debug_toplevel.winfo_exists():
                        self._debug_toplevel = tk.Toplevel(self.root)
                        self._debug_toplevel.title("Sidelines — Debug")
                        self._debug_toplevel.configure(bg="black")
                        self._debug_label = tk.Label(self._debug_toplevel, bg="black")
                        self._debug_label.pack()

                    self._debug_label.configure(image=photo)
        except Exception:
            pass
        self.root.after(3000, self._pump_debug_window)

    def _quit(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()