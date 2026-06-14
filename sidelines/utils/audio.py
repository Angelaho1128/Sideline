# =============================================================================
# utils/audio.py — Cross-platform audio playback
#
# What it does:
#   play_audio() takes a file path (MP3 or WAV) and plays it synchronously
#   (blocks until playback finishes). On macOS it shells out to afplay; on
#   Windows it uses the winmm MCI API (mciSendStringW) which supports MP3
#   natively without extra codecs; on Linux it falls back to xdg-open.
#
# Technologies:
#   - macOS: afplay (built-in CLI audio player)
#   - Windows: ctypes + winmm.dll MCI (Multimedia Command Interface)
#   - Linux: xdg-open fallback
#
# Why it matters:
#   TTS responses need to be played aloud. Blocking playback is intentional
#   — it keeps the speaker icon state in sync with actual audio output so
#   the UI accurately reflects whether audio is still playing. This module
#   abstracts the platform differences so TTS and tone playback just work.
# =============================================================================

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
