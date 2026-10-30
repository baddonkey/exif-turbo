---
description: "Use when editing the user manual or its generated PDF; keep both deliverables in sync."
applyTo: "docs/user-manual.*"
---
# User Manual Workflow

- Before changing `docs/user-manual.md` or `docs/user-manual.pdf`, read and follow `.github/agents/documentation.agent.md`.
- After changing the Markdown manual, regenerate the committed PDF with `.venv\Scripts\python.exe scripts\export_manual_pdf.py`.
- Verify the PDF was regenerated and contains the updated manual content. For text-only changes, do not rebuild screenshots; refresh them only when the change affects screenshot content or the task requests a full documentation rebuild.
- Do not stage or commit the generated PDF unless explicitly asked.