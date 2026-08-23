"""Process-isolated test runner for exif-turbo.

The UI test suite initializes QtWebEngine and spawns background ``QThread``
workers (``IndexWorker`` / ``ThumbWorker``) that touch SQLCipher/OpenSSL
state.  When enough UI tests accumulate in a single interpreter, leaked
native threads race process teardown and abort with SIGABRT (Windows exit
codes 0xC0000005 / 0xC0000409) — an intermittent crash that is *not* a
Python assertion failure.

Windows has no ``fork``, so ``pytest --forked`` is unavailable.  Instead we
isolate by process:

* all non-UI tests run in one pytest process, and
* each UI test *file* runs in its own pytest process.

Every child inherits this process's stdout/stderr (no capture pipe), so a
leaked native thread cannot deadlock a parent waiting for EOF, and per-test
timeouts from ``pytest-timeout`` still apply.

Usage::

    python scripts/run_tests.py                # isolated run of the whole suite
    python scripts/run_tests.py -k thumbnail   # extra args forwarded to pytest
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
UI_DIR = TESTS_DIR / "ui"
HEAVY_TEST_FILES = (
    TESTS_DIR / "tagging" / "test_bundled_vocabulary.py",
)


def _run_pytest(targets: list[str], extra: list[str]) -> int:
    """Run pytest as an isolated subprocess, inheriting this console."""
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *targets, *extra]
    print(f"\n=== pytest {' '.join(targets)} ===", flush=True)
    completed = subprocess.run(cmd, cwd=REPO_ROOT)
    return completed.returncode


def main(argv: list[str]) -> int:
    extra = argv[1:]

    results: list[tuple[str, int]] = []

    # 1) Everything except UI and memory-heavy release tests in one process.
    aggregate_ignores = [
        f"--ignore={path.as_posix()}"
        for path in (UI_DIR, *HEAVY_TEST_FILES)
    ]
    rc = _run_pytest(["tests", *aggregate_ignores], extra)
    results.append(("non-ui", rc))

    # 2) Release regeneration tests need a low-memory parent process.
    for heavy_test_file in HEAVY_TEST_FILES:
        rel = heavy_test_file.relative_to(REPO_ROOT).as_posix()
        rc = _run_pytest([rel], extra)
        results.append((rel, rc))

    # 3) Each UI test file in its own process so native state can't accumulate.
    ui_files = sorted(p for p in UI_DIR.glob("test_*.py"))
    for ui_file in ui_files:
        rel = ui_file.relative_to(REPO_ROOT).as_posix()
        rc = _run_pytest([rel], extra)
        results.append((rel, rc))

    # Summary.
    print("\n================ SUMMARY ================", flush=True)
    failures = [(name, rc) for name, rc in results if rc != 0]
    for name, rc in results:
        status = "PASS" if rc == 0 else f"FAIL (rc={rc})"
        print(f"  {status:<16} {name}", flush=True)
    print(f"\n{len(results) - len(failures)}/{len(results)} groups passed", flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
