from __future__ import annotations

import pytest
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWebEngineQuick import QtWebEngineQuick


def pytest_configure(config: pytest.Config) -> None:
    """Called before QApplication is created — required for WebEngine init."""
    QQuickStyle.setStyle("Material")
    QtWebEngineQuick.initialize()
