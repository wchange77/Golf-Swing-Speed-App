from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_batch import build_batch_index


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_fixture(tmp_path: Path, *, missing_asset: bool = False) -> tuple[Path, Path, Path]:
    export_dir = tmp_path / "DatasetCollectorExport"
    autolabel_dir = tmp_path / "tracknet_autolabel_priors"
    output_dir = tmp_path / "m1_batch"
    asset_rel = "ios_export/assets/golf_ball_detection/aa/ball.mov"
    asset_path = export_dir / "assets/golf_ball_detection/aa/ball.mov"
    if not missing_asset:
        asset_path.parent.mkdir(parents=True)
        asset_path.write_bytes(b"fake-video")
    _write_json(autolabel_dir / "alignment_summary.json", {
        "version": "1.0",
        "sourceExportDir": str(export_dir),
        "alignmentSummary": {"matchedShots": 1, "unmatchedShots": 0, "unmatchedPhotos": 0},
        "summary": {"processedSamples": 1, "errorSamples": 0, "reviewSamples": 0, "autoConfirmedFrames": 2},
        "samples": [{
            "sampleId": "sample_ball_001",
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "status": "ok",
            "observationsPath": "samples/sess_001/shot_001/ball_observations.json",
            "labelsPath": "samples/sess_001/shot_001/tracknet_labels.csv",
            "selectedTrackLength": 2,
            "autoConfirmedFrames": 2,
        }],
        "unmatchedShots": [],
        "unmatchedPhotos": [],
    })
    _write_json(autolabel_dir / "samples/sess_001/shot_001/ball_observations.json", {
        "version": "1.0",
        "sample": {
            "sampleId": "sample_ball_001",
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "domain": "golf_ball_detection",
            "assetPath": asset_rel,
        },
        "video": {"fps": 60.0, "frameCount": 90, "width": 320, "height": 180},
        "trackmanMatch": {
            "matchIndex": 1,
            "timeDeltaSeconds": 1.25,
            "shot": {"shotId": "shot_001"},
            "photo": {"archiveName": "IMG_20260510_180000.jpg"},
        },
        "impact": {"frameIndex": 30, "timeSeconds": 0.5, "source": "fixture", "confidence": 0.8},
        "summary": {"selectedTrackLength": 2, "autoConfirmedFrames": 2, "needsReview": False},
        "frames": [],
    })
    return export_dir, autolabel_dir, output_dir


def test_build_batch_index_collects_matched_shot_with_video_and_trackman(tmp_path):
    export_dir, autolabel_dir, output_dir = _make_fixture(tmp_path)
    result = build_batch_index(export_dir, autolabel_dir, output_dir)
    assert result["summary"]["usableShots"] == 1
    batch = json.loads((output_dir / "batch_index.json").read_text(encoding="utf-8"))
    shot = batch["shots"][0]
    assert shot["sessionId"] == "sess_001"
    assert shot["shotId"] == "shot_001"
    assert shot["sampleId"] == "sample_ball_001"
    assert shot["frameWidth"] == 320
    assert shot["frameHeight"] == 180
    assert shot["trackmanMatch"]["timeDeltaSeconds"] == 1.25
    assert shot["candidateObservationsPath"].endswith("ball_observations.json")
    assert Path(shot["sourceVideo"]).exists()


def test_build_batch_index_records_unusable_missing_asset(tmp_path):
    export_dir, autolabel_dir, output_dir = _make_fixture(tmp_path, missing_asset=True)
    result = build_batch_index(export_dir, autolabel_dir, output_dir)
    assert result["summary"]["usableShots"] == 0
    batch = json.loads((output_dir / "batch_index.json").read_text(encoding="utf-8"))
    assert batch["unusableSamples"][0]["sampleId"] == "sample_ball_001"
    assert batch["unusableSamples"][0]["reason"] == "asset_not_found"
