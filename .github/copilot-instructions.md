# Copilot Instructions — exif-turbo

## Project Overview

Cross-platform image EXIF metadata search and indexing tool with CLI and
PySide6 GUI. Scans image folders, extracts EXIF metadata, stores it in a
SQLite index, and provides fast full-text search over that data.
See [README.md](../README.md) for the full overview.

## Tech Stack

- Python 3.11+
- PySide6 (Qt Widgets — QML migration planned, see below)
- Type hints everywhere, mypy-strict compatible
- Dependency management: pip with `pyproject.toml`
- Testing: pytest
- Distribution: standalone binary via PyInstaller

## Project Structure

```
src/exif_turbo/
├── data/                          # Repository layer — SQLite access
│   └── image_index_repository.py
├── indexing/                      # Indexing domain
│   ├── cli.py                     # CLI adapter (argparse)
│   ├── image_finder.py            # File system scanning
│   ├── image_utils.py             # Image utilities
│   ├── indexer_service.py         # Indexing orchestration
│   ├── exif_metadata_extractor.py
│   └── metadata_extractor.py
├── models/                        # Domain types
│   ├── indexed_image.py
│   └── search_result.py
├── ui/                            # PySide6 widget adapter
│   ├── app_main.py
│   ├── main_window.py
│   ├── models/                    # Qt view models
│   └── workers/                   # Background Qt workers
├── utils/
│   └── thumb_cache.py
├── config.py                      # App configuration
└── app.py                         # GUI entry point
tests/                             # Mirrors src/ structure
```

## Build & Run

```bash
pip install -e .                                        # Install in dev mode
exif-turbo                                              # Launch GUI
exif-turbo --db animals                                 # Launch with named database
```

## Testing

Activate the venv and run pytest from the project root:

```bash
pytest              # Run all tests
pytest -x           # Stop on first failure
pytest --tb=short   # Shorter tracebacks
```

## Conventions

- Follow the standards defined in the `senior-python-engineer` agent for
  design, testing, and code style.
- Use `src/` layout with a top-level package.
- Separate domain logic from infrastructure (ports & adapters / hexagonal style).
- Keep modules small and focused — one concept per module.
- Name tests descriptively: `test_<unit>_<scenario>_<expected>`.

## Planned: QML UI Migration

The current PySide6 widget-based UI (`src/exif_turbo/ui/`) is planned to be
migrated to a PySide6 + QML (Qt Quick / Material style) architecture, matching
the pattern used in hash-turbo. When working on any UI code:

- Avoid tight coupling to Qt Widgets APIs that would hinder the migration.
- Prefer view models and workers that are independent of the rendering layer.
- New UI components should expose a clean Python API that QML can bind to via
  `QAbstractListModel`, `Q_PROPERTY`, and `Signal`/`Slot`.
- Keep QML files in `src/exif_turbo/ui/qml/` once the migration begins.

## Agent Reference

| Agent | Purpose |
|-------|---------|
| [senior-python-engineer](.github/agents/senior-python-engineer.md) | Default coding agent — senior IC style, opinionated on design, testing, and Python standards |
| [code-reviewer](.github/agents/code-reviewer.agent.md) | Read-only code review — SOLID, tests, types, coupling |

## Customizations

| Type | Name | Purpose |
|------|------|---------|
| Instruction | `testing-conventions` | Auto-applied to `tests/**` — naming, AAA structure, fixture patterns |

## Agent Behaviour Rules

- **Only commit or push when the user explicitly asks for it in the prompt.**
  Do not commit, stage, or push as a side-effect of any other task.
