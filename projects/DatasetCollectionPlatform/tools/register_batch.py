from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


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

    for f in files:
        ann = match_annotation(f, annotation_dir)
        cmd = [
            sys.executable,
            "tools/register_sample.py",
            "--domain",
            args.domain,
            "--file",
            str(f),
            "--session-id",
            args.session_id,
            "--collector",
            args.collector,
            "--shot-id",
            f.stem,
            "--fps",
            str(args.fps),
            "--resolution",
            args.resolution,
            "--club-type",
            args.club_type,
            "--handedness",
            args.handedness,
            "--swing-intensity",
            args.swing_intensity,
            "--surface",
            args.surface,
        ]
        if ann:
            cmd.extend(["--annotation", str(ann)])
        if args.metadata_json:
            cmd.extend(["--metadata-json", args.metadata_json])
        subprocess.run(cmd, check=True)

    print(f"BATCH_DONE count={len(files)}")


if __name__ == "__main__":
    main()
