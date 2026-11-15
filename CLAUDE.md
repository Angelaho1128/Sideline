# CLAUDE.md

## Project Overview

Sidelines is a cross-platform (macOS + Windows) sports AI assistant. It displays a persistent overlay chatbox, captures the screen in the background (excluding the overlay), and uses Google Gemini to answer real-time questions about the game. Users provide their own API keys via an in-app settings UI.

## Tech Stack

- **Language:** Python 3.10+
- **GUI:** tkinter (frameless overlay with `overrideredirect`)
- **Screen capture:** macOS Quartz (`CGWindowListCreateImage`) / Windows `d3dshot` — excludes overlay window by native ID
- **AI:** Google Gemini (`gemini-2.5-flash`) via `google-genai`
- **STT:** ElevenLabs Speech-to-Text
- **TTS:** ElevenLabs Text-to-Speech (requires API key with `text_to_speech` permission)
- **OCR:** pytesseract
- **Video/image processing:** OpenCV, numpy, Pillow
- **Audio playback:** `afplay` (macOS) / `winmm` MCI API (Windows)
- **Packaging:** PyInstaller (`.app` bundle / `.exe`)

## Architecture

- `main.py` — entry point: loads config, runs ROI selector on first launch, creates overlay, starts capture thread
- `capture/screen.py` — `FrameBuffer` class: continuous screen capture into a circular buffer, platform-specific with window exclusion
- `capture/analyzer.py` — `FrameAnalyzer`: per-frame metadata (motion score, scene cuts, scoreboard OCR)
- `overlay/window.py` — `SidelinesOverlay`: persistent tkinter chatbox, creates its own `tk.Tk()` root, resolves its CGWindowID
- `intelligence/` — Gemini client, key frame selection, TTS, video compilation
- `utils/` — config management, audio playback

## Key Patterns

- The overlay creates the `tk.Tk()` root internally — no hidden root window
- Screen capture runs in a daemon thread; UI runs on the main thread
- Window ID resolution: CGWindowID on macOS (Quartz), HWND on Windows (Win32 API)
- Frame buffer is a `collections.deque` with `maxlen` for automatic eviction
- Quartz returns BGRA; we drop the alpha channel to get BGR for OpenCV compatibility
- Audio playback is blocking — TTS thread waits for playback to complete before resetting UI state

## Running (Development)

```bash
python main.py
```

Requires Screen Recording permission in System Settings (macOS).

## API Keys

Keys are stored in `.env` (development) or `~/Library/Application Support/Sidelines/config.json` (production). Required env vars:
- `GEMINI_API_KEY` — Google Gemini API key
- `ELEVEN_STT_API_KEY` — ElevenLabs API key (needs speech-to-text permission)
- `ELEVEN_TTS_API_KEY` — ElevenLabs API key (needs text-to-speech permission)
- `ELEVEN_VOICE_ID` — ElevenLabs voice ID

## Packaging & Distribution

- **macOS:** PyInstaller → `.app` bundle → `.dmg` (not Mac App Store — Quartz screen capture APIs are incompatible). Requires Apple Developer certificate for signing + notarization
- **Windows:** PyInstaller → `.exe` bundle
