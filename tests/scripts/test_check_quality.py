import json
from pathlib import Path

import pytest

from scripts.check_quality import QualityGate


def test_quality_gate_new_type_diagnostic_fails_even_if_another_is_fixed() -> None:
    # Arrange
    existing = {"tool": "pyright", "file": "src/example.py", "rule": "reportArgumentType",
                "severity": "error", "message": "old type error"}
    regression = {**existing, "message": "new type error"}

    # Act
    actual = QualityGate.regressions([regression], [existing])

    # Assert
    assert len(actual) == 1
    assert "new type error" in actual[0]


def test_quality_gate_duplicate_qml_warning_is_a_regression() -> None:
    # Arrange
    warning = {"tool": "qmllint", "file": "src/View.qml", "rule": "unqualified",
               "severity": "warning", "message": "Unqualified access"}

    # Act
    actual = QualityGate.regressions([warning, warning], [warning])

    # Assert
    assert len(actual) == 1
    assert actual[0].startswith("1 new:")


def test_quality_gate_removed_diagnostic_passes() -> None:
    # Arrange
    warning = {"tool": "qmllint", "file": "src/View.qml", "rule": "unqualified",
               "severity": "warning", "message": "Unqualified access"}

    # Act
    actual = QualityGate.regressions([], [warning])

    # Assert
    assert actual == []


def test_quality_gate_python_syntax_cannot_be_baselined(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "src"
    source.mkdir()
    (source / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    gate = QualityGate(tmp_path)

    # Act / Assert
    with pytest.raises(SyntaxError):
        gate.run(update=True)


def test_quality_gate_deliberate_regression_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    gate = QualityGate(tmp_path)
    gate.output.mkdir(parents=True)
    gate.baseline.parent.mkdir(parents=True)
    gate.baseline.write_text(json.dumps({"pyright_version": gate.PYRIGHT_VERSION, "diagnostics": []}),
                             encoding="utf-8")
    diagnostic = {"tool": "pyright", "file": "src/regression.py", "rule": "reportAssignmentType",
                  "severity": "error", "message": "str is not assignable to int"}
    monkeypatch.setattr(gate, "collect", lambda: [diagnostic])

    # Act
    result = gate.run()

    # Assert
    assert result == 1
    assert "str is not assignable to int" in (gate.output / "summary.txt").read_text(encoding="utf-8")