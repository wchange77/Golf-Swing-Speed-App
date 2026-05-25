from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_reviewed_alignment import (
    ReviewedAlignmentError,
    build_reviewed_batch_index,
    load_reviewed_alignment,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _accepted(sample_id: str = "sample_001", photo_id: str = "photo_001") -> dict:
    return {
        "sampleId": sample_id,
        "sessionId": "sess_001",
        "shotId": "shot_001",
        "videoPath": f"/data/{sample_id}.mov",
        "trackmanPhotoPath": f"/data/{photo_id}.jpg",
        "timeDeltaSeconds": 1.25,
        "reviewStatus": "accepted",
        "trackmanDataStatus": "usable",
        "metricsUsable": True,
        "rawOcrText": "Ball Speed 148.2 mph",
        "ocrBoxes": [],
        "candidateFields": {},
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
    }


def test_load_reviewed_alignment_keeps_accepted_rejected_and_unmatched(tmp_path: Path):
    path = tmp_path / "reviewed_alignment.json"
    _write_json(path, {
        "version": "1.0",
        "pairs": [
            _accepted(),
            {**_accepted("sample_002", "photo_002"), "reviewStatus": "rejected", "rejectReason": "wrong shot"},
        ],
        "unmatchedVideos": [{"sampleId": "sample_003", "reason": "no_trackman_candidate"}],
        "unmatchedTrackmanPhotos": [{"trackmanPhotoPath": "/data/photo_003.jpg", "reason": "no_video_candidate"}],
    })

    reviewed = load_reviewed_alignment(path)

    assert reviewed.summary == {
        "accepted": 1,
        "rejected": 1,
        "needsReview": 0,
        "unmatchedVideos": 1,
        "unmatchedTrackmanPhotos": 1,
    }
    assert reviewed.accepted_pairs[0]["sampleId"] == "sample_001"
    assert reviewed.accepted_pairs[0]["correctedFields"]["ballSpeed"]["normalizedUnit"] == "m/s"
    rejected_pair = next(pair for pair in reviewed.pairs if pair["reviewStatus"] == "rejected")
    assert rejected_pair["sampleId"] == "sample_002"
    assert rejected_pair["rejectReason"] == "wrong shot"
    assert reviewed.unmatched_videos == [{"sampleId": "sample_003", "reason": "no_trackman_candidate"}]
    assert reviewed.unmatched_trackman_photos == [
        {"trackmanPhotoPath": "/data/photo_003.jpg", "reason": "no_video_candidate"}
    ]


def test_rejects_many_to_one_and_one_to_many_accepted_pairs(tmp_path: Path):
    path = tmp_path / "reviewed_alignment.json"
    _write_json(path, {
        "version": "1.0",
        "pairs": [
            _accepted("sample_001", "photo_001"),
            _accepted("sample_002", "photo_001"),
        ],
    })

    with pytest.raises(ReviewedAlignmentError, match="TrackMan photo matched more than once"):
        load_reviewed_alignment(path)


def test_unreadable_accepted_pair_enters_batch_with_metrics_unusable(tmp_path: Path):
    reviewed_path = tmp_path / "reviewed_alignment.json"
    pair = {**_accepted(), "trackmanDataStatus": "unreadable", "metricsUsable": False, "correctedFields": {}}
    _write_json(reviewed_path, {"version": "1.0", "pairs": [pair]})
    source_batch = {
        "version": "1.0",
        "shots": [{
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "sampleId": "sample_001",
            "sourceVideo": "/data/sample_001.mov",
            "frameCount": 240,
            "fps": 240,
            "frameWidth": 1920,
            "frameHeight": 1080,
            "trackmanMatch": {"legacy": True},
        }],
        "unusableSamples": [],
    }
    source_batch_path = tmp_path / "m1_batch" / "batch_index.json"
    _write_json(source_batch_path, source_batch)

    output = build_reviewed_batch_index(
        source_batch_path=source_batch_path,
        reviewed_alignment_path=reviewed_path,
        output_path=tmp_path / "m1_reviewed_batch" / "batch_index.json",
    )

    assert output["summary"]["acceptedPairs"] == 1
    assert output["shots"][0]["trackmanReviewed"]["metricsUsable"] is False
    assert output["shots"][0]["trackmanReviewed"]["trackmanDataStatus"] == "unreadable"
    assert output["shots"][0]["trackmanReviewed"]["rawOcrText"] == "Ball Speed 148.2 mph"


def test_cli_default_annotation_root_uses_workspace_root():
    from build_tracknet_m1_reviewed_batch import _default_annotation_root

    assert _default_annotation_root() == Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def test_missing_source_for_accepted_pair_is_reported_as_unusable(tmp_path: Path):
    reviewed_path = tmp_path / "reviewed_alignment.json"
    accepted_without_source = {**_accepted("sample_002", "photo_002"), "shotId": "shot_002"}
    _write_json(reviewed_path, {"version": "1.0", "pairs": [accepted_without_source]})
    source_batch_path = tmp_path / "m1_batch" / "batch_index.json"
    _write_json(source_batch_path, {
        "version": "1.0",
        "shots": [{
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "sampleId": "sample_001",
            "sourceVideo": "/data/sample_001.mov",
            "frameCount": 240,
            "fps": 240,
            "frameWidth": 1920,
            "frameHeight": 1080,
        }],
        "unusableSamples": [],
    })

    output = build_reviewed_batch_index(
        source_batch_path=source_batch_path,
        reviewed_alignment_path=reviewed_path,
        output_path=tmp_path / "m1_reviewed_batch" / "batch_index.json",
    )

    assert output["summary"]["acceptedPairs"] == 0
    assert output["summary"]["reviewedAcceptedPairs"] == 1
    assert output["summary"]["unmatchedAcceptedPairs"] == 1
    assert output["unusableSamples"] == [
        {
            "sampleId": "sample_001",
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "reason": "not_accepted_reviewed_alignment",
        },
        {
            "sampleId": "sample_002",
            "shotId": "shot_002",
            "reason": "accepted_reviewed_alignment_missing_source_batch",
        },
    ]


@pytest.mark.parametrize("field", ["pairs", "unmatchedVideos", "unmatchedTrackmanPhotos"])
def test_reviewed_alignment_rejects_malformed_list_fields(tmp_path: Path, field: str):
    path = tmp_path / "reviewed_alignment.json"
    payload = {"version": "1.0", "pairs": []}
    payload[field] = ""
    _write_json(path, payload)

    with pytest.raises(ReviewedAlignmentError, match=field):
        load_reviewed_alignment(path)
