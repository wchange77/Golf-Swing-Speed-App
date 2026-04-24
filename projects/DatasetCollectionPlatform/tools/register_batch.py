from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.registry import register_one_sample


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


def match_annotation(file: Path, annotation_dir: Path | None) -> Path | None:
    if annotation_dir is None:
        return None
    base = file.stem
    candidates = [annotation_dir / f"{base}.json", annotation_dir / f"{base}.txt", annotation_dir / f"{base}.xml"]
    for c in candidates:
        if c.exists():
            return c
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch register samples with dedup")
    parser.add_argument("--domain", required=True, choices=["human_club", "golf_ball_detection"])
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--annotation-dir", default="")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--collector", default="unknown")
    parser.add_argument("--ext", default=".jpg,.jpeg,.png,.mp4,.mov")
    parser.add_argument("--fps", type=int, default=240)
    parser.add_argument("--resolution", default="1920x1080")
    parser.add_argument("--club-type", default="unknown")
    parser.add_argument("--handedness", default="unknown", choices=["left", "right", "unknown"])
    parser.add_argument("--swing-intensity", default="unknown", choices=["warmup", "normal", "max", "unknown"])
    parser.add_argument("--surface", default="unknown")
    parser.add_argument("--metadata-json", default="")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists():
        raise FileNotFoundError(f"Input dir not found: {input_dir}")

    annotation_dir = Path(args.annotation_dir).resolve() if args.annotation_dir else None
    exts = {e.strip().lower() for e in args.ext.split(",") if e.strip()}

    files = [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    files.sort()

    metadata = {
        "fps": args.fps,
        "resolution": args.resolution,
        "clubType": args.club_type,
        "handedness": args.handedness,
        "swingIntensity": args.swing_intensity,
        "surface": args.surface,
    }
    metadata.update(load_extra_metadata(args.metadata_json))

    registered = 0
    duplicates = 0
    for f in files:
        ann = match_annotation(f, annotation_dir)
        sample_id = register_one_sample(
            domain=args.domain,
            source_file=f,
            annotation_file=ann,
            session_id=args.session_id,
            collector=args.collector,
            shot_id=f.stem,
            take_index=1,
            metadata=metadata,
            source_path=str(f),
        )
        if sample_id:
            registered += 1
            print(f"REGISTERED {sample_id}")
        else:
            duplicates += 1
            print(f"DUPLICATE {f.name}")

    print(f"BATCH_DONE registered={registered} duplicates={duplicates} total={len(files)}")


if __name__ == "__main__":
    main()
