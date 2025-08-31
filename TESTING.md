# Testing Strategy

## Dependencies

Install the base and test packages before running the suite:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Runtime dependencies such as `fastapi`, `sqlalchemy`, `httpx`,
`python-dotenv`, `jinja2`, `elevenlabs`, `python-multipart`, `piper-tts`,
`pedalboard`, `numpy`, `soundfile`, and `huggingface_hub` come from
`requirements.txt`, while `pytest` and `pytest-asyncio` are provided by
`requirements-dev.txt`.

## 1. Baseline tooling
- **Testing framework**: `pytest` for Python with `pytest-asyncio` for async endpoints and services.
- **Mocking HTTP calls**: use `respx` or `responses` to simulate external APIs like `openrouter`.
- **Static analysis**: run `flake8` or `ruff` and autoformat with tools such as `black` and `isort`; optionally run type checks with `mypy`.
- **Test layout**: mirror the repository structure (e.g., `tests/backend/services/test_openrouter.py`) and name files starting with `test_`.

## 2. Local workflow
- Use **pre-commit hooks** to run linters, formatters, and unit tests before committing.
- **Unit tests** isolate each service or helper, mocking external dependencies, and use `TestClient` for FastAPI endpoints.
- **Integration tests** verify that components interact correctly by starting the FastAPI app in a test context.
- **End-to-end tests** (as the frontend grows) can leverage tools like `Playwright` or `Selenium` to exercise the full stack.
- Perform **manual smoke tests** for major features to catch UX or integration issues not covered by automation.

## 3. Automation & continuous integration
- A **CI pipeline** should run linting/formatting checks, unit, integration, and end-to-end tests, and generate code coverage reports (e.g., `pytest --cov`), failing if coverage drops below a threshold.
- **Cache dependencies** (Python virtualenv, npm cache) to speed up CI runs.
- **Parallelize** large test suites using `pytest -n auto` via `pytest-xdist`.

## 4. Regression & ongoing quality
- Add a **regression test** whenever a bug is found, reproducing the issue before applying a fix.
- Include **performance tests** for key endpoints using tools like `locust` or `k6` to track behavior under load.
- Run **security checks** such as `bandit` and `pip-audit` to catch vulnerabilities.
- Keep this document updated with any new testing tools or procedures.

## 5. Pre-merge and release gating
- Enforce a **review policy** requiring code review approvals and a green CI pipeline before merging.
- Enable **branch protection** to ensure tests pass and code coverage remains above the required threshold.
- For **release candidates**, run final integration and smoke tests on a staging environment before production deployment.

