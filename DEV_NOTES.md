# Fantasyland Development Notes

A living document to track goals, scope, decisions, testing, and milestones for the `fantasyland` branch.

## Goals
- Deep customisation and usability upgrades without breaking existing flows.
- Keep commits small, descriptive, and logically grouped.
- Maintain user-friendly, accessible UI patterns (modals, dialogs, keyboard navigation).

## Scope Checklist
- [ ] Conversations: improved listing, filtering, quick actions
- [ ] Characters: richer editor (preview, validation), import/export
- [ ] Prompt UX: reusable snippets, template variables, inline tips
- [ ] TTS/Audio: playback controls, queueing, error recovery
- [ ] Accessibility: focus management, ARIA roles, keyboard shortcuts
- [ ] Settings: API key management polish, environment checks, hints
- [ ] Persistence: sync conversation/character meta reliably
- [ ] Error Handling: non-blocking toasts and retry flows
- [ ] Styling: theme polish, responsive layout improvements
- [ ] Tests: minimal smoke tests for critical flows

### From README TODOs
- [ ] Top bar "Config" toggle to collapse/expand the sidebar (mobile and desktop), with smooth transition and saved preference.

## Design & Decisions
- Dialogs use native `<dialog>` with backdrop for consistency and simplicity.
- System prompt composition is centralised (single helper) to avoid drift.
- Prefer id-based linking (character_id) with name fallback for resilience.

## Implementation Plan (High-Level)
1. Enhance character editor UX (preview, validation, inline help)
2. Prompt improvements (snippets, variables, preview)
3. Conversation list improvements (search, sort, pagination as needed)
4. Non-blocking notifications (toast component)
5. Accessibility pass (tab order, roles, focus traps)
6. Light smoke tests for critical flows

## Testing Notes
- Manual checks
  - Open conversation → character/avatar loads immediately
  - Delete flows via modals (conversation, character)
  - View Prompt shows fully composed system prompt
- Suggested automated checks (future)
  - Compose effective system prompt given character name
  - Dialog open/close handlers bound and cancel-safe

## Rollout Plan
- Keep `fantasyland` rebased on `main` regularly.
- Use squash-merge at the end for a clean history (or merge commit if preferred).
- Tag milestones for notable checkpoints.

## Milestones
- M1: Prompt composition + modals baseline (DONE on main)
- M2: Character editor UX enhancements
- M3: Prompt UX templates and snippets
- M4: Toast notifications + accessibility pass

## Stretch Goals
- Android app wrapper for the web UI:
  - Option A: PWA + Trusted Web Activity (TWA) wrapper
  - Option B: Capacitor (or Cordova) with embedded WebView
  - Deliverables: minimal Android project, app icon, splash, offline cache (if PWA), build docs

## Open Questions
- Which features should be behind experimental flags?
- Any telemetry or usage metrics desired (opt‑in only)?

## References
- Branch: `fantasyland`
- PR strategy: long‑running branch, PR later to `main`
