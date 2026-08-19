from __future__ import annotations

import logging

import pytest
from PySide6.QtCore import QtMsgType

from exif_turbo.ui.app_main import (
    _configure_third_party_logging,
    _qt_message_handler,
)


def test_qt_message_handler_invalid_cmyk_profile_logs_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    message = (
        "libpng warning: iCCP: profile 'ICC Profile': 'CMYK': "
        "invalid ICC profile color space"
    )

    # Act
    with caplog.at_level(logging.DEBUG, logger="qt"):
        _qt_message_handler(QtMsgType.QtWarningMsg, None, message)

    # Assert
    records = caplog.records
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG


def test_qt_message_handler_other_warning_remains_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    message = "A real Qt warning"

    # Act
    with caplog.at_level(logging.DEBUG, logger="qt"):
        _qt_message_handler(QtMsgType.QtWarningMsg, None, message)

    # Assert
    records = caplog.records
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING


def test_configure_third_party_logging_hides_faiss_loader_info() -> None:
    # Arrange
    logger = logging.getLogger("faiss.loader")
    original_level = logger.level

    try:
        # Act
        logger.setLevel(logging.NOTSET)
        _configure_third_party_logging()

        # Assert
        assert logger.level == logging.WARNING
        assert logger.isEnabledFor(logging.INFO) is False
    finally:
        logger.setLevel(original_level)