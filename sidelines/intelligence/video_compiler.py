# =============================================================================
# intelligence/video_compiler.py — Compile key frames into an MP4 clip
#
# What it does:
#   Takes the key frames selected by KeyFrameSelector and writes them into
#   a short MP4 video file at 2 FPS. Each frame is resized to 1280x720
#   before encoding. The resulting clip is what gets sent to Gemini as
#   visual context for the user's question.
#
# Technologies:
#   - OpenCV (cv2.VideoWriter) with mp4v codec for video encoding
#
# Why it matters:
#   Gemini accepts video input, not individual images. This module bridges
#   the gap between the frame buffer (individual numpy arrays) and the
#   Gemini API (a single MP4 file). The low FPS and fixed resolution keep
#   file size small and API costs low while preserving enough visual
#   information for the model to understand what happened on screen.
# =============================================================================

import cv2


def compile_to_video(key_frames, path, fps=2):
    """Compile key frames into a short mp4 video clip."""
    if not key_frames:
        return False

    target_size = (1280, 720)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, target_size)

    for frame_data in key_frames:
        frame = frame_data["frame"]
        resized = cv2.resize(frame, target_size)
        writer.write(resized)

    writer.release()
    return True
