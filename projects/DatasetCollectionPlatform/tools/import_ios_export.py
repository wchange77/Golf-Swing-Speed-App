from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from lib.registry import (
    ROOT,
    SESSIONS_FILE,
    SAMPLES_FILE,
    DUPLICATES_FILE,
    append_jsonl,
    ensure_registry_files,
    read_jsonl,
    register_one_sample,
    validate_with_schema,
    SESSION_SCHEMA_FILE,
)


def import_sessions(ios_dir: Path) -> dict[str, bool]:
    ios_sessions_file = ios_dir / "sessions.jsonl"
    if not ios_sessions_file.exists():
        print(f"WARN: {ios_sessions_file} not found, skipping session import")
        return {}

    existing_ids = {s["sessionId"] for s in read_jsonl(SESSIONS_FILE)}
    ios_sessions = read_jsonl(ios_sessions_file)
    imported = {}

    for session in ios_sessions:
        sid = session.get("sessionId", "")
        if sid in existing_ids:
            imported[sid] = False
            continue
        try:
            validate_with_schema(session, SESSION_SCHEMA_FILE)
        except ValueError:
            for key in ["iosVersion", "appVersion", "profileSnapshot", "notes"]:
                session.setdefault(key, "")
            session.setdefault("captureConfig", {"fps": 240, "resolution": "1920x1080"})
            session.setdefault("environment", {"sceneType": "unknown", "lighting": "unknown", "tripod": False})
            session.setdefault("targetDomains", ["human_club", "golf_ball_detection"])
        append_jsonl(SESSIONS_FILE, session)
        existing_ids.add(sid)
        imported[sid] = True

    return imported


def resolve_asset_file(ios_dir: Path, sample: dict) -> Path | None:
    asset_path = sample.get("assetPath", "")
    if not asset_path:
        return None
    candidates = [
        ios_dir / asset_path,
        ios_dir / "assets" / Path(asset_path).name,
        ios_dir / Path(asset_path).name,
    ]
    if asset_path.startswith("ios_export/"):
        candidates.insert(0, ios_dir / asset_path.removeprefix("ios_export/"))
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def import_samples(ios_dir: Path, session_map: dict[str, bool]) -> dict[str, int]:
    ios_samples_file = ios_dir / "samples.jsonl"
    if not ios_samples_file.exists():
        print(f"WARN: {ios_samples_file} not found, skipping sample import")
        return {"registered": 0, "duplicates": 0, "skipped": 0}

    ios_samples = read_jsonl(ios_samples_file)
    stats = {"registered": 0, "duplicates": 0, "skipped": 0}

    for sample in ios_samples:
        domain = sample.get("domain", "")
        session_id = sample.get("sessionId", "")
        if not domain or not session_id:
            stats["skipped"] += 1
            continue

        asset_file = resolve_asset_file(ios_dir, sample)
        if asset_file is None:
            print(f"WARN: asset not found for sample {sample.get('sampleId', '?')}, skipping")
            stats["skipped"] += 1
            continue

        ann_path_str = sample.get("annotationPath", "")
        ann_file = None
        if ann_path_str:
            ann_candidates = [ios_dir / ann_path_str, ios_dir / Path(ann_path_str).name]
            for c in ann_candidates:
                if c.exists():
                    ann_file = c
                    break

        metadata = sample.get("metadata", {})
        for key in ["fps", "resolution", "clubType", "handedness", "swingIntensity", "surface"]:
            metadata.setdefault(key, "unknown")
        if isinstance(metadata.get("fps"), str):
            try:
                metadata["fps"] = int(metadata["fps"])
            except ValueError:
                metadata["fps"] = 240

        result = register_one_sample(
            domain=domain,
            source_file=asset_file,
            annotation_file=ann_file,
            session_id=session_id,
            collector=sample.get("collector", "ios_import"),
            shot_id=sample.get("shotId", ""),
            take_index=sample.get("takeIndex", 1),
            metadata=metadata,
            tags=sample.get("tags", []),
            source_path=sample.get("sourcePath", str(asset_file)),
            captured_at=sample.get("capturedAt", ""),
        )

        if result:
            stats["registered"] += 1
            print(f"REGISTERED {result}")
        else:
            stats["duplicates"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 iOS DatasetCollectorApp 导出数据")
    parser.add_argument("--ios-export-dir", required=True, help="iOS 导出目录路径")
    args = parser.parse_args()

    ios_dir = Path(args.ios_export_dir).resolve()
    if not ios_dir.exists():
        raise FileNotFoundError(f"iOS export dir not found: {ios_dir}")

    ensure_registry_files()

    print(f"导入 iOS 数据: {ios_dir}")
    print()

    session_map = import_sessions(ios_dir)
    new_sessions = sum(1 for v in session_map.values() if v)
    skip_sessions = sum(1 for v in session_map.values() if not v)
    print(f"会话: 新增 {new_sessions}, 跳过 {skip_sessions}")

    sample_stats = import_samples(ios_dir, session_map)
    print(f"样本: 注册 {sample_stats['registered']}, 重复 {sample_stats['duplicates']}, 跳过 {sample_stats['skipped']}")

    print()
    print(json.dumps({
        "sessions": {"imported": new_sessions, "skipped": skip_sessions},
        "samples": sample_stats,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
