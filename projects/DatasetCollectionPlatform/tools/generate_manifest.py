from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from lib.registry import (
    DUPLICATES_FILE,
    MANIFEST_SCHEMA_FILE,
    ROOT,
    SAMPLE_SCHEMA_FILE,
    SAMPLES_FILE,
    SESSION_SCHEMA_FILE,
    SESSIONS_FILE,
    read_jsonl,
    validate_with_schema,
)

DOMAINS = [
    ("human_club", "datasets/processed/human_club", "coco"),
    ("golf_ball_detection", "datasets/processed/golf_ball_detection", "yolo"),
]

CONSUMERS = {
    "human_club_analysis_app": ["human_club"],
    "golf_ball_detection_app": ["golf_ball_detection"],
    "pitrac_feasibility_study": ["human_club", "golf_ball_detection"],
}


def count_split_files(domain: str) -> dict[str, int]:
    base = ROOT / "datasets" / "processed" / domain
    counts = {"train": 0, "val": 0, "test": 0}
    for split in counts.keys():
        img_dir = base / split / domain / "images"
        if img_dir.exists():
            counts[split] = sum(1 for p in img_dir.rglob("*") if p.is_file())
    return counts


def read_split_counts(domain: str) -> dict[str, int]:
    split_file = ROOT / "exports" / "splits" / f"{domain}.json"
    if not split_file.exists():
        return count_split_files(domain)
    payload = json.loads(split_file.read_text(encoding="utf-8"))
    return payload.get("counts", count_split_files(domain))


def build_consumer_manifest(consumer: str, domains: list[str], datasets: list[dict], registry: dict) -> dict:
    selected = [d for d in datasets if d["key"] in domains]
    return {
        "version": "1.2",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "consumer": consumer,
        "domains": domains,
        "registry": registry,
        "datasets": selected,
    }


def main() -> None:
    exports_dir = ROOT / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    consumers_dir = exports_dir / "consumers"
    consumers_dir.mkdir(parents=True, exist_ok=True)

    sample_rows = [r for r in read_jsonl(SAMPLES_FILE) if r.get("status") == "active"]
    duplicate_rows = read_jsonl(DUPLICATES_FILE)
    session_rows = read_jsonl(SESSIONS_FILE)

    datasets = []
    for key, path, fmt in DOMAINS:
        domain_rows = [r for r in sample_rows if r.get("domain") == key]
        split = read_split_counts(key)
        datasets.append(
            {
                "key": key,
                "path": path,
                "samples": len(domain_rows),
                "format": fmt,
                "duplicateFiltered": len([d for d in duplicate_rows if d.get("domain") == key]),
                "splitFile": f"exports/splits/{key}.json",
                "split": split,
            }
        )

    registry = {
        "samplesFile": "datasets/registry/samples.jsonl",
        "duplicatesFile": "datasets/registry/duplicates.jsonl",
        "sessionsFile": "datasets/registry/sessions.jsonl",
        "uniqueSamples": len(sample_rows),
        "duplicateSamples": len(duplicate_rows),
        "sessions": len(session_rows),
        "lastSessionAt": session_rows[-1]["createdAt"] if session_rows else None,
        "lastSampleAt": sample_rows[-1]["capturedAt"] if sample_rows else None,
    }

    consumers = []
    for consumer, domains in CONSUMERS.items():
        consumer_manifest = build_consumer_manifest(consumer, domains, datasets, registry)
        consumer_path = consumers_dir / f"{consumer}.json"
        consumer_path.write_text(json.dumps(consumer_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        consumers.append(
            {
                "consumer": consumer,
                "manifestPath": consumer_path.relative_to(ROOT).as_posix(),
                "domains": domains,
            }
        )

    manifest = {
        "version": "1.2",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "registry": registry,
        "contracts": {
            "session": SESSION_SCHEMA_FILE.relative_to(ROOT).as_posix(),
            "sample": SAMPLE_SCHEMA_FILE.relative_to(ROOT).as_posix(),
            "manifest": MANIFEST_SCHEMA_FILE.relative_to(ROOT).as_posix(),
        },
        "datasets": datasets,
        "consumers": consumers,
    }
    validate_with_schema(manifest, MANIFEST_SCHEMA_FILE)

    target = exports_dir / "dataset_manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote manifest: {target}")


if __name__ == "__main__":
    main()
