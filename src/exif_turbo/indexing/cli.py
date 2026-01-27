from __future__ import annotations

import argparse
from pathlib import Path

from ..data.image_index_repository import ImageIndexRepository
from .indexer_service import IndexerService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build EXIF search index")
    parser.add_argument("--folders", nargs="+", required=True, help="Folders to scan")
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--json", help="Optional JSON output path")
    parser.add_argument(
        "--workers",
        type=int,
        default=12,
        help="Number of parallel workers (default: 12)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    folders = [Path(p) for p in args.folders]
    db_path = Path(args.db)
    json_path = Path(args.json) if args.json else None
    repo = ImageIndexRepository(db_path)
    service = IndexerService(repo)
    count = service.build_index(folders, json_path, workers=args.workers)
    repo.close()
    print(f"Indexed {count} images")


if __name__ == "__main__":
    main()
