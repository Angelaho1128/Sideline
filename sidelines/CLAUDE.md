# CLAUDE.md

## Project Overview

Sidelines is a cross-platform (macOS + Windows) sports AI assistant. It displays a persistent overlay chatbox, captures the screen in the background (excluding the overlay), and uses Google Gemini to answer real-time questions about the game. Users provide their own API keys via an in-app settings UI.

## Tech Stack

- **Language:** Python 3.10+
- **GUI:** tkinter (frameless overlay with `overrideredirect`)
- **Screen capture:** macOS Quartz (`CGWindowListCreateImage`) / Windows `mss` — excludes overlay window by native ID
- **AI:** Google Gemini (`gemini-2.5-flash`) via `google-genai` with high-resolution media input
- **STT:** ElevenLabs Speech-to-Text (Scribe v1)
- **TTS:** ElevenLabs Text-to-Speech (Flash v2.5, requires API key with `text_to_speech` permission)
- **OCR:** pytesseract
- **Pose estimation:** YOLO (yolo11n-pose) via ultralytics for player detection and role inference
- **Video/image processing:** OpenCV, numpy, Pillow
- **Audio playback:** `afplay` (macOS) / `winmm` MCI API (Windows)
- **Packaging:** PyInstaller (`.app` bundle / `.exe`)

## Architecture

- `main.py` — entry point: loads config, runs ROI selector on first launch, creates overlay, starts capture thread with static-frame filtering (skips near-static frames, keeps at least one every 5s)
- `capture/screen.py` — `FrameBuffer` class: continuous screen capture into a circular buffer, platform-specific with window exclusion. Supports `get_last_n_seconds(n)` for recent-frame queries
- `capture/analyzer.py` — `FrameAnalyzer`: per-frame metadata (motion score, scene cuts, scoreboard OCR, YOLO pose estimation, uniform color classification)
- `overlay/window.py` — `SidelinesOverlay`: persistent tkinter chatbox, creates its own `tk.Tk()` root, resolves its CGWindowID. Auto-pauses system media on input focus and mic press
- `overlay/icons.py` — vector-drawn UI icons (4x render + LANCZOS downsample) and sine-wave audio tone generation
- `overlay/region_selector.py` — first-launch scoreboard region picker
- `intelligence/gemini.py` — Gemini client with comprehensive baseball rules reference in system prompt to reduce hallucination
- `intelligence/key_frames.py` — key frame selection: score changes > scene cuts > high-motion + recent frames (balanced mix)
- `intelligence/stt.py` — ElevenLabs speech-to-text client
- `intelligence/tts.py` — ElevenLabs text-to-speech client (Flash v2.5)
- `intelligence/video_compiler.py` — key frames to MP4 at 2 FPS, 1280x720
- `utils/config.py` — config persistence (config.json)
- `utils/audio.py` — cross-platform blocking audio playback

## Key Patterns

- The overlay creates the `tk.Tk()` root internally — no hidden root window
- Screen capture runs in a daemon thread; UI runs on the main thread
- Window ID resolution: CGWindowID on macOS (Quartz), HWND on Windows (Win32 API)
- Frame buffer is a `collections.deque` with `maxlen` for automatic eviction
- Capture loop filters out near-static frames (motion < 1.0, no score change, no scene cut) to keep the buffer focused on game action
- Questions use only the last 30 seconds of frames (`get_last_n_seconds`) for better "what just happened?" context
- Key frame selection balances high-motion and most-recent frames in remaining slots after score/cut picks
- Quartz returns BGRA; we drop the alpha channel to get BGR for OpenCV compatibility
- Audio playback is blocking — TTS thread waits for playback to complete before resetting UI state
- Media auto-pause sends system play/pause key (NSEvent on macOS, keybd_event on Windows) when user focuses input or presses mic

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
