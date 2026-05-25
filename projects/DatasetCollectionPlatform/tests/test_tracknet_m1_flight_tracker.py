from __future__ import annotations

from pathlib import Path

from tools.lib.tapnextpp_tracker import SeedPoint
from tools.lib import tracknet_m1_flight_tracker
from tools.lib.tracknet_m1_flight_tracker import (
    FlightCandidate,
    SeededFlightTracker,
    build_flight_trajectory,
    choose_validated_launch_frame,
    find_launch_frame,
    link_flight_candidates,
)


def test_find_launch_frame_ignores_small_seed_jitter_and_uses_first_real_departure():
    seed = SeedPoint("sample_001", 100, 900.0, 916.0)
    candidates = {
        102: [FlightCandidate(102, 902.0, 904.0, 10.0, 8, (900, 902, 4, 4), "motion")],
        105: [FlightCandidate(105, 889.0, 846.0, 30.0, 16, (884, 842, 8, 8), "motion")],
        106: [FlightCandidate(106, 885.0, 802.0, 26.0, 14, (880, 798, 8, 8), "motion")],
    }

    launch = find_launch_frame(candidates, seed=seed, max_scan_frame=220)

    assert launch == 105


def test_link_flight_candidates_allows_short_occlusion_and_reacquires_same_ball():
    seed = SeedPoint("sample_001", 100, 900.0, 916.0)
    candidates = {
        105: [FlightCandidate(105, 889.0, 846.0, 30.0, 16, (884, 842, 8, 8), "motion")],
        106: [FlightCandidate(106, 885.0, 802.0, 26.0, 14, (880, 798, 8, 8), "motion")],
        109: [FlightCandidate(109, 872.0, 716.0, 20.0, 12, (868, 712, 8, 8), "motion")],
        110: [
            FlightCandidate(110, 720.0, 720.0, 50.0, 100, (700, 700, 30, 20), "club"),
            FlightCandidate(110, 868.0, 690.0, 18.0, 9, (864, 686, 7, 7), "motion"),
        ],
    }

    linked = link_flight_candidates(candidates, seed=seed, launch_frame=105, end_frame=111)

    assert linked[105].visible is True
    assert linked[107].visible is False
    assert linked[108].visible is False
    assert round(linked[109].x, 1) == 872.0
    assert round(linked[110].x, 1) == 868.0


def test_build_flight_trajectory_marks_preimpact_static_occlusion_and_flight():
    seed = SeedPoint("sample_001", 100, 900.0, 916.0)
    shot = {
        "sampleId": "sample_001",
        "sessionId": "session_001",
        "shotId": "shot_001",
        "sourceVideo": "/data/video.mov",
        "frameCount": 130,
        "fps": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }
    linked = {
        105: FlightCandidate(105, 889.0, 846.0, 0.9, 16, (884, 842, 8, 8), "motion", visible=True),
    }

    trajectory = build_flight_trajectory(
        shot=shot,
        seed=seed,
        frame_indices=list(range(100, 107)),
        launch_frame=105,
        linked_candidates=linked,
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
    )

    assert trajectory["frames"][0]["frameIndex"] == 100
    assert trajectory["frames"][0]["visible"] is True
    assert trajectory["frames"][0]["source"] == "manual_seed_static"
    assert trajectory["frames"][3]["frameIndex"] == 103
    assert trajectory["frames"][3]["visible"] is False
    assert trajectory["frames"][3]["source"] == "occluded_by_clubhead"
    assert trajectory["frames"][3]["labelEligible"] is False
    assert trajectory["frames"][5]["frameIndex"] == 105
    assert trajectory["frames"][5]["visible"] is True
    assert trajectory["frames"][5]["source"] == "seeded_motion_reacquisition"


def test_trajectory_marks_clubhead_occlusion_not_label_eligible():
    seed = SeedPoint("sample_001", 100, 900.0, 916.0)
    shot = {
        "sampleId": "sample_001",
        "sessionId": "session_001",
        "shotId": "shot_001",
        "sourceVideo": "/data/video.mov",
        "frameCount": 130,
        "fps": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
        "trackmanReviewed": {"reviewStatus": "accepted", "metricsUsable": False},
    }
    linked = {105: FlightCandidate(105, 889.0, 846.0, 0.9, 16, (884, 842, 8, 8), "motion", visible=True)}

    trajectory = build_flight_trajectory(
        shot=shot,
        seed=seed,
        frame_indices=list(range(100, 107)),
        launch_frame=105,
        linked_candidates=linked,
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
        camera_model_summary={
            "status": "ok",
            "source": "quicktime_lens_metadata",
            "fx": 1272.5,
            "fy": 1272.5,
            "cx": 960.0,
            "cy": 540.0,
        },
        camera_model_path="/work/m1_camera_models/models/sample_001.camera_model.json",
    )

    occluded = trajectory["frames"][3]
    assert occluded["source"] == "occluded_by_clubhead"
    assert occluded["visible"] is False
    assert occluded["labelEligible"] is False
    assert trajectory["cameraModel"]["source"] == "quicktime_lens_metadata"
    assert trajectory["trackmanReviewed"]["reviewStatus"] == "accepted"
    assert trajectory["predictedFlight"]["status"] == "not_generated"


def test_trajectory_records_clubhead_seed_as_occlusion_evidence_not_track():
    seed = SeedPoint("sample_001", 100, 900.0, 916.0)
    object.__setattr__(seed, "clubhead_center", {"x": 930.0, "y": 920.0, "visible": True})
    shot = {
        "sampleId": "sample_001",
        "sessionId": "session_001",
        "shotId": "shot_001",
        "sourceVideo": "/data/video.mov",
        "frameCount": 130,
        "fps": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }
    linked = {105: FlightCandidate(105, 889.0, 846.0, 0.9, 16, (884, 842, 8, 8), "motion", visible=True)}

    trajectory = build_flight_trajectory(
        shot=shot,
        seed=seed,
        frame_indices=list(range(100, 107)),
        launch_frame=105,
        linked_candidates=linked,
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
    )

    assert trajectory["seed"]["clubheadCenter"] == {"x": 930.0, "y": 920.0, "visible": True}
    assert trajectory["impact"]["occlusionEvidence"] == "forced_impact_window_with_clubhead_seed"
    assert "clubheadTrack" not in trajectory


def test_clubhead_like_candidate_is_penalized_near_clubhead_track():
    candidate = FlightCandidate(110, 720.0, 720.0, 50.0, 140, (700, 700, 40, 24), "motion")
    clubhead = FlightCandidate(110, 721.0, 721.0, 1.0, 200, (700, 700, 45, 25), "clubhead_track")

    adjusted = tracknet_m1_flight_tracker.apply_clubhead_rejection([candidate], {110: clubhead})

    assert adjusted == []


def test_validated_launch_uses_clubhead_track_to_reject_nearby_club_candidate():
    seed = SeedPoint("sample_001", 100, 900.0, 916.0)
    clubhead_by_frame = {
        frame_index: FlightCandidate(frame_index, 900.0, 835.0, 100.0, 160, (880, 820, 40, 30), "clubhead_track")
        for frame_index in range(130, 136)
    }
    candidates: dict[int, list[FlightCandidate]] = {
        130: [
            FlightCandidate(130, 900.0, 835.0, 90.0, 140, (882, 820, 36, 28), "club_motion"),
            FlightCandidate(130, 940.0, 845.0, 70.0, 8, (936, 841, 8, 8), "ball_motion"),
        ],
    }
    for frame_index, y in enumerate([820.0, 795.0, 770.0, 745.0, 720.0], start=131):
        candidates[frame_index] = [
            FlightCandidate(frame_index, 900.0, 835.0, 90.0, 140, (882, 820, 36, 28), "club_motion"),
            FlightCandidate(frame_index, 940.0, y, 70.0, 8, (936, int(y) - 4, 8, 8), "ball_motion"),
        ]

    launch_frame, linked = choose_validated_launch_frame(
        candidates,
        seed=seed,
        min_scan_frame=120,
        max_scan_frame=140,
        end_frame=140,
        clubhead_by_frame=clubhead_by_frame,
    )

    assert launch_frame == 130
    assert linked[130].source == "ball_motion"


def test_build_flight_trajectory_records_clubhead_track_as_non_label_evidence():
    seed = SeedPoint("sample_001", 100, 900.0, 916.0)
    object.__setattr__(seed, "clubhead_center", {"x": 930.0, "y": 920.0, "visible": True})
    shot = {
        "sampleId": "sample_001",
        "sessionId": "session_001",
        "shotId": "shot_001",
        "sourceVideo": "/data/video.mov",
        "frameCount": 130,
        "fps": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }
    linked = {105: FlightCandidate(105, 889.0, 846.0, 0.9, 16, (884, 842, 8, 8), "motion", visible=True)}
    clubhead_by_frame = {
        100: FlightCandidate(100, 930.0, 920.0, 100.0, 25, (912, 902, 36, 36), "clubhead_track"),
        101: FlightCandidate(101, 925.0, 910.0, 95.0, 25, (907, 892, 36, 36), "clubhead_track"),
    }

    trajectory = build_flight_trajectory(
        shot=shot,
        seed=seed,
        frame_indices=list(range(100, 107)),
        launch_frame=105,
        linked_candidates=linked,
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
        clubhead_by_frame=clubhead_by_frame,
    )

    assert trajectory["clubheadTrack"][0]["frameIndex"] == 100
    assert trajectory["clubheadTrack"][0]["source"] == "clubhead_track"
    assert trajectory["frames"][5]["labelEligible"] is True


def test_seeded_tracker_scans_full_one_second_seed_window(monkeypatch):
    seed = SeedPoint("sample_late_launch", 240, 900.0, 916.0)
    shot = {
        "sampleId": "sample_late_launch",
        "sessionId": "session_001",
        "shotId": "shot_001",
        "sourceVideo": "/data/video.mov",
        "frameCount": 600,
        "fps": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }
    late_launch_candidates = {
        382: [FlightCandidate(382, 890.0, 850.0, 40.0, 8, (887, 847, 6, 6), "motion")],
        383: [FlightCandidate(383, 889.0, 831.0, 40.0, 8, (886, 828, 6, 6), "motion")],
        384: [FlightCandidate(384, 888.0, 812.0, 40.0, 8, (885, 809, 6, 6), "motion")],
        385: [FlightCandidate(385, 887.0, 794.0, 40.0, 8, (884, 791, 6, 6), "motion")],
        386: [FlightCandidate(386, 886.0, 777.0, 40.0, 8, (883, 774, 6, 6), "motion")],
    }

    def fake_collect_motion_candidates(*, video_path, frame_indices, seed):  # noqa: ANN001
        assert frame_indices[0] == 240
        assert frame_indices[-1] == 480
        return late_launch_candidates

    monkeypatch.setattr(tracknet_m1_flight_tracker, "collect_motion_candidates", fake_collect_motion_candidates)

    trajectory = SeededFlightTracker(
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
        max_frames_after_seed=240,
    ).track(shot, seed)

    assert trajectory["impact"]["launchFrame"] == 382
    assert trajectory["flightTracking"]["linkedVisibleFrames"] == 5


def test_validated_launch_prefers_smooth_ball_flight_over_early_club_motion():
    seed = SeedPoint("sample_001", 100, 900.0, 916.0)
    candidates: dict[int, list[FlightCandidate]] = {
        112: [FlightCandidate(112, 892.0, 790.0, 55.0, 20, (888, 786, 8, 8), "club_motion")],
        113: [FlightCandidate(113, 830.0, 760.0, 65.0, 120, (810, 748, 40, 24), "club_motion")],
        114: [FlightCandidate(114, 805.0, 735.0, 60.0, 110, (785, 722, 38, 24), "club_motion")],
        115: [FlightCandidate(115, 795.0, 710.0, 58.0, 105, (780, 700, 32, 20), "club_motion")],
        116: [FlightCandidate(116, 790.0, 700.0, 58.0, 95, (775, 690, 30, 20), "club_motion")],
        117: [FlightCandidate(117, 792.0, 698.0, 58.0, 90, (778, 690, 28, 18), "club_motion")],
        118: [
            FlightCandidate(118, 794.0, 701.0, 58.0, 90, (780, 692, 28, 18), "club_motion"),
            FlightCandidate(118, 901.0, 835.0, 60.0, 16, (897, 831, 8, 8), "ball_motion"),
        ],
    }
    for frame_index, y in enumerate([812.0, 790.0, 768.0, 746.0, 724.0, 702.0, 680.0, 658.0], start=119):
        candidates.setdefault(frame_index, []).append(
            FlightCandidate(frame_index, 901.0, y, 60.0, 14, (897, int(y) - 4, 8, 8), "ball_motion")
        )
        candidates[frame_index].append(
            FlightCandidate(frame_index, 795.0, 700.0 + (frame_index % 2), 55.0, 85, (780, 690, 28, 18), "club_motion")
        )

    launch_frame, linked = choose_validated_launch_frame(
        candidates,
        seed=seed,
        min_scan_frame=110,
        max_scan_frame=130,
        end_frame=130,
    )

    assert launch_frame == 118
    assert linked[118].source == "ball_motion"
