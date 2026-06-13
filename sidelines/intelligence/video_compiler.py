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
