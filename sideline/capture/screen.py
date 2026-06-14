# =============================================================================
# capture/screen.py — Continuous screen capture into a circular frame buffer
#
# What it does:
#   FrameBuffer captures the entire visible screen at a configurable FPS and
#   stores frames in a fixed-size deque (circular buffer). It excludes the
#   Sidelines overlay from the capture so Gemini never sees the chatbox.
#   On macOS it uses Quartz CGWindowListCreateImage with window-level
#   exclusion; on Windows it uses mss for fast grab and blacks out the
#   overlay region post-capture via the Win32 GetWindowRect API.
#
# Technologies:
#   - macOS Quartz (CoreGraphics) for composited screen capture
#   - mss (Python) for Windows screen grab
#   - numpy for raw pixel buffer → BGR array conversion
#   - ctypes + Win32 API for overlay region blackout on Windows
#   - collections.deque for automatic frame eviction
#
# Why it matters:
#   This is the visual input pipeline for the entire app. Every question the
#   user asks is answered from the frames stored here. The overlay exclusion
#   is critical — without it, Gemini would see and respond to its own UI.
# =============================================================================

import time
import collections
import sys
import numpy as np

# ---------------------------------------------------------------------------
# Platform-specific capture backend
# ---------------------------------------------------------------------------
if sys.platform == "darwin":
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
        CGPreflightScreenCaptureAccess,
        CGRequestScreenCaptureAccess,
    )
    _MACOS = True
else:
    import mss as _mss
    _MACOS = False


class FrameBuffer:
    def __init__(self, fps=3, buffer_seconds=30):
        self.fps = fps
        self.buffer_seconds = buffer_seconds
        self.buffer = collections.deque(maxlen=fps * buffer_seconds)

        # macOS: CGWindowID of the overlay (excludes it from capture via Quartz)
        # Windows: HWND of the overlay (we black-out that region post-capture)
        self._exclude_id = None

        # mss instance — reused across frames for performance
        self._sct = _mss.mss() if not _MACOS else None

    def set_exclude_window(self, window_id):
        """Register the overlay window ID (CGWindowID on macOS, HWND on Windows)."""
        self._exclude_id = window_id

    # ------------------------------------------------------------------
    # Public capture API
    # ------------------------------------------------------------------

    def capture_frame(self):
        """Capture the visible screen. Returns a BGR numpy array."""
        if _MACOS:
            return self._capture_macos()
        else:
            return self._capture_windows()

    # ------------------------------------------------------------------
    # macOS — Quartz composited capture, overlay excluded natively
    # ------------------------------------------------------------------

    def _capture_macos(self):
        if self._exclude_id is not None:
            cg_image = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionOnScreenBelowWindow,
                self._exclude_id,
                kCGWindowImageDefault,
            )
            # Fallback: capture everything (overlay may appear in frame).
            # Don't clear _exclude_id — the failure is often transient.
            if cg_image is None:
                cg_image = CGWindowListCreateImage(
                    CGRectNull,
                    kCGWindowListOptionOnScreenOnly,
                    kCGNullWindowID,
                    kCGWindowImageDefault,
                )
        else:
            cg_image = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowImageDefault,
            )

        if cg_image is None:
            if not CGPreflightScreenCaptureAccess():
                CGRequestScreenCaptureAccess()
                raise RuntimeError(
                    "Screen Recording permission not granted. A system prompt "
                    "should appear — grant access, then restart the app."
                )
            raise RuntimeError(
                "Screen capture returned None despite having permission. "
                "Try restarting the app."
            )

        w = CGImageGetWidth(cg_image)
        h = CGImageGetHeight(cg_image)
        if w == 0 or h == 0:
            raise RuntimeError("Quartz returned a zero-dimension image")
        bytes_per_row = CGImageGetBytesPerRow(cg_image)
        raw = CGDataProviderCopyData(CGImageGetDataProvider(cg_image))

        # Quartz returns BGRA — drop alpha to get BGR
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, bytes_per_row // 4, 4)
        return arr[:, :w, :3].copy()

    # ------------------------------------------------------------------
    # Windows — mss capture, overlay region blacked out post-capture
    # ------------------------------------------------------------------

    def _capture_windows(self):
        monitor = self._sct.monitors[1]  # primary monitor
        shot = self._sct.grab(monitor)

        # mss returns BGRA — drop alpha to get BGR
        arr = np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        frame = arr[:, :, :3].copy()

        # Black out the overlay's region so Gemini never sees the chatbox
        if self._exclude_id is not None:
            self._blackout_hwnd(frame, self._exclude_id)

        return frame

    @staticmethod
    def _blackout_hwnd(frame, hwnd):
        """Paint a black rectangle over the overlay's screen region."""
        try:
            import ctypes
            import ctypes.wintypes
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            x1 = max(0, rect.left)
            y1 = max(0, rect.top)
            x2 = min(frame.shape[1], rect.right)
            y2 = min(frame.shape[0], rect.bottom)
            if x2 > x1 and y2 > y1:
                frame[y1:y2, x1:x2] = 0
        except Exception:
            pass  # non-fatal — overlay just appears in the frame

    # ------------------------------------------------------------------
    # Buffer helpers
    # ------------------------------------------------------------------

    def add_frame(self, frame, metadata):
        entry = {"frame": frame, "timestamp": time.time(), **metadata}
        self.buffer.append(entry)

    def get_last_n_seconds(self, n):
        cutoff = time.time() - n
        return [f for f in self.buffer if f["timestamp"] >= cutoff]

    def get_all_frames(self):
        return list(self.buffer)