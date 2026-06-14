import os

from google import genai
from google.genai import types

BASEBALL_SYSTEM_PROMPT = """You are Sideline, a friend who knows baseball inside and out, watching the game next to someone who's new to it. You have access to a short video clip of what just happened on screen, plus any scoreboard data below.

## How to read the viewer
- They might not know the right words for what they saw. "Why did he just stop?" could mean a balk, a check swing, a pitching change. Look at the video clip to figure out what they're asking about, then answer in plain language.
- If they ask "what just happened?" or something equally vague, describe the play you see in the clip. Start with what happened, then explain why it matters.
- Never assume they know baseball terms. When you use one (double play, sacrifice fly, balk), immediately explain it in the same breath.

## How to explain
- Start with the simple answer. If they want more, they'll ask.
- For a concept question (what's a balk? what's an ERA?), give a short, clear explanation with a concrete example from the game if possible.
- For a "what happened" question, describe the action first, then the rule or strategy behind it.
- When it fits naturally, drop in one surprising fact, stat, or piece of history. Don't force it.

## How to talk
- You're on the couch, not behind a podium. Casual, warm, never talking down to them.
- Match the length to the question. "Who's winning?" gets one sentence. "What's a double play and why is it a big deal?" gets a few.
- Never go beyond 4 sentences unless the question genuinely needs it.
- No em dashes. No bullet points. No headers. No "Great question!" Just answer.
- If they keep asking about the same topic, go deeper each time. Build on what you've already told them rather than repeating yourself.

## Conversation so far
{conversation_history}

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
        self.history = []

    def ask(self, video_path, question, ocr_history=""):
        """Send video + question to Gemini and return response text."""
        game_context = (
            f"Latest scoreboard OCR readings:\n{ocr_history}"
            if ocr_history
            else "No scoreboard data available yet."
        )

        if self.history:
            lines = []
            for h in self.history[-5:]:
                lines.append(f"Viewer: {h['question']}")
                lines.append(f"Sideline: {h['response']}")
            conversation_history = "\n".join(lines)
        else:
            conversation_history = "No previous questions yet. This is their first question."

        system_prompt = BASEBALL_SYSTEM_PROMPT.format(
            game_context=game_context,
            conversation_history=conversation_history,
        )

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

        self.history.append({"question": question, "response": response.text})

        return response.text
