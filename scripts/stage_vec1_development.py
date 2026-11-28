"""Build a verified Vec1 extension for an editable source checkout."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from build_vec1 import staged_vec1


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    if sys.platform == "win32":
        from build_windows import stage_vec1

        destination = stage_vec1()
    else:
        destination = root / "build" / "vec1"
        with staged_vec1(root / "build") as stage:
            if stage is None:
                raise RuntimeError("Vec1 cannot be built for this platform")
            destination.mkdir(parents=True, exist_ok=True)
            for path in stage.iterdir():
                if path.is_file():
                    shutil.copy2(path, destination / path.name)
    print(f"Vec1 staged in {destination}")


if __name__ == "__main__":
    main()
