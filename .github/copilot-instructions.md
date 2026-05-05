# Copilot Instructions — exif-turbo

## Project Overview

Cross-platform image EXIF metadata search and indexing tool with CLI and
PySide6 GUI. Scans image folders, extracts EXIF metadata, stores it in a
SQLite index, and provides fast full-text search over that data.
See [README.md](../README.md) for the full overview.

## Tech Stack

- Python 3.11+
- PySide6 + QML (Qt Quick / Material style)
- Type hints everywhere, mypy-strict compatible
- Dependency management: pip with `pyproject.toml`
- Testing: pytest
- Distribution: standalone binary via PyInstaller

## Project Structure

```
src/exif_turbo/
├── data/                          # Repository layer — SQLite access
│   ├── _connection.py             # Shared SQLCipher connection helper
│   ├── image_index_repository.py
│   └── indexed_folder_repository.py
├── indexing/                      # Indexing domain
│   ├── image_finder.py            # File system scanning
│   ├── image_utils.py             # Image utilities
│   ├── indexer_service.py         # Indexing orchestration
│   ├── exif_metadata_extractor.py
│   └── metadata_extractor.py
├── models/                        # Domain types
│   ├── indexed_folder.py
│   ├── indexed_image.py
│   └── search_result.py
├── ui/                            # PySide6 + QML adapter
│   ├── app_main.py
│   ├── qml/                       # QML views
│   ├── models/                    # Qt list models exposed to QML
│   ├── providers/                 # QQuickImageProviders
│   ├── view_models/               # AppController & friends
│   └── workers/                   # Background QThread workers
├── utils/
│   ├── thumb_cache.py
│   └── thumb_crypto.py
├── i18n/                          # gettext translator + .po/.mo catalogs
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
