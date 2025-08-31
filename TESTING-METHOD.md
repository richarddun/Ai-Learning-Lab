Here’s a concise, repeatable testing script we will follow before every change/commit. All output is captured to `testing-log.txt`.

**One-Time Setup**

1. Activate venv: `source env/bin/activate` (or your venv). If not active, prefix with `env/bin/`.
2. Install deps: `pip install -r requirements.txt && pip install -r requirements-dev.txt`.
3. Sanity check tools: `python -V` and `pytest --version` should work.

**Core Command (timeout + logging)**

- Full suite with per-file 40s timeout, logging to `testing-log.txt`:
  - `env/bin/python tools/run_tests_timeout.py --timeout 40 tests -- --maxfail=1`

Notes
- The runner executes tests file-by-file and kills any that exceed the timeout.
- All stdout/stderr is appended to `testing-log.txt` at the repo root.

**Quick Loop (after each change)**

1. Run targeted area first:
   - Services: `env/bin/python tools/run_tests_timeout.py --timeout 40 tests/services`
   - Routes: `env/bin/python tools/run_tests_timeout.py --timeout 40 tests/routes`
   - Single file: `env/bin/python tools/run_tests_timeout.py --timeout 40 tests/test_api_keys.py`
2. If green, run full suite: `env/bin/python tools/run_tests_timeout.py --timeout 40 tests -- --maxfail=1`.
3. Review `testing-log.txt` if anything fails or times out.

**If Something Fails**

- Single test function: `pytest -q tests/path/to_test.py::test_name` (for fast iteration).
- Filter by keyword: `pytest -q -k "openrouter and not stream"`.
- More detail: `pytest -vv`; stop early: `pytest -x` or use `--maxfail=1` with the runner.

**Troubleshooting & Timeouts**

- Check `testing-log.txt` for the last test and its output.
- Re-run that file verbosely: `pytest -vv tests/that_file.py`.
- Environment isolation: tests avoid reading your real `.env` and DB. If you suspect leakage, ensure `ALLOW_ENV_SECRETS=0` for test runs.

**Before Committing**

1. Run the full suite with timeout: `env/bin/python tools/run_tests_timeout.py --timeout 40 tests -- --maxfail=1`.
2. Optional coverage: `pip install pytest-cov && pytest --cov=backend -q`.
3. Optional style: run `ruff`, `black`, `isort` if you use them locally.

**Repo-Specific Notes**

- No API keys required for tests; external calls are mocked.
- Route tests use in-memory SQLite via dependency overrides to keep runs deterministic.
- Run from repo root so imports resolve correctly.

**Adding New Tests**

- Place tests under `tests/` and name files `test_*.py` or `*_test.py`.
- The runner auto-discovers both patterns recursively under the paths you pass (default: `tests`).
- To run only a new subfolder: `env/bin/python tools/run_tests_timeout.py --timeout 40 tests/your_area`.
- Need markers/flags? Append after `--`, e.g.: `... tests -- -m "not slow"`.
