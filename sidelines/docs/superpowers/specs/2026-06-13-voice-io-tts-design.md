# Voice Input, STT & TTS with Ohtani Persona

## Context

Sidelines is a macOS sports AI overlay that captures the screen and answers questions via Gemini. The send button and Gemini pipeline already work end-to-end. The mic button currently triggers TTS playback of the last response. We need to add voice input (STT) and make the mic button dual-purpose, while keeping TTS playback accessible. No UI changes — only wiring up existing buttons with new functionality.

The user has 3 ElevenLabs accounts ($25 MLH voucher each, can't stack). We split: Account 1 for STT, Account 2 for TTS with an Ohtani voice clone.

## Features

### 1. Hold-to-Record Voice Input (Mic Button)

The existing mic button (left icon in input box) gets dual behavior:

- **Quick tap** (< 500ms press): Triggers TTS playback of last response (current behavior, unchanged)
- **Hold** (>= 500ms press): Starts recording mic audio. Release stops recording and sends to STT.

**Recording flow:**
1. `<ButtonPress-1>` on mic button → record press timestamp, start a 500ms `root.after()` timer
2. If timer fires (still holding) → start `pyaudio` recording in a daemon thread, visual feedback via existing icon (no UI changes beyond what tkinter canvas can do with the existing icon — e.g. change item color/state)
3. `<ButtonRelease-1>` → if recording was active: stop recording, save WAV buffer, send to ElevenLabs STT
4. If released before 500ms → cancel timer, call existing `_on_speak()` for TTS playback
5. STT returns transcribed text → feed into `_process_question(text)` (same pipeline as send button)

**Recording details:**
- `pyaudio` stream: 16kHz, mono, 16-bit PCM
- Buffer audio chunks in memory (no temp file needed for short questions)
- On release: assemble chunks into WAV bytes, POST to ElevenLabs STT API

### 2. New STT Client (`intelligence/stt.py`)

New class `STTClient`:
- Wraps ElevenLabs Speech-to-Text API (`POST https://api.elevenlabs.io/v1/speech-to-text`)
- Uses `ELEVEN_STT_API_KEY` (Account 1)
- Accepts WAV audio bytes, returns transcribed text string
- Simple synchronous method: `transcribe(audio_bytes: bytes) -> str`

### 3. TTS with Ohtani Voice (Update `intelligence/tts.py`)

Update existing `TTSClient`:
- Switch from `ELEVEN_API_KEY` to `ELEVEN_TTS_API_KEY` (Account 2)
- `ELEVEN_VOICE_ID` will point to the Ohtani voice clone (user creates this manually in ElevenLabs dashboard)
- No other changes — `speak()` method stays the same

### 4. Gemini Ohtani Persona (Update `intelligence/gemini.py`)

Update system prompt to instruct Gemini to respond in Shohei Ohtani's speaking style:
- Humble, enthusiastic about baseball
- Occasional Japanese phrases/expressions
- References to personal experience as a player
- Short, conversational responses

This is a system prompt text change only.

## Environment Variables

```
# Account 1 - STT
ELEVEN_STT_API_KEY=...

# Account 2 - TTS (Ohtani voice clone)
ELEVEN_TTS_API_KEY=...
ELEVEN_VOICE_ID=...       # Ohtani clone voice ID

# Gemini (unchanged)
GEMINI_API_KEY=...
```

The old `ELEVEN_API_KEY` is replaced by the two separate keys.

## Files to Modify

| File | Change |
|------|--------|
| `intelligence/stt.py` | **New file.** `STTClient` class — ElevenLabs STT API wrapper |
| `intelligence/tts.py` | Update to use `ELEVEN_TTS_API_KEY` instead of `ELEVEN_API_KEY` |
| `intelligence/gemini.py` | Update system prompt for Ohtani persona |
| `overlay/window.py` | Rewire mic button: hold-to-record + tap-for-TTS dual behavior, integrate `STTClient`, add `pyaudio` recording logic |
| `requirements.txt` | Add `pyaudio` |
| `.env` | Update key names |

## Data Flow

```
VOICE INPUT:
Hold mic → pyaudio records WAV chunks in memory
  → Release mic → assemble WAV bytes
  → POST to ElevenLabs STT API (Account 1)
  → transcribed text
  → _process_question(text) → key frames → video → Gemini → response displayed

TTS PLAYBACK:
Tap mic (quick) → _on_speak()
  → tts.speak(last_response) in daemon thread
  → POST to ElevenLabs TTS API (Account 2, Ohtani voice)
  → MP3 → afplay
```

## Dependencies

- `pyaudio` — mic recording (requires PortAudio: `brew install portaudio` on macOS)

## Manual Steps (User)

1. Create Ohtani voice clone on ElevenLabs Account 2 using Japanese press conference audio
2. Copy the voice ID to `.env` as `ELEVEN_VOICE_ID`
3. Set `ELEVEN_STT_API_KEY` from Account 1
4. Set `ELEVEN_TTS_API_KEY` from Account 2
5. `brew install portaudio && pip install pyaudio`

## Verification

1. **Send button**: Type a question, press send → Gemini responds with Ohtani-style text
2. **Mic hold-to-record**: Hold mic button > 500ms → speak → release → "Thinking..." → Gemini responds
3. **Mic tap for TTS**: Quick tap mic button → last response plays as audio in Ohtani voice
4. **No UI changes**: Overlay looks identical before and after
