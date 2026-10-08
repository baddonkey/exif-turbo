from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scripts.run_tests_logged import (
    RUNNER_DEAD_RC,
    STILL_RUNNING_RC,
    TIMEOUT_RC,
    BrokenGroup,
    FailedTest,
    build_summary,
    create_run_dir,
    latest_run_dir,
    wait_for_run,
)

_JUNIT_WITH_FAILURE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="tests.utils.test_thumb_cache" name="test_ok" />
  <testcase classname="tests.utils.test_thumb_cache.TestEviction" name="test_bad">
    <failure message="AssertionError: assert 1 == 2">details</failure>
  </testcase>
  <testcase classname="tests.utils.test_thumb_cache" name="test_skip">
    <skipped message="no gpu" />
  </testcase>
  <testcase classname="" name="tests.utils.test_broken">
    <error message="collection failure">ImportError</error>
  </testcase>
</testsuite></testsuites>
"""

_JUNIT_ALL_PASSED = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="1">
  <testcase classname="tests.ui.test_browse" name="test_ok" />
</testsuite></testsuites>
"""


@pytest.fixture
def make_run(tmp_path: Path) -> Callable[..., Path]:
    """Factory: a run folder with the given status and JUnit reports."""

    def _make(status: dict[str, Any], reports: dict[str, str] | None = None) -> Path:
        run_dir = create_run_dir(tmp_path)
        for name, xml in (reports or {}).items():
            (run_dir / "junit" / name).write_text(xml, encoding="utf-8")
        (run_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
        return run_dir

    return _make


def _group(name: str, rc: int, junit: str | None) -> dict[str, Any]:
    return {"name": name, "returncode": rc, "junit": junit, "seconds": 1.0}


def test_build_summary_junit_failures_lists_failed_tests_with_node_ids(
    make_run: Callable[..., Path],
) -> None:
    # Arrange
    status = {"total": 1, "groups": [_group("non-ui", 1, "non-ui.xml")]}
    run_dir = make_run(status, {"non-ui.xml": _JUNIT_WITH_FAILURE})

    # Act
    summary = build_summary(run_dir, status, runner_rc=1)

    # Assert
    assert summary.failures == [
        FailedTest(
            "FAILED",
            "tests/utils/test_thumb_cache.py::TestEviction::test_bad",
            "AssertionError: assert 1 == 2",
        ),
        FailedTest("ERROR", "tests.utils.test_broken", "collection failure"),
    ]
    assert (summary.passed, summary.failed, summary.errors, summary.skipped) == (1, 1, 1, 1)
    assert summary.broken_groups == []


def test_build_summary_group_without_report_is_reported_as_crashed(
    make_run: Callable[..., Path],
) -> None:
    # Arrange
    status = {
        "total": 2,
        "groups": [
            _group("tests/ui/test_browse.py", 0, "a.xml"),
            _group("tests/ui/test_controller.py", 3221226505, "missing.xml"),
        ],
    }
    run_dir = make_run(status, {"a.xml": _JUNIT_ALL_PASSED})

    # Act
    summary = build_summary(run_dir, status, runner_rc=1)

    # Assert
    assert [(g.name, g.reason.split(" ")[0]) for g in summary.broken_groups] == [
        ("tests/ui/test_controller.py", "CRASHED")
    ]
    assert not summary.ok


def test_build_summary_timed_out_group_is_reported_as_timeout(
    make_run: Callable[..., Path],
) -> None:
    # Arrange
    status = {"total": 1, "groups": [_group("tests/ui/test_x.py", TIMEOUT_RC, "x.xml")]}
    run_dir = make_run(status)

    # Act
    summary = build_summary(run_dir, status, runner_rc=1)

    # Assert
    assert summary.broken_groups[0].reason.startswith("TIMEOUT")


def test_build_summary_missing_groups_is_reported_as_incomplete(
    make_run: Callable[..., Path],
) -> None:
    # Arrange
    status = {"total": 3, "groups": [_group("non-ui", 0, "a.xml")]}
    run_dir = make_run(status, {"a.xml": _JUNIT_ALL_PASSED})

    # Act
    summary = build_summary(run_dir, status, runner_rc=1)

    # Assert
    assert summary.broken_groups == [
        BrokenGroup("runner", 1, "INCOMPLETE - only 1/3 groups ran")
    ]


def test_build_summary_all_passed_is_ok(make_run: Callable[..., Path]) -> None:
    # Arrange
    status = {"total": 1, "groups": [_group("non-ui", 0, "a.xml")]}
    run_dir = make_run(status, {"a.xml": _JUNIT_ALL_PASSED})

    # Act
    summary = build_summary(run_dir, status, runner_rc=0)

    # Assert
    assert summary.ok
    assert summary.passed == 1


def test_latest_run_dir_after_create_returns_new_run(tmp_path: Path) -> None:
    # Arrange
    run_dir = create_run_dir(tmp_path)

    # Act
    latest = latest_run_dir(tmp_path)

    # Assert
    assert latest == run_dir


def test_wait_for_run_still_running_after_max_wait_returns_still_running(
    make_run: Callable[..., Path],
) -> None:
    # Arrange
    run_dir = make_run({"state": "running", "done": 2, "total": 5, "groups": []})

    # Act
    rc = wait_for_run(run_dir, max_wait=0, sleep=lambda _: None)

    # Assert
    assert rc == STILL_RUNNING_RC


def test_wait_for_run_reported_returns_run_exit_code_and_prints_summary(
    make_run: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    run_dir = make_run({"state": "reported", "returncode": 1, "groups": []})
    (run_dir / "summary.txt").write_text("Result: FAILED\n", encoding="utf-8")

    # Act
    rc = wait_for_run(run_dir, max_wait=0, sleep=lambda _: None)

    # Assert
    assert rc == 1
    assert "Result: FAILED" in capsys.readouterr().out


def test_wait_for_run_stale_heartbeat_returns_runner_dead(
    make_run: Callable[..., Path],
) -> None:
    # Arrange
    run_dir = make_run({"state": "running", "groups": []})
    (run_dir / "heartbeat").write_text("1000.0", encoding="utf-8")

    # Act
    rc = wait_for_run(run_dir, max_wait=60, now=lambda: 2000.0, sleep=lambda _: None)

    # Assert
    assert rc == RUNNER_DEAD_RC
