# AI Learning Lab

A simple web application that teaches kids how to steer and converse with language models.
The project is structured with a Python backend and a lightweight frontend that includes voice features.

## Development Setup

1. **Install dependencies**

```bash
pip install -r requirements.txt
```

2. **Configure API keys**

Preferred: use the in‑app Settings panel (gear icon) to add API keys. Keys are stored in the local SQLite DB with reversible encryption and are not exposed to the browser.

Development option: you can still read from a local `.env` if you opt in. Set `ALLOW_ENV_SECRETS=1` and place your keys in `.env`.

```bash
export ALLOW_ENV_SECRETS=1
```

Example `.env` for development:

```
OPENROUTER_API_KEY=your_key_here
ELEVENLABS_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
```

3. **Run the web server**

```bash
uvicorn backend.app.main:app --reload
```

Visit `http://localhost:8000/` to access the frontend served by the backend. The page can call the API endpoints directly without any cross-origin configuration.

Notes
- Speech transcription is proxied through the backend at `/speech/transcribe`; configure `OPENAI_API_KEY` via the Settings UI (or `.env` only if `ALLOW_ENV_SECRETS=1`).

### Avatar Gallery

- Browse generated avatars: open `http://localhost:8000/avatar-gallery`.
- Download any image: use the Download button in the gallery (served with attachment headers).
- Images are stored under `frontend/assets/characters/<id>/avatar-*.png` when created by `/characters/{char_id}/avatar/generate`.

### Image Generate

- Try the dedicated image panel at `http://localhost:8000/image_generate`.
- Enter a prompt, pick a style/size, and each result appears as an item in a chat-like feed with a download button.
- Files are saved under `frontend/assets/generated/img-*.png`.

### Optional: HTTPS for Voice Streaming

Some browsers require HTTPS for microphone access. A local Certificate Authority is bundled in `certs/ca.cert.pem`.
Import this certificate into your system or browser trust store, then start the server with SSL:

```bash
python backend/run_ssl.py
```

This will serve the app at `https://localhost:8000` using the trusted certificate.

## Testing

See [TESTING.md](TESTING.md) for the full testing strategy and instructions on running checks.

## Documentation

- Architecture overview: [ARCHITECTURE.md](ARCHITECTURE.md)
- Development notes and roadmap: [DEV_NOTES.md](DEV_NOTES.md)

## Next steps

- Add support for more model providers using openrouter list-available-models method
- Improve the frontend with templates and more kid-friendly styling.
- Expand voice capabilities and persistence of conversations.
- TODO: Add a "Config" toggle in the top bar that collapses/expands the sidebar on mobile (and optionally desktop), with smooth transition and saved preference.
- Stretch Goal: Package as an Android app using a web wrapper (PWA + TWA or Capacitor), including icon/splash and basic offline support.
