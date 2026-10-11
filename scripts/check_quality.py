"""Reject new Python/QML diagnostics while preserving explicit existing debt."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


class QualityGate:
    PYRIGHT_VERSION = "1.1.414"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.output = self.root / "logs" / "quality"
        self.baseline = self.root / ".github" / "quality" / "baseline.json"

    def _run(self, name: str, command: list[str], allowed: set[int]) -> str:
        self.output.mkdir(parents=True, exist_ok=True)
        path = self.output / f"{name}.json"
        with path.open("w", encoding="utf-8") as output:
            result = subprocess.run(command, cwd=self.root, stdout=output,
                                    stderr=subprocess.PIPE, text=True, timeout=300)
        (self.output / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        if result.returncode not in allowed:
            raise RuntimeError(f"{name} tool failed ({result.returncode}): {result.stderr}")
        return path.read_text(encoding="utf-8-sig")

    def _relative(self, value: str) -> str:
        return Path(value).resolve().relative_to(self.root).as_posix()

    def collect(self) -> list[dict[str, str]]:
        for directory in ("src", "scripts"):
            for path in (self.root / directory).rglob("*.py"):
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        python = json.loads(self._run("pyright", [
            sys.executable, "-m", "uv", "tool", "run", "--from",
            f"pyright=={self.PYRIGHT_VERSION}", "pyright", "--outputjson",
            "--project", ".github/quality/pyrightconfig.json", "--pythonpath", sys.executable,
        ], {0, 1}))
        diagnostics: list[dict[str, str]] = []
        for entry in python["generalDiagnostics"]:
            diagnostics.append({
                "tool": "pyright", "file": self._relative(entry["file"]),
                "rule": entry.get("rule", "syntax"), "severity": entry["severity"],
                "message": entry["message"],
            })
        executable = Path(sys.executable).parent / (
            "pyside6-qmllint.exe" if sys.platform == "win32" else "pyside6-qmllint"
        )
        files = sorted((self.root / "src" / "exif_turbo" / "ui" / "qml").rglob("*.qml"))
        qml = json.loads(self._run("qmllint", [
            str(executable), "--ignore-settings", "--json", "-", *map(str, files),
        ], {0, 1, 255}))
        for file in qml["files"]:
            for entry in file["warnings"]:
                if entry["type"] in {"critical", "fatal"} or entry.get("id") == "syntax":
                    raise ValueError(f"QML syntax error in {file['filename']}: {entry['message']}")
                diagnostics.append({
                    "tool": "qmllint", "file": self._relative(file["filename"]),
                    "rule": entry.get("id", "qml"), "severity": entry["type"],
                    "message": entry["message"],
                })
        return diagnostics

    @staticmethod
    def counts(diagnostics: list[dict[str, str]]) -> Counter[str]:
        return Counter(json.dumps(entry, sort_keys=True) for entry in diagnostics)

    @classmethod
    def regressions(cls, current: list[dict[str, str]], baseline: list[dict[str, str]]) -> list[str]:
        added = cls.counts(current) - cls.counts(baseline)
        return [f"{count} new: {entry}" for entry, count in sorted(added.items())]

    def run(self, update: bool = False) -> int:
        current = self.collect()
        if update:
            records = [{**json.loads(entry), "count": count}
                       for entry, count in sorted(self.counts(current).items())]
            self.baseline.write_text(json.dumps({
                "pyright_version": self.PYRIGHT_VERSION, "diagnostics": records,
            }, indent=2) + "\n", encoding="utf-8")
            print(f"Recorded {len(current)} existing diagnostics. Review baseline changes explicitly.")
            return 0
        data: dict[str, Any] = json.loads(self.baseline.read_text(encoding="utf-8"))
        if data["pyright_version"] != self.PYRIGHT_VERSION:
            raise ValueError("Pyright version differs from baseline")
        baseline = []
        for entry in data["diagnostics"]:
            baseline.extend([{key: value for key, value in entry.items() if key != "count"}] * entry["count"])
        added = self.regressions(current, baseline)
        text = "\n".join(added) if added else f"PASS: no new diagnostics ({len(current)} existing)."
        (self.output / "summary.txt").write_text(text + "\n", encoding="utf-8")
        print(text)
        return 1 if added else 0

    @classmethod
    def main(cls) -> int:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--update-baseline", action="store_true")
        options = parser.parse_args()
        return cls(Path(__file__).resolve().parents[1]).run(options.update_baseline)


if __name__ == "__main__":
    raise SystemExit(QualityGate.main())