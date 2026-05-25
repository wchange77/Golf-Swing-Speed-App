from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_contract import TrackNetM1ValidationError, validate_package


LABEL_FIELDS = [
    "sample_id", "session_id", "shot_id", "frame_index", "x", "y", "visible",
    "frame_width", "frame_height", "source_video", "trackman_match_id",
    "reviewed_by", "reviewed_at", "label_source",
]


def _write_valid_package(root: Path) -> Path:
    package = root / "package"
    (package / "previews" / "sess_001" / "shot_001").mkdir(parents=True)
    (package / "previews" / "sess_001" / "shot_001" / "frame_000031.jpg").write_bytes(b"preview")
    (package / "manifest.json").write_text(json.dumps({
        "version": "1.0",
        "packageId": "m1_fixture",
        "generatedAt": "2026-05-21T00:00:00Z",
        "sourceExportDir": "DatasetCollectorExport",
        "exportCommand": "python tools/export_tracknet_m1_package.py --package-dir package",
        "shots": [{
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "sampleId": "sample_001",
            "sourceVideo": "DatasetCollectorExport/assets/ball.mov",
            "trackmanMatchId": "tm_001",
            "reviewStatus": "reviewed",
            "reviewedLabelCount": 2,
        }],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (package / "trackman.json").write_text(json.dumps({
        "shots": [{
            "trackmanMatchId": "tm_001",
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "timeDeltaSeconds": 1.25,
            "metrics": {"ballSpeedMph": 145.0, "launchAngleDeg": 12.4, "carryYards": 238.0},
        }]
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with (package / "labels.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        writer.writerow({
            "sample_id": "sample_001", "session_id": "sess_001", "shot_id": "shot_001",
            "frame_index": "31", "x": "82.5", "y": "120.0", "visible": "1",
            "frame_width": "320", "frame_height": "180", "source_video": "DatasetCollectorExport/assets/ball.mov",
            "trackman_match_id": "tm_001", "reviewed_by": "tester", "reviewed_at": "2026-05-21T00:00:01Z",
            "label_source": "manual_review",
        })
        writer.writerow({
            "sample_id": "sample_001", "session_id": "sess_001", "shot_id": "shot_001",
            "frame_index": "32", "x": "", "y": "", "visible": "0",
            "frame_width": "320", "frame_height": "180", "source_video": "DatasetCollectorExport/assets/ball.mov",
            "trackman_match_id": "tm_001", "reviewed_by": "tester", "reviewed_at": "2026-05-21T00:00:02Z",
            "label_source": "manual_review",
        })
    (package / "export_report.md").write_text("# M1 Export Report\n\n- Reviewed labels: 2\n", encoding="utf-8")
    return package


def _read_label_rows(package: Path) -> list[dict[str, str]]:
    with (package / "labels.csv").open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_label_rows(package: Path, rows: list[dict[str, str]]) -> None:
    with (package / "labels.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_validate_package_accepts_minimal_valid_package(tmp_path):
    package = _write_valid_package(tmp_path)
    result = validate_package(package)
    assert result["status"] == "ok"
    assert result["labels"] == 2
    assert result["shots"] == 1


def test_validate_package_rejects_auto_candidate_in_final_labels(tmp_path):
    package = _write_valid_package(tmp_path)
    rows = _read_label_rows(package)
    rows[0]["label_source"] = "auto_candidate"
    _write_label_rows(package, rows)
    with pytest.raises(TrackNetM1ValidationError, match="label_source"):
        validate_package(package)


def test_validate_package_rejects_visible_point_outside_frame(tmp_path):
    package = _write_valid_package(tmp_path)
    rows = _read_label_rows(package)
    rows[0]["x"] = "999.0"
    _write_label_rows(package, rows)
    with pytest.raises(TrackNetM1ValidationError, match="outside frame"):
        validate_package(package)


def test_validate_package_rejects_visible_zero_with_coordinates(tmp_path):
    package = _write_valid_package(tmp_path)
    rows = _read_label_rows(package)
    rows[1]["x"] = "10.0"
    rows[1]["y"] = "11.0"
    _write_label_rows(package, rows)
    with pytest.raises(TrackNetM1ValidationError, match="visible=0"):
        validate_package(package)
