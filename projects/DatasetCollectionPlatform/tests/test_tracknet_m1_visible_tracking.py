from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools.lib.tracknet_m1_visible_tracking import build_visible_tracking_artifact

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from run_tracknet_m1_visible_tracking import run_visible_tracking


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_visible_tracking_clips_clubhead_at_impact_and_keeps_raw_ball_points():
    ball = {
        "sampleId": "sample_001",
        "shotId": "shot_001",
        "sessionId": "session_001",
        "sourceVideo": "/data/session_001/sample_001.mov",
        "fps": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
        "seed": {"frameIndex": 100, "x": 900, "y": 910},
        "impact": {"launchFrame": 132, "occlusionStartFrame": 129},
        "frames": [
            {
                "frameIndex": 128,
                "x": 900,
                "y": 910,
                "visible": True,
                "confidence": 1.0,
                "source": "manual_seed_static",
                "labelEligible": True,
            },
            {"frameIndex": 129, "x": 900, "y": 910, "visible": False, "confidence": 0.0, "source": "occluded_by_clubhead"},
            {"frameIndex": 132, "x": 885.4, "y": 870.2, "visible": True, "confidence": 0.91, "source": "seeded_motion_reacquisition"},
            {"frameIndex": 133, "x": 877.2, "y": 830.8, "visible": True, "confidence": 0.88, "source": "seeded_motion_reacquisition"},
            {"frameIndex": 134, "x": 870.1, "y": 790.4, "visible": True, "confidence": 0.21, "source": "seeded_motion_reacquisition"},
            {"frameIndex": 135, "x": 862.3, "y": 751.9, "visible": True, "confidence": 0.18, "source": "seeded_motion_reacquisition"},
        ],
    }
    club = {
        "clubheadTrack": [
            {"frameIndex": 100, "x": 760, "y": 920, "confidence": 0.93, "source": "tapnextpp_clubhead_patch"},
            {"frameIndex": 128, "x": 850, "y": 930, "confidence": 0.9, "source": "tapnextpp_clubhead_patch"},
            {"frameIndex": 132, "x": 905, "y": 912, "confidence": 0.89, "source": "tapnextpp_clubhead_patch"},
            {"frameIndex": 140, "x": 1010, "y": 930, "confidence": 0.86, "source": "tapnextpp_clubhead_patch"},
        ]
    }

    artifact = build_visible_tracking_artifact(ball, club, min_reliable_confidence=0.35)

    assert artifact["sampleId"] == "sample_001"
    assert artifact["stage"] == "m1_visible_tracking"
    assert artifact["shotId"] == "shot_001"
    assert artifact["sessionId"] == "session_001"
    assert artifact["sourceVideo"] == "/data/session_001/sample_001.mov"
    assert artifact["fps"] == 240
    assert artifact["frameWidth"] == 1920
    assert artifact["frameHeight"] == 1080
    assert isinstance(artifact["generatedAt"], str)
    assert artifact["trainingLabelPolicy"]["automaticFramesLabelEligible"] is False
    assert "manual review" in artifact["trainingLabelPolicy"]["summary"]
    assert artifact["curveType"] == "filtered_observed_points"
    assert [frame["frameIndex"] for frame in artifact["clubheadTrackToImpact"]] == [100, 128, 132]
    assert [frame["frameIndex"] for frame in artifact["ballRawObservedFrames"]] == [128, 129, 132, 133, 134, 135]
    assert [frame["frameIndex"] for frame in artifact["ballSmoothVisibleFrames"]] == [132, 133]
    assert artifact["ballRawObservedFrames"][0]["labelEligible"] is False
    assert artifact["ballSmoothVisibleFrames"][0]["source"] == "filtered_visible_observation"
    assert artifact["ballSmoothVisibleFrames"][0]["labelEligible"] is False
    assert artifact["clubheadTrackToImpact"][0]["labelEligible"] is False
    assert artifact["impactWindow"] == {"startFrame": 129, "launchFrame": 132}
    assert artifact["launchFrame"] == 132
    assert artifact["lastReliableFrame"] == 133
    assert artifact["qc"]["status"] == "needs_review"


def test_visible_tracking_contract_includes_nested_dual_seed_and_provenance():
    ball = {
        "sampleId": "sample_nested_seed",
        "shotId": "shot_nested",
        "sessionId": "session_nested",
        "sourceVideo": "/data/session_nested/sample_nested.mov",
        "seed": {
            "ballCenter": {"frameIndex": 100, "x": 900, "y": 910, "visible": True},
            "clubheadCenter": {"frameIndex": 100, "x": 760, "y": 920, "visible": True},
        },
        "impact": {"launchFrame": 132, "occlusionStartFrame": 129},
        "frames": [
            {"frameIndex": 132 + index, "x": 885 - index * 8, "y": 870 - index * 12, "visible": True, "confidence": 0.9}
            for index in range(12)
        ],
    }
    club = {
        "clubheadTrack": [
            {"frameIndex": 100, "x": 760, "y": 920, "confidence": 0.93},
            {"frameIndex": 132, "x": 905, "y": 912, "confidence": 0.89},
            {"frameIndex": 140, "x": 1010, "y": 930, "confidence": 0.86},
        ]
    }

    artifact = build_visible_tracking_artifact(ball, club)

    assert artifact["seed"]["ballCenter"] == {"frameIndex": 100, "x": 900.0, "y": 910.0, "visible": True}
    assert artifact["seed"]["clubheadCenter"] == {"frameIndex": 100, "x": 760.0, "y": 920.0, "visible": True}
    assert artifact["provenance"]["sourceStage"] == "m1_visible_tracking"
    assert artifact["provenance"]["inputSampleId"] == "sample_nested_seed"
    assert artifact["provenance"]["inputHasClubheadTrajectory"] is True


def test_visible_tracking_qc_flags_low_confidence_raw_tail_after_last_reliable():
    ball = {
        "sampleId": "sample_low_tail",
        "seed": {"frameIndex": 100, "x": 900, "y": 910},
        "impact": {"launchFrame": 132, "occlusionStartFrame": 129},
        "frames": [
            *[
                {"frameIndex": 132 + index, "x": 885 - index * 8, "y": 870 - index * 12, "visible": True, "confidence": 0.9}
                for index in range(12)
            ],
            {"frameIndex": 150, "x": 400, "y": 220, "visible": True, "confidence": 0.1},
        ],
    }
    club = {"clubheadTrack": [{"frameIndex": 132, "x": 905, "y": 912, "confidence": 0.89}]}

    artifact = build_visible_tracking_artifact(ball, club, min_reliable_confidence=0.35)

    assert artifact["lastReliableFrame"] == 143
    assert "raw_observation_after_last_reliable_low_confidence" in artifact["qc"]["issues"]


def test_visible_tracking_marks_missing_launch_review_and_does_not_claim_unclipped_clubhead():
    ball = {
        "sampleId": "sample_missing_launch",
        "seed": {"frameIndex": 100, "x": 900, "y": 910},
        "frames": [
            {
                "frameIndex": 100 + index,
                "x": 700 + index,
                "y": 850 - index,
                "visible": True,
                "confidence": 0.9,
                "source": "seeded_motion_reacquisition",
            }
            for index in range(12)
        ],
    }
    club = {
        "clubheadTrack": [
            {"frameIndex": 100, "x": 100, "y": 100, "confidence": 0.8},
            {"frameIndex": 112, "x": 120, "y": 120, "confidence": 0.8},
        ]
    }

    artifact = build_visible_tracking_artifact(ball, club)

    assert artifact["launchFrame"] is None
    assert artifact["clubheadTrackToImpact"] == []
    assert artifact["qc"]["status"] == "needs_review"
    assert "missing_launch_frame" in artifact["qc"]["issues"]
    assert "unclipped_clubhead_track_to_impact" in artifact["qc"]["issues"]


def test_visible_tracking_preserves_frame_only_occlusion_without_label_eligibility():
    ball = {
        "sampleId": "sample_frame_only_occlusion",
        "seed": {"frameIndex": 100, "x": 900, "y": 910},
        "impact": {"launchFrame": 132, "occlusionStartFrame": 129},
        "frames": [
            {"frameIndex": 129, "visible": False, "source": "occluded_by_clubhead", "labelEligible": True},
            {"frameIndex": 132, "x": 885.4, "y": 870.2, "visible": True, "confidence": 0.91, "source": "seeded_motion_reacquisition"},
        ],
    }

    artifact = build_visible_tracking_artifact(ball)

    occlusion = artifact["ballRawObservedFrames"][0]
    assert occlusion == {
        "frameIndex": 129,
        "visible": False,
        "source": "occluded_by_clubhead",
        "labelEligible": False,
        "confidence": 0.0,
    }


def test_visible_tracking_preserves_frame_only_invisible_clubhead_and_clips_later_impact():
    ball = {
        "sampleId": "sample_frame_only_clubhead",
        "seed": {"frameIndex": 100, "x": 900, "y": 910},
        "impact": {"launchFrame": 132, "occlusionStartFrame": 129},
        "frames": [
            {"frameIndex": 132, "x": 885.4, "y": 870.2, "visible": True, "confidence": 0.91, "source": "seeded_motion_reacquisition"},
        ],
    }
    club = {
        "clubheadTrack": [
            {"frameIndex": 129, "visible": False, "source": "clubhead_occluded"},
            {"frameIndex": 132, "x": 905, "y": 912, "visible": True, "confidence": 0.89, "source": "tapnextpp_clubhead_patch"},
            {"frameIndex": 140, "x": 1010, "y": 930, "visible": True, "confidence": 0.86, "source": "tapnextpp_clubhead_patch"},
        ]
    }

    artifact = build_visible_tracking_artifact(ball, club)

    assert artifact["clubheadTrackToImpact"][0] == {
        "frameIndex": 129,
        "visible": False,
        "source": "clubhead_occluded",
        "confidence": 0.0,
        "labelEligible": False,
    }
    assert [frame["frameIndex"] for frame in artifact["clubheadTrackToImpact"]] == [129, 132]


def test_visible_tracking_removes_coordinates_from_invisible_clubhead_frames_to_avoid_origin_jumps():
    ball = {
        "sampleId": "sample_invisible_origin_clubhead",
        "seed": {"frameIndex": 100, "x": 900, "y": 910},
        "impact": {"launchFrame": 132, "occlusionStartFrame": 129},
        "frames": [
            {"frameIndex": 132, "x": 885.4, "y": 870.2, "visible": True, "confidence": 0.91},
        ],
    }
    club = {
        "clubheadTrack": [
            {"frameIndex": 128, "x": 850, "y": 930, "visible": True, "confidence": 0.9},
            {
                "frameIndex": 129,
                "x": 0.0,
                "y": 0.0,
                "visible": False,
                "confidence": 0.0,
                "invisibleReason": "too_few_visible_points",
            },
            {"frameIndex": 132, "x": 905, "y": 912, "visible": True, "confidence": 0.89},
        ]
    }

    artifact = build_visible_tracking_artifact(ball, club)

    invisible = artifact["clubheadTrackToImpact"][1]
    assert invisible["frameIndex"] == 129
    assert invisible["visible"] is False
    assert "x" not in invisible
    assert "y" not in invisible
    assert [frame["frameIndex"] for frame in artifact["clubheadTrackToImpact"]] == [128, 129, 132]


def _ball_source() -> dict:
    return {
        "sampleId": "sample_001",
        "shotId": "shot_001",
        "sessionId": "session_001",
        "sourceVideo": "/data/session_001/sample_001.mov",
        "fps": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
        "seed": {"frameIndex": 100, "x": 900, "y": 910},
        "impact": {"launchFrame": 132, "occlusionStartFrame": 129},
        "frames": [
            {"frameIndex": 132, "x": 885.4, "y": 870.2, "visible": True, "confidence": 0.91},
        ],
    }


def _club_source() -> dict:
    return {
        "clubheadTrack": [
            {"frameIndex": 128, "x": 850, "y": 930, "confidence": 0.9},
            {"frameIndex": 132, "x": 905, "y": 912, "confidence": 0.89},
        ]
    }


def test_run_visible_tracking_writes_artifacts(tmp_path: Path):
    _write_json(tmp_path / "ball/sample_001.json", _ball_source())
    _write_json(tmp_path / "club/sample_001.json", _club_source())

    report = run_visible_tracking(
        ball_trajectories_dir=tmp_path / "ball",
        clubhead_trajectories_dir=tmp_path / "club",
        output_dir=tmp_path / "out",
    )

    output_path = tmp_path / "out/trajectories/sample_001.json"
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    report_path = tmp_path / "out/visible_tracking_report.json"
    written_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert report["trajectories"] == [str(output_path)]
    assert written_report == report
    assert artifact["stage"] == "m1_visible_tracking"


def test_run_visible_tracking_rejects_missing_ball_trajectories_dir(tmp_path: Path):
    with pytest.raises((FileNotFoundError, ValueError), match="ball.*trajectories"):
        run_visible_tracking(
            ball_trajectories_dir=tmp_path / "missing_ball",
            clubhead_trajectories_dir=tmp_path / "club",
            output_dir=tmp_path / "out",
        )


def test_run_visible_tracking_removes_stale_output_artifacts(tmp_path: Path):
    _write_json(tmp_path / "ball/sample_001.json", _ball_source())
    _write_json(tmp_path / "club/sample_001.json", _club_source())
    _write_json(tmp_path / "out/trajectories/stale_sample.json", {"stage": "stale"})

    run_visible_tracking(
        ball_trajectories_dir=tmp_path / "ball",
        clubhead_trajectories_dir=tmp_path / "club",
        output_dir=tmp_path / "out",
    )

    assert not (tmp_path / "out/trajectories/stale_sample.json").exists()
    assert sorted(path.name for path in (tmp_path / "out/trajectories").glob("*.json")) == ["sample_001.json"]


def test_run_visible_tracking_report_contains_failed_and_status_counts(tmp_path: Path):
    good_ball = _ball_source()
    review_ball = {
        **_ball_source(),
        "sampleId": "sample_needs_review",
        "frames": [{"frameIndex": 132, "x": 885.4, "y": 870.2, "visible": True, "confidence": 0.2}],
    }
    _write_json(tmp_path / "ball/sample_001.json", good_ball)
    _write_json(tmp_path / "ball/sample_needs_review.json", review_ball)
    _write_json(tmp_path / "club/sample_001.json", _club_source())
    _write_json(tmp_path / "club/sample_needs_review.json", _club_source())

    report = run_visible_tracking(
        ball_trajectories_dir=tmp_path / "ball",
        clubhead_trajectories_dir=tmp_path / "club",
        output_dir=tmp_path / "out",
    )

    assert report["processed"] == 2
    assert report["failed"] == 0
    assert report["statusCounts"]["needs_review"] == 2
    assert "ok" in report["statusCounts"]
    assert len(report["trajectories"]) == 2


def test_run_visible_tracking_reports_missing_clubhead_and_writes_report(tmp_path: Path):
    _write_json(tmp_path / "ball/sample_001.json", _ball_source())
    (tmp_path / "club").mkdir()

    report = run_visible_tracking(
        ball_trajectories_dir=tmp_path / "ball",
        clubhead_trajectories_dir=tmp_path / "club",
        output_dir=tmp_path / "out",
    )

    report_path = tmp_path / "out/visible_tracking_report.json"
    written_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert report["missingClubhead"] == ["sample_001"]
    assert written_report == report
