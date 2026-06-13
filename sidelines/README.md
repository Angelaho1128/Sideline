# Sidelines

AI-powered sports companion that watches your screen and answers questions about the game in real time.

## How It Works

Sidelines runs a persistent overlay chatbox on the right side of your screen. It continuously captures screen frames in the background, analyzes them for key moments (scoreboard changes, scene cuts, motion), and uses Google Gemini's multimodal AI to answer your questions about what's happening.

- **Screen capture** via macOS Quartz API (excludes the overlay from captures)
- **Frame analysis** with motion detection, scene cut detection, and OCR
- **AI queries** powered by Google Gemini (video + text)
- **Text-to-speech** via ElevenLabs

## Requirements

- macOS (uses Quartz framework for screen capture)
- Python 3.10+
- Screen Recording permission (System Settings > Privacy & Security)
- Tesseract OCR (`brew install tesseract`)

## Setup

1. Clone the repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and add your API keys:
   ```bash
   cp .env.example .env
   ```

3. Run:
   ```bash
   python main.py
   ```

On first launch, you'll be prompted to select the scoreboard region on screen (or press Escape to use the ESPN preset).

## Configuration

Edit `config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `fps` | 3 | Capture frames per second |
| `buffer_seconds` | 30 | Seconds of frame history to keep |
| `scoreboard_roi` | — | Scoreboard region `[x, y, w, h]` |

## Project Structure

```
sidelines/
├── main.py                  # Entry point
├── capture/
│   ├── screen.py            # Screen capture (Quartz)
│   └── analyzer.py          # Frame analysis (motion, OCR)
├── overlay/
│   ├── window.py            # Persistent chatbox overlay
│   └── region_selector.py   # Scoreboard ROI selector
├── intelligence/
│   ├── gemini.py            # Google Gemini client
│   ├── key_frames.py        # Key frame selection
│   ├── tts.py               # ElevenLabs TTS
│   └── video_compiler.py    # Frame-to-video compilation
└── utils/
    ├── config.py            # Config load/save
    └── audio.py             # Audio playback
```
