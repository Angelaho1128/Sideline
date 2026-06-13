"""Standalone render harness: build the overlay with stubbed AI clients,
screenshot its window region, then quit. For visual diffing only."""
import subprocess
import sys

import overlay.window as W


class _Stub:
    def __init__(self, *a, **k):
        pass

    def select(self, *a, **k):
        return []


# Stub out the AI clients so no API keys are needed.
W.GeminiClient = _Stub
W.TTSClient = _Stub
W.KeyFrameSelector = _Stub


class _DummyBuffer:
    def set_exclude_window(self, *a, **k):
        pass

    def get_all_frames(self):
        return []


ov = W.SidelinesOverlay(_DummyBuffer(), None)


def _shoot():
    r = ov.root
    r.update_idletasks()
    r.update()
    x, y = r.winfo_x(), r.winfo_y()
    w, h = r.winfo_width(), r.winfo_height()
    # Capture a generous region around the window (points; screencapture handles retina)
    pad = 8
    region = f"{x - pad},{y - pad},{w + 2 * pad},{h + 2 * pad}"
    subprocess.run(["screencapture", "-x", "-R", region, "current.png"], check=False)
    r.destroy()


ov.root.after(1200, _shoot)
ov.run()
print("done")
