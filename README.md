# Exif Turbo

Fast EXIF full-text search with a PySide6 desktop UI. Fully generated using VSCode Co-Pilot and GPT-5.2-Codex.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies and the package:

```
pip install -r requirements.txt
pip install -e .
```

## Index (ETL)

```
python -m exif_turbo.index --folders "C:\\Photos" --db data\\index.db --json data\\index.json
```

## Run UI

```
python -m exif_turbo.app --db data\\index.db
```
