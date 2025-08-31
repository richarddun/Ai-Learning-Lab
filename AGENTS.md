# AI Learning Lab

## Repository Overview
- Web application that helps kids learn to steer and converse with language models.
- Python **FastAPI** backend (`backend/`), static frontend with optional voice features (`frontend/`).
- Resources such as avatars and generated images live under `frontend/assets/`.
- See `ARCHITECTURE.md` for a deeper architectural discussion.

## Development Notes
- API keys are configured through the in-app Settings panel and stored in an encrypted local SQLite DB. For development you may opt into `.env` by setting `ALLOW_ENV_SECRETS=1`.
- The backend also proxies speech transcription at `/speech/transcribe` and can be served over HTTPS using the provided certificates (`python backend/run_ssl.py`).

## Testing Strategy
1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
2. **Core test command**
   ```bash
   python tools/run_tests_timeout.py --timeout 40 tests -- --maxfail=1
   ```
   - Runs the full pytest suite with a per-file timeout, logging to `testing-log.txt`.
3. **Quick loop**
   - Targeted tests: `python tools/run_tests_timeout.py --timeout 40 tests/your_area`
   - If green, run the full suite.
4. **If something fails**
   - Re-run individual tests with `pytest -q path/to_test.py::test_name`.
5. **Before committing**
   - Run the full suite again. Optionally generate coverage reports or run linting/formatters.

## Expectations for Contributions
- Mirror repository structure when adding tests (e.g., `tests/backend/...` or `tests/routes/...`).
- Any new route or other fundamental change **must include a corresponding test case** to prevent regressions.
- Keep commits small and descriptive. Follow existing code style; run formatters/linting when available.

