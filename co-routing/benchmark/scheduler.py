"""Local scheduler helpers for benchmark profiles."""
from __future__ import annotations

import argparse
import plistlib
import shlex
from pathlib import Path

from benchmark.profiles import load_profiles


def _schedule(profile: dict) -> dict:
    hour = int(profile.get("hour", 3))
    minute = int(profile.get("minute", 0))
    cadence = profile.get("cadence", "manual")
    if cadence == "weekly":
        return {"Weekday": int(profile.get("weekday", 1)), "Hour": hour, "Minute": minute}
    if cadence == "daily":
        return {"Hour": hour, "Minute": minute}
    raise ValueError(f"launchd schedule only supports daily/weekly profiles, got {cadence!r}")


def build_launchd_plist(profiles_path: Path, profile_name: str) -> dict:
    profiles_path = profiles_path.expanduser().resolve()
    profiles = load_profiles(profiles_path)
    if profile_name not in profiles:
        raise KeyError(profile_name)
    profile = profiles[profile_name] or {}
    co_routing_dir = profiles_path.parent.parent
    logs_dir = co_routing_dir / "benchmark" / "logs"
    command = (
        f"cd {shlex.quote(str(co_routing_dir))} && "
        f"uv run python -m benchmark.runner --profile {shlex.quote(profile_name)} "
        f"--profiles {shlex.quote(str(profiles_path))}"
    )
    return {
        "Label": f"com.hivewire.benchmark.{profile_name}",
        "ProgramArguments": ["/bin/zsh", "-lc", command],
        "WorkingDirectory": str(co_routing_dir),
        "StartCalendarInterval": _schedule(profile),
        "RunAtLoad": False,
        "StandardOutPath": str(logs_dir / f"{profile_name}.out.log"),
        "StandardErrorPath": str(logs_dir / f"{profile_name}.err.log"),
    }


def collect_scheduler_status(profiles_path: Path, latest_manifest: dict | None = None) -> dict:
    """Summarize local scheduling config for the dashboard."""
    profiles_path = profiles_path.expanduser().resolve()
    profiles_exists = profiles_path.exists()
    source_path = profiles_path
    source = "local"
    if not profiles_exists:
        example_path = profiles_path.with_suffix(profiles_path.suffix + ".example")
        if example_path.exists():
            source_path = example_path
            source = "example"
        else:
            source = "missing"

    profiles: dict[str, dict] = {}
    if source != "missing":
        profiles = load_profiles(source_path)

    co_routing_dir = profiles_path.parent.parent
    logs_dir = co_routing_dir / "benchmark" / "logs"
    profile_rows = []
    for name, profile in sorted(profiles.items()):
        profile = profile or {}
        profile_rows.append(
            {
                "name": name,
                "cadence": profile.get("cadence", "manual"),
                "description": profile.get("description", ""),
                "launchd_label": f"com.hivewire.benchmark.{name}",
                "out_log": str(logs_dir / f"{name}.out.log"),
                "err_log": str(logs_dir / f"{name}.err.log"),
            }
        )

    latest_manifest = latest_manifest or {}
    return {
        "profiles_path": str(profiles_path),
        "source_path": str(source_path),
        "profiles_exists": profiles_exists,
        "source": source,
        "profile_count": len(profile_rows),
        "profiles": profile_rows,
        "latest_run_id": latest_manifest.get("run_id"),
        "latest_finished_at": latest_manifest.get("finished_at"),
        "latest_mock": latest_manifest.get("mock"),
    }


def write_launchd_plist(profiles_path: Path, profile_name: str, out_path: Path) -> Path:
    plist = build_launchd_plist(profiles_path, profile_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        plistlib.dump(plist, fh, sort_keys=True)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a launchd plist for a benchmark profile")
    parser.add_argument("--profile", required=True, help="profile name from benchmark/profiles.yaml")
    parser.add_argument(
        "--profiles",
        default=str(Path(__file__).parent / "profiles.yaml"),
        help="profiles file (default: benchmark/profiles.yaml)",
    )
    parser.add_argument(
        "--out",
        help="output plist path (default: ~/Library/LaunchAgents/com.hivewire.benchmark.<profile>.plist)",
    )
    args = parser.parse_args()

    out_path = (
        Path(args.out).expanduser()
        if args.out
        else Path.home() / "Library" / "LaunchAgents" / f"com.hivewire.benchmark.{args.profile}.plist"
    )
    written = write_launchd_plist(Path(args.profiles), args.profile, out_path)
    print(f"[scheduler] wrote {written}")
    print(f"[scheduler] inspect it, then install with:")
    print(f"launchctl bootstrap gui/$(id -u) {shlex.quote(str(written))}")


if __name__ == "__main__":
    main()
