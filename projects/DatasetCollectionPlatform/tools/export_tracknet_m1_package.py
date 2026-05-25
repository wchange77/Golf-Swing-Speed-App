from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.tracknet_m1_contract import TrackNetM1ValidationError
from lib.tracknet_m1_export import export_m1_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a TrackNetV6 M1 stable dataset package")
    parser.add_argument("--batch-index", type=Path, required=True)
    parser.add_argument("--reviewed-labels", type=Path, required=True)
    parser.add_argument("--review-output-dir", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--min-shots", type=int, default=5)
    parser.add_argument("--min-total-labels", type=int, default=100)
    parser.add_argument("--min-labels-per-shot", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        report = export_m1_package(
            args.batch_index,
            args.reviewed_labels,
            args.review_output_dir,
            args.package_dir,
            min_shots=args.min_shots,
            min_total_labels=args.min_total_labels,
            min_labels_per_shot=args.min_labels_per_shot,
        )
    except TrackNetM1ValidationError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
