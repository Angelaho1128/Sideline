import ctypes
import subprocess
import sys


def play_audio(filepath):
    """Cross-platform audio playback (blocks until complete)."""
    if sys.platform == "darwin":
        subprocess.run(["afplay", filepath], check=False)
    elif sys.platform == "win32":
        # Use Windows Multimedia API (winmm) — supports MP3 natively
        winmm = ctypes.windll.winmm
        filepath_abs = filepath.replace("/", "\\")
        winmm.mciSendStringW(f'open "{filepath_abs}" type mpegvideo alias tts_play', None, 0, 0)
        winmm.mciSendStringW("play tts_play wait", None, 0, 0)
        winmm.mciSendStringW("close tts_play", None, 0, 0)
    else:
        subprocess.run(["xdg-open", filepath], check=False)
