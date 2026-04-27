from __future__ import annotations

import argparse
from pathlib import Path

from lib.registry import (
    ROOT,
    SESSION_SCHEMA_FILE,
    SESSIONS_FILE,
    append_jsonl,
    ensure_registry_files,
    load_yaml_file,
    make_session_id,
    utc_now_iso,
    validate_domain,
    validate_with_schema,
)


def resolve_profile_path(profile_arg: str) -> Path:
    raw = Path(profile_arg)
    if raw.is_absolute():
        return raw
    if raw.suffix:
        return (ROOT / raw).resolve()
    return (ROOT / "config" / "device_profiles" / f"{profile_arg}.yaml").resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a dataset collection session")
    parser.add_argument("--collector", required=True)
    parser.add_argument("--session-name", default="")
    parser.add_argument("--device", required=True)
    parser.add_argument("--device-profile", default="iphone17max")
    parser.add_argument("--ios-version", default="")
    parser.add_argument("--app-version", default="")
    parser.add_argument("--fps", type=int, default=240)
    parser.add_argument("--resolution", default="1920x1080")
    parser.add_argument("--scene-type", default="indoor", choices=["indoor", "outdoor", "mixed"])
    parser.add_argument("--lighting", default="indoor_led")
    parser.add_argument("--tripod", action="store_true")
    parser.add_argument("--distance-m", type=float, default=0.0)
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--horizontal-accuracy-m", type=float, default=0.0)
    parser.add_argument("--altitude-m", type=float)
    parser.add_argument("--vertical-accuracy-m", type=float)
    parser.add_argument("--location-source", default="manual_cli")
    parser.add_argument("--target-domains", default="human_club,golf_ball_detection")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    ensure_registry_files()
    profile_path = resolve_profile_path(args.device_profile)
    profile = load_yaml_file(profile_path) if profile_path.exists() else {}
    target_domains = [validate_domain(d.strip()) for d in args.target_domains.split(",") if d.strip()]
    if not target_domains:
        raise ValueError("target-domains cannot be empty")

    session_id = make_session_id()
    environment = {
        "sceneType": args.scene_type,
        "lighting": args.lighting,
        "tripod": bool(args.tripod),
    }
    if args.distance_m > 0:
        environment["distanceMeters"] = args.distance_m
    has_location = args.latitude is not None or args.longitude is not None
    if has_location and (args.latitude is None or args.longitude is None):
        raise ValueError("--latitude and --longitude must be provided together")
    location = None
    if has_location:
        location = {
            "latitude": args.latitude,
            "longitude": args.longitude,
            "horizontalAccuracyMeters": max(args.horizontal_accuracy_m, 0.0),
            "altitudeMeters": args.altitude_m,
            "verticalAccuracyMeters": args.vertical_accuracy_m,
            "capturedAt": utc_now_iso(),
            "source": args.location_source,
        }

    record = {
        "sessionId": session_id,
        "collector": args.collector,
        "device": args.device,
        "deviceProfile": profile.get("profileId", profile_path.stem),
        "createdAt": utc_now_iso(),
        "status": "active",
        "iosVersion": args.ios_version,
        "appVersion": args.app_version,
        "captureConfig": {"fps": args.fps, "resolution": args.resolution},
        "environment": environment,
        "targetDomains": target_domains,
        "profileSnapshot": profile,
        "notes": args.notes,
    }
    if args.session_name.strip():
        record["sessionName"] = args.session_name.strip()
    if location:
        record["location"] = location
    validate_with_schema(record, SESSION_SCHEMA_FILE)
    append_jsonl(SESSIONS_FILE, record)
    print(session_id)


if __name__ == "__main__":
    main()
