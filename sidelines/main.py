# =============================================================================
# main.py — Application entry point
#
# What it does:
#   Boots Sidelines: loads environment variables and config, prompts the user
#   to select a scoreboard region on first launch, initializes the screen
#   capture buffer and frame analyzer, creates the persistent overlay window,
#   and starts a background thread that continuously captures and analyzes
#   screen frames. The capture loop filters out near-static frames (paused
#   video, idle screens) so the buffer retains actual game action, while
#   still adding at least one frame every 5 seconds for liveness. The main
#   thread runs the tkinter event loop (the overlay).
#
# Technologies:
#   - python-dotenv for .env loading
#   - threading for background screen capture
#   - tkinter (via SidelinesOverlay) for the GUI
#
# Why it matters:
#   This is the single file you run to start Sidelines. It wires together
#   every subsystem — capture, analysis, AI, and UI — and manages the
#   capture-loop / UI-loop threading model that keeps the app responsive.
# =============================================================================

import sys
import os
import threading
import time

# Ensure the sidelines package is importable when running as a script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

from utils.config import load_config, save_config
from capture.screen import FrameBuffer
from capture.analyzer import FrameAnalyzer
from overlay.region_selector import RegionSelector
from overlay.window import SidelinesOverlay


def capture_loop(frame_buffer, analyzer, fps):
    count = 0
    last_add_time = 0
    while True:
        try:
            frame = frame_buffer.capture_frame()
            metadata = analyzer.analyze(frame)

            # Skip near-static frames (e.g. paused video) so the buffer
            # retains the actual action.  Always add the first frame and
            # at least one frame every 5 seconds for liveness.
            motion = metadata.get("motion_score", 0)
            is_interesting = (
                motion >= 1.0
                or metadata.get("score_changed")
                or metadata.get("is_scene_cut")
            )
            now = time.time()
            if is_interesting or not frame_buffer.buffer or (now - last_add_time) >= 5.0:
                frame_buffer.add_frame(frame, metadata)
                last_add_time = now

            count += 1
            if count == 1:
                h, w = frame.shape[:2]
                print(f"[capture] First frame captured: {w}x{h}")
            elif count % (fps * 10) == 0:
                print(f"[capture] {count} frames, buffer: {len(frame_buffer.buffer)}")
        except Exception as e:
            print(f"Capture error: {e}", file=sys.stderr)
        time.sleep(1.0 / fps)


def main():
    load_dotenv()

    # Load config
    config = load_config()
    fps = config.get("fps", 3)
    buffer_seconds = config.get("buffer_seconds", 30)

    # Check for scoreboard ROI — prompt user on first launch
    scoreboard_roi = config.get("scoreboard_roi")
    if not scoreboard_roi:
        selector = RegionSelector()
        scoreboard_roi = selector.run()
        if not scoreboard_roi:
            print("No scoreboard region selected. Using ESPN preset.")
            scoreboard_roi = [50, 40, 350, 85]
            config["scoreboard_roi"] = scoreboard_roi
            save_config(config)

    # Initialize core components
    frame_buffer = FrameBuffer(fps=fps, buffer_seconds=buffer_seconds)
    analyzer = FrameAnalyzer(scoreboard_roi=tuple(scoreboard_roi))

    # Create the persistent overlay (this creates the tk root internally)
    overlay = SidelinesOverlay(frame_buffer, analyzer)

    # Start background capture thread (daemon — dies with main)
    capture_thread = threading.Thread(
        target=capture_loop,
        args=(frame_buffer, analyzer, fps),
        daemon=True,
    )
    capture_thread.start()

    # Run the app (blocks until overlay is closed)
    print("Sidelines running.")
    overlay.run()


if __name__ == "__main__":
    main()
