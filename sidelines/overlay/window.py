import os
import tempfile
import threading
import tkinter as tk

from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID,
)

from intelligence.gemini import GeminiClient
from intelligence.key_frames import KeyFrameSelector
from intelligence.tts import TTSClient
from intelligence.video_compiler import compile_to_video


class SidelinesOverlay:
    def __init__(self, frame_buffer, analyzer):
        self.frame_buffer = frame_buffer
        self.analyzer = analyzer
        self.last_response = ""
        self.cg_window_id = None

        self.key_frame_selector = KeyFrameSelector()
        self.gemini = GeminiClient()
        self.tts = TTSClient()

        # Theme colors — Gemini sidebar style
        self.bg = "#1e1e1e"
        self.input_bg = "#2d2d2d"
        self.text_color = "#e0e0e0"
        self.muted = "#9e9e9e"
        self.accent = "#8ab4f8"
        self.border = "#3c3c3c"

        self.root = tk.Tk()
        self._build_window()

        # Resolve CGWindowID after window is mapped, then register with frame buffer
        self.root.after(500, self._resolve_and_register_window)

    def _build_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg=self.bg)

        # Position: right-middle of screen
        width, height = 380, 500
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = screen_w - width - 20
        y = (screen_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # --- Title bar ---
        header = tk.Frame(self.root, bg=self.bg, height=36)
        header.pack(fill=tk.X)
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

        # Make header draggable
        header.bind("<ButtonPress-1>", self._start_drag)
        header.bind("<B1-Motion>", self._on_drag)

        # --- Chat / response area ---
        response_frame = tk.Frame(self.root, bg=self.bg)
        response_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 8))

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

        # --- Separator ---
        tk.Frame(self.root, bg=self.border, height=1).pack(fill=tk.X, padx=16)

        # --- Input bar ---
        input_container = tk.Frame(self.root, bg=self.input_bg, padx=12, pady=10)
        input_container.pack(fill=tk.X, padx=16, pady=(8, 12))

        # Input field
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

        # Bottom icons row
        icons_row = tk.Frame(input_container, bg=self.input_bg)
        icons_row.pack(fill=tk.X, pady=(6, 0))

        # Speaker button (left side)
        self.speaker_btn = tk.Label(
            icons_row, text="\U0001F50A", font=("Helvetica", 14),
            bg=self.input_bg, fg=self.muted, cursor="hand2",
        )
        self.speaker_btn.pack(side=tk.LEFT)
        self.speaker_btn.bind("<Button-1>", self._on_speak)

        # Send button (right side)
        send_btn = tk.Label(
            icons_row, text="\u2191", font=("Helvetica", 16, "bold"),
            bg=self.accent, fg="#1e1e1e", cursor="hand2",
            padx=6, pady=1,
        )
        send_btn.pack(side=tk.RIGHT)
        send_btn.bind("<Button-1>", self._on_submit)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

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
        try:
            # 1. Select key frames from buffer
            all_frames = self.frame_buffer.get_all_frames()
            key_frames = self.key_frame_selector.select(all_frames)

            if not key_frames:
                self.root.after(
                    0, self._set_response,
                    "No frames captured yet. Make sure screen recording permission is enabled.",
                )
                return

            # 2. Compile to video
            video_path = tempfile.mktemp(suffix=".mp4")
            compile_to_video(key_frames, video_path)

            # 3. Gather OCR history
            ocr_texts = [
                f.get("ocr_text", "") for f in all_frames if f.get("ocr_text")
            ]
            ocr_history = "\n".join(ocr_texts[-5:]) if ocr_texts else ""

            # 4. Ask Gemini
            response = self.gemini.ask(video_path, question, ocr_history)
            self.last_response = response

            # 5. Display response
            self.root.after(0, self._set_response, response)

            # 6. Clean up video file
            try:
                os.unlink(video_path)
            except OSError:
                pass

        except Exception as e:
            self.root.after(0, self._set_response, f"Error: {e}")

    def _on_speak(self, event):
        if self.last_response:
            threading.Thread(
                target=self.tts.speak, args=(self.last_response,), daemon=True
            ).start()

    def _resolve_and_register_window(self):
        """Find our overlay's CGWindowID and register it with the frame buffer."""
        pid = os.getpid()
        windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
        if windows:
            for w in windows:
                if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowNumber", 0) > 0:
                    self.cg_window_id = w["kCGWindowNumber"]
                    self.frame_buffer.set_exclude_window(self.cg_window_id)
                    print(f"Overlay CGWindowID: {self.cg_window_id}")
                    return
        # Retry if not found yet
        self.root.after(200, self._resolve_and_register_window)

    def _quit(self):
        self.root.destroy()

    def run(self):
        """Start the application main loop."""
        self.root.mainloop()
