"""Regenerate translation catalogs (.pot -> .po -> .mo).

Extracts translatable strings from both Python (_()) and QML (qsTr()),
merges them into a single .pot, updates .po files, fills in translations
from populate_translations.py, and compiles .mo files.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src" / "exif_turbo"
LOCALES = SRC / "i18n" / "locales"
POT = LOCALES / "exif_turbo.pot"
LANGUAGES = ["de", "fr", "it", "rm"]

QML_DIR = SRC / "ui" / "qml"
QSTR_RE = re.compile(r'qsTr\("((?:[^"\\]|\\.)*)"\)')


def extract_qml_strings() -> set[str]:
    """Extract all qsTr("...") strings from QML files."""
    strings: set[str] = set()
    for qml_file in QML_DIR.glob("*.qml"):
        text = qml_file.read_text(encoding="utf-8")
        for match in QSTR_RE.finditer(text):
            raw = match.group(1)
            raw = raw.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
            strings.add(raw)
    return strings


def _find_pybabel() -> str:
    """Locate the pybabel executable."""
    candidate = Path(sys.executable).parent / "pybabel.exe"
    if candidate.exists():
        return str(candidate)
    candidate = Path(sys.executable).parent / "pybabel"
    if candidate.exists():
        return str(candidate)
    exe = shutil.which("pybabel")
    if exe:
        return exe
    print("ERROR: pybabel not found. Install babel: pip install babel", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], *, allow_stderr: bool = False) -> None:
    """Run a subprocess, raising on failure."""
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


def main() -> None:
    LOCALES.mkdir(parents=True, exist_ok=True)
    for lang in LANGUAGES:
        (LOCALES / lang / "LC_MESSAGES").mkdir(parents=True, exist_ok=True)

    pybabel = _find_pybabel()

    # 1. Extract Python strings with pybabel
    print("Extracting Python strings...")
    run([
        pybabel, "extract",
        "-F", "babel.cfg",
        "-o", str(POT),
        "src/exif_turbo",
    ], allow_stderr=True)

    # 2. Extract QML strings and append to .pot
    print("Extracting QML strings...")
    qml_strings = extract_qml_strings()

    pot_text = POT.read_text(encoding="utf-8")

    existing_re = re.compile(r'^msgid "((?:[^"\\]|\\.)*)"$', re.MULTILINE)
    existing = {m.group(1).replace('\\"', '"').replace("\\\\", "\\")
                for m in existing_re.finditer(pot_text)}

    multiline_re = re.compile(r'msgid ""\n((?:"[^"]*"\n)+)', re.MULTILINE)
    for m in multiline_re.finditer(pot_text):
        lines = m.group(1).strip().split("\n")
        full = "".join(
            line.strip().strip('"').replace('\\"', '"').replace("\\\\", "\\")
            for line in lines
        )
        existing.add(full)

    new_strings = qml_strings - existing
    if new_strings:
        print(f"  Adding {len(new_strings)} QML-only string(s) to .pot")
        additions: list[str] = []
        for s in sorted(new_strings):
            escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            additions.append(f'\n#: QML\nmsgid "{escaped}"\nmsgstr ""\n')
        pot_text += "\n".join(additions)
        POT.write_text(pot_text, encoding="utf-8")
    else:
        print("  All QML strings already present in .pot")

    # 3. Create or update .po files from .pot
    print("Updating .po files...")
    for lang in LANGUAGES:
        po_path = LOCALES / lang / "LC_MESSAGES" / "exif_turbo.po"
        if po_path.exists():
            run([
                pybabel, "update",
                "-i", str(POT),
                "-o", str(po_path),
                "-l", lang,
                "--no-fuzzy-matching",
            ], allow_stderr=True)
        else:
            run([
                pybabel, "init",
                "-i", str(POT),
                "-o", str(po_path),
                "-l", lang,
            ], allow_stderr=True)

    # 4. Fill translations from dictionary
    print("Populating translations...")
    run([sys.executable, str(ROOT / "scripts" / "populate_translations.py")])

    # 5. Compile .mo files
    print("Compiling .mo files...")
    for lang in LANGUAGES:
        po_path = LOCALES / lang / "LC_MESSAGES" / "exif_turbo.po"
        mo_path = po_path.with_suffix(".mo")
        run([
            pybabel, "compile",
            "-i", str(po_path),
            "-o", str(mo_path),
        ], allow_stderr=True)

    print("Done.")


if __name__ == "__main__":
    main()
