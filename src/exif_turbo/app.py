from __future__ import annotations

from exif_turbo.ui.app_main import main
from exif_turbo.ui.models.exif_list_model import ExifListModel
from exif_turbo.ui.models.search_list_model import SearchListModel
from exif_turbo.ui.view_models.app_controller import AppController
from exif_turbo.ui.workers.index_worker import IndexWorker
from exif_turbo.ui.workers.thumb_worker import ThumbWorker

__all__ = [
    "main",
    "AppController",
    "ExifListModel",
    "SearchListModel",
    "IndexWorker",
    "ThumbWorker",
]


if __name__ == "__main__":
    main()
