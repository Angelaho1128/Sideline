# Sidelines

AI-powered sports companion that watches your screen and answers questions about the game in real time.

## How It Works

Sidelines runs a persistent overlay chatbox on the right side of your screen. It continuously captures screen frames in the background, analyzes them for key moments (scoreboard changes, scene cuts, motion), and uses Google Gemini's multimodal AI to answer your questions about what's happening.

- **Screen capture** via macOS Quartz API / Windows mss (excludes the overlay from captures)
- **Frame analysis** with motion detection, scene cut detection, YOLO pose estimation, and scoreboard OCR
- **Smart frame selection** prioritizing score changes, camera cuts, high-motion, and recency
- **AI queries** powered by Google Gemini 2.5 Flash (video + text multimodal) with a comprehensive baseball rules reference to reduce hallucination
- **Speech-to-text** via ElevenLabs Scribe (hold-to-talk mic input)
- **Text-to-speech** via ElevenLabs Flash v2.5 (hear answers aloud)
- **Media auto-pause** when you start typing or recording, so the game pauses while you interact

## Install

1. Download the `.dmg` (macOS) or `.exe` (Windows) from the Sidelines website
2. macOS: drag **Sidelines.app** to your Applications folder
3. Open Sidelines — on first launch, enter your API keys:
   - **Gemini API key** (for AI queries)
   - **ElevenLabs API key** + **Voice ID** (for speech-to-text and text-to-speech)
4. Grant Screen Recording permission when prompted (macOS: System Settings > Privacy & Security)

On first launch, you'll also be prompted to select the scoreboard region on screen (or press Escape to use the ESPN preset).

## API Keys

Sidelines requires you to bring your own API keys. Enter them in the settings UI on first launch — they're stored locally on your machine.

- `GEMINI_API_KEY` — Google Gemini API key
- `ELEVEN_STT_API_KEY` — ElevenLabs API key (needs speech-to-text permission)
- `ELEVEN_TTS_API_KEY` — ElevenLabs API key (needs text-to-speech permission)
- `ELEVEN_VOICE_ID` — ElevenLabs voice ID

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

Requires Screen Recording permission on macOS.

### Project Structure

```
sidelines/
├── main.py                      # Entry point, capture loop with static-frame filtering
├── capture/
│   ├── screen.py                # Screen capture + circular frame buffer
│   └── analyzer.py              # Motion, scene cuts, OCR, YOLO pose estimation
├── overlay/
│   ├── window.py                # Persistent chatbox overlay with media auto-pause
│   ├── icons.py                 # Vector-drawn UI icons + audio tone generation
│   └── region_selector.py       # Scoreboard ROI selector (first launch)
├── intelligence/
│   ├── gemini.py                # Gemini client + baseball system prompt
│   ├── key_frames.py            # Key frame selection (score, cuts, motion, recency)
│   ├── stt.py                   # ElevenLabs speech-to-text
│   ├── tts.py                   # ElevenLabs text-to-speech
│   └── video_compiler.py        # Key frames → MP4 compilation
└── utils/
    ├── config.py                # Config load/save (config.json)
    └── audio.py                 # Cross-platform audio playback
```
