from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.registry import (
    register_one_sample,
    validate_domain,
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

    metadata = {
        "fps": args.fps,
        "resolution": args.resolution,
        "clubType": args.club_type,
        "handedness": args.handedness,
        "swingIntensity": args.swing_intensity,
        "surface": args.surface,
    }
    metadata.update(load_extra_metadata(args.metadata_json))

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    ann_file = Path(args.annotation).resolve() if args.annotation else None

    sample_id = register_one_sample(
        domain=args.domain,
        source_file=Path(args.file),
        annotation_file=ann_file,
        session_id=args.session_id,
        collector=args.collector,
        shot_id=args.shot_id,
        take_index=args.take_index,
        metadata=metadata,
        tags=tags,
        source_path=args.source_path,
        captured_at=args.captured_at,
    )

    if sample_id:
        print(f"REGISTERED {sample_id}")
    else:
        print("DUPLICATE")


if __name__ == "__main__":
    main()
