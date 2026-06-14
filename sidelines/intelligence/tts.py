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
            print("ElevenLabs API key not set")
            return None

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
        if response.status_code == 200:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(response.content)
            tmp.close()
            play_audio(tmp.name)
            return tmp.name
        else:
            print(f"TTS error: {response.status_code} {response.text}")
            return None
