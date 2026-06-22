"""Tests for scheduled benchmark run profiles."""
from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.profiles import load_profiles, resolve_profile
from benchmark.scheduler import build_launchd_plist, collect_scheduler_status


def test_load_profiles_reads_named_profiles(tmp_path: Path):
    path = tmp_path / "profiles.yaml"
    path.write_text(
        """
profiles:
  weekly-proxycheap-baseline:
    cadence: weekly
    config: targets.yaml
    out: results.jsonl
    archive_dir: runs
    description: Proxy-cheap baseline
"""
    )

    profiles = load_profiles(path)

    assert profiles["weekly-proxycheap-baseline"]["cadence"] == "weekly"
    assert profiles["weekly-proxycheap-baseline"]["description"] == "Proxy-cheap baseline"


def test_resolve_profile_expands_paths_relative_to_profiles_file(tmp_path: Path):
    path = tmp_path / "profiles.yaml"
    path.write_text(
        """
profiles:
  weekly-proxycheap-baseline:
    cadence: weekly
    config: targets.yaml
    out: results.jsonl
    archive_dir: runs
"""
    )

    profile = resolve_profile(path, "weekly-proxycheap-baseline")

    assert profile["name"] == "weekly-proxycheap-baseline"
    assert profile["cadence"] == "weekly"
    assert profile["config_path"] == tmp_path / "targets.yaml"
    assert profile["out_path"] == tmp_path / "results.jsonl"
    assert profile["archive_dir"] == tmp_path / "runs"


def test_resolve_profile_rejects_unknown_profile(tmp_path: Path):
    path = tmp_path / "profiles.yaml"
    path.write_text("profiles: {}\n")

    with pytest.raises(KeyError):
        resolve_profile(path, "missing")


def test_build_launchd_plist_for_weekly_profile(tmp_path: Path):
    profiles_path = tmp_path / "benchmark" / "profiles.yaml"
    profiles_path.parent.mkdir()
    profiles_path.write_text(
        """
profiles:
  weekly-proxycheap-baseline:
    cadence: weekly
    config: targets.yaml
    out: results.jsonl
    archive_dir: runs
"""
    )

    plist = build_launchd_plist(profiles_path, "weekly-proxycheap-baseline")

    assert plist["Label"] == "com.hivewire.benchmark.weekly-proxycheap-baseline"
    assert plist["WorkingDirectory"] == str(tmp_path)
    assert plist["StartCalendarInterval"] == {"Weekday": 1, "Hour": 3, "Minute": 0}
    assert plist["RunAtLoad"] is False
    assert plist["ProgramArguments"][:2] == ["/bin/zsh", "-lc"]
    command = plist["ProgramArguments"][2]
    assert "uv run python -m benchmark.runner --profile weekly-proxycheap-baseline" in command
    assert "--profiles" in command
    assert str(profiles_path) in command
    assert plist["StandardOutPath"].endswith("benchmark/logs/weekly-proxycheap-baseline.out.log")


def test_build_launchd_plist_respects_daily_schedule_fields(tmp_path: Path):
    profiles_path = tmp_path / "benchmark" / "profiles.yaml"
    profiles_path.parent.mkdir()
    profiles_path.write_text(
        """
profiles:
  daily-smoke:
    cadence: daily
    hour: 7
    minute: 45
"""
    )

    plist = build_launchd_plist(profiles_path, "daily-smoke")

    assert plist["StartCalendarInterval"] == {"Hour": 7, "Minute": 45}


def test_collect_scheduler_status_uses_example_when_local_profiles_missing(tmp_path: Path):
    profiles_path = tmp_path / "benchmark" / "profiles.yaml"
    profiles_path.parent.mkdir()
    example_path = tmp_path / "benchmark" / "profiles.yaml.example"
    example_path.write_text(
        """
profiles:
  weekly-proxycheap-baseline:
    cadence: weekly
    description: Proxy-cheap baseline
"""
    )

    status = collect_scheduler_status(
        profiles_path,
        latest_manifest={"run_id": "latest-run", "finished_at": "2026-06-23T00:00:00Z"},
    )

    assert status["profiles_exists"] is False
    assert status["source"] == "example"
    assert status["profile_count"] == 1
    assert status["profiles"][0]["name"] == "weekly-proxycheap-baseline"
    assert status["profiles"][0]["launchd_label"] == "com.hivewire.benchmark.weekly-proxycheap-baseline"
    assert status["latest_run_id"] == "latest-run"


def test_collect_scheduler_status_prefers_local_profiles(tmp_path: Path):
    profiles_path = tmp_path / "benchmark" / "profiles.yaml"
    profiles_path.parent.mkdir()
    profiles_path.write_text(
        """
profiles:
  daily-smoke:
    cadence: daily
    description: Smoke run
"""
    )

    status = collect_scheduler_status(profiles_path, latest_manifest=None)

    assert status["profiles_exists"] is True
    assert status["source"] == "local"
    assert status["profiles"][0]["name"] == "daily-smoke"
