"""Tests for the frozen-app entrypoint bootstrap."""
from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


def _make_module(name: str, **attrs: object) -> ModuleType:
    module = ModuleType(name)
    for attr_name, value in attrs.items():
        setattr(module, attr_name, value)
    return module


def _make_package(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []
    return module


def _install_entrypoint_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "exif_turbo.ui", _make_package("exif_turbo.ui"))
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.models",
        _make_package("exif_turbo.ui.models"),
    )
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.view_models",
        _make_package("exif_turbo.ui.view_models"),
    )
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.workers",
        _make_package("exif_turbo.ui.workers"),
    )
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.app_main",
        _make_module("exif_turbo.ui.app_main", main=lambda: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.models.exif_list_model",
        _make_module(
            "exif_turbo.ui.models.exif_list_model",
            ExifListModel=type("ExifListModel", (), {}),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.models.search_list_model",
        _make_module(
            "exif_turbo.ui.models.search_list_model",
            SearchListModel=type("SearchListModel", (), {}),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.view_models.app_controller",
        _make_module(
            "exif_turbo.ui.view_models.app_controller",
            AppController=type("AppController", (), {}),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.workers.index_worker",
        _make_module(
            "exif_turbo.ui.workers.index_worker",
            IndexWorker=type("IndexWorker", (), {}),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "exif_turbo.ui.workers.thumb_worker",
        _make_module(
            "exif_turbo.ui.workers.thumb_worker",
            ThumbWorker=type("ThumbWorker", (), {}),
        ),
    )


def test_app_import_bootstraps_missing_standard_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _install_entrypoint_stubs(monkeypatch)
    monkeypatch.setattr(sys, "stdin", None, raising=False)
    monkeypatch.setattr(sys, "stdout", None, raising=False)
    monkeypatch.setattr(sys, "stderr", None, raising=False)
    sys.modules.pop("exif_turbo.app", None)

    # Act
    importlib.import_module("exif_turbo.app")

    # Assert
    assert sys.stdin is not None and sys.stdout is not None and sys.stderr is not None