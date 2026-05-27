from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.tracknet_m1_predicted_flight import SUPPORTED_VARIANTS, build_predictions


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Generate review-only predicted full ball trajectories from M1 flight tracking JSON")
    parser.add_argument("--trajectories-dir", type=Path, default=annotation_root / "work/m1_flight_tracking_batch/trajectories")
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "work/m1_predicted_full_trajectory")
    parser.add_argument("--variant", action="append", choices=SUPPORTED_VARIANTS, default=[])
    parser.add_argument("--output-frame-count", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    report = build_predictions(
        args.trajectories_dir,
        args.output_dir,
        variants=args.variant or SUPPORTED_VARIANTS,
        output_frame_count=args.output_frame_count,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
