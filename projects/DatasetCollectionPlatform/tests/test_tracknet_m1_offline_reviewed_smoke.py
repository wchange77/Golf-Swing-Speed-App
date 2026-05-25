from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tapnextpp_tracker import SeedPoint
from lib.tracknet_m1_camera_model import build_camera_models
from lib.tracknet_m1_flight_tracker import FlightCandidate, build_flight_trajectory
from lib.tracknet_m1_reviewed_alignment import build_reviewed_batch_index
from lib.tracknet_m1_seed_store import TrackNetM1SeedStore


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_offline_reviewed_tracknet_m1_flow_keeps_only_accepted_pairs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video_dir = tmp_path / "videos"
    accepted_video = video_dir / "sample_accepted.mov"
    rejected_video = video_dir / "sample_rejected.mov"
    accepted_video.parent.mkdir(parents=True, exist_ok=True)
    accepted_video.write_bytes(b"fake quicktime placeholder")
    rejected_video.write_bytes(b"fake quicktime placeholder")

    source_batch_path = tmp_path / "work" / "m1_batch" / "batch_index.json"
    _write_json(source_batch_path, {
        "version": "1.0",
        "shots": [
            {
                "sessionId": "session_001",
                "shotId": "shot_accepted",
                "sampleId": "sample_accepted",
                "sourceVideo": str(accepted_video),
                "frameCount": 240,
                "fps": 240,
                "frameWidth": 1920,
                "frameHeight": 1080,
                "trackmanMatch": {"timeDeltaSeconds": 0.04},
            },
            {
                "sessionId": "session_001",
                "shotId": "shot_rejected",
                "sampleId": "sample_rejected",
                "sourceVideo": str(rejected_video),
                "frameCount": 240,
                "fps": 240,
                "frameWidth": 1920,
                "frameHeight": 1080,
                "trackmanMatch": {"timeDeltaSeconds": 0.06},
            },
        ],
        "unusableSamples": [],
    })
    reviewed_alignment_path = tmp_path / "work" / "m1_trackman_alignment" / "reviewed_alignment.json"
    _write_json(reviewed_alignment_path, {
        "version": "1.0",
        "pairs": [
            {
                "sampleId": "sample_accepted",
                "sessionId": "session_001",
                "shotId": "shot_accepted",
                "videoPath": str(accepted_video),
                "trackmanPhotoPath": str(tmp_path / "trackman" / "accepted.jpg"),
                "timeDeltaSeconds": 0.04,
                "reviewStatus": "accepted",
                "trackmanDataStatus": "usable",
                "metricsUsable": True,
                "rawOcrText": "Ball Speed 148.2 mph",
                "ocrBoxes": [],
                "candidateFields": {"ballSpeed": "148.2 mph"},
                "correctedFields": {
                    "ballSpeed": {
                        "rawValue": 148.2,
                        "rawUnit": "mph",
                        "normalizedValue": 66.25,
                        "normalizedUnit": "m/s",
                    }
                },
                "extraFields": {},
                "reviewer": "tester",
                "reviewedAt": "2026-05-25T00:00:00Z",
            },
            {
                "sampleId": "sample_rejected",
                "sessionId": "session_001",
                "shotId": "shot_rejected",
                "videoPath": str(rejected_video),
                "trackmanPhotoPath": str(tmp_path / "trackman" / "rejected.jpg"),
                "timeDeltaSeconds": 0.06,
                "reviewStatus": "rejected",
                "rejectReason": "wrong TrackMan photo",
            },
        ],
        "unmatchedVideos": [],
        "unmatchedTrackmanPhotos": [],
    })

    reviewed_batch_path = tmp_path / "work" / "m1_reviewed_batch" / "batch_index.json"
    reviewed_batch = build_reviewed_batch_index(
        source_batch_path=source_batch_path,
        reviewed_alignment_path=reviewed_alignment_path,
        output_path=reviewed_batch_path,
    )

    assert [shot["sampleId"] for shot in reviewed_batch["shots"]] == ["sample_accepted"]
    assert reviewed_batch["summary"]["acceptedPairs"] == 1
    assert reviewed_batch["summary"]["reviewedAcceptedPairs"] == 1
    assert reviewed_batch["summary"]["rejectedPairs"] == 1
    assert reviewed_batch["unusableSamples"] == [
        {
            "sampleId": "sample_rejected",
            "sessionId": "session_001",
            "shotId": "shot_rejected",
            "reason": "not_accepted_reviewed_alignment",
        }
    ]

    monkeypatch.setattr(
        "lib.tracknet_m1_camera_model.parse_quicktime_lens_metadata",
        lambda _: {"focalLength35mmEquivalent": 25.0},
    )
    camera_report = build_camera_models(reviewed_batch_path, tmp_path / "work" / "m1_camera_models")

    assert camera_report["summary"]["totalShots"] == 1
    assert camera_report["summary"]["modelsWritten"] == 1
    assert camera_report["sourceCounts"] == {"quicktime_lens_metadata": 1}

    seed_store = TrackNetM1SeedStore(tmp_path / "work" / "m1_sota_tracking" / "seeds.json", reviewed_batch["shots"])
    seed = seed_store.save_seed("sample_accepted", {
        "seedFrame": 100,
        "points": {
            "ball_center": {"x": 900, "y": 916, "visible": True},
            "clubhead_center": {"x": 860, "y": 930, "visible": True},
        },
    }, reviewer="tester")

    assert seed_store.progress() == {"total": 1, "seeded": 1, "missing": 0, "clubheadSeeded": 1, "missingClubhead": 0}
    assert seed["points"]["ball_center"]["visible"] is True
    assert seed["points"]["clubhead_center"]["visible"] is True
    assert "sample_rejected" not in {saved["sampleId"] for saved in seed_store.export()["seeds"]}

    shot = reviewed_batch["shots"][0]
    camera_model_path = camera_report["models"][0]["path"]
    camera_model = json.loads(Path(camera_model_path).read_text(encoding="utf-8"))
    trajectory = build_flight_trajectory(
        shot=shot,
        seed=SeedPoint("sample_accepted", 100, 900.0, 916.0),
        frame_indices=list(range(100, 107)),
        launch_frame=105,
        linked_candidates={
            105: FlightCandidate(105, 889.0, 846.0, 0.9, 16, (884, 842, 8, 8), "motion", visible=True)
        },
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
        camera_model_summary={
            "status": camera_model["status"],
            "source": camera_model["cameraModel"]["source"],
            **camera_model["cameraModel"]["intrinsics"],
        },
        camera_model_path=camera_model_path,
    )

    assert trajectory["sampleId"] == "sample_accepted"
    assert trajectory["trackmanReviewed"]["reviewStatus"] == "accepted"
    assert trajectory["cameraModel"]["source"] == "quicktime_lens_metadata"
    assert trajectory["predictedFlight"]["status"] == "not_generated"
    assert "sample_rejected" not in json.dumps(trajectory, ensure_ascii=False)
