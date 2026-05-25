from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.tracknet_m1_camera_model import build_camera_models


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Build TrackNetV6 M1 camera models for reviewed shots")
    parser.add_argument("--batch-index", type=Path, default=annotation_root / "work/m1_reviewed_batch/batch_index.json")
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "work/m1_camera_models")
    args = parser.parse_args(argv)

    report = build_camera_models(args.batch_index, args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
