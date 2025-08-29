AI Learning Lab — Architecture Snapshot

A concise, LLM‑friendly overview of the app’s structure, major flows, and key entry points. Use this to quickly reorient in future sessions.

Project Structure
- backend/
  - app/main.py — FastAPI app, all API endpoints, serves frontend.
  - services/
    - openrouter.py — OpenRouter chat/stream helpers
    - database.py, models.py — SQLAlchemy setup and models
    - secrets.py — encrypted API key storage helpers
- frontend/
  - index.html — Single‑file app (HTML + JS) with all UI logic.
  - styles.css — Global styles, modal/backdrop styling.
  - assets/ — Static images (e.g., generated character avatars).
- local.db — SQLite database (users, messages, characters, secrets).
- DEV_NOTES.md — Goals, scope, milestones, TODOs.
- ARCHITECTURE.md — This doc.

Run & Development
- Install: `pip install -r requirements.txt`
- Dev server: `uvicorn backend.app.main:app --reload`
- HTTPS option: `python backend/run_ssl.py` (uses bundled CA certs)
- Frontend is served by FastAPI at `/` (no CORS needed).

Frontend Overview (frontend/index.html)
- Views
  - Landing (`#landing`)
    - Conversations list (`#conversations`) with Open, Rename, Delete
    - Settings (`#settings-panel`) for API keys
    - Modals: New Conversation (`#new-convo-dialog`), Delete Conversation (`#delete-convo-dialog`)
  - Chat Interface (`#chat-interface`)
    - Top bar (Back, avatar, name)
    - Sidebar Configuration
      - Character select (`#persona-select`) with actions: New, Edit, Delete, View Prompt
      - Character editor form (`#new-character-form`)
      - Modals: Delete Character (`#delete-char-dialog`), View Prompt (`#view-prompt-dialog`), Prompt Wizard (`#prompt-wizard-dialog`)
    - Main chat area (`#chat`), prompt input, send button, push‑to‑talk

- Core UI/JS Functions
  - Conversations
    - `loadConversations()` — GET `/users`; renders avatar/title/meta
    - `selectConversation(convo)` — POST `/users` to open; applies stored `avatar/voice/system_prompt/character` and sets pending character for auto‑apply; loads history
    - `openNewConvoDialog()` → create via POST `/users`; opens on success
    - `openDeleteConvoDialog(user)` → DELETE `/users/{id}`; refreshes list
    - Rename flow — PUT `/users/{id}/name` or suggest via `/users/{id}/suggest_name` (LLM) with fallback `/conversations/suggest_name`
  - Characters (Personas)
    - `loadCharacters()` — GET `/characters`; populates select; applies saved/pending id or matching name
    - `applyCharacterSelection(id)` — sets `systemPrompt`, voice, avatar; persists via PUT `/users/{uid}/meta` with `system_prompt`, `character_id`, `character_name`, `voice_id`, `voice_name`
    - Create/Update — POST `/characters`, PUT `/characters/{id}`
    - Delete — `openDeleteCharDialog()` → DELETE `/characters/{id}` (clears selection if needed)
    - Avatar generate — POST `/characters/{id}/avatar/generate` (server stores file under `frontend/assets/characters/{id}/...` and updates character `avatar`)
    - Prompt wizard — POST `/characters/suggest_system_prompt` (graceful fallback template when unavailable)
  - Prompt Composition
    - `buildEffectiveSystemPrompt()` — assembles the sent system prompt; prepends `Your name is <Name>. ` when a named character is selected
    - `View Prompt` modal displays the fully composed prompt with Copy
  - Chat & Speech
    - `sendMessage()` — appends user message, then POST `/chat/stream`; streams tokens into a bot paragraph; sends `system_prompt: buildEffectiveSystemPrompt()`
    - Speech input — MediaRecorder → POST `/speech/transcribe` → on success, calls `sendMessage()`
    - TTS
      - Voices: GET `/tts/voices` → cache in `window.__voices` and `window.__voiceMap`
      - Synthesis: POST `/tts` (buffered) or GET `/tts/stream` (if supported)
  - Settings (API Keys)
    - List: GET `/settings/api_keys` (names + has_value only)
    - Add/Update: POST `/settings/api_keys`
    - Delete: DELETE `/settings/api_keys/{name}`

- Client State
  - DOM: `#user-id` holds current conversation/user id
  - Local Storage
    - `selectedCharacterId` — last chosen character
    - `speechToggle` — on/off
    - `elevenlabsVoiceId` — preferred voice id
  - Window globals
    - `window.ELEVENLABS_VOICE_ID` — current voice id
    - `window.__voices`, `window.__voiceMap` — cached voices and id→name
    - `window.__pendingCharacterIdForConvo`, `window.__pendingCharacterNameForConvo` — used to auto‑apply character after opening a conversation

- Modals (native <dialog>)
  - `#new-convo-dialog`, `#delete-convo-dialog`
  - `#delete-char-dialog`, `#prompt-wizard-dialog`, `#view-prompt-dialog`
  - Backdrops in `styles.css` for consistent dimming

Backend Overview (backend/app/main.py)
- App
  - FastAPI; mounts `frontend/` as static at `/` with index fallback
  - SQLAlchemy DB; secrets encrypted in DB; optional `.env` reading only when `ALLOW_ENV_SECRETS=1`
- Endpoints (selected)
  - Settings
    - GET `/settings/api_keys` — list key names (no values)
    - POST `/settings/api_keys` — set key value
    - DELETE `/settings/api_keys/{name}` — remove key
  - Speech
    - POST `/speech/transcribe` — proxy to OpenAI Whisper using server key
  - Chat
    - POST `/chat` — non‑streaming reply
    - POST `/chat/stream` — streaming tokens (used by UI)
  - Users/Conversations
    - POST `/users` — create/open a conversation
    - GET `/users` — list conversations
    - PUT `/users/{user_id}/preferences` — set raw preferences JSON
    - PUT `/users/{user_id}/avatar` — set avatar URL for convo
    - PUT `/users/{user_id}/meta` — set `system_prompt`, `character_id`, name, voice info
    - DELETE `/users/{user_id}` — delete conversation
    - GET `/users/{user_id}/history` — fetch messages
    - POST `/users/{user_id}/history/import` — import messages
    - PUT `/users/{user_id}/name` — rename (query param `name`)
    - POST `/users/{user_id}/suggest_name` — LLM‑based rename suggestion
    - GET `/conversations/suggest_name` — fallback random slug
  - Characters
    - GET `/characters` — list characters
    - POST `/characters` — create
    - PUT `/characters/{char_id}` — update
    - DELETE `/characters/{char_id}` — delete
    - POST `/characters/suggest_system_prompt` — LLM prompt generator
    - POST `/characters/{char_id}/avatar/generate` — generate/store avatar and update URL
  - TTS (ElevenLabs)
    - GET `/tts/voices` — list voices
    - POST `/tts` — synthesize to audio bytes
    - GET `/tts/stream` — streaming synthesis (if supported)

Data Model (summary)
- Users — conversations with `name`, `preferences` JSON (prompt, voice, character refs, avatar)
- Messages — chat history per user
- Characters — personas (`name`, `system_prompt`, `voice_id`, `avatar`)
- ApiSecret — encrypted name/value for API keys

Cross‑cutting Behaviors
- Avatar application
  - On opening a conversation, if preferences include `character_id`/`character_name`, UI auto‑applies the character so avatar/background show immediately
- Transparent prompts
  - UI prepends `Your name is <Name>.` when a named character is active; visible in View Prompt modal
- Error tolerance
  - Prompt wizard falls back to a local template; voices UI hints when no API key is present

Quick Reference (for LLMs)
- Effective system prompt: `buildEffectiveSystemPrompt()`
- Select/apply character: `applyCharacterSelection(id)` → persists via `/users/{uid}/meta`
- Open conversation: `selectConversation(convo)` → POST `/users` then apply prefs/character
- Load lists: `loadConversations()` / `loadCharacters()`
- Chat stream: `sendMessage()` → POST `/chat/stream` (read chunks)
- Speech input: MediaRecorder → `/speech/transcribe` → `sendMessage()`
- TTS voices: `/tts/voices` → `window.__voiceMap`
- Modals: `#new-convo-dialog`, `#delete-convo-dialog`, `#delete-char-dialog`, `#prompt-wizard-dialog`, `#view-prompt-dialog`
- Client state: `selectedCharacterId`, `speechToggle`, `elevenlabsVoiceId`, `ELEVENLABS_VOICE_ID`, `__pendingCharacterIdForConvo`

Where to Extend Next
- See `DEV_NOTES.md` for roadmap, TODOs, and milestones.
- Extension points: character editor UX, prompt templates/snippets, toasts, accessibility, and Android wrapper (PWA+TWA/Capacitor).

