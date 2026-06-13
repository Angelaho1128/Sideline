import tkinter as tk

from utils.config import load_config, save_config


class RegionSelector:
    def __init__(self):
        self.roi = None
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None

    def run(self):
        """Show fullscreen overlay for scoreboard region selection."""
        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(bg="black")
        self.root.attributes("-topmost", True)

        self.canvas = tk.Canvas(
            self.root, cursor="cross", bg="black", highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        screen_w = self.root.winfo_screenwidth()
        self.canvas.create_text(
            screen_w // 2,
            50,
            text="Draw a rectangle around the scoreboard",
            fill="white",
            font=("Helvetica", 24, "bold"),
        )
        self.canvas.create_text(
            screen_w // 2,
            90,
            text="Press Escape to use ESPN preset",
            fill="#888888",
            font=("Helvetica", 14),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", self._use_preset)

        self.root.mainloop()
        return self.roi

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#e94560", width=2,
        )

    def _on_drag(self, event):
        if self.rect_id:
            self.canvas.coords(
                self.rect_id, self.start_x, self.start_y, event.x, event.y
            )

    def _on_release(self, event):
        x = min(self.start_x, event.x)
        y = min(self.start_y, event.y)
        w = abs(event.x - self.start_x)
        h = abs(event.y - self.start_y)

        if w > 10 and h > 10:
            self.roi = (x, y, w, h)
            config = load_config()
            config["scoreboard_roi"] = list(self.roi)
            save_config(config)
            self.root.destroy()

    def _use_preset(self, event):
        config = load_config()
        preset = config.get("presets", {}).get("espn_baseball", {})
        self.roi = (
            preset.get("left", 50),
            preset.get("top", 40),
            preset.get("width", 350),
            preset.get("height", 85),
        )
        config["scoreboard_roi"] = list(self.roi)
        save_config(config)
        self.root.destroy()
