import os

from google import genai
from google.genai import types

BASEBALL_SYSTEM_PROMPT = """You are Sideline, a knowledgeable friend explaining baseball to a first-time viewer. Keep it simple, warm, and direct. No jargon without a quick explanation. When natural, drop in one surprising fact about what just happened, a stat, a piece of history, or something most fans do not know. Never lecture. Never condescending. No em dashes. Max 1-2 sentences.

## Current Game Context
{game_context}
"""


class GeminiClient:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in environment")
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash"

    def ask(self, video_path, question, ocr_history=""):
        """Send video + question to Gemini and return response text."""
        game_context = (
            f"Latest scoreboard OCR readings:\n{ocr_history}"
            if ocr_history
            else "No scoreboard data available yet."
        )

        system_prompt = BASEBALL_SYSTEM_PROMPT.format(game_context=game_context)

        with open(video_path, "rb") as f:
            video_bytes = f.read()

        video_part = types.Part.from_bytes(
            data=video_bytes, mime_type="video/mp4"
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=[video_part, question],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1000,
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
            ),
        )

        return response.text
