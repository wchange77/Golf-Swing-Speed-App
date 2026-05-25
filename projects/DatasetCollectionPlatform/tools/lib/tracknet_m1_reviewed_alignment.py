from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_REVIEW_STATUSES = {"accepted", "rejected", "needs_review"}
VALID_TRACKMAN_DATA_STATUSES = {"usable", "partial", "unreadable"}


class ReviewedAlignmentError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewedAlignment:
    version: str
    pairs: list[dict[str, Any]]
    unmatched_videos: list[dict[str, Any]]
    unmatched_trackman_photos: list[dict[str, Any]]
    summary: dict[str, int]

    @property
    def accepted_pairs(self) -> list[dict[str, Any]]:
        return [pair for pair in self.pairs if pair.get("reviewStatus") == "accepted"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _optional_list(payload: dict[str, Any], field: str) -> list[Any]:
    if field not in payload:
        return []
    value = payload[field]
    if not isinstance(value, list):
        raise ReviewedAlignmentError(f"{field} must be a list")
    return value


def _require_field(pair: dict[str, Any], field: str, index: int) -> Any:
    value = pair.get(field)
    if value is None or value == "":
        raise ReviewedAlignmentError(f"pair {index} missing required field: {field}")
    return value


def _validate_accepted_pair(
    pair: dict[str, Any],
    index: int,
    sample_ids: set[str],
    trackman_photo_paths: set[str],
) -> None:
    sample_id = str(_require_field(pair, "sampleId", index))
    trackman_photo_path = str(_require_field(pair, "trackmanPhotoPath", index))
    data_status = _require_field(pair, "trackmanDataStatus", index)
    if data_status not in VALID_TRACKMAN_DATA_STATUSES:
        raise ReviewedAlignmentError(f"pair {index} has invalid trackmanDataStatus: {data_status}")
    if "metricsUsable" not in pair:
        raise ReviewedAlignmentError(f"pair {index} missing required field: metricsUsable")
    if not isinstance(pair["metricsUsable"], bool):
        raise ReviewedAlignmentError(f"pair {index} metricsUsable must be boolean")
    if sample_id in sample_ids:
        raise ReviewedAlignmentError(f"sampleId matched more than once: {sample_id}")
    if trackman_photo_path in trackman_photo_paths:
        raise ReviewedAlignmentError(f"TrackMan photo matched more than once: {trackman_photo_path}")
    sample_ids.add(sample_id)
    trackman_photo_paths.add(trackman_photo_path)


def _validate_pair(pair: dict[str, Any], index: int, sample_ids: set[str], trackman_photo_paths: set[str]) -> None:
    status = pair.get("reviewStatus")
    if status not in VALID_REVIEW_STATUSES:
        raise ReviewedAlignmentError(f"pair {index} has invalid reviewStatus: {status}")
    if status == "accepted":
        _validate_accepted_pair(pair, index, sample_ids, trackman_photo_paths)
    elif status == "rejected" and not pair.get("rejectReason"):
        raise ReviewedAlignmentError(f"pair {index} rejected pair missing rejectReason")


def load_reviewed_alignment(path: Path | str) -> ReviewedAlignment:
    path = Path(path)
    payload = _read_json(path)
    pairs = _optional_list(payload, "pairs")

    sample_ids: set[str] = set()
    trackman_photo_paths: set[str] = set()
    for index, pair in enumerate(pairs, start=1):
        if not isinstance(pair, dict):
            raise ReviewedAlignmentError(f"pair {index} must be an object")
        _validate_pair(pair, index, sample_ids, trackman_photo_paths)

    unmatched_videos = _optional_list(payload, "unmatchedVideos")
    unmatched_trackman_photos = _optional_list(payload, "unmatchedTrackmanPhotos")
    summary = {
        "accepted": sum(1 for pair in pairs if pair.get("reviewStatus") == "accepted"),
        "rejected": sum(1 for pair in pairs if pair.get("reviewStatus") == "rejected"),
        "needsReview": sum(1 for pair in pairs if pair.get("reviewStatus") == "needs_review"),
        "unmatchedVideos": len(unmatched_videos),
        "unmatchedTrackmanPhotos": len(unmatched_trackman_photos),
    }
    return ReviewedAlignment(
        version=str(payload.get("version") or "1.0"),
        pairs=pairs,
        unmatched_videos=unmatched_videos,
        unmatched_trackman_photos=unmatched_trackman_photos,
        summary=summary,
    )


def _accepted_pairs_by_sample(reviewed: ReviewedAlignment) -> dict[str, dict[str, Any]]:
    return {str(pair["sampleId"]): pair for pair in reviewed.accepted_pairs}


def _skipped_unusable_sample(shot: dict[str, Any]) -> dict[str, Any]:
    return {
        "sampleId": shot.get("sampleId"),
        "sessionId": shot.get("sessionId"),
        "shotId": shot.get("shotId"),
        "reason": "not_accepted_reviewed_alignment",
    }


def _missing_source_unusable_sample(pair: dict[str, Any]) -> dict[str, Any]:
    return {
        "sampleId": pair.get("sampleId"),
        "shotId": pair.get("shotId"),
        "reason": "accepted_reviewed_alignment_missing_source_batch",
    }


def build_reviewed_batch_index(
    source_batch_path: Path | str,
    reviewed_alignment_path: Path | str,
    output_path: Path | str,
) -> dict[str, Any]:
    source_batch_path = Path(source_batch_path)
    reviewed_alignment_path = Path(reviewed_alignment_path)
    output_path = Path(output_path)
    source_batch = _read_json(source_batch_path)
    reviewed = load_reviewed_alignment(reviewed_alignment_path)
    accepted_by_sample = _accepted_pairs_by_sample(reviewed)

    shots: list[dict[str, Any]] = []
    unusable: list[dict[str, Any]] = list(source_batch.get("unusableSamples") or [])
    source_sample_ids: set[str] = set()
    for source_shot in source_batch.get("shots") or []:
        sample_id = str(source_shot.get("sampleId") or "")
        source_sample_ids.add(sample_id)
        accepted_pair = accepted_by_sample.get(sample_id)
        if accepted_pair is None:
            unusable.append(_skipped_unusable_sample(source_shot))
            continue
        shots.append({
            **source_shot,
            "trackmanReviewed": accepted_pair,
        })

    unmatched_accepted_pairs = [
        pair for pair in reviewed.accepted_pairs if str(pair.get("sampleId") or "") not in source_sample_ids
    ]
    for pair in unmatched_accepted_pairs:
        unusable.append(_missing_source_unusable_sample(pair))

    payload = {
        "version": "1.0",
        "generatedAt": _utc_now(),
        "sourceBatchPath": str(source_batch_path),
        "reviewedAlignmentPath": str(reviewed_alignment_path),
        "shots": shots,
        "unusableSamples": unusable,
        "summary": {
            "acceptedPairs": len(shots),
            "reviewedAcceptedPairs": reviewed.summary["accepted"],
            "unmatchedAcceptedPairs": len(unmatched_accepted_pairs),
            "usableShots": len(shots),
            "unusableSamples": len(unusable),
            "rejectedPairs": reviewed.summary["rejected"],
            "needsReviewPairs": reviewed.summary["needsReview"],
            "unmatchedVideos": reviewed.summary["unmatchedVideos"],
            "unmatchedTrackmanPhotos": reviewed.summary["unmatchedTrackmanPhotos"],
        },
    }
    _write_json(output_path, payload)
    return payload
