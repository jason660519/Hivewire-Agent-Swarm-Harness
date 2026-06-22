"""Scheduled benchmark run profiles.

Profiles are declarative: they say what to run and how often it should be run.
An external scheduler can call the runner with ``--profile <name>``.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def load_profiles(path: Path) -> dict[str, dict]:
    if not path.exists():
        raise FileNotFoundError(path)
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    profiles = raw.get("profiles") or {}
    if not isinstance(profiles, dict):
        raise ValueError("profiles.yaml must contain a mapping under 'profiles'")
    return profiles


def _resolve_path(base: Path, value: str | None, default: str) -> Path:
    raw = Path(value or default)
    return raw if raw.is_absolute() else base / raw


def resolve_profile(path: Path, name: str) -> dict:
    profiles = load_profiles(path)
    if name not in profiles:
        raise KeyError(name)
    profile = dict(profiles[name] or {})
    base = path.parent
    return {
        "name": name,
        "cadence": profile.get("cadence", "manual"),
        "description": profile.get("description", ""),
        "config_path": _resolve_path(base, profile.get("config"), "targets.yaml"),
        "out_path": _resolve_path(base, profile.get("out"), "results.jsonl"),
        "archive_dir": _resolve_path(base, profile.get("archive_dir"), "runs"),
    }
