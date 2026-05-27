from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.trackman_review import validate_reviewed_trackman_metrics


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Validate accepted TrackMan reviewed metrics before 3D import")
    parser.add_argument("--reviewed-dir", type=Path, default=annotation_root / "work/trackman_reviewed")
    parser.add_argument(
        "--output-report",
        type=Path,
        default=annotation_root / "work/trackman_reviewed/trackman_review_import_report.json",
    )
    args = parser.parse_args(argv)
    report = validate_reviewed_trackman_metrics(args.reviewed_dir)
    _write_json(args.output_report, report)
    print(json.dumps({
        "reviewedCount": report["reviewedCount"],
        "importableCount": report["importableCount"],
        "outputReport": str(args.output_report),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
