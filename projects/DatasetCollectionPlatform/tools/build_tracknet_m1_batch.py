from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.tracknet_m1_batch import build_batch_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a TrackNetV6 M1 batch index from autolabel outputs")
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--autolabel-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = build_batch_index(args.export_dir, args.autolabel_dir, args.output_dir)
    print(json.dumps({"outputDir": str(args.output_dir), "summary": payload["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
