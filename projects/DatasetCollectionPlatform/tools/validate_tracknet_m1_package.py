from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.tracknet_m1_contract import TrackNetM1ValidationError, validate_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a TrackNetV6 M1 dataset package")
    parser.add_argument("package_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_package(args.package_dir)
    except TrackNetM1ValidationError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
