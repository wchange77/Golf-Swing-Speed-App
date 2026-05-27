from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.tracknet_m1_contract import TrackNetM1ValidationError, read_label_rows, validate_label_row, validate_package


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _rows_by_sample(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["sample_id"]].append(row)
    return grouped


def _reject_legacy_predicted_rows(rows: list[dict[str, str]]) -> None:
    rejection_reason = "legacy_predicted_flight_not_training_truth"
    false_values = {"0", "false", "no", "n"}
    for index, row in enumerate(rows, start=2):
        label_source = str(row.get("label_source") or "")
        source = str(row.get("source") or "")
        predicted_flag = str(row.get("predictedFlight") or "").strip().lower()
        label_eligible = str(row.get("labelEligible") or "").strip().lower()
        if (
            label_source.startswith("predicted_")
            or source.startswith("predicted_")
            or predicted_flag in {"1", "true", "yes", "y"}
            or label_eligible in false_values
        ):
            raise TrackNetM1ValidationError(
                f"labels.csv row {index} rejected: {rejection_reason}"
            )


def _copy_previews(review_output_dir: Path, package_dir: Path) -> None:
    target = package_dir / "previews"
    source = review_output_dir / "frames"
    if target.exists():
        shutil.rmtree(target)
    if source.exists():
        shutil.copytree(source, target)
    else:
        target.mkdir(parents=True, exist_ok=True)


def _write_report(path: Path, *, label_count: int, shot_count: int, unusable: list[dict[str, Any]]) -> None:
    lines = [
        "# TrackNetV6 M1 Export Report",
        "",
        "## 结论",
        "",
        f"- 导出 matched shots：{shot_count}",
        f"- 导出 reviewed labels：{label_count}",
        "",
        "## 覆盖率",
        "",
        f"- 不可用样本数：{len(unusable)}",
        "",
        "## 跳过原因",
        "",
    ]
    if unusable:
        counts = Counter(str(item.get("reason", "unknown")) for item in unusable)
        for reason, count in sorted(counts.items()):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- 无")
    lines.extend([
        "",
        "## 风险",
        "",
        "- 本包只包含人工确认标签；自动候选未直接作为训练真值。",
        "- 本包为项目内稳定格式，TrackNetV6 训练仓库格式仍需后续 adapter。",
        "",
        "## 下一步",
        "",
        "1. 抽查 previews 与 labels.csv 的一致性。",
        "2. 确认 TrackNetV6 训练仓库格式后新增 adapter。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_m1_package(
    batch_index_path: Path | str,
    reviewed_labels_path: Path | str,
    review_output_dir: Path | str,
    package_dir: Path | str,
    *,
    min_shots: int = 5,
    min_total_labels: int = 100,
    min_labels_per_shot: int = 20,
) -> dict[str, Any]:
    batch_index_path = Path(batch_index_path)
    reviewed_labels_path = Path(reviewed_labels_path)
    review_output_dir = Path(review_output_dir)
    package_dir = Path(package_dir)
    batch = _load_json(batch_index_path)
    rows = read_label_rows(reviewed_labels_path)
    _reject_legacy_predicted_rows(rows)
    for index, row in enumerate(rows, start=2):
        validate_label_row(row, row_index=index)
    grouped = _rows_by_sample(rows)
    exported_shots = []
    trackman_shots = []
    for shot in batch.get("shots", []):
        sample_id = str(shot["sampleId"])
        sample_rows = grouped.get(sample_id, [])
        if len(sample_rows) < min_labels_per_shot:
            continue
        trackman_match = shot.get("trackmanMatch", {})
        exported_shots.append({
            "sessionId": shot.get("sessionId"),
            "shotId": shot.get("shotId"),
            "sampleId": sample_id,
            "sourceVideo": shot.get("sourceVideo"),
            "trackmanMatchId": str(trackman_match.get("matchIndex") or f"{shot.get('sessionId')}:{shot.get('shotId')}"),
            "reviewStatus": "reviewed",
            "reviewedLabelCount": len(sample_rows),
        })
        trackman_shots.append({
            "trackmanMatchId": str(trackman_match.get("matchIndex") or f"{shot.get('sessionId')}:{shot.get('shotId')}"),
            "sessionId": shot.get("sessionId"),
            "shotId": shot.get("shotId"),
            "sampleId": sample_id,
            "timeDeltaSeconds": trackman_match.get("timeDeltaSeconds"),
            "metrics": trackman_match.get("metrics", {}),
            "rawMatch": trackman_match,
        })
    if len(exported_shots) < min_shots:
        raise TrackNetM1ValidationError(f"minimum shots not met: {len(exported_shots)} < {min_shots}")
    if len(rows) < min_total_labels:
        raise TrackNetM1ValidationError(f"minimum reviewed labels not met: {len(rows)} < {min_total_labels}")
    package_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(package_dir / "labels.csv", rows, list(rows[0].keys()))
    manifest = {
        "version": "1.0",
        "packageId": package_dir.name,
        "generatedAt": _utc_now(),
        "sourceExportDir": batch.get("sourceExportDir", ""),
        "exportCommand": "python tools/export_tracknet_m1_package.py",
        "shots": exported_shots,
        "unusableSamples": batch.get("unusableSamples", []),
    }
    (package_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_dir / "trackman.json").write_text(json.dumps({"shots": trackman_shots}, ensure_ascii=False, indent=2), encoding="utf-8")
    _copy_previews(review_output_dir, package_dir)
    _write_report(package_dir / "export_report.md", label_count=len(rows), shot_count=len(exported_shots), unusable=batch.get("unusableSamples", []))
    validation = validate_package(package_dir)
    return {"status": validation["status"], "packageDir": str(package_dir), "labels": len(rows), "shots": len(exported_shots)}
