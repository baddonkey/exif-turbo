"""Device selection and on-demand accelerator installation for AI-Scan/search.

Backends fall into two groups:

- **No-download backends** (``cuda``, ``mps``, ``cpu``) — usable whenever the
  torch build already installed/bundled with the app happens to support them.
  Nothing is ever downloaded for these by this module.
- **Downloadable backends** (``rocm``; see ``directml`` note below) — require
  fetching a vendor-specific ``torch`` build into a user-writable "GPU
  runtime" directory (``~/.exif-turbo/gpu-runtime/<backend>/``) on explicit,
  informed user consent (see ``GpuBackendConsentDialog.qml``). That directory
  is prepended to ``sys.path`` so it shadows the frozen app's own CPU torch
  without touching the installed application at all.

AMD DirectML (Windows) spike result — NOT SUPPORTED:
    ``torch-directml``'s latest release (0.2.5.dev240914, Sept 2024) pins
    ``torch==2.4.1`` exactly and ships no Python 3.13 wheel. This project
    requires Python >=3.11 and currently runs a much newer torch (pulled in
    by ``open-clip-torch``/``transformers>=4.51,<6``); installing
    torch-directml would force a torch downgrade that breaks those packages.
    The package is also still "Development Status :: 3 - Alpha" and has not
    been updated since. Per the project plan, this descopes Phase 3 to a
    clear "not supported" message instead of a silently broken install.

The GPU-enabled preference is a module-level flag (mirrors the existing
``_cached_model`` module-level cache in ``ai_indexer_service.py``) rather than
a constructor argument, so every ``AiIndexerService`` instance and worker
picks it up without threading a parameter through every call site.
"""
from __future__ import annotations

import logging
import platform as _platform
import shutil
import subprocess
import sys
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..config import gpu_runtime_dir

_log = logging.getLogger(__name__)

# Backends that never need a runtime download — available whenever the
# installed torch build already supports them.
_NO_DOWNLOAD_BACKENDS = ("cuda", "mps", "cpu")

_INSTALLED_MARKER = ".installed"


@dataclass(frozen=True)
class BackendInfo:
    """Everything the consent screen needs to display for one backend."""

    key: str
    display_name: str
    supported: bool
    unsupported_reason: str = ""
    requires_download: bool = True
    index_url: str = ""
    package_spec: str = "torch"
    size_mb: int = 0
    license_name: str = ""
    license_url: str = ""
    risk_note: str = (
        "This installs unaudited-by-exif-turbo binaries from a third-party "
        "vendor, running with the same privileges as the application. Use at "
        "your own risk."
    )


_BACKEND_INFO: dict[str, BackendInfo] = {
    "cuda": BackendInfo(
        key="cuda",
        display_name="NVIDIA CUDA",
        supported=True,
        requires_download=True,
        # Verified via `pip index versions torch --index-url <this>` to have a
        # wheel matching the installed torch (2.13.0) for the current Python —
        # older tags (cu121/cu124/cu128/cu129) only go up to torch 2.6-2.11 and
        # fail with "Could not find a version that satisfies the requirement".
        # Re-verify the same way if this ever starts failing again.
        index_url="https://download.pytorch.org/whl/cu130",
        package_spec="torch",
        size_mb=3500,
        license_name="PyTorch (BSD-3-Clause) + NVIDIA CUDA runtime libraries (NVIDIA EULA)",
        license_url="https://github.com/pytorch/pytorch/blob/main/LICENSE",
    ),
    "rocm": BackendInfo(
        key="rocm",
        display_name="AMD ROCm",
        supported=True,
        requires_download=True,
        # ROCm wheels are Linux-only, so this can't be verified with `pip index
        # versions` from this Windows dev machine (it always reports "No
        # matching distribution" regardless of tag validity, since pip filters
        # by platform). Confirmed the rocm6.4 index directory itself exists and
        # is a current-looking snapshot; version-match still needs confirming
        # on an actual Linux box before relying on it.
        index_url="https://download.pytorch.org/whl/rocm6.4",
        package_spec="torch",
        size_mb=6000,
        license_name="PyTorch (BSD-3-Clause) + AMD ROCm runtime libraries",
        license_url="https://github.com/pytorch/pytorch/blob/main/LICENSE",
    ),
    "directml": BackendInfo(
        key="directml",
        display_name="AMD DirectML",
        supported=False,
        unsupported_reason=(
            "torch-directml requires torch==2.4.1 and has no Python 3.13 "
            "build — incompatible with this app's current torch/transformers "
            "versions. Not available."
        ),
        requires_download=True,
    ),
    "mps": BackendInfo(
        key="mps",
        display_name="Apple Metal (MPS)",
        supported=True,
        requires_download=False,
    ),
}

_gpu_enabled = False
_gpu_disabled_for_session = False
_paths_synced = False


def set_gpu_enabled(value: bool) -> None:
    """Set the user's GPU-acceleration preference (mirrors ``SettingsModel``)."""
    global _gpu_enabled
    _gpu_enabled = value


def is_gpu_enabled() -> bool:
    """Cheap, torch-free check of the current preference (no import cost)."""
    return _gpu_enabled and not _gpu_disabled_for_session


def downloadable_backend_for_platform() -> Optional[str]:
    """Return the one downloadable backend key relevant to this OS, if any.

    Only offer a vendor-specific runtime when its hardware can be detected.
    AMD's Windows path, DirectML, is unsupported — see module docstring.
    macOS needs no downloadable backend (MPS already works out of the box).
    """
    system = _platform.system()
    if system == "Darwin":
        return None
    if _has_nvidia_gpu():
        return "cuda"
    if system == "Linux" and _has_amd_gpu():
        return "rocm"
    return None


def _has_nvidia_gpu() -> bool:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return False
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _has_amd_gpu() -> bool:
    executable = shutil.which("lspci")
    if executable is None:
        return False
    try:
        result = subprocess.run(
            [executable], capture_output=True, text=True, timeout=5,
        )
    except OSError:
        return False
    output = result.stdout.lower()
    return result.returncode == 0 and "amd" in output and "vga" in output


def _ensure_runtime_on_path() -> None:
    """Prepend any previously-downloaded, installed runtime dir to sys.path.

    Idempotent per-process — safe to call from every ``detect_backend()``.
    """
    global _paths_synced
    if _paths_synced:
        return
    _paths_synced = True
    for backend in ("cuda", "rocm"):
        runtime_dir = gpu_runtime_dir(backend)
        if (runtime_dir / _INSTALLED_MARKER).is_file():
            path_str = str(runtime_dir)
            if path_str not in sys.path:
                sys.path.insert(0, path_str)


def detect_backend() -> str:
    """Return the best torch backend available without any extra download."""
    _ensure_runtime_on_path()
    try:
        import torch  # noqa: PLC0415
    except ImportError:
        return "cpu"
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"cudaGetDeviceCount\(\) returned cudaErrorNotSupported.*",
            category=UserWarning,
        )
        cuda_available = torch.cuda.is_available()
    if cuda_available:
        # A ROCm-built torch also reports itself via torch.cuda.* (HIP is
        # exposed through the same CUDA-shaped API); disambiguate via
        # torch.version.hip, which is only set on ROCm builds.
        if getattr(torch.version, "hip", None):
            return "rocm"
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def resolve_device():
    """Return the ``torch.device`` to use for model/tensor placement."""
    import torch  # noqa: PLC0415

    if not _gpu_enabled or _gpu_disabled_for_session:
        return torch.device("cpu")
    backend = detect_backend()
    # ROCm torch builds still use the "cuda" device string.
    return torch.device("cuda" if backend == "rocm" else backend)


def mark_gpu_failed(exc: Exception) -> None:
    """Record a GPU failure so the rest of the session falls back to CPU."""
    global _gpu_disabled_for_session
    if not _gpu_disabled_for_session:
        _log.warning("GPU acceleration disabled for this session after a failure: %s", exc)
    _gpu_disabled_for_session = True


def reset_session_state() -> None:
    """Test hook: clear the sticky GPU-failure flag."""
    global _gpu_disabled_for_session
    _gpu_disabled_for_session = False


def is_gpu_available() -> bool:
    """Whether a backend needing no extra download is currently usable."""
    return detect_backend() != "cpu"


def backend_display_name(backend: str) -> str:
    info = _BACKEND_INFO.get(backend)
    return info.display_name if info else backend


def backend_info(backend: str) -> Optional[BackendInfo]:
    return _BACKEND_INFO.get(backend)


def is_gpu_runtime_installed(backend: str) -> bool:
    # cuda can be "installed" either because it was downloaded (marker file)
    # or because the bundled torch already supports it natively — check the
    # marker first since it's cheaper and backend-specific.
    if (gpu_runtime_dir(backend) / _INSTALLED_MARKER).is_file():
        return True
    if backend in _NO_DOWNLOAD_BACKENDS:
        return detect_backend() == backend
    return False


def remove_gpu_runtime(backend: str) -> None:
    """Delete a downloaded accelerator runtime.

    No-op for backends that are never downloaded by this app (mps/cpu never
    are; cuda/rocm are only removed if this module itself downloaded them).
    """
    if backend in ("mps", "cpu"):
        return
    shutil.rmtree(gpu_runtime_dir(backend), ignore_errors=True)


def _pip_available() -> bool:
    command = _python_command()
    if command is None:
        return False
    try:
        result = subprocess.run(
            [*command, "-m", "pip", "--version"],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _python_command() -> Optional[list[str]]:
    """Return a command that can run pip outside a frozen application."""
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    for executable_name in ("python", "python3"):
        executable = shutil.which(executable_name)
        if executable is not None:
            return [executable]
    launcher = shutil.which("py")
    return [launcher, "-3"] if launcher is not None else None


def install_gpu_backend(
    backend: str,
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> tuple[bool, str]:
    """Download and install an accelerator runtime. Returns (success, message).

    Runs ``pip install --target=<dir> --index-url <backend index> torch`` as
    a subprocess so the frozen app's own environment is never modified — the
    result lives entirely under ``gpu_runtime_dir(backend)`` and is only
    added to ``sys.path`` by ``detect_backend()`` after a successful install.

    Known limitation: PyInstaller-frozen builds do not bundle ``pip``. If
    ``pip`` is unavailable this fails with a clear message rather than a
    silent/confusing error (flagged as an open risk in the project plan).
    """
    info = _BACKEND_INFO.get(backend)
    if info is None or not info.requires_download:
        return False, f"Backend '{backend}' is not a downloadable backend."
    if not info.supported:
        return False, info.unsupported_reason or f"Backend '{backend}' is not supported."
    if not _pip_available():
        return False, (
            "A Python interpreter with pip is not available — cannot "
            "install GPU packages automatically. This is a known limitation "
            "of frozen desktop builds; see project plan."
        )

    target_dir = gpu_runtime_dir(backend)
    parent_dir = target_dir.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{backend}-install-", dir=str(parent_dir))
    )

    python_command = _python_command()
    if python_command is None:
        shutil.rmtree(staging_dir, ignore_errors=True)
        return False, "A Python interpreter with pip is not available."
    cmd = [
        *python_command, "-m", "pip", "install",
        "--target", str(staging_dir),
        "--index-url", info.index_url,
        "--upgrade",
        info.package_spec,
    ]
    if on_progress:
        on_progress(f"Downloading {info.display_name} components...")
    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except OSError as exc:
        return False, f"Could not start pip: {exc}"

    tail: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            tail[:] = tail[-20:]
            if on_progress:
                on_progress(line)
        if cancel_check and cancel_check():
            process.terminate()
            return False, "Canceled."
    process.wait()

    if process.returncode != 0:
        shutil.rmtree(staging_dir, ignore_errors=True)
        return False, "Install failed:\n" + "\n".join(tail[-10:])

    (staging_dir / _INSTALLED_MARKER).write_text(info.package_spec, encoding="utf-8")
    try:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(staging_dir), str(target_dir))
    except OSError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        return False, (
            f"Install downloaded successfully, but could not replace the existing "
            f"GPU runtime at {target_dir}: {exc}. Close exif-turbo and remove "
            "that folder manually, then try again."
        )
    return True, f"{info.display_name} installed."

