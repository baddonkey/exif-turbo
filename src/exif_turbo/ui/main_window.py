from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from PySide6.QtCore import QModelIndex, QPoint, Qt, QUrl, QSize, QEvent, QTimer
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPolygon,
    QPixmap,
    QShortcut,
    QTextCursor,
    QTextDocument,
    QColor,
)
from PySide6.QtWidgets import (
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QToolButton,
)

from ..data.image_index_repository import ImageIndexRepository
from ..models.search_result import SearchResult
from .models.exif_table_model import ExifTableModel
from .models.search_model import SearchModel
from .workers.index_worker import IndexWorker
from .workers.thumb_worker import ThumbWorker


class ThumbCenterDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if index.column() == 0:
            pixmap = index.data(Qt.DecorationRole)
            if isinstance(pixmap, QPixmap):
                opt = QStyleOptionViewItem(option)
                self.initStyleOption(opt, index)
                style = opt.widget.style() if opt.widget else None
                if style:
                    style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)

                rect = opt.rect
                x = rect.x() + max(0, (rect.width() - pixmap.width()) // 2)
                y = rect.y() + max(0, (rect.height() - pixmap.height()) // 2)
                painter.drawPixmap(x, y, pixmap)
                return
        super().paint(painter, option, index)


class MainWindow(QMainWindow):
    def __init__(self, repo: ImageIndexRepository) -> None:
        super().__init__()
        self.repo = repo
        self.db_path = repo.db_path

        icon_path = Path(__file__).resolve().parent.parent / "assets" / "app_icon.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setWindowTitle("Exif-Turbo 1.0")
        self.resize(1000, 650)

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Full-text search (e.g. camera:Canon lens:50mm)")
        self.query_input.setClearButtonEnabled(True)

        self._clear_button_connected = False

        self.query_input.setMinimumHeight(42)

        self.search_button = QPushButton("")
        self.search_button.setObjectName("searchButton")
        self.index_button = QPushButton("Index folders")
        self.cancel_index_button = QPushButton("Cancel index")
        self.build_thumbs_button = QPushButton("Build thumbs")
        self.cancel_thumbs_button = QPushButton("Cancel thumbs")
        self.search_button.setMinimumHeight(44)
        self.index_button.setMinimumHeight(44)
        self.search_button.setMinimumWidth(60)
        self.search_button.setToolTip("Search")
        self.cancel_index_button.setMinimumHeight(44)
        self.cancel_index_button.setVisible(False)
        self.build_thumbs_button.setMinimumHeight(44)
        self.cancel_thumbs_button.setMinimumHeight(44)
        self.cancel_thumbs_button.setVisible(False)

        lense_icon_path = Path(__file__).resolve().parent.parent / "assets" / "lense.svg"
        if lense_icon_path.exists():
            self.search_button.setIcon(QIcon(str(lense_icon_path)))
            self.search_button.setIconSize(QSize(22, 22))

        self.page_size = 100

        self.export_csv_button = QPushButton("Export CSV")
        self.export_csv_button.setMinimumHeight(42)

        self.status_label = QLabel("Ready")

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select an image to see metadata")

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find in details")
        find_height = 36
        self.find_input.setMinimumHeight(find_height)
        self.find_prev_action = QAction(self)
        self.find_prev_action.setIcon(self._make_arrow_icon("up"))
        self.find_prev_action.setToolTip("Previous")
        self.find_next_action = QAction(self)
        self.find_next_action.setIcon(self._make_arrow_icon("down"))
        self.find_next_action.setToolTip("Next")
        self.find_input.addAction(self.find_prev_action, QLineEdit.TrailingPosition)
        self.find_input.addAction(self.find_next_action, QLineEdit.TrailingPosition)
        self.find_bar = QWidget()
        find_layout = QHBoxLayout()
        find_layout.setContentsMargins(0, 0, 6, 0)
        find_layout.setSpacing(8)
        find_layout.addWidget(QLabel("Find"))
        find_layout.addWidget(self.find_input, 1)
        self.find_bar.setLayout(find_layout)
        self.find_bar.setVisible(False)
        self.find_bar.setMaximumHeight(36)

        self.table = QTableView()
        self.model = SearchModel()
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(0, ThumbCenterDelegate(self.table))
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(150)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 240)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setMinimumHeight(36)
        self.table.verticalHeader().setMinimumSectionSize(150)

        self.exif_table = QTableView()
        self.exif_model = ExifTableModel()
        self.exif_table.setModel(self.exif_model)
        self.exif_table.horizontalHeader().setStretchLastSection(True)
        self.exif_table.verticalHeader().setDefaultSectionSize(32)
        self.exif_table.horizontalHeader().setMinimumHeight(32)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(200, 200)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._preview_pixmap = None

        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)
        top_layout.addWidget(self.query_input, 1)
        top_layout.addWidget(self.search_button)
        top_layout.addWidget(self.index_button)
        top_layout.addWidget(self.cancel_index_button)
        top_layout.addSpacing(6)
        top_layout.addWidget(self.build_thumbs_button)
        top_layout.addWidget(self.cancel_thumbs_button)
        top_layout.addWidget(self.export_csv_button)

        details_container = QWidget()
        details_layout = QVBoxLayout()
        details_layout.setSpacing(8)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_label = QLabel("Details")
        details_label.setFixedHeight(20)
        details_layout.addWidget(details_label)
        details_layout.addWidget(self.find_bar)
        details_splitter = QSplitter(Qt.Horizontal)
        details_splitter.addWidget(self.details)
        details_splitter.addWidget(self.exif_table)
        details_splitter.setStretchFactor(0, 1)
        details_splitter.setStretchFactor(1, 1)
        details_layout.addWidget(details_splitter)
        details_container.setLayout(details_layout)

        preview_container = QWidget()
        preview_layout = QVBoxLayout()
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        preview_layout.addWidget(self.preview_label, 1)
        preview_container.setLayout(preview_layout)

        self.top_splitter = QSplitter(Qt.Horizontal)
        self.top_splitter.addWidget(self.table)
        self.top_splitter.addWidget(preview_container)
        self.top_splitter.setStretchFactor(0, 3)
        self.top_splitter.setStretchFactor(1, 2)

        self.results_splitter = QSplitter(Qt.Vertical)
        self.results_splitter.addWidget(self.top_splitter)
        self.results_splitter.addWidget(details_container)
        self.results_splitter.setStretchFactor(0, 2)
        self.results_splitter.setStretchFactor(1, 1)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.results_splitter)
        main_layout.addWidget(self.status_label)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.apply_styles()

        self.search_button.clicked.connect(self.search)
        self.query_input.returnPressed.connect(self.search)
        self.query_input.textChanged.connect(self.on_query_changed)
        self.index_button.clicked.connect(self.index_folders)
        self.cancel_index_button.clicked.connect(self.cancel_index)
        self.build_thumbs_button.clicked.connect(self.build_thumbnails)
        self.cancel_thumbs_button.clicked.connect(self.cancel_thumbnails)
        self.export_csv_button.clicked.connect(self.export_csv)
        self.table.verticalScrollBar().valueChanged.connect(self.on_scroll)
        self.table.selectionModel().selectionChanged.connect(self.update_details)
        self.table.doubleClicked.connect(self.on_double_click)
        self.find_input.returnPressed.connect(self.find_next)
        self.find_next_action.triggered.connect(self.find_next)
        self.find_prev_action.triggered.connect(self.find_prev)
        self.top_splitter.splitterMoved.connect(lambda *_: self._render_preview_pixmap())
        self.results_splitter.splitterMoved.connect(lambda *_: self._render_preview_pixmap())
        self.shortcut_find = QShortcut(QKeySequence.Find, self)
        self.shortcut_find.activated.connect(self.show_find_bar)
        self.shortcut_find_next = QShortcut(QKeySequence.FindNext, self)
        self.shortcut_find_next.activated.connect(self.find_next)
        self.shortcut_find_prev = QShortcut(QKeySequence.FindPrevious, self)
        self.shortcut_find_prev.activated.connect(self.find_prev)

        self.query_input.installEventFilter(self)
        self._hook_clear_button()
        self.search()

    def _make_arrow_icon(self, direction: str) -> QIcon:
        size = 14
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#5a6b86"))
        painter.setPen(Qt.NoPen)
        if direction == "up":
            points = [
                QPoint(size // 2, 3),
                QPoint(size - 3, size - 3),
                QPoint(3, size - 3),
            ]
        else:
            points = [
                QPoint(3, 3),
                QPoint(size - 3, 3),
                QPoint(size // 2, size - 3),
            ]
        painter.drawPolygon(QPolygon(points))
        painter.end()
        return QIcon(pixmap)

    def apply_styles(self) -> None:
        base_font = QFont("Segoe UI", 11)
        self.setFont(base_font)
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f5f7fb;
            }
            QWidget {
                color: #1f2a44;
            }
            QLineEdit {
                background: #ffffff;
                border: 1px solid #d6dde8;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 12pt;
            }
            QTextEdit {
                background: #ffffff;
                border: 1px solid #d6dde8;
                border-radius: 8px;
                padding: 10px;
                font-size: 11pt;
            }
            QTableView {
                background: #ffffff;
                border: 1px solid #d6dde8;
                border-radius: 8px;
                gridline-color: #e6ecf5;
                font-size: 11pt;
                selection-background-color: #dbeafe;
                selection-color: #1f2a44;
            }
            QTableView::item {
                padding: 6px 8px;
            }
            QTableView::item:selected {
                background: #dbeafe;
                color: #1f2a44;
            }
            QTableView::item:selected:active {
                background: #cfe5ff;
            }
            QTableView::item:focus {
                outline: none;
            }
            QHeaderView::section {
                background: #f0f4fa;
                color: #5a6b86;
                border: none;
                padding: 6px 10px;
                font-size: 10.5pt;
            }
            QPushButton {
                background: #1976d2;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-weight: 600;
                font-size: 11pt;
                min-height: 42px;
            }
            QPushButton#searchButton {
                font-size: 18pt;
                padding: 4px 10px;
                min-width: 64px;
                min-height: 48px;
            }
            QPushButton:hover {
                background: #1565c0;
            }
            QPushButton:pressed {
                background: #0d47a1;
            }
            QPushButton:disabled {
                background: #c5d1e6;
                color: #ffffff;
            }
            QLabel {
                color: #4b5b78;
            }
            QLabel#previewLabel {
                background: #ffffff;
                border: 1px solid #d6dde8;
                border-radius: 8px;
            }
            QSplitter::handle {
                background: #e6ecf5;
            }
            """
        )

    def search(self) -> None:
        query = self.query_input.text().strip()
        page_size = self.page_size
        rows = self.repo.search_images(query, page_size, 0)
        results = [SearchResult(path=r[1], filename=r[2], metadata_json=r[3]) for r in rows]
        self.model.set_rows(results)

        total = self.repo.count_images(query)
        self.status_label.setText(f"{len(results)} of {total} results")
        self._loaded = len(results)
        self._total = total
        self._loading = False
        self.update_details()
        self.update_details_highlight()

    def on_query_changed(self, text: str) -> None:
        if not text.strip():
            if getattr(self, "_clear_triggered", False):
                self._clear_triggered = False
                return
            self.search()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.query_input and event.type() == QEvent.ChildAdded:
            self._hook_clear_button()
        return super().eventFilter(obj, event)

    def _hook_clear_button(self) -> None:
        if self._clear_button_connected:
            return
        button = self.query_input.findChild(QToolButton, "qt_clear_button")
        if button is not None:
            button.clicked.connect(self.on_clear_clicked)
            self._clear_button_connected = True

    def on_clear_clicked(self) -> None:
        if self.query_input.text().strip():
            self._clear_triggered = True
        QTimer.singleShot(0, self.search)

    def on_scroll(self) -> None:
        if getattr(self, "_loading", False):
            return
        if getattr(self, "_loaded", 0) >= getattr(self, "_total", 0):
            return
        bar = self.table.verticalScrollBar()
        if bar.maximum() - bar.value() > 200:
            return
        self.load_more()

    def load_more(self) -> None:
        self._loading = True
        query = self.query_input.text().strip()
        page_size = self.page_size
        offset = getattr(self, "_loaded", 0)
        rows = self.repo.search_images(query, page_size, offset)
        results = [SearchResult(path=r[1], filename=r[2], metadata_json=r[3]) for r in rows]
        self.model.append_rows(results)
        self._loaded = offset + len(results)
        self.status_label.setText(f"{self._loaded} of {self._total} results")
        self._loading = False

    def update_details(self) -> None:
        row = self.table.currentIndex().row()
        meta_json = self.model.get_metadata_json(row)
        path = self.model.get_path(row)
        if not meta_json:
            self.details.setPlainText("")
            self.details.setExtraSelections([])
            self.exif_model.set_rows([])
            self.preview_label.clear()
            self._preview_pixmap = None
            return
        try:
            parsed = json.loads(meta_json)
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            self.details.setPlainText(pretty)
        except Exception:
            self.details.setPlainText(meta_json)
        self.update_details_highlight()
        self.update_exif_table(meta_json)
        self.update_preview_image(path)

    def update_exif_table(self, meta_json: str) -> None:
        try:
            parsed = json.loads(meta_json)
            if isinstance(parsed, dict):
                rows = [(str(k), str(v)) for k, v in parsed.items()]
                rows.sort(key=lambda r: r[0].lower())
                self.exif_model.set_rows(rows)
                return
        except Exception:
            pass
        self.exif_model.set_rows([])

    def update_details_highlight(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            self.details.setExtraSelections([])
            return

        selections = []
        doc = self.details.document()
        cursor = self.details.textCursor()
        cursor.movePosition(QTextCursor.Start)
        fmt = cursor.charFormat()
        fmt.setBackground(Qt.yellow)

        while True:
            cursor = doc.find(query, cursor, QTextDocument.FindFlags())
            if cursor.isNull():
                break
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = fmt
            selections.append(selection)

        self.details.setExtraSelections(selections)

    def show_find_bar(self) -> None:
        if self.find_bar.isVisible():
            self.find_bar.setVisible(False)
            self.details.setFocus()
            return
        self.find_bar.setVisible(True)
        self.find_input.setText(self.query_input.text().strip())
        self.find_input.setFocus()
        self.find_input.selectAll()

    def find_next(self) -> None:
        text = self.find_input.text()
        if not text:
            return
        found = self.details.find(text, QTextDocument.FindFlags())
        if not found:
            cursor = self.details.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.details.setTextCursor(cursor)
            self.details.find(text, QTextDocument.FindFlags())

    def find_prev(self) -> None:
        text = self.find_input.text()
        if not text:
            return
        found = self.details.find(text, QTextDocument.FindBackward)
        if not found:
            cursor = self.details.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.details.setTextCursor(cursor)
            self.details.find(text, QTextDocument.FindBackward)

    def update_preview_image(self, path: str | None = None) -> None:
        if path is None:
            row = self.table.currentIndex().row()
            path = self.model.get_path(row)
        if not path or not os.path.exists(path):
            self.preview_label.clear()
            self._preview_pixmap = None
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview_label.clear()
            self._preview_pixmap = None
            return
        self._preview_pixmap = pixmap
        self._render_preview_pixmap()

    def _render_preview_pixmap(self) -> None:
        if not getattr(self, "_preview_pixmap", None):
            return
        pixmap: QPixmap = self._preview_pixmap
        label_size = self.preview_label.size()
        if label_size.width() <= 0 or label_size.height() <= 0:
            return
        base_scale = min(
            label_size.width() / pixmap.width(),
            label_size.height() / pixmap.height(),
            1.0,
        )
        scale = min(base_scale, 1.0)
        target_w = max(1, int(pixmap.width() * scale))
        target_h = max(1, int(pixmap.height() * scale))
        scaled = pixmap.scaled(
            target_w,
            target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

    def index_folders(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder to index")
        if not folder:
            return
        self.clear_thumbnail_cache()
        self.status_label.setText("Indexing...")
        self.index_button.setEnabled(False)
        self.cancel_index_button.setVisible(True)
        self.cancel_index_button.setEnabled(True)
        self.worker = IndexWorker(self.db_path, [Path(folder)], workers=12)
        self.worker.finished.connect(self.on_index_done)
        self.worker.failed.connect(self.on_index_failed)
        self.worker.progress.connect(self.on_index_progress)
        self.worker.canceled.connect(self.on_index_canceled)
        self.worker.start()

    def on_index_done(self, count: int) -> None:
        self.index_button.setEnabled(True)
        self.cancel_index_button.setVisible(False)
        self.status_label.setText(f"Indexed {count} images")
        self.search()

    def on_index_failed(self, error: str) -> None:
        self.index_button.setEnabled(True)
        self.cancel_index_button.setVisible(False)
        QMessageBox.critical(self, "Index error", error)
        self.status_label.setText("Index failed")

    def on_index_canceled(self, count: int) -> None:
        self.index_button.setEnabled(True)
        self.cancel_index_button.setVisible(False)
        self.status_label.setText("Index canceled")
        self.search()

    def cancel_index(self) -> None:
        if getattr(self, "worker", None) and self.worker.isRunning():
            self.cancel_index_button.setEnabled(False)
            self.status_label.setText("Canceling...")
            self.worker.cancel()

    def clear_thumbnail_cache(self) -> None:
        cache_dir = Path(tempfile.gettempdir()) / "exif_turbo_thumbs"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

    def build_thumbnails(self) -> None:
        rows = self.repo.all_images()
        paths = [r[0] for r in rows]
        if not paths:
            QMessageBox.information(self, "Build thumbs", "No images indexed.")
            return
        self.build_thumbs_button.setEnabled(False)
        self.cancel_thumbs_button.setVisible(True)
        self.cancel_thumbs_button.setEnabled(True)
        self.status_label.setText("Building thumbnails...")
        cache_dir = self.model._cache_dir
        max_bytes = self.model._max_thumb_bytes
        self.thumb_worker = ThumbWorker(paths, cache_dir, max_bytes, workers=12)
        self.thumb_worker.progress.connect(self.on_thumb_progress)
        self.thumb_worker.finished.connect(self.on_thumb_done)
        self.thumb_worker.failed.connect(self.on_thumb_failed)
        self.thumb_worker.canceled.connect(self.on_thumb_canceled)
        self.thumb_worker.start()

    def on_thumb_progress(self, current: int, total: int, path: str) -> None:
        self.status_label.setText(f"Building thumbnails... {current} / {total}")

    def on_thumb_done(self, cached: int, total: int) -> None:
        self.build_thumbs_button.setEnabled(True)
        self.cancel_thumbs_button.setVisible(False)
        self.status_label.setText(f"Thumbnails cached: {cached} / {total}")
        self._render_preview_pixmap()

    def on_thumb_failed(self, error: str) -> None:
        self.build_thumbs_button.setEnabled(True)
        self.cancel_thumbs_button.setVisible(False)
        QMessageBox.critical(self, "Build thumbs", error)
        self.status_label.setText("Build thumbs failed")

    def on_thumb_canceled(self, cached: int, total: int) -> None:
        self.build_thumbs_button.setEnabled(True)
        self.cancel_thumbs_button.setVisible(False)
        self.status_label.setText("Build thumbs canceled")

    def cancel_thumbnails(self) -> None:
        if getattr(self, "thumb_worker", None) and self.thumb_worker.isRunning():
            self.cancel_thumbs_button.setEnabled(False)
            self.status_label.setText("Canceling thumbs...")
            self.thumb_worker.cancel()

    def on_index_progress(self, current: int, total: int, path: str) -> None:
        self.status_label.setText(f"Indexing... {current} / {total}")

    def open_image(self) -> None:
        row = self.table.currentIndex().row()
        path = self.model.get_path(row)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_folder(self) -> None:
        row = self.table.currentIndex().row()
        path = self.model.get_path(row)
        if not path:
            return
        if os.name == "nt":
            normalized = os.path.normpath(path)
            subprocess.Popen(["explorer", "/select,", normalized])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def on_double_click(self, index: QModelIndex) -> None:
        if index.column() == 2:
            path = self.model.get_path(index.row())
            if not path:
                return
            if os.name == "nt":
                normalized = os.path.normpath(path)
                subprocess.Popen(["explorer", "/select,", normalized])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
            return
        self.open_image()

    def export_csv(self) -> None:
        query = self.query_input.text().strip()
        total = self.repo.count_images(query)
        if total == 0:
            QMessageBox.information(self, "Export CSV", "No results to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            "exif_export.csv",
            "CSV Files (*.csv)",
        )
        if not file_path:
            return

        batch_size = 500
        offset = 0
        records: List[dict] = []
        all_keys: set[str] = set()

        while offset < total:
            rows = self.repo.search_images(query, batch_size, offset)
            for r in rows:
                meta = {}
                try:
                    parsed = json.loads(r[3])
                    if isinstance(parsed, dict):
                        meta = self.flatten_metadata(parsed)
                except Exception:
                    meta = {}
                all_keys.update(meta.keys())
                records.append({"path": r[1], "filename": r[2], **meta})
            offset += batch_size

        headers = ["path", "filename"] + sorted(all_keys)
        with open(file_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                writer.writerow(record)
        QMessageBox.information(self, "Export CSV", "CSV export completed.")

    def flatten_metadata(self, metadata: dict) -> dict:
        flat: dict = {}
        for key, value in metadata.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    flat[f"{key}:{sub_key}"] = str(sub_value)
            else:
                flat[str(key)] = str(value)
        return flat
