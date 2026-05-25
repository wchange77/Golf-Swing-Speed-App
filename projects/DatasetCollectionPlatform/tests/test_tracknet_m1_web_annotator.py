from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_web_annotator import AnnotationStore, AnnotationValidationError


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _frame(path: Path, name: str) -> Path:
    frame = path / name
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"fake-jpeg")
    return frame


def _task(frame_path: Path, frame_index: int, *, sample_id: str = "sample_001", shot_id: str = "shot_001") -> dict:
    return {
        "data": {
            "image": frame_path.resolve().as_uri(),
            "sample_id": sample_id,
            "session_id": "sess_001",
            "shot_id": shot_id,
            "frame_index": frame_index,
            "frame_width": 320,
            "frame_height": 180,
            "source_video": "/data/source.mov",
            "trackman": {"timeDeltaSeconds": 0.027},
        },
        "predictions": [{
            "model_version": "tracknet_m1_auto_candidate",
            "score": 0.5,
            "result": [{
                "from_name": "ball_center",
                "to_name": "image",
                "type": "keypointlabels",
                "value": {"x": 25.0, "y": 50.0, "keypointlabels": ["ball"]},
            }],
        }],
    }


def _make_store(tmp_path: Path) -> AnnotationStore:
    frame_a = _frame(tmp_path / "frames/sess_001/shot_001", "frame_000031.jpg")
    frame_b = _frame(tmp_path / "frames/sess_001/shot_001", "frame_000032.jpg")
    tasks_path = tmp_path / "labelstudio/tracknet_m1_tasks.json"
    _write_json(tasks_path, [_task(frame_a, 31), _task(frame_b, 32)])
    return AnnotationStore(tasks_path, tmp_path / "labelstudio/labelstudio_export.json")


def _batch_index(
    path: Path,
    *,
    source_video: str | None = None,
    session_id: str = "sess_001",
    shot_id: str = "shot_001",
) -> Path:
    batch_index = path / "m1_batch/batch_index.json"
    _write_json(batch_index, {
        "version": "1.0",
        "shots": [{
            "sessionId": session_id,
            "shotId": shot_id,
            "sampleId": "sample_001",
            "sourceVideo": source_video or str(path / "missing.mov"),
            "frameCount": 2400,
            "fps": 239.9,
            "frameWidth": 320,
            "frameHeight": 180,
            "impact": {
                "frameIndex": 1560,
                "source": "duration_ratio_heuristic",
                "confidence": 0.4,
            },
            "trackmanMatch": {"timeDeltaSeconds": 0.027},
        }],
        "unusableSamples": [],
    })
    return batch_index


def test_loads_tasks_with_stable_ids_and_initial_progress(tmp_path):
    store = _make_store(tmp_path)

    payload = store.api_payload()

    assert payload["progress"] == {"total": 2, "reviewed": 0, "visible": 0, "notVisible": 0, "skipped": 0}
    assert payload["shots"][0]["shotId"] == "shot_001"
    assert payload["shots"][0]["total"] == 2
    assert payload["tasks"][0]["id"] == "sample_001__31"
    assert payload["tasks"][0]["annotation"] is None
    assert payload["tasks"][0]["candidate"]["score"] == 0.5


def test_saves_visible_annotation_as_labelstudio_export(tmp_path):
    store = _make_store(tmp_path)

    saved = store.save_annotation("sample_001__31", {"state": "visible", "x": 80, "y": 90}, reviewer="tester")

    assert saved["state"] == "visible"
    exported = json.loads((tmp_path / "labelstudio/labelstudio_export.json").read_text(encoding="utf-8"))
    task = exported[0]
    assert task["completed_by"] == "tester"
    assert task["updated_by"] == "tester"
    result = task["annotations"][0]["result"]
    keypoint = next(item for item in result if item["type"] == "keypointlabels")
    choices = next(item for item in result if item["type"] == "choices")
    assert keypoint["value"]["x"] == 25.0
    assert keypoint["value"]["y"] == 50.0
    assert choices["value"]["choices"] == ["visible"]


def test_saves_not_visible_and_skip_without_keypoint(tmp_path):
    store = _make_store(tmp_path)

    not_visible = store.save_annotation("sample_001__31", {"state": "not_visible"}, reviewer="tester")
    skipped = store.save_annotation("sample_001__32", {"state": "skip"}, reviewer="tester")

    assert not_visible == {"state": "not_visible"}
    assert skipped == {"state": "skip"}
    exported = json.loads((tmp_path / "labelstudio/labelstudio_export.json").read_text(encoding="utf-8"))
    first_result = exported[0]["annotations"][0]["result"]
    second_result = exported[1]["annotations"][0]["result"]
    assert [item["type"] for item in first_result] == ["choices"]
    assert first_result[0]["value"]["choices"] == ["not_visible"]
    assert [item["type"] for item in second_result] == ["choices"]
    assert second_result[0]["value"]["choices"] == ["skip"]


def test_rejects_visible_annotation_outside_frame(tmp_path):
    store = _make_store(tmp_path)

    with pytest.raises(AnnotationValidationError, match="outside frame"):
        store.save_annotation("sample_001__31", {"state": "visible", "x": 321, "y": 90}, reviewer="tester")


def test_resumes_existing_export(tmp_path):
    store = _make_store(tmp_path)
    store.save_annotation("sample_001__31", {"state": "visible", "x": 80, "y": 90}, reviewer="tester")

    resumed = _make_store(tmp_path)

    task = next(item for item in resumed.api_payload()["tasks"] if item["id"] == "sample_001__31")
    assert task["annotation"] == {"state": "visible", "x": 80.0, "y": 90.0}
    assert resumed.progress()["reviewed"] == 1


def test_exposes_batch_video_shots_for_full_frame_browsing(tmp_path):
    tasks_path = tmp_path / "labelstudio/tracknet_m1_tasks.json"
    _write_json(tasks_path, [])
    store = AnnotationStore(
        tasks_path,
        tmp_path / "labelstudio/labelstudio_export.json",
        batch_index_path=_batch_index(tmp_path),
    )

    payload = store.api_payload()

    assert payload["videoShots"] == [{
        "sessionId": "sess_001",
        "shotId": "shot_001",
        "sampleId": "sample_001",
        "frameCount": 2400,
        "fps": 239.9,
        "frameWidth": 320,
        "frameHeight": 180,
        "sourceVideo": str(tmp_path / "missing.mov"),
        "impact": {
            "frameIndex": 1560,
            "source": "duration_ratio_heuristic",
            "confidence": 0.4,
        },
        "trackman": {"timeDeltaSeconds": 0.027},
        "reviewed": 0,
        "seed": None,
    }]


def test_saves_annotation_for_dynamic_video_frame_not_in_candidate_tasks(tmp_path):
    tasks_path = tmp_path / "labelstudio/tracknet_m1_tasks.json"
    _write_json(tasks_path, [])
    store = AnnotationStore(
        tasks_path,
        tmp_path / "labelstudio/labelstudio_export.json",
        batch_index_path=_batch_index(tmp_path),
    )

    saved = store.save_annotation("sample_001__120", {"state": "visible", "x": 80, "y": 90}, reviewer="tester")

    assert saved == {"state": "visible", "x": 80.0, "y": 90.0}
    exported = json.loads((tmp_path / "labelstudio/labelstudio_export.json").read_text(encoding="utf-8"))
    assert len(exported) == 1
    assert exported[0]["data"]["sample_id"] == "sample_001"
    assert exported[0]["data"]["frame_index"] == 120
    assert exported[0]["data"]["frame_width"] == 320
    assert exported[0]["data"]["frame_height"] == 180
    assert exported[0]["data"]["image"].endswith("/frames/sess_001/shot_001/frame_000120.jpg")


def test_dynamic_video_frame_path_sanitizes_session_and_shot_ids(tmp_path):
    tasks_path = tmp_path / "labelstudio/tracknet_m1_tasks.json"
    _write_json(tasks_path, [])
    store = AnnotationStore(
        tasks_path,
        tmp_path / "labelstudio/labelstudio_export.json",
        batch_index_path=_batch_index(tmp_path, session_id="../sess", shot_id="../shot"),
    )

    store.save_annotation("sample_001__120", {"state": "visible", "x": 80, "y": 90}, reviewer="tester")

    exported = json.loads((tmp_path / "labelstudio/labelstudio_export.json").read_text(encoding="utf-8"))
    frame_path = Path(exported[0]["data"]["image"].replace("file://", "")).resolve()
    frames_root = (tmp_path / "labelstudio/frames").resolve()
    assert frame_path.is_relative_to(frames_root)
    assert not (tmp_path / "labelstudio/sess").exists()
    assert not (tmp_path / "labelstudio/shot").exists()


def test_static_seed_ui_contains_dual_point_controls_and_payload():
    app_js = (PLATFORM_ROOT.parents[2] / "tracknetv6-dataset-annotation/annotator/app.js").read_text(encoding="utf-8")

    assert "clubhead_center" in app_js
    assert "clubheadPoint" in app_js
    assert "points" in app_js


def test_static_seed_ui_treats_missing_clubhead_as_next_open_seed():
    app_js = (PLATFORM_ROOT.parents[2] / "tracknetv6-dataset-annotation/annotator/app.js").read_text(encoding="utf-8")

    assert "seedHasClubhead" in app_js
    assert "missingClubhead" in app_js
    assert "缺杆头" in app_js


def test_alignment_review_payload_and_save_reviewed_pair(tmp_path):
    tasks_path = tmp_path / "labelstudio/tracknet_m1_tasks.json"
    _write_json(tasks_path, [])
    candidate_path = tmp_path / "m1_trackman_alignment/candidate_alignment.json"
    _write_json(candidate_path, {
        "version": "1.0",
        "pairs": [{
            "sampleId": "sample_001",
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "videoPath": "/data/sample_001.mov",
            "trackmanPhotoPath": "/data/photo_001.jpg",
            "timeDeltaSeconds": 1.25,
            "rawOcrText": "Ball Speed 148.2 mph",
            "ocrBoxes": [],
            "candidateFields": {},
        }],
        "unmatchedVideos": [],
        "unmatchedTrackmanPhotos": [],
    })
    store = AnnotationStore(
        tasks_path,
        tmp_path / "labelstudio/labelstudio_export.json",
        alignment_candidates_path=candidate_path,
        reviewed_alignment_path=tmp_path / "m1_trackman_alignment/reviewed_alignment.json",
    )

    payload = store.alignment_payload()
    assert payload["pairs"][0]["reviewStatus"] == "needs_review"
    saved = store.save_alignment_review("sample_001", {
        "reviewStatus": "accepted",
        "trackmanDataStatus": "usable",
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {
                "rawValue": 148.2,
                "rawUnit": "mph",
                "normalizedValue": 66.25,
                "normalizedUnit": "m/s",
            }
        },
    }, reviewer="tester")
    assert saved["reviewStatus"] == "accepted"
    reviewed = json.loads((tmp_path / "m1_trackman_alignment/reviewed_alignment.json").read_text(encoding="utf-8"))
    assert reviewed["pairs"][0]["reviewer"] == "tester"


def test_seed_video_shots_can_be_limited_to_reviewed_accepted_pairs(tmp_path):
    tasks_path = tmp_path / "labelstudio/tracknet_m1_tasks.json"
    _write_json(tasks_path, [])
    batch_index = _batch_index(tmp_path)
    reviewed_path = tmp_path / "reviewed_alignment.json"
    _write_json(reviewed_path, {
        "version": "1.0",
        "pairs": [{
            "sampleId": "sample_001",
            "reviewStatus": "accepted",
            "trackmanDataStatus": "unreadable",
            "metricsUsable": False,
            "trackmanPhotoPath": "/data/photo.jpg",
        }],
    })
    store = AnnotationStore(
        tasks_path,
        tmp_path / "labelstudio/labelstudio_export.json",
        batch_index_path=batch_index,
        reviewed_alignment_path=reviewed_path,
        accepted_only=True,
    )

    payload = store.video_shots_payload()

    assert [shot["sampleId"] for shot in payload["shots"]] == ["sample_001"]


def test_accepted_only_requires_existing_reviewed_alignment(tmp_path):
    tasks_path = tmp_path / "labelstudio/tracknet_m1_tasks.json"
    _write_json(tasks_path, [])
    batch_index = _batch_index(tmp_path)

    with pytest.raises(AnnotationValidationError, match="reviewed alignment|accepted-only"):
        AnnotationStore(
            tasks_path,
            tmp_path / "labelstudio/labelstudio_export.json",
            batch_index_path=batch_index,
            reviewed_alignment_path=tmp_path / "missing_reviewed_alignment.json",
            accepted_only=True,
        )


def test_rejects_unknown_task_id_and_unknown_state(tmp_path):
    store = _make_store(tmp_path)

    with pytest.raises(AnnotationValidationError, match="unknown task"):
        store.save_annotation("missing", {"state": "visible", "x": 1, "y": 1}, reviewer="tester")
    with pytest.raises(AnnotationValidationError, match="unsupported annotation state"):
        store.save_annotation("sample_001__31", {"state": "maybe"}, reviewer="tester")


def test_frame_path_returns_only_known_task_frames(tmp_path):
    store = _make_store(tmp_path)

    frame_path = store.frame_path("sample_001__31")

    assert frame_path.name == "frame_000031.jpg"
    with pytest.raises(AnnotationValidationError, match="unknown task"):
        store.frame_path("../secret")


def test_http_app_returns_tasks_and_saves_annotation(tmp_path):
    from lib.tracknet_m1_web_annotator import AnnotatorHttpApp

    store = _make_store(tmp_path)
    app = AnnotatorHttpApp(store, asset_dir=tmp_path)

    status, headers, body = app.handle("GET", "/api/tasks", b"")
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body.decode("utf-8"))["progress"]["total"] == 2

    status, headers, body = app.handle(
        "PUT",
        "/api/annotations/sample_001__31",
        json.dumps({"state": "visible", "x": 80, "y": 90}).encode("utf-8"),
    )
    assert status == 200
    assert json.loads(body.decode("utf-8"))["annotation"] == {"state": "visible", "x": 80.0, "y": 90.0}


def test_http_app_returns_video_shots_and_saves_seed(tmp_path):
    from lib.tracknet_m1_web_annotator import AnnotatorHttpApp

    tasks_path = tmp_path / "labelstudio/tracknet_m1_tasks.json"
    _write_json(tasks_path, [])
    store = AnnotationStore(
        tasks_path,
        tmp_path / "labelstudio/labelstudio_export.json",
        batch_index_path=_batch_index(tmp_path),
        seed_path=tmp_path / "m1_sota_tracking/seeds.json",
    )
    app = AnnotatorHttpApp(store, asset_dir=tmp_path)

    status, headers, body = app.handle("GET", "/api/video-shots", b"")
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body.decode("utf-8"))["progress"] == {
        "total": 1,
        "seeded": 0,
        "missing": 1,
        "clubheadSeeded": 0,
        "missingClubhead": 1,
    }

    status, headers, body = app.handle(
        "PUT",
        "/api/seeds/sample_001",
        json.dumps({"frameIndex": 12, "x": 80, "y": 90}).encode("utf-8"),
    )

    assert status == 200
    payload = json.loads(body.decode("utf-8"))
    assert payload["seed"]["sampleId"] == "sample_001"
    assert payload["seed"]["frameIndex"] == 12
    assert payload["progress"] == {
        "total": 1,
        "seeded": 1,
        "missing": 0,
        "clubheadSeeded": 0,
        "missingClubhead": 1,
    }


def test_http_app_rejects_bad_annotation_request(tmp_path):
    from lib.tracknet_m1_web_annotator import AnnotatorHttpApp

    store = _make_store(tmp_path)
    app = AnnotatorHttpApp(store, asset_dir=tmp_path)

    status, headers, body = app.handle(
        "PUT",
        "/api/annotations/sample_001__31",
        json.dumps({"state": "visible", "x": 999, "y": 90}).encode("utf-8"),
    )

    assert status == 400
    assert "outside frame" in json.loads(body.decode("utf-8"))["error"]


def test_server_asset_path_maps_root_and_rejects_traversal(tmp_path):
    from serve_tracknet_m1_annotator import _safe_asset_path

    index = tmp_path / "index.html"
    index.write_text("ok", encoding="utf-8")

    assert _safe_asset_path(tmp_path, "/") == index
    assert _safe_asset_path(tmp_path, "/../secret.txt") is None


def test_annotator_static_assets_exist_and_default_candidates_off():
    asset_dir = PLATFORM_ROOT.parents[2] / "tracknetv6-dataset-annotation" / "annotator"

    index = (asset_dir / "index.html").read_text(encoding="utf-8")
    app_js = (asset_dir / "app.js").read_text(encoding="utf-8")
    styles = (asset_dir / "styles.css").read_text(encoding="utf-8")

    assert "TrackNetV6 M1 Annotator" in index
    assert "candidateOverlayEnabled = false" in app_js
    assert "function imagePointFromEvent" in app_js
    assert ".annotation-stage" in styles




def test_annotator_keeps_click_visible_and_supports_zoom_controls():
    asset_dir = PLATFORM_ROOT.parents[2] / "tracknetv6-dataset-annotation" / "annotator"

    index = (asset_dir / "index.html").read_text(encoding="utf-8")
    app_js = (asset_dir / "app.js").read_text(encoding="utf-8")
    styles = (asset_dir / "styles.css").read_text(encoding="utf-8")

    assert 'id="zoomInButton"' in index
    assert 'id="autoAdvanceToggle"' in index
    assert "let autoAdvanceEnabled = false" in app_js
    assert "function setZoom" in app_js
    assert "function renderZoom" in app_js
    assert "if (autoAdvanceEnabled) goRelative(1);" in app_js
    assert "--zoom-scale" in styles

def test_annotator_defaults_to_video_frame_browsing_controls():
    asset_dir = PLATFORM_ROOT.parents[2] / "tracknetv6-dataset-annotation" / "annotator"

    index = (asset_dir / "index.html").read_text(encoding="utf-8")
    app_js = (asset_dir / "app.js").read_text(encoding="utf-8")

    assert 'id="frameInput"' in index
    assert 'id="frameSlider"' in index
    assert 'id="jumpBack120Button"' in index
    assert 'id="jumpForward120Button"' in index
    assert 'id="saveSeedButton"' in index
    assert 'let mode = "seed"' in app_js
    assert "function renderVideoFrame" in app_js
    assert "function saveSeed" in app_js
    assert "/video-frame/" in app_js


def test_web_annotator_export_imports_with_existing_review_importer(tmp_path):
    from lib.tracknet_m1_review_import import import_reviewed_labels

    store = _make_store(tmp_path)
    store.save_annotation("sample_001__31", {"state": "visible", "x": 80, "y": 90}, reviewer="web_annotator")
    store.save_annotation("sample_001__32", {"state": "not_visible"}, reviewer="web_annotator")
    batch_index = tmp_path / "m1_batch/batch_index.json"
    _write_json(batch_index, {
        "version": "1.0",
        "sourceExportDir": str(tmp_path / "DatasetCollectorExport"),
        "shots": [{
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "sampleId": "sample_001",
            "sourceVideo": "/data/source.mov",
            "frameWidth": 320,
            "frameHeight": 180,
            "trackmanMatch": {"matchIndex": 7},
        }],
        "unusableSamples": [],
    })

    report = import_reviewed_labels(
        tmp_path / "labelstudio/labelstudio_export.json",
        batch_index,
        tmp_path / "reviewed",
        min_reviewed_frames_per_shot=2,
    )

    assert report["reviewedLabels"] == 2
    labels = (tmp_path / "reviewed/reviewed_labels.csv").read_text(encoding="utf-8")
    assert "web_annotator" in labels
    assert "80.000,90.000,1" in labels
