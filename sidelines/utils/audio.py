import subprocess
import sys


def play_audio(filepath):
    """Cross-platform audio playback."""
    if sys.platform == "darwin":
        subprocess.Popen(["afplay", filepath])
    elif sys.platform == "win32":
        import os
        os.startfile(filepath)
    else:
        subprocess.Popen(["xdg-open", filepath])
