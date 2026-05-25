from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.tracknet_m1_review import export_review_tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export TrackNetV6 M1 Label Studio review tasks")
    parser.add_argument("--batch-index", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frames-per-shot", type=int, default=20)
    args = parser.parse_args(argv)
    report = export_review_tasks(args.batch_index, args.output_dir, frames_per_shot=args.frames_per_shot)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
