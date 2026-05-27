from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from lib.tracknet_m1_3d_qc import aggregate_summaries, summarize_trajectory_file


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M1 3D Trajectory QC Report",
        "",
        f"- thresholds: max_error_carry_yd={report['thresholds']['maxErrorCarryYd']}, max_reprojection_rmse_px={report['thresholds']['maxReprojectionRmsePx']}",
        f"- samples: {report['sampleCount']}",
        f"- statusCounts: `{json.dumps(report['statusCounts'], ensure_ascii=False)}`",
        f"- TrackMan available: {report['trackmanAvailableCount']}",
        "",
        "| sample | status | model | TrackMan | TM carry err yd | video carry err yd | curve | reproj rmse px | evidence | failures | warnings | errors |",
        "| --- | --- | --- | --- | ---: | ---: | --- | ---: | --- | --- | --- | --- |",
    ]
    for item in report["samples"]:
        metrics = item["metrics"]
        models = item.get("modelVersions") if isinstance(item.get("modelVersions"), dict) else {}
        trackman = "available" if item["trackmanComparisonStatus"] == "available" else "TrackMan unavailable"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["sampleId"]),
                    str(item["status"]),
                    str(models.get("videoOnlyFamily") or models.get("videoOnlyType")),
                    trackman,
                    str(metrics.get("carryErrorYd")),
                    str(metrics.get("videoOnlyCarryErrorYd")),
                    str(metrics.get("curveDirectionStatus")),
                    str(metrics.get("visibleReprojectionRmsePx")),
                    ",".join(str(frame) for frame in item.get("evidenceFrames") or []),
                    ",".join(item.get("failureReasons") or []),
                    ",".join(item.get("warnings") or []),
                    ",".join(item.get("errors") or []),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _html(report: dict[str, Any]) -> str:
    rows = []
    for item in report["samples"]:
        metrics = item["metrics"]
        models = item.get("modelVersions") if isinstance(item.get("modelVersions"), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item['sampleId']))}</td>"
            f"<td>{html.escape(str(item['status']))}</td>"
            f"<td>{html.escape(str(models.get('videoOnlyFamily') or models.get('videoOnlyType')))}</td>"
            f"<td>{html.escape(str(item['trackmanComparisonStatus']))}</td>"
            f"<td>{html.escape(str(metrics.get('carryErrorYd')))}</td>"
            f"<td>{html.escape(str(metrics.get('videoOnlyCarryErrorYd')))}</td>"
            f"<td>{html.escape(str(metrics.get('curveDirectionStatus')))}</td>"
            f"<td>{html.escape(str(metrics.get('visibleReprojectionRmsePx')))}</td>"
            f"<td>{html.escape(','.join(str(frame) for frame in item.get('evidenceFrames') or []))}</td>"
            f"<td>{html.escape(','.join(item.get('failureReasons') or []))}</td>"
            f"<td>{html.escape(','.join(item.get('warnings') or []))}</td>"
            f"<td>{html.escape(','.join(item.get('errors') or []))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>M1 3D Trajectory QC</title>
<style>body{{font-family:Arial,Helvetica,sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}th{{background:#f6f6f6}}</style>
<h1>M1 3D Trajectory QC</h1>
<p>Thresholds: max_error_carry_yd={html.escape(str(report['thresholds']['maxErrorCarryYd']))}, max_reprojection_rmse_px={html.escape(str(report['thresholds']['maxReprojectionRmsePx']))}</p>
<table><thead><tr><th>Sample</th><th>Status</th><th>Model</th><th>TrackMan</th><th>TM carry err yd</th><th>Video carry err yd</th><th>Curve</th><th>Reproj RMSE px</th><th>Evidence</th><th>Failures</th><th>Warnings</th><th>Errors</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
"""


def validate_3d_reconstruction(
    *,
    trajectories_dir: Path | str,
    output_root: Path | str,
    max_error_carry_yd: float = 20.0,
    max_reprojection_rmse_px: float = 10.0,
) -> dict[str, Any]:
    trajectories_dir = Path(trajectories_dir)
    output_root = Path(output_root)
    if not trajectories_dir.exists() or not trajectories_dir.is_dir():
        raise ValueError(f"trajectories_dir does not exist or is not a directory: {trajectories_dir}")
    samples = [
        summarize_trajectory_file(
            _read_json(path),
            max_error_carry_yd=max_error_carry_yd,
            max_reprojection_rmse_px=max_reprojection_rmse_px,
        )
        for path in sorted(trajectories_dir.glob("*.json"))
    ]
    aggregate = aggregate_summaries(samples)
    report = {
        "version": "1.0",
        "trajectoriesDir": str(trajectories_dir),
        "outputRoot": str(output_root),
        "thresholds": {
            "maxErrorCarryYd": float(max_error_carry_yd),
            "maxReprojectionRmsePx": float(max_reprojection_rmse_px),
        },
        "sampleCount": len(samples),
        "samples": samples,
        **aggregate,
    }
    _write_json(output_root / "trajectory_3d_qc_report.json", report)
    _write_text(output_root / "trajectory_3d_qc_report.md", _markdown(report))
    _write_text(output_root / "trajectory_3d_qc_report.html", _html(report))
    return report


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Validate M1 3D reconstruction trajectories")
    parser.add_argument("--trajectories-dir", type=Path, default=annotation_root / "work/m1_3d_reconstruction/trajectories")
    parser.add_argument("--output-root", type=Path, default=annotation_root / "previews/m1_3d_review/qc")
    parser.add_argument("--max-error-carry-yd", type=float, default=20.0)
    parser.add_argument("--max-reprojection-rmse-px", type=float, default=10.0)
    args = parser.parse_args(argv)
    report = validate_3d_reconstruction(
        trajectories_dir=args.trajectories_dir,
        output_root=args.output_root,
        max_error_carry_yd=args.max_error_carry_yd,
        max_reprojection_rmse_px=args.max_reprojection_rmse_px,
    )
    print(json.dumps({"sampleCount": report["sampleCount"], "statusCounts": report["statusCounts"], "outputRoot": str(args.output_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
