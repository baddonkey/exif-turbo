#!/usr/bin/env python3
"""Export docs/user-manual.md to docs/user-manual.pdf.

Usage (from the project root, with the venv active):
    python scripts/export_manual_pdf.py

Requirements (install once):
    pip install weasyprint markdown pygments

Screenshots must already exist in docs/screenshots/ — run
scripts/take_screenshots.py first if they are missing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _REPO_ROOT / "docs"
_SOURCE = _DOCS / "user-manual.md"
_OUTPUT = _DOCS / "user-manual.pdf"
_SCREENSHOTS = _DOCS / "screenshots"


# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>exif-turbo User Manual</title>
<style>
  @page {{
    size: A4;
    margin: 2cm 2.2cm;
    @bottom-center {{
      content: counter(page) " / " counter(pages);
      font-size: 9pt;
      color: #888;
    }}
  }}
  body {{
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.65;
    color: #1a1a1a;
  }}
  h1 {{ font-size: 22pt; border-bottom: 2px solid #1565C0; padding-bottom: 6px;
        color: #1565C0; margin-top: 0; page-break-before: avoid; }}
  h2 {{ font-size: 15pt; border-bottom: 1px solid #ccc; padding-bottom: 4px;
        color: #1a1a1a; margin-top: 1.6em; page-break-after: avoid; }}
  h3 {{ font-size: 12pt; color: #333; margin-top: 1.2em; page-break-after: avoid; }}
  a  {{ color: #1565C0; text-decoration: none; }}
  p  {{ margin: 0.4em 0 0.8em 0; }}
  code {{
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9.5pt;
    background: #f0f4ff;
    border: 1px solid #d0d8f0;
    border-radius: 3px;
    padding: 1px 4px;
  }}
  pre {{
    background: #f5f7fb;
    border: 1px solid #d0d8f0;
    border-radius: 4px;
    padding: 10px 14px;
    font-size: 9pt;
    line-height: 1.45;
    overflow-x: auto;
    page-break-inside: avoid;
  }}
  pre code {{ background: none; border: none; padding: 0; }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 0.8em 0 1.2em 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
  }}
  th {{
    background: #e8eef8;
    color: #1565C0;
    font-weight: 600;
    border: 1px solid #c0ccdf;
    padding: 6px 10px;
    text-align: left;
  }}
  td {{
    border: 1px solid #d5dde8;
    padding: 5px 10px;
    vertical-align: top;
  }}
  tr:nth-child(even) td {{ background: #f7f9fd; }}
  img {{
    max-width: 100%;
    height: auto;
    display: block;
    margin: 1em auto;
    border: 1px solid #d0d8f0;
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.10);
    page-break-inside: avoid;
  }}
  blockquote {{
    border-left: 3px solid #1565C0;
    margin: 1em 0;
    padding: 6px 14px;
    background: #f0f4ff;
    color: #444;
    border-radius: 0 4px 4px 0;
    page-break-inside: avoid;
  }}
  hr {{
    border: none;
    border-top: 1px solid #dde2ec;
    margin: 1.5em 0;
  }}
  /* Table of contents links — suppress underlines */
  li a {{ color: #1565C0; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


# ── Markdown → HTML ────────────────────────────────────────────────────────────

def _md_to_html(md_text: str, base_dir: Path) -> str:
    try:
        import markdown
        from markdown.extensions.tables import TableExtension
        from markdown.extensions.fenced_code import FencedCodeExtension
        from markdown.extensions.codehilite import CodeHiliteExtension
        from markdown.extensions.toc import TocExtension
    except ImportError:
        print("ERROR: 'markdown' is not installed.  Run: pip install markdown pygments")
        sys.exit(1)

    # Rewrite relative image paths to absolute file:// URIs so WeasyPrint can
    # locate screenshots placed in docs/screenshots/.
    def _abs_img(match: re.Match) -> str:
        alt = match.group(1)
        src = match.group(2)
        img_path = (base_dir / src).resolve()
        return f"![{alt}]({img_path.as_uri()})"

    md_text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _abs_img, md_text)

    html_body = markdown.markdown(
        md_text,
        extensions=[
            TableExtension(),
            FencedCodeExtension(),
            CodeHiliteExtension(css_class="highlight", guess_lang=False),
            TocExtension(toc_depth="2-3"),
        ],
    )
    return _HTML_TEMPLATE.format(body=html_body)


# ── PDF render ─────────────────────────────────────────────────────────────────

def _render_pdf(html: str, output: Path) -> None:
    try:
        from weasyprint import HTML
    except ImportError:
        print("ERROR: 'weasyprint' is not installed.  Run: pip install weasyprint")
        sys.exit(1)

    print(f"Rendering PDF …")
    HTML(string=html).write_pdf(str(output))
    size_kb = output.stat().st_size // 1024
    print(f"  Saved: {output.relative_to(_REPO_ROOT)}  ({size_kb} KB)")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    if not _SOURCE.exists():
        print(f"ERROR: source not found: {_SOURCE}")
        sys.exit(1)

    # Warn if screenshots are missing
    if not _SCREENSHOTS.exists() or not any(_SCREENSHOTS.glob("*.png")):
        print(
            "WARNING: no screenshots found in docs/screenshots/\n"
            "         Run scripts/take_screenshots.py first for a complete PDF."
        )

    md_text = _SOURCE.read_text(encoding="utf-8")
    html = _md_to_html(md_text, base_dir=_DOCS)
    _render_pdf(html, _OUTPUT)


if __name__ == "__main__":
    main()
