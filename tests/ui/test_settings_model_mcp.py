from __future__ import annotations

import json
from pathlib import Path

from exif_turbo.ui.models.settings_model import SettingsModel


def test_mcp_settings_default_disabled_localhost(tmp_path: Path) -> None:
    # Arrange / Act
    model = SettingsModel(tmp_path / "settings.json")

    # Assert
    assert model.mcpEnabled is False
    assert model.mcpHost == "127.0.0.1"
    assert model.mcpPort == 8765


def test_mcp_settings_persist_enabled_host_and_port(tmp_path: Path) -> None:
    # Arrange
    settings_path = tmp_path / "settings.json"
    model = SettingsModel(settings_path)

    # Act
    model.setMcpEnabled(True)
    model.setMcpHost(" 127.0.0.1 ")
    model.setMcpPort(9001)
    reloaded = SettingsModel(settings_path)
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))

    # Assert
    assert reloaded.mcpEnabled is True
    assert reloaded.mcpHost == "127.0.0.1"
    assert reloaded.mcpPort == 9001
    assert persisted["mcpEnabled"] is True
    assert persisted["mcpHost"] == "127.0.0.1"
    assert persisted["mcpPort"] == 9001


def test_mcp_settings_clamp_port_and_fallback_empty_host(tmp_path: Path) -> None:
    # Arrange
    model = SettingsModel(tmp_path / "settings.json")

    # Act
    model.setMcpPort(70000)
    high_port = model.mcpPort
    model.setMcpPort(0)
    low_port = model.mcpPort
    model.setMcpHost("   ")

    # Assert
    assert high_port == 65535
    assert low_port == 1
    assert model.mcpHost == "127.0.0.1"
