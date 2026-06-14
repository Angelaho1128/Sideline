# =============================================================================
# intelligence/tts.py — Text-to-speech via ElevenLabs
#
# What it does:
#   TTSClient converts Gemini's text response into spoken audio using the
#   ElevenLabs Text-to-Speech API (Flash v2.5 model). It writes the MP3
#   response to a temp file, plays it through the platform audio system
#   (blocking until playback completes), then cleans up the temp file.
#   Voice settings (stability, similarity boost, style) are tuned for a
#   natural, conversational tone.
#
# Technologies:
#   - ElevenLabs Text-to-Speech REST API (v1/text-to-speech)
#   - requests library for HTTP POST
#   - tempfile for transient MP3 storage
#   - utils.audio.play_audio for cross-platform playback
#
# Why it matters:
#   This lets users hear the answer spoken aloud via the speaker button,
#   so they don't have to read the overlay while watching the game. The
#   blocking playback model ensures the UI state (speaker icon) stays in
#   sync with actual audio output.
# =============================================================================

import os
import tempfile

import requests

from utils.audio import play_audio


class TTSClient:
    def __init__(self):
        self.api_key = os.getenv("ELEVEN_TTS_API_KEY")
        self.voice_id = os.getenv("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        self.base_url = "https://api.elevenlabs.io/v1/text-to-speech"

    def speak(self, text):
        """Convert text to speech and play audio."""
        if not self.api_key:
            print("[sidelines] TTS: ElevenLabs API key not set")
            return None

        print(f"[sidelines] TTS: requesting audio for {len(text)} chars...")
        url = f"{self.base_url}/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_flash_v2_5",
            "voice_settings": {
                "stability": 0.6,
                "similarity_boost": 0.75,
                "style": 0.4,
            },
        }

        response = requests.post(url, json=payload, headers=headers)
        print(f"[sidelines] TTS: API response {response.status_code}, {len(response.content)} bytes")
        if response.status_code == 200:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(response.content)
            tmp.close()
            print(f"[sidelines] TTS: playing {tmp.name}")
            try:
                play_audio(tmp.name)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
        else:
            print(f"[sidelines] TTS error: {response.status_code} {response.text}")
            return None
