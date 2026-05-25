from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

REQUIRED_PACKAGE_FILES = ("manifest.json", "labels.csv", "trackman.json", "export_report.md")
REQUIRED_LABEL_FIELDS = (
    "sample_id", "session_id", "shot_id", "frame_index", "x", "y", "visible",
    "frame_width", "frame_height", "source_video", "trackman_match_id",
    "reviewed_by", "reviewed_at", "label_source",
)
MANUAL_LABEL_SOURCE = "manual_review"


class TrackNetM1ValidationError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrackNetM1ValidationError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TrackNetM1ValidationError(f"{path.name} must contain a JSON object")
    return payload


def read_label_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_LABEL_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise TrackNetM1ValidationError(f"labels.csv missing fields: {sorted(missing)}")
        return list(reader)


def _require(value: str | None, *, field: str, row_index: int) -> str:
    if value is None or str(value).strip() == "":
        raise TrackNetM1ValidationError(f"labels.csv row {row_index} missing {field}")
    return str(value).strip()


def _parse_int(value: str, *, field: str, row_index: int) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise TrackNetM1ValidationError(f"labels.csv row {row_index} invalid {field}: {value}") from exc


def _parse_float(value: str, *, field: str, row_index: int) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise TrackNetM1ValidationError(f"labels.csv row {row_index} invalid {field}: {value}") from exc


def validate_label_row(row: dict[str, str], *, row_index: int) -> None:
    for field in (
        "sample_id", "session_id", "shot_id", "frame_index", "visible",
        "frame_width", "frame_height", "source_video", "trackman_match_id",
        "reviewed_by", "reviewed_at", "label_source",
    ):
        _require(row.get(field), field=field, row_index=row_index)
    if row["label_source"] != MANUAL_LABEL_SOURCE:
        raise TrackNetM1ValidationError(
            f"labels.csv row {row_index} label_source must be {MANUAL_LABEL_SOURCE}"
        )
    _parse_int(row["frame_index"], field="frame_index", row_index=row_index)
    frame_width = _parse_int(row["frame_width"], field="frame_width", row_index=row_index)
    frame_height = _parse_int(row["frame_height"], field="frame_height", row_index=row_index)
    if frame_width <= 0 or frame_height <= 0:
        raise TrackNetM1ValidationError(f"labels.csv row {row_index} frame size must be positive")
    visible = _parse_int(row["visible"], field="visible", row_index=row_index)
    if visible not in (0, 1):
        raise TrackNetM1ValidationError(f"labels.csv row {row_index} visible must be 0 or 1")
    x_raw = (row.get("x") or "").strip()
    y_raw = (row.get("y") or "").strip()
    if visible == 0:
        if x_raw or y_raw:
            raise TrackNetM1ValidationError(f"labels.csv row {row_index} visible=0 must have empty x,y")
        return
    if not x_raw or not y_raw:
        raise TrackNetM1ValidationError(f"labels.csv row {row_index} visible=1 requires x,y")
    x = _parse_float(x_raw, field="x", row_index=row_index)
    y = _parse_float(y_raw, field="y", row_index=row_index)
    if not (0 <= x < frame_width and 0 <= y < frame_height):
        raise TrackNetM1ValidationError(f"labels.csv row {row_index} point outside frame")


def validate_package(package_dir: Path | str) -> dict[str, Any]:
    package_dir = Path(package_dir)
    if not package_dir.exists():
        raise TrackNetM1ValidationError(f"package directory not found: {package_dir}")
    for name in REQUIRED_PACKAGE_FILES:
        if not (package_dir / name).exists():
            raise TrackNetM1ValidationError(f"missing required package file: {name}")
    if not (package_dir / "previews").exists():
        raise TrackNetM1ValidationError("missing previews directory")
    manifest = _load_json(package_dir / "manifest.json")
    trackman = _load_json(package_dir / "trackman.json")
    labels = read_label_rows(package_dir / "labels.csv")
    if not labels:
        raise TrackNetM1ValidationError("labels.csv must contain at least one reviewed label")
    shots = manifest.get("shots") or []
    if not isinstance(shots, list) or not shots:
        raise TrackNetM1ValidationError("manifest.json must contain shots")
    if not isinstance(trackman.get("shots"), list):
        raise TrackNetM1ValidationError("trackman.json must contain shots")
    for index, row in enumerate(labels, start=2):
        validate_label_row(row, row_index=index)
    return {"status": "ok", "labels": len(labels), "shots": len(shots)}
