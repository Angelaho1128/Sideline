import time
import collections
import numpy as np

from Quartz import (
    CGWindowListCreateImage,
    CGRectNull,
    kCGWindowListOptionOnScreenOnly,
    kCGWindowListOptionOnScreenBelowWindow,
    kCGWindowImageDefault,
    kCGNullWindowID,
    CGImageGetWidth,
    CGImageGetHeight,
    CGImageGetBytesPerRow,
    CGImageGetDataProvider,
    CGDataProviderCopyData,
)


class FrameBuffer:
    def __init__(self, fps=3, buffer_seconds=30):
        self.fps = fps
        self.buffer_seconds = buffer_seconds
        self.buffer = collections.deque(maxlen=fps * buffer_seconds)
        self._exclude_window_id = kCGNullWindowID

    def set_exclude_window(self, cg_window_id):
        """Set the overlay window ID so capture grabs everything below it."""
        self._exclude_window_id = cg_window_id

    def capture_frame(self, bounding_box=None):
        """Capture the visible screen, excluding the overlay window. Returns BGR numpy array."""
        if self._exclude_window_id != kCGNullWindowID:
            # Capture the composited screen below our overlay — exactly what's visible
            cg_image = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionOnScreenBelowWindow,
                self._exclude_window_id,
                kCGWindowImageDefault,
            )
        else:
            # Overlay not registered yet — capture everything
            cg_image = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowImageDefault,
            )

        if cg_image is None:
            raise RuntimeError(
                "Screen capture failed. Check Screen Recording permission in "
                "System Settings > Privacy & Security."
            )

        # Convert CGImage to BGR numpy array
        w = CGImageGetWidth(cg_image)
        h = CGImageGetHeight(cg_image)
        bytes_per_row = CGImageGetBytesPerRow(cg_image)
        raw = CGDataProviderCopyData(CGImageGetDataProvider(cg_image))

        # Quartz returns BGRA on macOS — reshape and drop alpha for BGR
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, bytes_per_row // 4, 4)
        frame = arr[:, :w, :3].copy()  # BGRA -> BGR (first 3 channels)
        return frame

    def add_frame(self, frame, metadata):
        """Add a frame with metadata to the buffer."""
        entry = {"frame": frame, "timestamp": time.time(), **metadata}
        self.buffer.append(entry)

    def get_last_n_seconds(self, n):
        """Return frames from the last n seconds."""
        cutoff = time.time() - n
        return [f for f in self.buffer if f["timestamp"] >= cutoff]

    def get_all_frames(self):
        """Return all frames in the buffer."""
        return list(self.buffer)
