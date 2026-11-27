from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.smoke_release import smoke_release


@pytest.mark.parametrize(
    ("payload", "returncode", "passes"),
    [
        ({"status": "passed"}, 0, True),
        ({"status": "failed", "error": "missing extension"}, 1, False),
        ({"status": "passed"}, 1, False),
        (None, 0, False),
    ],
)
def test_smoke_release_requires_successful_process_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, str] | None, returncode: int, passes: bool,
) -> None:
    # Arrange
    executable = tmp_path / "app"
    monkeypatch.setenv("EXIF_TURBO_VEC1_EXTENSION", "external-extension")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        report = Path(command[-1])
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
        assert "EXIF_TURBO_VEC1_EXTENSION" not in env
        assert kwargs["timeout"] == 120
        if payload is not None:
            report.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(subprocess, "run", run)

    # Act / Assert
    if passes:
        smoke_release(executable)
    else:
        with pytest.raises(RuntimeError, match="Frozen smoke test"):
            smoke_release(executable)
