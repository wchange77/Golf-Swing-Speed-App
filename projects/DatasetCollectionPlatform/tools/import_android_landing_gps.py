from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib.registry import (
    SAMPLES_FILE,
    SESSIONS_FILE,
    SAMPLE_SCHEMA_FILE,
    ensure_registry_files,
    read_jsonl,
    validate_with_schema,
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL row must be an object: {line[:80]}")
        rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def build_session_name_map(sessions: list[dict[str, Any]]) -> tuple[dict[str, str], set[str]]:
    grouped: dict[str, list[str]] = {}
    for session in sessions:
        name = str(session.get("sessionName", "")).strip()
        session_id = str(session.get("sessionId", "")).strip()
        if name and session_id:
            grouped.setdefault(name, []).append(session_id)

    unique: dict[str, str] = {}
    ambiguous: set[str] = set()
    for name, ids in grouped.items():
        distinct = sorted(set(ids))
        if len(distinct) == 1:
            unique[name] = distinct[0]
        else:
            ambiguous.add(name)
    return unique, ambiguous


def measurements_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    measurements = record.get("referenceMeasurements")
    if isinstance(measurements, list) and measurements:
        return [m for m in measurements if isinstance(m, dict)]

    landing = record.get("landingLocation")
    if not isinstance(landing, dict):
        return []

    return [{
        "source": "android_landing_point",
        "device": record.get("device"),
        "capturedAt": record.get("capturedAt"),
        "clubSpeedMph": None,
        "ballSpeedMph": None,
        "carryDistanceMeters": None,
        "totalDistanceMeters": None,
        "launchAngleDegrees": None,
        "spinRateRpm": None,
        "landingLocation": landing,
        "notes": "android landing gps import",
    }]


def import_landing_points(android_jsonl: Path) -> dict[str, int]:
    ensure_registry_files()
    sessions = read_jsonl(SESSIONS_FILE)
    samples = read_jsonl(SAMPLES_FILE)
    landing_rows = load_jsonl(android_jsonl)
    name_to_session_id, ambiguous_names = build_session_name_map(sessions)

    stats = {
        "landingRows": len(landing_rows),
        "matchedRows": 0,
        "updatedSamples": 0,
        "skippedRows": 0,
        "ambiguousRows": 0,
    }

    measurements_by_session: dict[str, list[dict[str, Any]]] = {}
    for row in landing_rows:
        session_name = str(row.get("sessionName", "")).strip()
        if not session_name:
            stats["skippedRows"] += 1
            continue
        if session_name in ambiguous_names:
            stats["ambiguousRows"] += 1
            continue
        session_id = name_to_session_id.get(session_name)
        if not session_id:
            stats["skippedRows"] += 1
            continue
        measurements = measurements_from_record(row)
        if not measurements:
            stats["skippedRows"] += 1
            continue
        measurements_by_session.setdefault(session_id, []).extend(measurements)
        stats["matchedRows"] += 1

    if not measurements_by_session:
        return stats

    updated: list[dict[str, Any]] = []
    for sample in samples:
        session_measurements = measurements_by_session.get(sample.get("sessionId", ""))
        if session_measurements:
            metadata = dict(sample.get("metadata") or {})
            existing = metadata.get("referenceMeasurements")
            if not isinstance(existing, list):
                existing = []
            metadata["referenceMeasurements"] = existing + session_measurements
            sample = dict(sample)
            sample["metadata"] = metadata
            validate_with_schema(sample, SAMPLE_SCHEMA_FILE)
            stats["updatedSamples"] += 1
        updated.append(sample)

    write_jsonl(SAMPLES_FILE, updated)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 Android 落球点 GPS JSONL 到样本参考测量")
    parser.add_argument("--android-jsonl", required=True, help="AndroidLandingGpsCollector 导出的 landing_points.jsonl")
    args = parser.parse_args()

    stats = import_landing_points(Path(args.android_jsonl).resolve())
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
