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
