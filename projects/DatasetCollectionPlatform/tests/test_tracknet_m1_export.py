from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_contract import TrackNetM1ValidationError, validate_package
from lib.tracknet_m1_export import export_m1_package


LABEL_FIELDS = [
    "sample_id", "session_id", "shot_id", "frame_index", "x", "y", "visible",
    "frame_width", "frame_height", "source_video", "trackman_match_id",
    "reviewed_by", "reviewed_at", "label_source",
]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    batch_index_path = tmp_path / "m1_batch/batch_index.json"
    _write_json(batch_index_path, {
        "version": "1.0",
        "sourceExportDir": "DatasetCollectorExport",
        "shots": [{
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "sampleId": "sample_001",
            "sourceVideo": "DatasetCollectorExport/assets/ball.mov",
            "frameWidth": 320,
            "frameHeight": 180,
            "trackmanMatch": {"matchIndex": 1, "timeDeltaSeconds": 1.25, "metrics": {"ballSpeedMph": 145.0}},
        }],
        "unusableSamples": [{"sampleId": "sample_bad", "reason": "asset_not_found"}],
    })
    reviewed_labels_path = tmp_path / "reviewed/reviewed_labels.csv"
    reviewed_labels_path.parent.mkdir(parents=True)
    with reviewed_labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        writer.writerow({
            "sample_id": "sample_001", "session_id": "sess_001", "shot_id": "shot_001",
            "frame_index": "31", "x": "80.000", "y": "90.000", "visible": "1",
            "frame_width": "320", "frame_height": "180", "source_video": "DatasetCollectorExport/assets/ball.mov",
            "trackman_match_id": "1", "reviewed_by": "tester", "reviewed_at": "2026-05-21T00:00:01Z",
            "label_source": "manual_review",
        })
        writer.writerow({
            "sample_id": "sample_001", "session_id": "sess_001", "shot_id": "shot_001",
            "frame_index": "32", "x": "", "y": "", "visible": "0",
            "frame_width": "320", "frame_height": "180", "source_video": "DatasetCollectorExport/assets/ball.mov",
            "trackman_match_id": "1", "reviewed_by": "tester", "reviewed_at": "2026-05-21T00:00:02Z",
            "label_source": "manual_review",
        })
    review_output_dir = tmp_path / "review"
    preview_dir = review_output_dir / "frames/sess_001/shot_001"
    preview_dir.mkdir(parents=True)
    (preview_dir / "frame_000031.jpg").write_bytes(b"preview")
    return batch_index_path, reviewed_labels_path, review_output_dir


def test_export_m1_package_writes_required_files_and_passes_validator(tmp_path):
    batch_index_path, reviewed_labels_path, review_output_dir = _make_inputs(tmp_path)
    package_dir = tmp_path / "package"
    report = export_m1_package(
        batch_index_path,
        reviewed_labels_path,
        review_output_dir,
        package_dir,
        min_shots=1,
        min_total_labels=2,
        min_labels_per_shot=2,
    )
    assert report["status"] == "ok"
    assert (package_dir / "manifest.json").exists()
    assert (package_dir / "labels.csv").exists()
    assert (package_dir / "trackman.json").exists()
    assert (package_dir / "previews").exists()
    assert (package_dir / "export_report.md").exists()
    assert validate_package(package_dir)["status"] == "ok"


def test_export_m1_package_fails_when_minimum_counts_not_met(tmp_path):
    batch_index_path, reviewed_labels_path, review_output_dir = _make_inputs(tmp_path)
    package_dir = tmp_path / "package"
    with pytest.raises(TrackNetM1ValidationError, match="minimum"):
        export_m1_package(
            batch_index_path,
            reviewed_labels_path,
            review_output_dir,
            package_dir,
            min_shots=5,
            min_total_labels=100,
            min_labels_per_shot=20,
        )
