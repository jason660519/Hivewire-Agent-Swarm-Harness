"""Tests for the one-click local console launcher."""
from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "open_hivewire_console.sh"
COMMAND_LAUNCHER = ROOT / "open_hivewire_console.command"
SCHEDULER_SETUP = ROOT / "setup_hivewire_benchmark_scheduler.sh"
SCHEDULER_INSTALL = ROOT / "install_hivewire_benchmark_scheduler.sh"
SCHEDULER_UNINSTALL = ROOT / "uninstall_hivewire_benchmark_scheduler.sh"


def test_one_click_console_launcher_exists_and_opens_single_port_home():
    text = LAUNCHER.read_text()

    assert os.access(LAUNCHER, os.X_OK)
    assert "co-routing" in text
    assert "benchmark.dashboard" in text
    assert 'URL="http://127.0.0.1:${PORT}/"' in text
    assert "HIVEWIRE_CONSOLE_PORT" in text
    assert "mock_dashboard" not in text


def test_macos_command_launcher_delegates_to_shell_script():
    text = COMMAND_LAUNCHER.read_text()

    assert os.access(COMMAND_LAUNCHER, os.X_OK)
    assert "open_hivewire_console.sh" in text


def test_scheduler_setup_script_is_safe_and_does_not_install_launchd():
    text = SCHEDULER_SETUP.read_text()

    assert os.access(SCHEDULER_SETUP, os.X_OK)
    assert "co-routing" in text
    assert "profiles.yaml.example" in text
    assert "benchmark.scheduler" in text
    assert "HIVEWIRE_BENCHMARK_PROFILE" in text
    assert "launchctl bootstrap" in text
    assert "DRY-RUN" in text
    assert "launchctl bootstrap gui" not in text


def test_scheduler_install_script_requires_explicit_confirmation():
    text = SCHEDULER_INSTALL.read_text()

    assert os.access(SCHEDULER_INSTALL, os.X_OK)
    assert "setup_hivewire_benchmark_scheduler.sh" in text
    assert "HIVEWIRE_CONFIRM_INSTALL" in text
    assert "install" in text
    assert "launchctl bootstrap" in text
    assert "com.hivewire.benchmark.${PROFILE}" in text
    assert "PLIST_PATH" in text


def test_scheduler_uninstall_script_requires_explicit_confirmation():
    text = SCHEDULER_UNINSTALL.read_text()

    assert os.access(SCHEDULER_UNINSTALL, os.X_OK)
    assert "HIVEWIRE_CONFIRM_UNINSTALL" in text
    assert "uninstall" in text
    assert "launchctl bootout" in text
    assert "com.hivewire.benchmark.${PROFILE}" in text
    assert "PLIST_PATH" in text
