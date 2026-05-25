from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.tracknet_m1_contract import REQUIRED_LABEL_FIELDS, validate_label_row


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tasks", "items", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("could not locate Label Studio tasks")


def _load_batch(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _best_annotation(task: dict[str, Any]) -> list[dict[str, Any]]:
    annotations = [item for item in task.get("annotations", []) if not item.get("was_cancelled")]
    if not annotations:
        return []
    annotations.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "")
    return annotations[-1].get("result") or []


def _choices(results: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for item in results:
        if item.get("type") == "choices":
            for choice in (item.get("value") or {}).get("choices") or []:
                values.add(str(choice))
    return values


def _keypoint(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in results:
        if item.get("type") == "keypointlabels":
            value = item.get("value") or {}
            labels = value.get("keypointlabels") or []
            if "ball" in labels:
                return value
    return None


def _batch_shots_by_sample(batch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(shot["sampleId"]): shot for shot in batch.get("shots", [])}


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REQUIRED_LABEL_FIELDS))
        writer.writeheader()
        writer.writerows(rows)


def import_reviewed_labels(
    labelstudio_export_path: Path | str,
    batch_index_path: Path | str,
    output_dir: Path | str,
    min_reviewed_frames_per_shot: int = 20,
) -> dict[str, Any]:
    labelstudio_export_path = Path(labelstudio_export_path)
    batch_index_path = Path(batch_index_path)
    output_dir = Path(output_dir)
    tasks = _load_tasks(labelstudio_export_path)
    batch = _load_batch(batch_index_path)
    shots_by_sample = _batch_shots_by_sample(batch)
    rows: list[dict[str, str]] = []
    for task in tasks:
        data = task.get("data") or {}
        sample_id = str(data.get("sample_id") or "")
        if not sample_id:
            continue
        results = _best_annotation(task)
        if not results:
            continue
        choices = _choices(results)
        if "skip" in choices:
            continue
        frame_width = int(data["frame_width"])
        frame_height = int(data["frame_height"])
        base = {
            "sample_id": sample_id,
            "session_id": str(data["session_id"]),
            "shot_id": str(data["shot_id"]),
            "frame_index": str(int(data["frame_index"])),
            "frame_width": str(frame_width),
            "frame_height": str(frame_height),
            "source_video": str(data["source_video"]),
            "trackman_match_id": str((shots_by_sample.get(sample_id, {}).get("trackmanMatch") or {}).get("matchIndex") or f"{data['session_id']}:{data['shot_id']}"),
            "reviewed_by": str(task.get("updated_by") or task.get("completed_by") or "labelstudio"),
            "reviewed_at": str(task.get("updated_at") or task.get("created_at") or _utc_now()),
            "label_source": "manual_review",
        }
        if "not_visible" in choices:
            row = {**base, "x": "", "y": "", "visible": "0"}
        else:
            keypoint = _keypoint(results)
            if keypoint is None:
                continue
            x = float(keypoint["x"]) / 100.0 * frame_width
            y = float(keypoint["y"]) / 100.0 * frame_height
            row = {**base, "x": f"{x:.3f}", "y": f"{y:.3f}", "visible": "1"}
        validate_label_row(row, row_index=len(rows) + 2)
        rows.append(row)

    rows_by_sample: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_by_sample[row["sample_id"]].append(row)
    usable_rows: list[dict[str, str]] = []
    unusable: list[dict[str, Any]] = []
    for shot in batch.get("shots", []):
        sample_id = str(shot["sampleId"])
        sample_rows = rows_by_sample.get(sample_id, [])
        if len(sample_rows) < min_reviewed_frames_per_shot:
            unusable.append({
                "sampleId": sample_id,
                "sessionId": shot.get("sessionId"),
                "shotId": shot.get("shotId"),
                "reason": "insufficient_reviewed_frames",
                "reviewedFrames": len(sample_rows),
                "minReviewedFrames": min_reviewed_frames_per_shot,
            })
            continue
        usable_rows.extend(sample_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "reviewed_labels.csv", usable_rows)
    (output_dir / "unusable_samples.json").write_text(json.dumps(unusable, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "reviewedLabels": len(usable_rows),
        "usableShots": len({row["sample_id"] for row in usable_rows}),
        "unusableSamples": unusable,
    }
    (output_dir / "review_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
