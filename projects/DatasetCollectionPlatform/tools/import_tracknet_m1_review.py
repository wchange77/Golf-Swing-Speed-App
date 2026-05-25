from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.tracknet_m1_review_import import import_reviewed_labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import TrackNetV6 M1 reviewed Label Studio labels")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--batch-index", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-reviewed-frames-per-shot", type=int, default=20)
    args = parser.parse_args(argv)
    report = import_reviewed_labels(
        args.input,
        args.batch_index,
        args.output_dir,
        min_reviewed_frames_per_shot=args.min_reviewed_frames_per_shot,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
