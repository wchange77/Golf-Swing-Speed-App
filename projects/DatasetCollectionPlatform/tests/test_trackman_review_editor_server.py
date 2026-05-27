from __future__ import annotations

import json
from pathlib import Path
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.trackman_review import build_trackman_review_candidate, export_trackman_review_templates
from serve_trackman_review_editor import TrackManReviewStore, _index_html, make_handler, save_review_payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate() -> dict:
    return build_trackman_review_candidate(
        {
            "sampleId": "sample_001",
            "shotId": "shot_001",
            "trackmanPhoto": "IMG_001.jpg",
            "trackmanPhotoPath": "/data/IMG_001.jpg",
            "ocrPath": "/work/IMG_001.ocr.json",
            "ocrStatus": "ok",
            "text": "杆头速度\n72.9\n起飞角度\n15.3\n落点距离\n152.7\n球路弯曲\n1.3右\n初射球速\n108.3",
            "needsHumanConfirmation": True,
        }
    )


def test_trackman_review_store_lists_editable_samples(tmp_path: Path):
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", _candidate())
    export_trackman_review_templates(candidates_dir=tmp_path / "candidates", output_dir=tmp_path / "reviewed")

    store = TrackManReviewStore(candidates_dir=tmp_path / "candidates", reviewed_dir=tmp_path / "reviewed")
    state = store.editor_state()

    assert state["fieldOrder"][0] == "clubSpeed"
    assert len(state["fieldOrder"]) == 20
    assert state["fieldMeta"]["curve"]["displayNameZh"] == "球路弯曲"
    assert state["samples"] == [
        {
            "sampleId": "sample_001",
            "shotId": "shot_001",
            "trackmanPhoto": "IMG_001.jpg",
            "reviewStatus": "needs_review",
            "metricsUsable": False,
            "importStatus": "not_accepted",
        }
    ]
    review = store.review_for_sample("sample_001")
    assert review["correctedFields"]["clubSpeed"]["normalizedValue"] == 72.9
    assert review["correctedFields"]["curve"]["direction"] == "right"


def test_save_review_payload_updates_json_without_dropping_candidate_context(tmp_path: Path):
    candidate = _candidate()
    reviewed_path = tmp_path / "reviewed/sample_001.trackman_review.json"
    _write_json(reviewed_path, {
        **candidate,
        "reviewStatus": "needs_review",
        "metricsUsable": False,
        "correctedFields": candidate["correctedFieldTemplate"],
    })

    saved = save_review_payload(
        reviewed_path,
        {
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "reviewer": "wangwei",
            "correctedFields": {
                "ballSpeed": {"normalizedValue": 108.3, "normalizedUnit": "mph"},
                "launchAngle": {"normalizedValue": 15.3, "normalizedUnit": "deg"},
                "carry": {"normalizedValue": 152.7, "normalizedUnit": "yd"},
                "curve": {"normalizedValue": 1.3, "normalizedUnit": "yd", "direction": "right"},
            },
        },
    )

    persisted = json.loads(reviewed_path.read_text(encoding="utf-8"))
    assert saved["reviewStatus"] == "accepted"
    assert persisted["metricsUsable"] is True
    assert persisted["reviewer"] == "wangwei"
    assert persisted["correctedFields"]["curve"]["direction"] == "right"
    assert persisted["candidateFields"]["curve"]["rawCandidates"] == ["1.3右"]
    assert persisted["reviewedAt"].endswith("Z")


def test_save_review_payload_normalizes_chinese_units_before_persisting(tmp_path: Path):
    reviewed_path = tmp_path / "reviewed/sample_001.trackman_review.json"
    _write_json(reviewed_path, {"sampleId": "sample_001", "reviewStatus": "needs_review", "metricsUsable": False})

    save_review_payload(
        reviewed_path,
        {
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "reviewer": "wangwei",
            "correctedFields": {
                "ballSpeed": {"normalizedValue": 107.9, "normalizedUnit": "英里"},
                "launchAngle": {"normalizedValue": 16.2, "normalizedUnit": "度"},
                "carry": {"normalizedValue": 154.0, "normalizedUnit": "码"},
                "spinRate": {"normalizedValue": 3556.0, "normalizedUnit": "转/分"},
                "smashFactor": {"normalizedValue": 1.46, "normalizedUnit": "无"},
                "impactHeight": {"normalizedValue": 10.0, "normalizedUnit": "毫米"},
            },
        },
    )

    persisted = json.loads(reviewed_path.read_text(encoding="utf-8"))
    assert persisted["correctedFields"]["ballSpeed"]["normalizedUnit"] == "mph"
    assert persisted["correctedFields"]["launchAngle"]["normalizedUnit"] == "deg"
    assert persisted["correctedFields"]["carry"]["normalizedUnit"] == "yd"
    assert persisted["correctedFields"]["spinRate"]["normalizedUnit"] == "rpm"
    assert persisted["correctedFields"]["smashFactor"]["normalizedUnit"] == "ratio"
    assert persisted["correctedFields"]["impactHeight"]["normalizedUnit"] == "mm"


def test_save_review_payload_preserves_alphanumeric_trackman_values(tmp_path: Path):
    reviewed_path = tmp_path / "reviewed/sample_001.trackman_review.json"
    _write_json(reviewed_path, {"sampleId": "sample_001", "reviewStatus": "needs_review", "metricsUsable": False})

    save_review_payload(
        reviewed_path,
        {
            "reviewStatus": "needs_review",
            "metricsUsable": False,
            "reviewer": "wangwei",
            "correctedFields": {
                "impactHeight": {"normalizedValue": None, "normalizedUnit": "mm", "rawValue": "4U"},
                "lowPointDistance": {"normalizedValue": None, "normalizedUnit": "yd", "rawValue": "5.4A"},
            },
        },
    )

    persisted = json.loads(reviewed_path.read_text(encoding="utf-8"))
    assert persisted["correctedFields"]["impactHeight"] == {
        "normalizedValue": None,
        "normalizedUnit": "mm",
        "rawValue": "4U",
    }
    assert persisted["correctedFields"]["lowPointDistance"] == {
        "normalizedValue": None,
        "normalizedUnit": "yd",
        "rawValue": "5.4A",
    }


def test_editor_html_allows_alphanumeric_trackman_value_inputs():
    html = _index_html()

    assert 'class="value" type="text"' in html
    assert 'type="number"' not in html
    assert "function fieldValueText(value)" in html
    assert "function fieldFromEditor(valueText, unit, direction)" in html
    assert "rawValue" in html
    assert "Number.isFinite(numericValue)" in html


def test_editor_html_reports_save_errors_and_sets_button_types():
    html = _index_html()

    assert 'type="button" id="save-draft"' in html
    assert 'type="button" id="accept"' in html
    assert "保存中..." in html
    assert "保存失败" in html
    assert ".catch" in html


def test_editor_html_flushes_pending_save_before_switching_samples():
    html = _index_html()

    assert "let dirty = false;" in html
    assert "const draftsBySample = {};" in html
    assert "const dirtySamples = new Set();" in html
    assert "function cacheCurrentDraft()" in html
    assert "async function saveSampleDraft(sampleId, payloadFields, accept)" in html
    assert "async function flushPendingSave()" in html
    assert "await flushPendingSave();" in html
    assert "const sampleId = current.sampleId;" in html
    assert "if (current && current.sampleId === sampleId)" in html
    assert "draftsBySample[review.sampleId]" in html
    assert "input.addEventListener('change', scheduleAutosave)" in html


def test_photo_head_returns_headers_for_existing_trackman_photo(tmp_path: Path):
    photo_path = tmp_path / "photos/IMG_001.jpg"
    photo_path.parent.mkdir(parents=True)
    photo_path.write_bytes(b"\xff\xd8\xff\xd9")
    candidate = {**_candidate(), "trackmanPhotoPath": str(photo_path)}
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    export_trackman_review_templates(candidates_dir=tmp_path / "candidates", output_dir=tmp_path / "reviewed")
    store = TrackManReviewStore(candidates_dir=tmp_path / "candidates", reviewed_dir=tmp_path / "reviewed")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.request("HEAD", "/api/photos/sample_001")
        response = conn.getresponse()

        assert response.status == 200
        assert response.getheader("Content-Type") == "image/jpeg"
        assert response.getheader("Content-Length") == "4"
        assert response.read() == b""
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
