#!/usr/bin/env python3
import argparse
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_TIMEOUT = 30  # seconds
LOG_PATH = Path("testing-log.txt")


def log(msg: str) -> None:
    line = msg.rstrip("\n") + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


def find_test_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    if not paths:
        paths = ["tests"]
    for p in paths:
        pp = Path(p)
        if pp.is_file() and pp.suffix == ".py":
            files.append(pp)
        elif pp.is_dir():
            # Discover common pytest naming patterns
            discovered = set()
            for pattern in ("test_*.py", "*_test.py"):
                for f in pp.rglob(pattern):
                    discovered.add(f)
            files.extend(sorted(discovered))
        else:
            # allow specifying a single test node id like file::test_name
            files.append(Path(p))
    # De-duplicate while preserving order
    seen = set()
    out: list[Path] = []
    for f in files:
        key = str(f)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def run_one(pytest_cmd: list[str], timeout: int) -> tuple[int, str]:
    """Run a single pytest command with timeout. Return (exit_code, status)."""
    # Use a new process group so we can terminate children on timeout
    try:
        proc = subprocess.Popen(
            pytest_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        try:
            out, _ = proc.communicate(timeout=timeout)
            if out:
                for line in out.splitlines():
                    log(line)
            return proc.returncode, "ok" if proc.returncode == 0 else "fail"
        except subprocess.TimeoutExpired:
            # Kill the whole process group
            try:
                if hasattr(os, "getpgid"):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except Exception:
                pass
            log("[TIMEOUT] exceeded {}s".format(timeout))
            return 124, "timeout"
    except FileNotFoundError as e:
        log(f"[ERROR] {e}")
        return 127, "error"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pytest per-file with timeout and log output.")
    parser.add_argument("paths", nargs="*", help="Test files or directories (default: tests)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-test timeout in seconds")
    parser.add_argument("--pytest-args", nargs=argparse.REMAINDER, help="Additional args passed to pytest after '--'")
    args = parser.parse_args()

    # Header
    LOG_PATH.write_text("")  # truncate
    log(f"=== Test run start {datetime.now().isoformat()} ===")
    log(f"Python: {sys.version.split()[0]}")

    # Prefer running pytest via the repo venv if present
    venv_pytest = Path("env/bin/python")
    if venv_pytest.exists():
        base_cmd = [str(venv_pytest), "-m", "pytest", "-q"]
        log("Runner: env/bin/python -m pytest -q")
    else:
        base_cmd = [sys.executable, "-m", "pytest", "-q"]
        log("Runner: python -m pytest -q")

    extra_args = []
    if args.pytest_args:
        # strip leading '--' if present
        extra_args = [a for a in args.pytest_args if a != "--"]
        if extra_args:
            log(f"Extra pytest args: {' '.join(extra_args)}")

    tests = find_test_files(args.paths)
    if not tests:
        log("No test files found.")
        return 0

    overall_rc = 0
    for t in tests:
        log("")
        log(f"=== Running {t} with timeout={args.timeout}s ===")
        cmd = base_cmd + extra_args + [str(t)]
        rc, status = run_one(cmd, args.timeout)
        log(f"=== Result {t}: {status} (rc={rc}) ===")
        if rc != 0 and overall_rc == 0:
            overall_rc = rc

    log("")
    log("=== Test run complete ===")
    return overall_rc


if __name__ == "__main__":
    raise SystemExit(main())
