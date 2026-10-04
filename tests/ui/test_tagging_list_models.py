from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models.free_tag_list_model import FreeTagListModel


def test_free_tag_list_model_exposes_label_rows(qtbot: QtBot) -> None:
    # Arrange
    model = FreeTagListModel()

    # Act
    model.set_rows(("Family", "Summer 2026"))

    # Assert
    assert model.rowCount() == 2
    assert model.data(model.index(0), model.LabelRole) == "Family"
    assert model.data(model.index(1), Qt.DisplayRole) == "Summer 2026"

