from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from run_tracknet_m1_sota_tracking import parse_args
from run_tracknet_m1_sota_tracking import run_sota_tracking
import run_tracknet_m1_flight_tracking
import render_tracknet_m1_trajectory_viewer


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _shot(sample_id: str, *, source_video: str = "/data/video.mov") -> dict:
    return {
        "sessionId": "sess_001",
        "shotId": f"shot_{sample_id}",
        "sampleId": sample_id,
        "sourceVideo": source_video,
        "frameCount": 3,
        "fps": 239.9,
        "frameWidth": 320,
        "frameHeight": 180,
        "trackmanMatch": {"timeDeltaSeconds": 0.027},
    }


def test_run_sota_tracking_writes_tapnextpp_trajectory_and_cotracker_crosscheck(tmp_path):
    batch_index = tmp_path / "m1_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_sota_tracking"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("sample_001"), _shot("sample_missing")]})
    _write_json(seeds_path, {
        "version": "1.0",
        "seeds": [{
            "sampleId": "sample_001",
            "sessionId": "sess_001",
            "shotId": "shot_sample_001",
            "sourceVideo": "/data/video.mov",
            "frameIndex": 0,
            "x": 80.0,
            "y": 90.0,
        }],
    })

    def fake_tapnext(shot, seed):
        return {
            "tracks_xy": [(80.0, 90.0), (84.0, 91.0), (88.0, 92.0)],
            "occluded": [False, False, False],
            "confidence": [0.99, 0.88, 0.87],
        }

    def fake_cotracker(shot, seed):
        return [
            {"frameIndex": 0, "x": 80.5, "y": 90.5, "visible": True, "confidence": 0.9},
            {"frameIndex": 1, "x": 130.0, "y": 140.0, "visible": True, "confidence": 0.8},
            {"frameIndex": 2, "x": 88.0, "y": 92.0, "visible": True, "confidence": 0.9},
        ]

    report = run_sota_tracking(
        batch_index_path=batch_index,
        seeds_path=seeds_path,
        output_dir=output_dir,
        tapnext_tracker=fake_tapnext,
        cotracker_tracker=fake_cotracker,
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
        max_distance_px=5.0,
    )

    trajectory_path = output_dir / "trajectories/sample_001.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert report["missingSeeds"] == ["sample_missing"]
    assert report["trajectories"] == [str(trajectory_path)]
    assert trajectory["sampleId"] == "sample_001"
    assert trajectory["frames"][0]["crossCheck"]["status"] == "agree"
    assert trajectory["frames"][1]["crossCheck"]["status"] == "disagree"
    assert trajectory["frames"][1]["needsReview"] is True


def test_run_sota_tracking_requires_cotracker_by_default(tmp_path):
    batch_index = tmp_path / "m1_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_sota_tracking"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("sample_001")]})
    _write_json(seeds_path, {"version": "1.0", "seeds": [{"sampleId": "sample_001", "frameIndex": 0, "x": 80, "y": 90}]})

    def fake_tapnext(shot, seed):
        return {"tracks_xy": [(80.0, 90.0)], "occluded": [False], "confidence": [0.99]}

    try:
        run_sota_tracking(
            batch_index_path=batch_index,
            seeds_path=seeds_path,
            output_dir=output_dir,
            tapnext_tracker=fake_tapnext,
            cotracker_tracker=None,
            checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
        )
    except RuntimeError as exc:
        assert "CoTracker3" in str(exc)
    else:
        raise AssertionError("expected CoTracker3 requirement to fail")


def test_cli_accepts_separate_gpu_devices_for_tapnext_and_cotracker():
    args = parse_args([
        "--tapnext-device",
        "cuda:0",
        "--cotracker-device",
        "cuda:1",
    ])

    assert args.tapnext_device == "cuda:0"
    assert args.cotracker_device == "cuda:1"


def test_cli_defaults_to_online_cotracker_for_long_videos():
    args = parse_args([])

    assert args.cotracker_mode == "online"
    assert args.frame_stride == 1
    assert args.max_frames_after_seed == 240


def test_run_sota_tracking_preserves_tracker_sampled_frame_indices(tmp_path):
    batch_index = tmp_path / "m1_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_sota_tracking"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("sample_001") | {"frameCount": 1000}]})
    _write_json(seeds_path, {"version": "1.0", "seeds": [{"sampleId": "sample_001", "frameIndex": 654, "x": 80, "y": 90}]})

    def fake_tapnext(shot, seed):
        return {
            "tracks_xy": [(80.0, 90.0), (84.0, 91.0), (88.0, 92.0)],
            "occluded": [False, False, False],
            "confidence": [0.99, 0.88, 0.87],
            "frame_indices": [654, 656, 658],
            "frame_stride": 2,
        }

    report = run_sota_tracking(
        batch_index_path=batch_index,
        seeds_path=seeds_path,
        output_dir=output_dir,
        tapnext_tracker=fake_tapnext,
        cotracker_tracker=None,
        require_cotracker=False,
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
    )

    trajectory = json.loads((output_dir / "trajectories/sample_001.json").read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert [frame["frameIndex"] for frame in trajectory["frames"]] == [654, 656, 658]
    assert trajectory["sampling"] == {"startFrame": 654, "frameStride": 2, "sampledFrameCount": 3}


def test_run_sota_tracking_sanitizes_trajectory_filename_for_bad_sample_id(tmp_path):
    batch_index = tmp_path / "m1_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_sota_tracking"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("../escape")]})
    _write_json(seeds_path, {
        "version": "1.0",
        "seeds": [{"sampleId": "../escape", "frameIndex": 0, "x": 80.0, "y": 90.0}],
    })

    def fake_tapnext(shot, seed):
        return {"tracks_xy": [(80.0, 90.0)], "occluded": [False], "confidence": [0.99]}

    report = run_sota_tracking(
        batch_index_path=batch_index,
        seeds_path=seeds_path,
        output_dir=output_dir,
        tapnext_tracker=fake_tapnext,
        cotracker_tracker=None,
        require_cotracker=False,
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
    )

    trajectories_root = (output_dir / "trajectories").resolve()
    trajectory_path = Path(report["trajectories"][0]).resolve()
    assert report["processed"] == 1
    assert trajectory_path.is_relative_to(trajectories_root)
    assert not (tmp_path / "escape.json").exists()


def test_run_sota_tracking_reads_seed_from_points_ball_center_without_legacy_aliases(tmp_path):
    batch_index = tmp_path / "m1_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_sota_tracking"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("sample_001")]})
    _write_json(seeds_path, {
        "version": "1.0",
        "seeds": [{
            "sampleId": "sample_001",
            "seedFrame": 4,
            "points": {"ball_center": {"x": 81.0, "y": 91.0, "visible": True}},
        }],
    })
    seen = {}

    def fake_tapnext(shot, seed):
        seen["seed"] = seed
        return {"tracks_xy": [(seed.x, seed.y)], "occluded": [False], "confidence": [0.99], "frame_indices": [seed.frame_index]}

    report = run_sota_tracking(
        batch_index_path=batch_index,
        seeds_path=seeds_path,
        output_dir=output_dir,
        tapnext_tracker=fake_tapnext,
        cotracker_tracker=None,
        require_cotracker=False,
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
    )

    assert report["processed"] == 1
    assert seen["seed"].frame_index == 4
    assert seen["seed"].x == 81.0
    assert seen["seed"].y == 91.0


def test_run_flight_tracking_passes_camera_model_summary_to_tracker(tmp_path):
    batch_index = tmp_path / "m1_reviewed_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_flight_tracking"
    camera_model_dir = tmp_path / "m1_camera_models/models"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("sample_001")]})
    _write_json(seeds_path, {
        "version": "1.0",
        "seeds": [{
            "sampleId": "sample_001",
            "frameIndex": 0,
            "x": 80.0,
            "y": 90.0,
        }],
    })
    _write_json(camera_model_dir / "sample_001.camera_model.json", {
        "cameraModel": {
            "source": "quicktime_lens_metadata",
            "fx": 1272.5,
            "fy": 1272.5,
            "cx": 960.0,
            "cy": 540.0,
            "confidences": {"intrinsics": 0.8},
        }
    })
    seen = {}

    class FakeTracker:
        def track(self, shot, seed, *, camera_model_summary=None, camera_model_path=None):  # noqa: ANN001
            seen["summary"] = camera_model_summary
            seen["path"] = camera_model_path
            return {
                "sampleId": shot["sampleId"],
                "frames": [{"frameIndex": seed.frame_index, "visible": True}],
                "impact": {"launchFrame": None},
                "flightTracking": {},
                "cameraModel": camera_model_summary,
                "cameraModelPath": camera_model_path,
            }

    report = run_tracknet_m1_flight_tracking.run_flight_tracking(
        batch_index_path=batch_index,
        seeds_path=seeds_path,
        output_dir=output_dir,
        camera_model_dir=camera_model_dir,
        tracker=FakeTracker(),
    )

    trajectory_path = output_dir / "trajectories/sample_001.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert trajectory["cameraModel"]["source"] == "quicktime_lens_metadata"
    assert seen["summary"]["source"] == "quicktime_lens_metadata"
    assert seen["path"] == str(camera_model_dir / "sample_001.camera_model.json")


def test_run_flight_tracking_does_not_escape_camera_model_dir_for_bad_sample_id(tmp_path):
    batch_index = tmp_path / "m1_reviewed_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_flight_tracking"
    camera_model_dir = tmp_path / "m1_camera_models/models"
    escape_path = tmp_path / "m1_camera_models/escape.camera_model.json"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("../escape")]})
    _write_json(seeds_path, {
        "version": "1.0",
        "seeds": [{
            "sampleId": "../escape",
            "frameIndex": 0,
            "x": 80.0,
            "y": 90.0,
        }],
    })
    _write_json(escape_path, {
        "cameraModel": {
            "source": "quicktime_lens_metadata",
            "fx": 1272.5,
            "fy": 1272.5,
            "cx": 960.0,
            "cy": 540.0,
        }
    })
    seen = {}

    class FakeTracker:
        def track(self, shot, seed, *, camera_model_summary=None, camera_model_path=None):  # noqa: ANN001
            seen["summary"] = camera_model_summary
            seen["path"] = camera_model_path
            return {
                "sampleId": shot["sampleId"],
                "frames": [{"frameIndex": seed.frame_index, "visible": True}],
                "impact": {"launchFrame": None},
                "flightTracking": {},
            }

    report = run_tracknet_m1_flight_tracking.run_flight_tracking(
        batch_index_path=batch_index,
        seeds_path=seeds_path,
        output_dir=output_dir,
        camera_model_dir=camera_model_dir,
        tracker=FakeTracker(),
    )

    assert report["processed"] == 1
    assert seen["summary"] == {"status": "missing", "reason": "invalid_sample_id"}
    assert seen["path"] is None
    assert not (output_dir / "escape.json").exists()


def test_run_flight_tracking_accepts_callable_tracker_with_camera_model_kwargs(tmp_path):
    batch_index = tmp_path / "m1_reviewed_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_flight_tracking"
    camera_model_dir = tmp_path / "m1_camera_models/models"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("sample_001")]})
    _write_json(seeds_path, {
        "version": "1.0",
        "seeds": [{
            "sampleId": "sample_001",
            "frameIndex": 0,
            "x": 80.0,
            "y": 90.0,
        }],
    })
    _write_json(camera_model_dir / "sample_001.camera_model.json", {
        "cameraModel": {
            "source": "quicktime_lens_metadata",
            "fx": 1272.5,
            "fy": 1272.5,
            "cx": 960.0,
            "cy": 540.0,
        }
    })
    seen = {}

    def fake_tracker(shot, seed, *, camera_model_summary=None, camera_model_path=None):  # noqa: ANN001
        seen["sampleId"] = shot["sampleId"]
        seen["seedFrame"] = seed.frame_index
        seen["summary"] = camera_model_summary
        seen["path"] = camera_model_path
        return {
            "sampleId": shot["sampleId"],
            "frames": [{"frameIndex": seed.frame_index, "visible": True}],
            "impact": {"launchFrame": None},
            "flightTracking": {},
            "cameraModel": camera_model_summary,
            "cameraModelPath": camera_model_path,
        }

    report = run_tracknet_m1_flight_tracking.run_flight_tracking(
        batch_index_path=batch_index,
        seeds_path=seeds_path,
        output_dir=output_dir,
        camera_model_dir=camera_model_dir,
        tracker=fake_tracker,
    )

    assert report["processed"] == 1
    assert seen["sampleId"] == "sample_001"
    assert seen["summary"]["source"] == "quicktime_lens_metadata"
    assert seen["path"] == str(camera_model_dir / "sample_001.camera_model.json")


def test_run_flight_tracking_reads_points_seed_and_passes_clubhead_seed(tmp_path):
    batch_index = tmp_path / "m1_reviewed_batch/batch_index.json"
    seeds_path = tmp_path / "m1_sota_tracking/seeds.json"
    output_dir = tmp_path / "m1_flight_tracking"
    _write_json(batch_index, {"version": "1.0", "shots": [_shot("sample_001")]})
    _write_json(seeds_path, {
        "version": "1.0",
        "seeds": [{
            "sampleId": "sample_001",
            "seedFrame": 7,
            "points": {
                "ball_center": {"x": 80.0, "y": 90.0, "visible": True},
                "clubhead_center": {"x": 112.0, "y": 96.0, "visible": True},
            },
        }],
    })
    seen = {}

    def fake_tracker(shot, seed, **kwargs):  # noqa: ANN001
        seen["seed"] = seed
        return {
            "sampleId": shot["sampleId"],
            "frames": [{"frameIndex": seed.frame_index, "visible": True}],
            "impact": {},
            "flightTracking": {},
            "seed": {
                "frameIndex": seed.frame_index,
                "x": seed.x,
                "y": seed.y,
                "clubheadCenter": getattr(seed, "clubhead_center", None),
            },
        }

    report = run_tracknet_m1_flight_tracking.run_flight_tracking(
        batch_index_path=batch_index,
        seeds_path=seeds_path,
        output_dir=output_dir,
        tracker=fake_tracker,
    )

    trajectory = json.loads((output_dir / "trajectories/sample_001.json").read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert seen["seed"].frame_index == 7
    assert seen["seed"].clubhead_center == {"x": 112.0, "y": 96.0, "visible": True}
    assert trajectory["seed"]["clubheadCenter"] == {"x": 112.0, "y": 96.0, "visible": True}


def test_run_flight_tracking_cli_defaults_to_reviewed_batch_and_camera_models():
    args = run_tracknet_m1_flight_tracking.parse_args([])

    assert str(args.batch_index).endswith("work/m1_reviewed_batch/batch_index.json")
    assert str(args.camera_model_dir).endswith("work/m1_camera_models/models")


def test_render_many_sanitizes_sample_id_preview_directory(tmp_path, monkeypatch):
    trajectory_path = tmp_path / "trajectories/bad.json"
    output_root = tmp_path / "previews"
    _write_json(trajectory_path, {
        "sampleId": "../escape",
        "sourceVideo": "/data/video.mov",
        "frameWidth": 1920,
        "frameHeight": 1080,
        "seed": {"frameIndex": 0, "x": 80.0, "y": 90.0},
        "frames": [],
    })
    seen_output_dirs = []

    def fake_render_trajectory_viewer(path, output_dir):  # noqa: ANN001
        output_dir = Path(output_dir)
        seen_output_dirs.append(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return {"trajectory": str(path), "outputDir": str(output_dir)}

    monkeypatch.setattr(render_tracknet_m1_trajectory_viewer, "render_trajectory_viewer", fake_render_trajectory_viewer)

    render_tracknet_m1_trajectory_viewer.render_many([trajectory_path], output_root)

    preview_dir = seen_output_dirs[0].resolve()
    assert preview_dir == (output_root / "escape").resolve()
    assert preview_dir.is_relative_to(output_root.resolve())
    assert not (output_root.parent / "escape").exists()


def test_render_trajectory_viewer_escapes_sample_id_in_html_title(tmp_path, monkeypatch):
    trajectory_path = tmp_path / "trajectory.json"
    output_dir = tmp_path / "preview"
    _write_json(trajectory_path, {
        "sampleId": "<script>alert(1)</script>",
        "sourceVideo": "/data/video.mov",
        "frameWidth": 320,
        "frameHeight": 180,
        "seed": {"frameIndex": 0, "x": 80.0, "y": 90.0},
        "frames": [{"frameIndex": 0, "x": 80.0, "y": 90.0, "visible": True, "source": "manual_seed_static"}],
    })

    class FakeCapture:
        def isOpened(self):
            return True

        def read(self):
            return True, np.zeros((180, 320, 3), dtype=np.uint8)

        def release(self):
            return None

    monkeypatch.setattr(render_tracknet_m1_trajectory_viewer.cv2, "VideoCapture", lambda path: FakeCapture())
    monkeypatch.setattr(render_tracknet_m1_trajectory_viewer.cv2, "imwrite", lambda path, image, params=None: True)

    render_tracknet_m1_trajectory_viewer.render_trajectory_viewer(trajectory_path, output_dir)

    html = (output_dir / "trajectory_viewer.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_render_trajectory_viewer_shows_trackman_match_context(tmp_path, monkeypatch):
    trajectory_path = tmp_path / "trajectory.json"
    output_dir = tmp_path / "preview"
    _write_json(trajectory_path, {
        "sampleId": "sample_001",
        "sourceVideo": "/data/video.mov",
        "frameWidth": 320,
        "frameHeight": 180,
        "seed": {"frameIndex": 0, "x": 80.0, "y": 90.0},
        "frames": [{"frameIndex": 0, "x": 80.0, "y": 90.0, "visible": True, "source": "manual_seed_static"}],
        "trackman": {
            "timeDeltaSeconds": 2.801,
            "photo": {
                "archiveName": "IMG_20260510_105337.jpg",
                "ocr": {"status": "skipped", "reason": "disabled_by_flag"},
            },
        },
    })

    class FakeCapture:
        def isOpened(self):
            return True

        def read(self):
            return True, np.zeros((180, 320, 3), dtype=np.uint8)

        def release(self):
            return None

    monkeypatch.setattr(render_tracknet_m1_trajectory_viewer.cv2, "VideoCapture", lambda path: FakeCapture())
    monkeypatch.setattr(render_tracknet_m1_trajectory_viewer.cv2, "imwrite", lambda path, image, params=None: True)

    render_tracknet_m1_trajectory_viewer.render_trajectory_viewer(trajectory_path, output_dir)

    html = (output_dir / "trajectory_viewer.html").read_text(encoding="utf-8")
    assert "TrackMan" in html
    assert "IMG_20260510_105337.jpg" in html
    assert "2.801s" in html
    assert "disabled_by_flag" in html


def test_render_many_enriches_trackman_ocr_from_report(tmp_path, monkeypatch):
    trajectory_path = tmp_path / "trajectory.json"
    output_root = tmp_path / "previews"
    ocr_report_path = tmp_path / "ocr_report.json"
    _write_json(trajectory_path, {
        "sampleId": "sample_001",
        "sourceVideo": "/data/video.mov",
        "frameWidth": 320,
        "frameHeight": 180,
        "seed": {"frameIndex": 0, "x": 80.0, "y": 90.0},
        "frames": [{"frameIndex": 0, "x": 80.0, "y": 90.0, "visible": True, "source": "manual_seed_static"}],
        "trackman": {
            "timeDeltaSeconds": 2.801,
            "photo": {
                "archiveName": "IMG_20260510_105337.jpg",
                "ocr": {"status": "skipped", "reason": "disabled_by_flag"},
            },
        },
    })
    _write_json(ocr_report_path, {
        "items": [{
            "sampleId": "sample_001",
            "trackmanPhoto": "IMG_20260510_105337.jpg",
            "ocrStatus": "ok",
            "ocrEngine": "rapidocr_onnxruntime",
            "lineCount": 2,
            "text": "CLUB SPEED\n72.9",
            "needsHumanConfirmation": True,
        }],
    })

    class FakeCapture:
        def isOpened(self):
            return True

        def read(self):
            return True, np.zeros((180, 320, 3), dtype=np.uint8)

        def release(self):
            return None

    monkeypatch.setattr(render_tracknet_m1_trajectory_viewer.cv2, "VideoCapture", lambda path: FakeCapture())
    monkeypatch.setattr(render_tracknet_m1_trajectory_viewer.cv2, "imwrite", lambda path, image, params=None: True)

    render_tracknet_m1_trajectory_viewer.render_many([trajectory_path], output_root, trackman_ocr_report_path=ocr_report_path)

    html = (output_root / "sample_001/trajectory_viewer.html").read_text(encoding="utf-8")
    assert "rapidocr_onnxruntime" in html
    assert "ok" in html
    assert "CLUB SPEED" in html
    assert "needs human confirmation" in html
