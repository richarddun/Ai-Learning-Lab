Here’s a concise, repeatable testing script we can follow before every commit.  

**One-Time Setup**

1. Activate venv: source env/bin/activate (or your venv).  Note : You may need to call env/bin/pytest from the repo root if the venv wasn't activated properly.
2. Install deps: uv pip install -r requirements.txt && uv pip install -r requirements-dev.txt.
3. Sanity check: pytest -q runs and collects tests.

**Quick Loop (after each change)**

1. BE SURE TO pipe the output of all tests and commands run to testing-log.txt in the repo root.
2. Targeted tests (area you touched): pytest -q tests/services or pytest -q tests/routes -k users.
3. Full suite (quick): pytest -q.
4. Rerun with cache cleared if things act odd: pytest -q --cache-clear.

**If Something Fails**

1. Run the single failing test: pytest -q tests/path/to_test.py::test_name.
2. Filter by keyword: pytest -q -k "openrouter and not stream".
3. Get more detail: pytest -vv.
4. Debug locally: add a quick assertion/print or drop into pdb with pytest -q -k test_name -x.

**Before Committing**

1. Full suite with verbosity: pytest -q → confirm all green.
2. Optional coverage (if you want a gauge): pip install pytest-cov then pytest --cov=backend -q.
3. Optional style pass (if you use them): run ruff, black, isort, or just commit if you’re not enforcing linters yet.

**Repo-Specific Notes**

- No API keys required for tests; external calls are mocked.
- DB: most API tests use an in-memory SQLite; one test uses the default engine but cleans up after itself.
- Run from repo root so imports resolve (tests assume project root on PYTHONPATH).