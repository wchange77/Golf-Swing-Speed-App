from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_contract import TrackNetM1ValidationError
from lib.tracknet_m1_review_import import import_reviewed_labels


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_batch_index(tmp_path: Path) -> Path:
    path = tmp_path / "m1_batch/batch_index.json"
    _write_json(path, {
        "version": "1.0",
        "sourceExportDir": str(tmp_path / "DatasetCollectorExport"),
        "shots": [{
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "sampleId": "sample_001",
            "sourceVideo": "DatasetCollectorExport/assets/ball.mov",
            "frameWidth": 320,
            "frameHeight": 180,
            "trackmanMatch": {"timeDeltaSeconds": 1.25},
        }],
        "unusableSamples": [],
    })
    return path


def _task(frame_index: int, *, result: list[dict]) -> dict:
    return {
        "data": {
            "image": f"file:///frames/frame_{frame_index:06d}.jpg",
            "sample_id": "sample_001",
            "session_id": "sess_001",
            "shot_id": "shot_001",
            "frame_index": frame_index,
            "frame_width": 320,
            "frame_height": 180,
            "source_video": "DatasetCollectorExport/assets/ball.mov",
            "trackman": {"timeDeltaSeconds": 1.25},
        },
        "predictions": [{"result": [{"type": "keypointlabels", "value": {"x": 50, "y": 50}}]}],
        "annotations": [{"was_cancelled": False, "created_at": "2026-05-21T00:00:00Z", "result": result}],
    }


def _visible_result(x_pct: float, y_pct: float) -> list[dict]:
    return [
        {"from_name": "ball_center", "to_name": "image", "type": "keypointlabels", "value": {"x": x_pct, "y": y_pct, "keypointlabels": ["ball"]}},
        {"from_name": "visibility", "to_name": "image", "type": "choices", "value": {"choices": ["visible"]}},
    ]


def _not_visible_result() -> list[dict]:
    return [
        {"from_name": "visibility", "to_name": "image", "type": "choices", "value": {"choices": ["not_visible"]}},
    ]


def _write_export(tmp_path: Path, tasks: list[dict]) -> Path:
    path = tmp_path / "labelstudio_export.json"
    _write_json(path, tasks)
    return path


def test_import_reviewed_labels_writes_only_manual_reviewed_rows(tmp_path):
    batch_index_path = _make_batch_index(tmp_path)
    export_path = _write_export(tmp_path, [
        _task(31, result=_visible_result(25.0, 50.0)),
        _task(32, result=_not_visible_result()),
    ])
    output_dir = tmp_path / "reviewed"
    report = import_reviewed_labels(export_path, batch_index_path, output_dir, min_reviewed_frames_per_shot=2)
    assert report["reviewedLabels"] == 2
    rows = list(csv.DictReader((output_dir / "reviewed_labels.csv").open(encoding="utf-8")))
    assert rows[0]["label_source"] == "manual_review"
    assert rows[0]["visible"] == "1"
    assert rows[0]["x"] == "80.000"
    assert rows[0]["y"] == "90.000"
    assert rows[1]["visible"] == "0"
    assert rows[1]["x"] == ""
    assert rows[1]["y"] == ""


def test_import_reviewed_labels_rejects_unreviewed_prediction_only_task(tmp_path):
    batch_index_path = _make_batch_index(tmp_path)
    task = _task(31, result=[])
    task["annotations"] = []
    export_path = _write_export(tmp_path, [task])
    output_dir = tmp_path / "reviewed"
    report = import_reviewed_labels(export_path, batch_index_path, output_dir, min_reviewed_frames_per_shot=1)
    assert report["reviewedLabels"] == 0
    unusable = json.loads((output_dir / "unusable_samples.json").read_text(encoding="utf-8"))
    assert unusable[0]["reason"] == "insufficient_reviewed_frames"


def test_import_reviewed_labels_rejects_coordinate_outside_frame(tmp_path):
    batch_index_path = _make_batch_index(tmp_path)
    export_path = _write_export(tmp_path, [_task(31, result=_visible_result(125.0, 50.0))])
    output_dir = tmp_path / "reviewed"
    with pytest.raises(TrackNetM1ValidationError, match="outside frame"):
        import_reviewed_labels(export_path, batch_index_path, output_dir, min_reviewed_frames_per_shot=1)
