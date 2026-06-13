# CLAUDE.md

## Project Overview

Sidelines is a macOS sports AI assistant. It displays a persistent overlay chatbox, captures the screen in the background (excluding the overlay), and uses Google Gemini to answer real-time questions about the game.

## Tech Stack

- **Language:** Python 3.10+
- **GUI:** tkinter (frameless overlay with `overrideredirect`)
- **Screen capture:** macOS Quartz (`CGWindowListCreateImage`) — excludes overlay window by CGWindowID
- **AI:** Google Gemini (`gemini-2.5-flash`) via `google-genai`
- **TTS:** ElevenLabs
- **OCR:** pytesseract
- **Video/image processing:** OpenCV, numpy, Pillow

## Architecture

- `main.py` — entry point: loads config, runs ROI selector on first launch, creates overlay, starts capture thread
- `capture/screen.py` — `FrameBuffer` class: continuous screen capture into a circular buffer, Quartz-based with window exclusion
- `capture/analyzer.py` — `FrameAnalyzer`: per-frame metadata (motion score, scene cuts, scoreboard OCR)
- `overlay/window.py` — `SidelinesOverlay`: persistent tkinter chatbox, creates its own `tk.Tk()` root, resolves its CGWindowID
- `intelligence/` — Gemini client, key frame selection, TTS, video compilation
- `utils/` — config management, audio playback

## Key Patterns

- The overlay creates the `tk.Tk()` root internally — no hidden root window
- Screen capture runs in a daemon thread; UI runs on the main thread
- CGWindowID resolution uses `CGWindowListCopyWindowInfo` with PID matching, retries via `root.after()` until found
- Frame buffer is a `collections.deque` with `maxlen` for automatic eviction
- Quartz returns BGRA; we drop the alpha channel to get BGR for OpenCV compatibility

## Running

```bash
python main.py
```

Requires Screen Recording permission in System Settings.

## Environment Variables

Set in `.env`:
- `GEMINI_API_KEY` — Google Gemini API key
- `ELEVEN_API_KEY` — ElevenLabs API key
- `ELEVEN_VOICE_ID` — ElevenLabs voice ID
