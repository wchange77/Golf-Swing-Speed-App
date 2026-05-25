from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.tracknet_m1_reviewed_alignment import build_reviewed_batch_index


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Build an accepted-only TrackNetV6 M1 reviewed batch index")
    parser.add_argument("--source-batch", type=Path, default=annotation_root / "work/m1_batch/batch_index.json")
    parser.add_argument(
        "--reviewed-alignment",
        type=Path,
        default=annotation_root / "work/m1_trackman_alignment/reviewed_alignment.json",
    )
    parser.add_argument("--output", type=Path, default=annotation_root / "work/m1_reviewed_batch/batch_index.json")
    args = parser.parse_args(argv)

    payload = build_reviewed_batch_index(
        source_batch_path=args.source_batch,
        reviewed_alignment_path=args.reviewed_alignment,
        output_path=args.output,
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
