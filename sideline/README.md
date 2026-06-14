# Sideline

AI-powered sports companion that watches your screen and answers questions about the game in real time.

## How It Works

Sideline runs a persistent overlay chatbox on the right side of your screen. It continuously captures screen frames in the background, analyzes them for key moments (scoreboard changes, scene cuts, motion), and uses Google Gemini's multimodal AI to answer your questions about what's happening.

- **Screen capture** via macOS Quartz API (excludes the overlay from captures)
- **Frame analysis** with OpenCV motion detection, scene cut detection, and OCR
- **AI queries** powered by Google Gemini (video + text)
- **Text-to-speech** via ElevenLabs

## Install

1. Download the `.dmg` from the Sideline website
2. Drag **Sideline.app** to your Applications folder
3. Open Sideline — on first launch, enter your API keys:
   - **Gemini API key** (for AI queries)
   - **ElevenLabs API key** + **Voice ID** (for text-to-speech)
4. Grant Screen Recording permission when prompted (System Settings > Privacy & Security)

On first launch, you'll also be prompted to select the scoreboard region on screen (or press Escape to use the ESPN preset).

## API Keys

Sideline requires you to bring your own API keys. Enter them in the settings UI on first launch — they're stored locally on your machine in `~/Library/Application Support/Sideline/config.json`.

## Configuration

Settings are managed in-app. Available options:

| Key | Default | Description |
|-----|---------|-------------|
| `fps` | 3 | Capture frames per second |
| `buffer_seconds` | 30 | Seconds of frame history to keep |
| `scoreboard_roi` | — | Scoreboard region `[x, y, w, h]` |

## Development

```bash
pip install -r requirements.txt
python main.py
```

### Project Structure

```
sideline/
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
