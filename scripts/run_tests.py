"""Process-isolated test runner for exif-turbo.

The UI test suite initializes QtWebEngine and spawns background ``QThread``
workers (``IndexWorker`` / ``ThumbWorker``) that touch SQLCipher/OpenSSL
state. When many UI tests accumulate in one interpreter, leaked native threads
can race process teardown and abort with SIGABRT on Windows.

Windows has no ``fork``, so ``pytest --forked`` is unavailable.  Instead we
isolate by process:

* all non-UI tests run in one pytest process, and
* each UI test file runs in its own pytest process.

Every child inherits this process's stdout/stderr (no capture pipe), so a
leaked native thread cannot deadlock a parent waiting for EOF, and per-test
timeouts from ``pytest-timeout`` still apply.

Each group is bounded by a wall-clock ``--group-timeout``; a group that exceeds
it (e.g. wedged in native teardown) has its whole process tree killed and is
recorded with return code ``TIMEOUT_RC``.

Usage::

    python scripts/run_tests.py                # isolated run of the whole suite
    python scripts/run_tests.py -k thumbnail   # extra args forwarded to pytest
    python scripts/run_tests.py --junit-dir out/junit --status-file out/status.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
UI_DIR = TESTS_DIR / "ui"

DEFAULT_GROUP_TIMEOUT = 900
TIMEOUT_RC = 124
# pytest exit codes that mean "nothing went wrong" (5 = no tests collected, e.g. via -k).
OK_RCS = frozenset({0, 5})


def group_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Windows refuses the replace while a reader briefly holds the target open.
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def _run_pytest(
    targets: list[str],
    extra: list[str],
    junit_path: Path | None,
    group_timeout: float | None,
) -> int:
    """Run pytest as an isolated subprocess, inheriting this console."""
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *targets, *extra]
    if junit_path is not None:
        cmd.append(f"--junitxml={junit_path}")
    print(f"\n=== pytest {' '.join(targets)} ===", flush=True)
    proc = subprocess.Popen(cmd, cwd=REPO_ROOT, start_new_session=os.name != "nt")
    try:
        return proc.wait(timeout=group_timeout)
    except subprocess.TimeoutExpired:
        print(
            f"\n!!! group exceeded {group_timeout:.0f}s wall-clock limit; "
            "killing its process tree",
            flush=True,
        )
        _kill_tree(proc)
        return TIMEOUT_RC


def _build_groups() -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = [
        ("non-ui", ["tests", f"--ignore={UI_DIR.as_posix()}"])
    ]
    # Each UI test file in its own process so native state can't accumulate.
    for ui_file in sorted(UI_DIR.glob("test_*.py")):
        rel = ui_file.relative_to(REPO_ROOT).as_posix()
        groups.append((rel, [rel]))
    return groups


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(allow_abbrev=False, add_help=False)
    parser.add_argument("--junit-dir", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--group-timeout", type=float, default=DEFAULT_GROUP_TIMEOUT)
    return parser.parse_known_args(argv)


def main(argv: list[str]) -> int:
    args, extra = _parse_args(argv[1:])
    group_timeout = args.group_timeout if args.group_timeout > 0 else None
    if args.junit_dir is not None:
        args.junit_dir.mkdir(parents=True, exist_ok=True)

    groups = _build_groups()
    status: dict[str, Any] = {
        "state": "running",
        "started": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total": len(groups),
        "done": 0,
        "current_group": None,
        "groups": [],
    }

    def publish() -> None:
        if args.status_file is not None:
            write_json_atomic(args.status_file, status)

    results: list[tuple[str, int]] = []
    for name, targets in groups:
        status["current_group"] = name
        publish()
        junit_name = f"{group_slug(name)}.xml"
        junit_path = args.junit_dir / junit_name if args.junit_dir else None
        started = time.monotonic()
        rc = _run_pytest(targets, extra, junit_path, group_timeout)
        results.append((name, rc))
        status["groups"].append(
            {
                "name": name,
                "returncode": rc,
                "junit": junit_name if junit_path is not None else None,
                "seconds": round(time.monotonic() - started, 1),
            }
        )
        status["done"] += 1

    print("\n================ SUMMARY ================", flush=True)
    failures = [(name, rc) for name, rc in results if rc not in OK_RCS]
    for name, rc in results:
        label = "PASS" if rc in OK_RCS else f"FAIL (rc={rc})"
        print(f"  {label:<16} {name}", flush=True)
    print(f"\n{len(results) - len(failures)}/{len(results)} groups passed", flush=True)

    overall = 1 if failures else 0
    status.update(state="finished", current_group=None, returncode=overall)
    publish()
    return overall


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
