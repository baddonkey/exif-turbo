"""Tests for the frozen-app entrypoint bootstrap."""
from __future__ import annotations

import builtins
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
    monkeypatch.setitem(sys.modules, "triton", _make_package("triton"))
    monkeypatch.setitem(sys.modules, "triton._C", _make_package("triton._C"))
    monkeypatch.setitem(
        sys.modules, "triton._C.libtriton", _make_module("triton._C.libtriton")
    )
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


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_app_import_platform_preloads_triton_only_before_linux_ui(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    _install_entrypoint_stubs(monkeypatch)
    monkeypatch.setattr(sys, "platform", platform)
    imports: list[str] = []
    original_import = builtins.__import__

    def record_import(name: str, *args: object, **kwargs: object) -> ModuleType:
        imports.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", record_import)
    monkeypatch.delitem(sys.modules, "exif_turbo.app", raising=False)

    importlib.import_module("exif_turbo.app")

    if platform == "linux":
        assert imports.index("triton._C.libtriton") < imports.index("exif_turbo.ui.app_main")
    else:
        assert "triton._C.libtriton" not in imports


def test_app_import_triton_unavailable_still_loads_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entrypoint_stubs(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "triton", None)
    monkeypatch.delitem(sys.modules, "triton._C", raising=False)
    monkeypatch.delitem(sys.modules, "triton._C.libtriton", raising=False)
    monkeypatch.delitem(sys.modules, "exif_turbo.app", raising=False)

    app_module = importlib.import_module("exif_turbo.app")

    assert callable(app_module.main)