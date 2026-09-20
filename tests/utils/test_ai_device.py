from __future__ import annotations

import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from exif_turbo.utils import ai_device


@pytest.fixture(autouse=True)
def _reset_ai_device_state():
    # Arrange / cleanup: ai_device holds module-level state (mirrors the
    # existing _cached_model pattern in ai_indexer_service.py).
    ai_device.set_gpu_enabled(False)
    ai_device.reset_session_state()
    yield
    ai_device.set_gpu_enabled(False)
    ai_device.reset_session_state()


def test_resolve_device_returns_cpu_when_gpu_disabled() -> None:
    # Arrange
    ai_device.set_gpu_enabled(False)

    # Act
    device = ai_device.resolve_device()

    # Assert
    assert device.type == "cpu"


def test_is_gpu_enabled_reflects_set_gpu_enabled() -> None:
    # Act / Assert
    assert ai_device.is_gpu_enabled() is False
    ai_device.set_gpu_enabled(True)
    assert ai_device.is_gpu_enabled() is True


def test_mark_gpu_failed_disables_gpu_for_the_session() -> None:
    # Arrange
    ai_device.set_gpu_enabled(True)
    assert ai_device.is_gpu_enabled() is True

    # Act
    ai_device.mark_gpu_failed(RuntimeError("boom"))

    # Assert
    assert ai_device.is_gpu_enabled() is False
    assert ai_device.resolve_device().type == "cpu"


def test_reset_session_state_clears_gpu_failure_flag() -> None:
    # Arrange
    ai_device.set_gpu_enabled(True)
    ai_device.mark_gpu_failed(RuntimeError("boom"))
    assert ai_device.is_gpu_enabled() is False

    # Act
    ai_device.reset_session_state()

    # Assert
    assert ai_device.is_gpu_enabled() is True


def test_backend_display_name_returns_readable_labels() -> None:
    # Act / Assert
    assert ai_device.backend_display_name("cuda") == "NVIDIA CUDA"
    assert ai_device.backend_display_name("mps") == "Apple Metal (MPS)"
    assert ai_device.backend_display_name("unknown-backend") == "unknown-backend"


def test_detect_backend_unsupported_cuda_probe_returns_cpu_without_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            warnings.warn(
                "cudaGetDeviceCount() returned cudaErrorNotSupported, likely using older driver",
                UserWarning,
            )
            return False

    fake_torch = SimpleNamespace(
        cuda=_Cuda(),
        backends=SimpleNamespace(mps=None),
        version=SimpleNamespace(hip=None),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    # Act
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        backend = ai_device.detect_backend()

    # Assert
    assert backend == "cpu"
    assert caught == []


def test_remove_gpu_runtime_is_a_noop_for_backends_that_are_never_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    called = []
    monkeypatch.setattr(ai_device.shutil, "rmtree", lambda *a, **k: called.append(a))

    # Act
    ai_device.remove_gpu_runtime("mps")
    ai_device.remove_gpu_runtime("cpu")

    # Assert
    assert called == []


def test_remove_gpu_runtime_deletes_the_downloaded_backend_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    runtime_dir = tmp_path / "gpu-runtime" / "directml"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "marker.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ai_device, "gpu_runtime_dir", lambda backend: runtime_dir)

    # Act
    ai_device.remove_gpu_runtime("directml")

    # Assert
    assert not runtime_dir.exists()


def test_directml_backend_is_marked_unsupported() -> None:
    # Act
    info = ai_device.backend_info("directml")

    # Assert
    assert info is not None
    assert info.supported is False
    assert "torch==2.4.1" in info.unsupported_reason


def test_downloadable_backend_for_platform_is_none_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(ai_device._platform, "system", lambda: "Darwin")

    # Act / Assert
    assert ai_device.downloadable_backend_for_platform() is None


def test_downloadable_backend_for_platform_is_cuda_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(ai_device._platform, "system", lambda: "Windows")

    # Act / Assert
    assert ai_device.downloadable_backend_for_platform() == "cuda"


def test_install_gpu_backend_rejects_unsupported_backend() -> None:
    # Act
    success, message = ai_device.install_gpu_backend("directml")

    # Assert
    assert success is False
    assert "torch==2.4.1" in message


def test_install_gpu_backend_fails_clearly_without_pip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(ai_device, "_pip_available", lambda: False)

    # Act
    success, message = ai_device.install_gpu_backend("cuda")

    # Assert
    assert success is False
    assert "pip is not available" in message


def test_install_gpu_backend_succeeds_and_writes_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    runtime_dir = tmp_path / "gpu-runtime" / "cuda"
    monkeypatch.setattr(ai_device, "gpu_runtime_dir", lambda backend: runtime_dir)
    monkeypatch.setattr(ai_device, "_pip_available", lambda: True)

    class _FakeProcess:
        returncode = 0
        stdout = iter(["Collecting torch", "Successfully installed torch"])

        def wait(self) -> None:
            pass

    monkeypatch.setattr(
        ai_device.subprocess, "Popen", lambda *a, **k: _FakeProcess()
    )
    progress_lines: list[str] = []

    # Act
    success, message = ai_device.install_gpu_backend(
        "cuda", on_progress=progress_lines.append
    )

    # Assert
    assert success is True
    assert (runtime_dir / ai_device._INSTALLED_MARKER).is_file()
    assert not list(runtime_dir.parent.glob(".cuda-install-*"))
    assert any("Successfully installed torch" in line for line in progress_lines)


def test_install_gpu_backend_cleans_up_on_pip_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    runtime_dir = tmp_path / "gpu-runtime" / "cuda"
    monkeypatch.setattr(ai_device, "gpu_runtime_dir", lambda backend: runtime_dir)
    monkeypatch.setattr(ai_device, "_pip_available", lambda: True)

    class _FakeProcess:
        returncode = 1
        stdout = iter(["ERROR: could not find a version that satisfies"])

        def wait(self) -> None:
            pass

    monkeypatch.setattr(
        ai_device.subprocess, "Popen", lambda *a, **k: _FakeProcess()
    )

    # Act
    success, message = ai_device.install_gpu_backend("cuda")

    # Assert
    assert success is False
    assert "Install failed" in message
    assert not runtime_dir.exists()
    assert not list(runtime_dir.parent.glob(".cuda-install-*"))


def test_install_gpu_backend_replaces_existing_partial_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    runtime_dir = tmp_path / "gpu-runtime" / "cuda"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "partial.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(ai_device, "gpu_runtime_dir", lambda backend: runtime_dir)
    monkeypatch.setattr(ai_device, "_pip_available", lambda: True)

    class _FakeProcess:
        returncode = 0
        stdout = iter(["Successfully installed torch"])

        def wait(self) -> None:
            pass

    monkeypatch.setattr(
        ai_device.subprocess, "Popen", lambda *a, **k: _FakeProcess()
    )

    # Act
    success, message = ai_device.install_gpu_backend("cuda")

    # Assert
    assert success is True
    assert not (runtime_dir / "partial.txt").exists()
    assert (runtime_dir / ai_device._INSTALLED_MARKER).is_file()


def test_is_gpu_runtime_installed_checks_marker_for_downloadable_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    runtime_dir = tmp_path / "gpu-runtime" / "cuda"
    runtime_dir.mkdir(parents=True)
    monkeypatch.setattr(ai_device, "gpu_runtime_dir", lambda backend: runtime_dir)

    # Act / Assert
    assert ai_device.is_gpu_runtime_installed("cuda") is False
    (runtime_dir / ai_device._INSTALLED_MARKER).write_text("torch", encoding="utf-8")
    assert ai_device.is_gpu_runtime_installed("cuda") is True
