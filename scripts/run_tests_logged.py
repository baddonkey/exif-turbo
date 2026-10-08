"""Run the isolated test suite in a per-run folder and report the failed tests.

Agent-friendly workflow; every command returns within a bounded time::

    python scripts/run_tests_logged.py --detach   # start in background, returns at once
    python scripts/run_tests_logged.py --wait     # block <= --max-wait (8) s; exit 3 = still running

Without ``--detach``/``--wait`` the suite runs in the foreground and the summary
is printed at the end. Unrecognised arguments are forwarded to pytest.

Each run lives in ``logs/test-runs/<stamp>/`` (``pytest.log``, ``junit/*.xml``,
``status.json``, ``heartbeat``, ``summary.txt``); ``logs/test-runs/latest.txt``
names the newest run.

Exit codes: 0 all passed, 1 failures, 2 no run found, 3 still running,
4 runner died (no heartbeat). The last output line is always ``RUN-STATUS: <state>``
because terminal tools do not always surface the exit code.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_ROOT = REPO_ROOT / "logs" / "test-runs"
RUN_TESTS = REPO_ROOT / "scripts" / "run_tests.py"

NO_RUN_RC = 2
STILL_RUNNING_RC = 3
RUNNER_DEAD_RC = 4
# Must match scripts/run_tests.py.
TIMEOUT_RC = 124
OK_RCS = frozenset({0, 5})

HEARTBEAT_INTERVAL = 10.0
HEARTBEAT_STALE_AFTER = 120.0
LOW_DISK_BYTES = 5 * 1024**3


@dataclass(frozen=True)
class FailedTest:
    kind: str
    nodeid: str
    message: str


@dataclass(frozen=True)
class BrokenGroup:
    name: str
    returncode: int
    reason: str


@dataclass
class RunSummary:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failures: list[FailedTest] = field(default_factory=list)
    broken_groups: list[BrokenGroup] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures and not self.broken_groups


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    # Windows refuses the replace while a reader briefly holds the target open.
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)


def _read_status(run_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _touch_heartbeat(run_dir: Path) -> None:
    _write_text_atomic(run_dir / "heartbeat", str(time.time()))


def _read_heartbeat(run_dir: Path) -> float | None:
    try:
        return float((run_dir / "heartbeat").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _nodeid(classname: str, name: str) -> str:
    """Rebuild a pytest node id from JUnit ``classname`` + ``name``."""
    if not classname:
        return name
    parts = classname.split(".")
    for i, part in enumerate(parts):
        if part.startswith("test_") or part == "conftest":
            path = "/".join(parts[: i + 1]) + ".py"
            return "::".join([path, *parts[i + 1 :], name])
    return f"{classname}::{name}"


def _first_line(elem: ET.Element) -> str:
    text = elem.get("message") or elem.text or ""
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def _collect_junit(report: Path, summary: RunSummary) -> int:
    """Add one JUnit report to ``summary``; return its number of failures + errors."""
    problems = 0
    for case in ET.parse(report).getroot().iter("testcase"):
        nodeid = _nodeid(case.get("classname", ""), case.get("name", ""))
        case_problems = 0
        for elem in case.findall("failure"):
            summary.failures.append(FailedTest("FAILED", nodeid, _first_line(elem)))
            summary.failed += 1
            case_problems += 1
        for elem in case.findall("error"):
            summary.failures.append(FailedTest("ERROR", nodeid, _first_line(elem)))
            summary.errors += 1
            case_problems += 1
        if case_problems:
            problems += case_problems
        elif case.find("skipped") is not None:
            summary.skipped += 1
        else:
            summary.passed += 1
    return problems


def build_summary(run_dir: Path, status: dict[str, Any], runner_rc: int) -> RunSummary:
    summary = RunSummary()
    groups: list[dict[str, Any]] = status.get("groups", [])
    for group in groups:
        name = str(group["name"])
        rc = int(group["returncode"])
        junit = group.get("junit")
        report = run_dir / "junit" / junit if junit else None
        problems: int | None = None
        if report is not None and report.is_file():
            try:
                problems = _collect_junit(report, summary)
            except ET.ParseError:
                problems = None
        if rc in OK_RCS:
            continue
        if rc == TIMEOUT_RC:
            reason = "TIMEOUT - exceeded the group wall-clock limit and was killed"
        elif problems is None:
            reason = "CRASHED - no test report (a test may have hit the per-test timeout)"
        elif problems == 0:
            reason = "CRASHED - exited non-zero without a recorded test failure"
        else:
            continue
        summary.broken_groups.append(BrokenGroup(name, rc, reason))

    total = int(status.get("total", 0))
    if len(groups) < total:
        summary.broken_groups.append(
            BrokenGroup("runner", runner_rc, f"INCOMPLETE - only {len(groups)}/{total} groups ran")
        )
    elif runner_rc not in OK_RCS and summary.ok:
        summary.broken_groups.append(
            BrokenGroup("runner", runner_rc, "CRASHED - runner exited non-zero")
        )
    return summary


def format_summary(summary: RunSummary, run_dir: Path, total_groups: int) -> str:
    lines = [
        f"Test run: {run_dir}",
        f"Result: {'PASSED' if summary.ok else 'FAILED'}",
        f"Totals: {summary.passed} passed, {summary.failed} failed, "
        f"{summary.errors} errors, {summary.skipped} skipped ({total_groups} groups)",
    ]
    if summary.failures:
        lines += ["", f"Failed tests ({len(summary.failures)}):"]
        for failure in summary.failures:
            suffix = f" - {failure.message}" if failure.message else ""
            lines.append(f"  {failure.kind} {failure.nodeid}{suffix}")
    if summary.broken_groups:
        lines += ["", f"Crashed / timed-out groups ({len(summary.broken_groups)}):"]
        for group in summary.broken_groups:
            lines.append(f"  {group.name} (rc={group.returncode}) - {group.reason}")
    lines += ["", f"Full log: {run_dir / 'pytest.log'}"]
    return "\n".join(lines) + "\n"


def create_run_dir(log_root: Path) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S-%f")
    run_dir = log_root / stamp
    (run_dir / "junit").mkdir(parents=True)
    initial = {"state": "starting", "started": _now_iso(), "total": 0, "done": 0, "groups": []}
    _write_text_atomic(run_dir / "status.json", json.dumps(initial, indent=2))
    _touch_heartbeat(run_dir)
    (log_root / "latest.txt").write_text(stamp, encoding="utf-8")
    return run_dir


def latest_run_dir(log_root: Path) -> Path | None:
    try:
        name = (log_root / "latest.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    run_dir = log_root / Path(name).name
    return run_dir if name and run_dir.is_dir() else None


def _is_active(run_dir: Path, now: float) -> bool:
    status = _read_status(run_dir)
    if status is not None and status.get("state") == "reported":
        return False
    heartbeat = _read_heartbeat(run_dir)
    return heartbeat is not None and now - heartbeat <= HEARTBEAT_STALE_AFTER


def run_suite(run_dir: Path, extra: list[str]) -> int:
    command = [
        sys.executable,
        str(RUN_TESTS),
        f"--junit-dir={run_dir / 'junit'}",
        f"--status-file={run_dir / 'status.json'}",
        "--timeout=120",
        "--timeout-method=thread",
        *extra,
    ]
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}

    # Child output goes to a file, never a pipe: QtWebEngine leaks a thread that
    # keeps a pipe open forever after pytest exits.
    with (run_dir / "pytest.log").open("a", encoding="utf-8") as log_file:
        log_file.write(f"Started: {_now_iso()}\nCommand: {' '.join(command)}\n\n")
        log_file.flush()
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        while True:
            try:
                runner_rc = proc.wait(timeout=HEARTBEAT_INTERVAL)
                break
            except subprocess.TimeoutExpired:
                _touch_heartbeat(run_dir)
        log_file.write(f"\nCompleted: {_now_iso()}\nRunner exit code: {runner_rc}\n")

    status = _read_status(run_dir) or {}
    summary = build_summary(run_dir, status, runner_rc)
    text = format_summary(summary, run_dir, int(status.get("total", 0)))
    _write_text_atomic(run_dir / "summary.txt", text)
    rc = 0 if summary.ok else 1
    status.update(state="reported", current_group=None, returncode=rc, finished=_now_iso())
    _write_text_atomic(run_dir / "status.json", json.dumps(status, indent=2))
    print(text, end="", flush=True)
    print(f"RUN-STATUS: {'PASSED' if rc == 0 else 'FAILED'}", flush=True)
    return rc


def spawn_detached(run_dir: Path, extra: list[str]) -> int:
    command = [sys.executable, str(Path(__file__).resolve()), f"--run-dir={run_dir}", *extra]
    with (run_dir / "runner.log").open("w", encoding="utf-8") as runner_log:
        if sys.platform == "win32":
            # CREATE_NO_WINDOW (not DETACHED_PROCESS) so pytest children share a
            # hidden console instead of each popping up a window.
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            kwargs: dict[str, Any] = {
                "cwd": REPO_ROOT,
                "stdin": subprocess.DEVNULL,
                "stdout": runner_log,
                "stderr": subprocess.STDOUT,
            }
            try:
                proc = subprocess.Popen(
                    command,
                    creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                    **kwargs,
                )
            except OSError:
                # The terminal's job object may forbid breakaway.
                proc = subprocess.Popen(command, creationflags=flags, **kwargs)
        else:
            proc = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=runner_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    return proc.pid


def wait_for_run(
    run_dir: Path,
    max_wait: float,
    *,
    poll_interval: float = 1.0,
    monotonic: Callable[[], float] = time.monotonic,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    deadline = monotonic() + max_wait
    while True:
        status = _read_status(run_dir)
        if status is not None and status.get("state") == "reported":
            rc = int(status.get("returncode", 1))
            print((run_dir / "summary.txt").read_text(encoding="utf-8"), end="")
            print(f"RUN-STATUS: {'PASSED' if rc == 0 else 'FAILED'}", flush=True)
            return rc
        heartbeat = _read_heartbeat(run_dir)
        if heartbeat is not None and now() - heartbeat > HEARTBEAT_STALE_AFTER:
            print(
                f"RUNNER DEAD: no heartbeat for {now() - heartbeat:.0f}s. "
                f"Inspect {run_dir / 'pytest.log'} and {run_dir / 'runner.log'}"
            )
            print("RUN-STATUS: RUNNER_DEAD")
            return RUNNER_DEAD_RC
        remaining = deadline - monotonic()
        if remaining <= 0:
            status = status or {}
            print(
                f"STILL RUNNING: {status.get('done', 0)}/{status.get('total', '?')} groups done; "
                f"current: {status.get('current_group') or '-'}. Run --wait again."
            )
            print("RUN-STATUS: STILL_RUNNING")
            return STILL_RUNNING_RC
        sleep(min(poll_interval, remaining))


def _warn_low_disk() -> None:
    free = shutil.disk_usage(tempfile.gettempdir()).free
    print(f"Free disk space (temp dir): {free / 1024**3:.1f} GB")
    if free < LOW_DISK_BYTES:
        print(
            "WARNING: low disk space can cause native crashes/hangs; "
            "clear %TEMP%\\pytest-of-<user> first."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated test suite and report failed tests.", allow_abbrev=False
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--detach", action="store_true", help="start the run in the background")
    mode.add_argument("--wait", action="store_true", help="wait for the latest run")
    # Keep short: agent terminal tools return early from commands running ~10 s+.
    parser.add_argument("--max-wait", type=float, default=8.0, help="seconds --wait blocks")
    parser.add_argument("--run-dir", type=Path, help=argparse.SUPPRESS)
    args, extra = parser.parse_known_args(sys.argv[1:] if argv is None else argv)

    if args.wait:
        run_dir = latest_run_dir(LOG_ROOT)
        if run_dir is None:
            print("No test run found. Start one with --detach.")
            print("RUN-STATUS: NO_RUN")
            return NO_RUN_RC
        return wait_for_run(run_dir, args.max_wait)

    if args.run_dir is not None:
        return run_suite(args.run_dir, extra)

    previous = latest_run_dir(LOG_ROOT)
    if previous is not None and _is_active(previous, time.time()):
        print(f"A test run is already in progress: {previous}\nUse --wait to follow it.")
        print("RUN-STATUS: STILL_RUNNING")
        return STILL_RUNNING_RC

    _warn_low_disk()
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    run_dir = create_run_dir(LOG_ROOT)
    if args.detach:
        pid = spawn_detached(run_dir, extra)
        print(
            f"Test run started in background (pid {pid}).\nRun folder: {run_dir}\n"
            "Follow it with: .venv\\Scripts\\python.exe scripts\\run_tests_logged.py --wait"
        )
        print("RUN-STATUS: STARTED")
        return 0

    print(f"Running tests; waiting for completion. Run folder: {run_dir}", flush=True)
    return run_suite(run_dir, extra)


if __name__ == "__main__":
    raise SystemExit(main())