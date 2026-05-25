from __future__ import annotations

import argparse
import contextlib
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from export_tracknet_m1_sota_review import export_sota_review_tasks
from lib.tracknet_m1_contract import validate_package
from lib.tracknet_m1_export import export_m1_package
from lib.tracknet_m1_review_import import import_reviewed_labels
from lib.tapnextpp_tracker import SeedPoint
from run_tracknet_m1_sota_tracking import run_sota_tracking


LABEL_FIELDS = [
    "sample_id", "session_id", "shot_id", "frame_index", "x", "y", "visible",
    "frame_width", "frame_height", "source_video", "trackman_match_id",
    "reviewed_by", "reviewed_at", "label_source",
]


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 60.0, (320, 180))
    if not writer.isOpened():
        raise RuntimeError(f"could not write smoke video: {path}")
    try:
        for frame_index in range(3):
            frame = np.zeros((180, 320, 3), dtype=np.uint8)
            cv2.circle(frame, (80 + frame_index * 4, 90), 3, (255, 255, 255), -1)
            writer.write(frame)
    finally:
        writer.release()


def _write_fixture(output_dir: Path) -> tuple[Path, Path, Path]:
    fixture_dir = output_dir / "fixture"
    review_dir = output_dir / "review"
    (review_dir / "frames/sess_smoke/shot_smoke").mkdir(parents=True, exist_ok=True)
    (review_dir / "frames/sess_smoke/shot_smoke/frame_000031.jpg").write_bytes(b"preview")
    batch_index = fixture_dir / "batch_index.json"
    _write_json(batch_index, {
        "version": "1.0",
        "sourceExportDir": "DatasetCollectorExport",
        "shots": [{
            "sessionId": "sess_smoke",
            "shotId": "shot_smoke",
            "sampleId": "sample_smoke",
            "sourceVideo": "DatasetCollectorExport/assets/smoke.mov",
            "frameWidth": 320,
            "frameHeight": 180,
            "trackmanMatch": {"matchIndex": 1, "timeDeltaSeconds": 0.5, "metrics": {"ballSpeedMph": 140.0}},
        }],
        "unusableSamples": [],
    })
    labelstudio_export = fixture_dir / "labelstudio_export.json"
    _write_json(labelstudio_export, [
        {
            "data": {
                "image": "file:///frames/frame_000031.jpg",
                "sample_id": "sample_smoke",
                "session_id": "sess_smoke",
                "shot_id": "shot_smoke",
                "frame_index": 31,
                "frame_width": 320,
                "frame_height": 180,
                "source_video": "DatasetCollectorExport/assets/smoke.mov",
                "trackman": {"timeDeltaSeconds": 0.5},
            },
            "annotations": [{
                "was_cancelled": False,
                "created_at": "2026-05-21T00:00:00Z",
                "result": [
                    {"from_name": "ball_center", "to_name": "image", "type": "keypointlabels", "value": {"x": 25.0, "y": 50.0, "keypointlabels": ["ball"]}},
                    {"from_name": "visibility", "to_name": "image", "type": "choices", "value": {"choices": ["visible"]}},
                ],
            }],
        },
        {
            "data": {
                "image": "file:///frames/frame_000032.jpg",
                "sample_id": "sample_smoke",
                "session_id": "sess_smoke",
                "shot_id": "shot_smoke",
                "frame_index": 32,
                "frame_width": 320,
                "frame_height": 180,
                "source_video": "DatasetCollectorExport/assets/smoke.mov",
                "trackman": {"timeDeltaSeconds": 0.5},
            },
            "annotations": [{
                "was_cancelled": False,
                "created_at": "2026-05-21T00:00:01Z",
                "result": [
                    {"from_name": "visibility", "to_name": "image", "type": "choices", "value": {"choices": ["not_visible"]}},
                ],
            }],
        },
    ])
    return batch_index, labelstudio_export, review_dir


def _write_sota_fixture(output_dir: Path) -> tuple[Path, Path]:
    fixture_dir = output_dir / "sota_fixture"
    video_path = fixture_dir / "assets/smoke.mov"
    _write_video(video_path)
    batch_index = fixture_dir / "batch_index.json"
    _write_json(batch_index, {
        "version": "1.0",
        "shots": [{
            "sessionId": "sess_smoke",
            "shotId": "shot_smoke",
            "sampleId": "sample_smoke",
            "sourceVideo": str(video_path),
            "frameWidth": 320,
            "frameHeight": 180,
            "frameCount": 3,
            "fps": 60.0,
            "trackmanMatch": {"matchIndex": 1, "timeDeltaSeconds": 0.5},
        }],
        "unusableSamples": [],
    })
    seeds = fixture_dir / "seeds.json"
    _write_json(seeds, {
        "version": "1.0",
        "seeds": [{
            "sampleId": "sample_smoke",
            "sessionId": "sess_smoke",
            "shotId": "shot_smoke",
            "sourceVideo": str(video_path),
            "frameIndex": 0,
            "x": 80.0,
            "y": 90.0,
        }],
    })
    return batch_index, seeds


def _fake_tapnext(shot: dict, seed: SeedPoint) -> dict:
    return {
        "tracks_xy": [(80.0, 90.0), (84.0, 90.0), (88.0, 90.0)],
        "occluded": [False, False, False],
        "confidence": [0.99, 0.40, 0.95],
    }


def _fake_cotracker(shot: dict, seed: SeedPoint) -> list[dict]:
    return [
        {"frameIndex": 0, "x": 80.0, "y": 90.0, "visible": True, "confidence": 1.0},
        {"frameIndex": 1, "x": 84.5, "y": 90.0, "visible": True, "confidence": 1.0},
        {"frameIndex": 2, "x": 88.0, "y": 90.0, "visible": True, "confidence": 1.0},
    ]


def _run_sota_smoke(output_dir: Path) -> dict:
    batch_index, seeds = _write_sota_fixture(output_dir)
    tracking_dir = output_dir / "sota_tracking"
    with contextlib.redirect_stdout(sys.stderr):
        tracking_report = run_sota_tracking(
            batch_index_path=batch_index,
            seeds_path=seeds,
            output_dir=tracking_dir,
            tapnext_tracker=_fake_tapnext,
            cotracker_tracker=_fake_cotracker,
            max_distance_px=5.0,
            checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
        )
    review_report = export_sota_review_tasks(
        [Path(path) for path in tracking_report["trajectories"]],
        output_dir / "sota_review",
    )
    return {"processed": tracking_report["processed"], "reviewTasks": review_report["tasks"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a TrackNetV6 M1 fixture smoke test")
    parser.add_argument("--output-dir", type=Path, default=Path("exports/tracknet_m1_smoke"))
    args = parser.parse_args(argv)
    output_dir = args.output_dir
    batch_index, labelstudio_export, review_dir = _write_fixture(output_dir)
    reviewed_dir = output_dir / "reviewed"
    import_reviewed_labels(labelstudio_export, batch_index, reviewed_dir, min_reviewed_frames_per_shot=2)
    package_dir = output_dir / "package"
    export_m1_package(
        batch_index,
        reviewed_dir / "reviewed_labels.csv",
        review_dir,
        package_dir,
        min_shots=1,
        min_total_labels=2,
        min_labels_per_shot=2,
    )
    validation = validate_package(package_dir)
    sota = _run_sota_smoke(output_dir)
    print(json.dumps({"status": validation["status"], "packageDir": str(package_dir), "sota": sota}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
