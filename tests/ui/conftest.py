from __future__ import annotations

import pytest
from PySide6.QtQuickControls2 import QQuickStyle


@pytest.fixture(scope="session", autouse=True)
def _set_material_style() -> None:
    """Configure Material style once before any QML engine is created."""
    QQuickStyle.setStyle("Material")
