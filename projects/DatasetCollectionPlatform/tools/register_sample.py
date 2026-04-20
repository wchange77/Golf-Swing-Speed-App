from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.registry import (
    DUPLICATES_FILE,
    SAMPLE_SCHEMA_FILE,
    SAMPLES_FILE,
    append_jsonl,
    canonical_annotation_path,
    canonical_asset_path,
    copy_if_needed,
    ensure_session_exists,
    ensure_registry_files,
    make_sample_id,
    relative_to_root,
    read_jsonl,
    sha256_of_file,
    utc_now_iso,
    validate_domain,
    validate_with_schema,
)


def load_extra_metadata(path: str) -> dict:
    if not path:
        return {}
    meta_path = Path(path).resolve()
    if not meta_path.exists():
        raise FileNotFoundError(f"Metadata json not found: {meta_path}")
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Metadata json must be an object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Register one sample with dedup")
    parser.add_argument("--domain", required=True, choices=["human_club", "golf_ball_detection"])
    parser.add_argument("--file", required=True)
    parser.add_argument("--annotation", default="")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--collector", default="unknown")
    parser.add_argument("--tags", default="")
    parser.add_argument("--captured-at", default="")
    parser.add_argument("--shot-id", default="")
    parser.add_argument("--take-index", type=int, default=1)
    parser.add_argument("--fps", type=int, default=240)
    parser.add_argument("--resolution", default="1920x1080")
    parser.add_argument("--club-type", default="unknown")
    parser.add_argument("--handedness", default="unknown", choices=["left", "right", "unknown"])
    parser.add_argument("--swing-intensity", default="unknown", choices=["warmup", "normal", "max", "unknown"])
    parser.add_argument("--surface", default="unknown")
    parser.add_argument("--source-path", default="")
    parser.add_argument("--metadata-json", default="")
    args = parser.parse_args()

    domain = validate_domain(args.domain)
    source_file = Path(args.file).resolve()
    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError(f"Sample file not found: {source_file}")
    if args.take_index < 1:
        raise ValueError("take-index must be >= 1")

    ann_file = Path(args.annotation).resolve() if args.annotation else None
    if ann_file and not ann_file.exists():
        raise FileNotFoundError(f"Annotation file not found: {ann_file}")

    ensure_registry_files()
    session = ensure_session_exists(args.session_id)
    target_domains = session.get("targetDomains", [])
    if target_domains and domain not in target_domains:
        raise ValueError(f"domain {domain} not declared in session targetDomains={target_domains}")
    metadata = {
        "fps": args.fps,
        "resolution": args.resolution,
        "clubType": args.club_type,
        "handedness": args.handedness,
        "swingIntensity": args.swing_intensity,
        "surface": args.surface,
    }
    metadata.update(load_extra_metadata(args.metadata_json))
    captured_at = args.captured_at or utc_now_iso()
    source_path = args.source_path or str(source_file)

    checksum = sha256_of_file(source_file)
    existing = [r for r in read_jsonl(SAMPLES_FILE) if r.get("domain") == domain and r.get("sha256") == checksum and r.get("status") == "active"]
    if existing:
        duplicate_record = {
            "duplicateAt": utc_now_iso(),
            "domain": domain,
            "sha256": checksum,
            "incomingFile": str(source_file),
            "incomingSourcePath": source_path,
            "existingSampleId": existing[0]["sampleId"],
            "sessionId": args.session_id,
            "collector": args.collector,
            "metadata": metadata,
        }
        append_jsonl(DUPLICATES_FILE, duplicate_record)
        print(f"DUPLICATE {existing[0]['sampleId']}")
        return

    sample_id = make_sample_id(domain, checksum)
    asset_path = canonical_asset_path(domain, source_file, checksum)
    ann_path = canonical_annotation_path(domain, checksum, ann_file)

    copy_if_needed(source_file, asset_path)
    if ann_file and ann_path:
        copy_if_needed(ann_file, ann_path)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    record = {
        "sampleId": sample_id,
        "domain": domain,
        "sha256": checksum,
        "hashAlgorithm": "sha256",
        "assetPath": relative_to_root(asset_path),
        "annotationPath": relative_to_root(ann_path) if ann_path else None,
        "fileSize": source_file.stat().st_size,
        "sessionId": args.session_id,
        "collector": args.collector,
        "device": session.get("device", "unknown"),
        "deviceProfile": session.get("deviceProfile", "unknown"),
        "capturedAt": captured_at,
        "sourcePath": source_path,
        "shotId": args.shot_id or None,
        "takeIndex": args.take_index,
        "tags": tags,
        "metadata": metadata,
        "status": "active",
    }
    validate_with_schema(record, SAMPLE_SCHEMA_FILE)
    append_jsonl(SAMPLES_FILE, record)
    print(f"REGISTERED {sample_id}")


if __name__ == "__main__":
    main()
