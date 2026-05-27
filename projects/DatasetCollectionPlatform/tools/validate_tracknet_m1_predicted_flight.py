from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib.tracknet_m1_predicted_flight import load_prediction_files, validate_predictions


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _trackman_reviewed_by_sample(review_dir: Path | None) -> dict[str, dict[str, Any]]:
    if review_dir is None:
        return {}
    reviewed: dict[str, dict[str, Any]] = {}
    if not review_dir.exists() or not review_dir.is_dir():
        raise ValueError(f"trackman review dir does not exist or is not a directory: {review_dir}")
    for path in sorted(review_dir.glob("*.trackman_review.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        sample_id = payload.get("sampleId")
        if not isinstance(sample_id, str) or not sample_id:
            sample_id = path.name[: -len(".trackman_review.json")]
        if sample_id and sample_id not in reviewed:
            reviewed[sample_id] = payload
    return reviewed


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# TrackNet M1 Predicted Flight QC",
        "",
        "Legacy/debug review-only output; formal M2 uses `video_only_3d` and `trackman_constrained_3d`.",
        "",
        f"- predictionCount: {report['summary']['predictionCount']}",
        f"- statusCounts: `{json.dumps(report['summary']['statusCounts'], ensure_ascii=False)}`",
        f"- legacyReviewOnlyCount: {report['summary'].get('legacyReviewOnlyCount', 0)}",
        "",
        "| sampleId | variant | status | legacy | fit points | rmse px | confidence | TrackMan |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["items"]:
        quality = item.get("quality") or {}
        comparison = item.get("trackmanComparison") or {}
        lines.append(
            "| "
            + " | ".join([
                _cell(item.get("sampleId")),
                _cell(item.get("variant")),
                _cell(item.get("status")),
                _cell(item.get("legacyReviewOnly")),
                _cell(quality.get("fitPointCount")),
                _cell(quality.get("reprojectionRmsePx")),
                _cell(quality.get("confidence")),
                _cell(comparison.get("status")),
            ])
            + " |"
        )
    lines.extend([
        "",
        "TrackMan 对比只在人工确认后才可作为 debug 参考；legacy predictedFlight 的 TrackMan comparison 不能作为正式 M2 误差验收，正式 M2 只使用 `video_only_3d` 和 `trackman_constrained_3d`。",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_prediction_root(
    predictions_root: Path | str,
    output_root: Path | str,
    *,
    variants: list[str] | None = None,
    trackman_ocr_report_path: Path | None = None,
    trackman_review_dir: Path | None = None,
) -> dict[str, Any]:
    output_root = Path(output_root)
    predictions = load_prediction_files(predictions_root, variants=variants)
    reviewed_by_sample = _trackman_reviewed_by_sample(trackman_review_dir)
    report = validate_predictions(
        predictions,
        trackman_ocr_report=_load_json(trackman_ocr_report_path),
        trackman_reviewed_by_sample=reviewed_by_sample,
    )
    report["predictionsRoot"] = str(predictions_root)
    report["trackmanOcrReport"] = str(trackman_ocr_report_path) if trackman_ocr_report_path else None
    report["trackmanReviewDir"] = str(trackman_review_dir) if trackman_review_dir else None
    _write_json(output_root / "predicted_flight_qc_report.json", report)
    _write_markdown(output_root / "predicted_flight_qc_report.md", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate review-only TrackNet M1 predicted full trajectories")
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--variant", action="append", default=[])
    parser.add_argument("--trackman-ocr-report", type=Path)
    parser.add_argument("--trackman-review-dir", type=Path)
    args = parser.parse_args(argv)
    report = validate_prediction_root(
        args.predictions_root,
        args.output_root,
        variants=args.variant or None,
        trackman_ocr_report_path=args.trackman_ocr_report,
        trackman_review_dir=args.trackman_review_dir,
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
