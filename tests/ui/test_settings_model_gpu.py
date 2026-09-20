from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from exif_turbo.ui.models import settings_model as settings_model_module
from exif_turbo.ui.models.settings_model import SettingsModel


def test_gpu_acceleration_defaults_to_disabled(qtbot: QtBot, tmp_path: Path) -> None:
    # Arrange / Act
    model = SettingsModel(tmp_path / "settings.json")

    # Assert
    assert model.gpuAccelerationEnabled is False


def test_set_gpu_acceleration_enabled_is_ignored_without_a_backend(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_available", lambda: False
    )
    model = SettingsModel(tmp_path / "settings.json")

    # Act
    model.setGpuAccelerationEnabled(True)

    # Assert
    assert model.gpuAccelerationEnabled is False


def test_gpu_acceleration_enabled_persists_across_reload(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_available", lambda: True
    )
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)

    # Act
    model.setGpuAccelerationEnabled(True)
    reloaded = SettingsModel(settings_path)

    # Assert
    assert reloaded.gpuAccelerationEnabled is True


def test_remove_gpu_runtime_disables_acceleration(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_available", lambda: True
    )
    monkeypatch.setattr(settings_model_module.ai_device, "remove_gpu_runtime", lambda backend: None)
    model = SettingsModel(tmp_path / "settings.json")
    model.setGpuAccelerationEnabled(True)

    # Act
    model.removeGpuRuntime("cuda")

    # Assert
    assert model.gpuAccelerationEnabled is False


def test_gpu_installable_backend_is_empty_when_a_backend_is_already_available(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_available", lambda: True
    )
    model = SettingsModel(tmp_path / "settings.json")

    # Act / Assert
    assert model.gpuInstallableBackend == ""


def test_gpu_installable_backend_reflects_platform_when_unavailable(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_available", lambda: False
    )
    monkeypatch.setattr(
        settings_model_module.ai_device, "downloadable_backend_for_platform", lambda: "cuda"
    )
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_runtime_installed", lambda backend: False
    )
    model = SettingsModel(tmp_path / "settings.json")

    # Act / Assert
    assert model.gpuInstallableBackend == "cuda"


def test_gpu_installable_backend_is_empty_when_runtime_is_installed(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_available", lambda: False
    )
    monkeypatch.setattr(
        settings_model_module.ai_device, "downloadable_backend_for_platform", lambda: "cuda"
    )
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_runtime_installed", lambda backend: True
    )
    model = SettingsModel(tmp_path / "settings.json")

    # Act / Assert
    assert model.gpuRuntimeInstalled is True
    assert model.gpuInstallableBackend == ""


def test_gpu_restart_required_is_false_after_reload_when_runtime_is_unavailable(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_available", lambda: False
    )
    monkeypatch.setattr(
        settings_model_module.ai_device, "downloadable_backend_for_platform", lambda: "cuda"
    )
    monkeypatch.setattr(
        settings_model_module.ai_device, "is_gpu_runtime_installed", lambda backend: True
    )

    # Act
    model = SettingsModel(tmp_path / "settings.json")

    # Assert
    assert model.gpuRestartRequired is False


def test_gpu_backend_metadata_returns_dict_for_known_backend(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    model = SettingsModel(tmp_path / "settings.json")

    # Act
    meta = model.gpuBackendMetadata("cuda")

    # Assert
    assert meta["displayName"] == "NVIDIA CUDA"
    assert meta["supported"] is True
    assert meta["licenseUrl"]


def test_gpu_consent_is_required_before_install_and_persists(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)

    # Act / Assert
    assert model.hasGpuConsent("cuda") is False
    model.recordGpuConsent("cuda")
    assert model.hasGpuConsent("cuda") is True

    reloaded = SettingsModel(settings_path)
    assert reloaded.hasGpuConsent("cuda") is True


def test_start_gpu_backend_install_is_ignored_without_consent(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    started = []
    monkeypatch.setattr(
        settings_model_module, "GpuBackendInstallWorker", lambda backend: started.append(backend)
    )
    model = SettingsModel(tmp_path / "settings.json")

    # Act
    model.startGpuBackendInstall("cuda")

    # Assert
    assert started == []
    assert model.gpuInstallInProgress is False


def test_start_gpu_backend_install_runs_worker_with_consent(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    class _FakeWorker:
        def __init__(self, backend: str) -> None:
            self.backend = backend
            self.progress = _FakeSignal()
            self.finished = _FakeSignal()
            self.started = False

        def start(self) -> None:
            self.started = True
            self.finished.emit(True, "NVIDIA CUDA installed.")

        def cancel(self) -> None:
            pass

    class _FakeSignal:
        def __init__(self) -> None:
            self._slot = None

        def connect(self, slot) -> None:
            self._slot = slot

        def emit(self, *args) -> None:
            if self._slot:
                self._slot(*args)

    monkeypatch.setattr(settings_model_module, "GpuBackendInstallWorker", _FakeWorker)
    model = SettingsModel(tmp_path / "settings.json")
    model.recordGpuConsent("cuda")
    finished_calls = []
    model.gpuInstallFinished.connect(lambda ok, msg: finished_calls.append((ok, msg)))

    # Act
    model.startGpuBackendInstall("cuda")

    # Assert
    assert finished_calls == [(True, "NVIDIA CUDA installed.")]
    assert model.gpuInstallInProgress is False
    assert model.gpuRestartRequired is True
    assert "restart" in model.gpuInstallStatusText.lower()

