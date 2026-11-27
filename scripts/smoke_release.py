"""Run the frozen application's offline smoke check with a bounded timeout."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


def smoke_release(executable: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="exif-turbo-release-check-") as work:
        root = Path(work)
        report = root / "result.json"
        environment = os.environ.copy()
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TRANSFORMERS_OFFLINE"] = "1"
        environment.pop("EXIF_TURBO_VEC1_EXTENSION", None)
        with (root / "output.log").open("w", encoding="utf-8") as output:
            result = subprocess.run(
                [str(executable.resolve()), "--release-smoke-test", str(report)],
                cwd=root, env=environment, stdout=output, stderr=subprocess.STDOUT,
                timeout=120, check=False,
            )
        diagnostics = (root / "output.log").read_text(encoding="utf-8", errors="replace")
        if not report.is_file():
            raise RuntimeError(f"Frozen smoke test produced no report ({result.returncode}): {diagnostics}")
        payload = json.loads(report.read_text(encoding="utf-8"))
        if result.returncode != 0 or payload != {"status": "passed"}:
            raise RuntimeError(f"Frozen smoke test failed: {payload}\n{diagnostics}")
        print(f"  Frozen offline tokenizer and encrypted Vec1 smoke test passed: {executable}")
