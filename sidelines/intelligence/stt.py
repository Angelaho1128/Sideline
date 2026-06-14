# =============================================================================
# intelligence/stt.py — Speech-to-text via ElevenLabs Scribe
#
# What it does:
#   STTClient takes raw WAV audio bytes (recorded from the user's mic via
#   the overlay's hold-to-talk button) and sends them to the ElevenLabs
#   Speech-to-Text API (Scribe v1 model). Returns the transcribed text,
#   which is then passed to Gemini as the user's question.
#
# Technologies:
#   - ElevenLabs Speech-to-Text REST API (v1/speech-to-text)
#   - requests library for HTTP multipart file upload
#
# Why it matters:
#   This enables hands-free interaction. Users can hold the mic button and
#   ask their question out loud instead of typing, which is natural when
#   you're watching a game. The transcribed text feeds directly into the
#   same Gemini pipeline as typed questions.
# =============================================================================

import os

import requests


class STTClient:
    def __init__(self):
        self.api_key = os.getenv("ELEVEN_STT_API_KEY")

    def transcribe(self, audio_bytes):
        """Send WAV audio bytes to ElevenLabs STT and return transcribed text."""
        if not self.api_key:
            print("ElevenLabs STT API key not set")
            return ""

        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {"xi-api-key": self.api_key}
        files = {"file": ("recording.wav", audio_bytes, "audio/wav")}
        payload = {"model_id": "scribe_v1"}

        response = requests.post(url, headers=headers, files=files, data=payload)
        if response.status_code == 200:
            return response.json().get("text", "")
        else:
            print(f"STT error: {response.status_code} {response.text}")
            return ""
