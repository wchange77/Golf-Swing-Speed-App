from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_export_path(export_dir: Path, rel: str | None) -> Path | None:
    if not rel:
        return None
    candidates = [export_dir / rel]
    if rel.startswith("ios_export/"):
        candidates.insert(0, export_dir / rel.removeprefix("ios_export/"))
    candidates.append(export_dir / Path(rel).name)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _unusable(*, sample_id: str | None, shot_id: str | None, reason: str) -> dict[str, Any]:
    return {"sampleId": sample_id, "shotId": shot_id, "reason": reason}


def build_batch_index(export_dir: Path | str, autolabel_dir: Path | str, output_dir: Path | str) -> dict[str, Any]:
    export_dir = Path(export_dir).resolve()
    autolabel_dir = Path(autolabel_dir).resolve()
    output_dir = Path(output_dir).resolve()
    summary_path = autolabel_dir / "alignment_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"alignment summary not found: {summary_path}")
    summary = _read_json(summary_path)
    shots: list[dict[str, Any]] = []
    unusable: list[dict[str, Any]] = []
    for item in summary.get("samples", []):
        if item.get("status") != "ok":
            unusable.append(_unusable(
                sample_id=item.get("sampleId"),
                shot_id=item.get("shotId"),
                reason=str(item.get("reason") or "autolabel_error"),
            ))
            continue
        observations_path = autolabel_dir / str(item["observationsPath"])
        observations = _read_json(observations_path)
        sample = observations.get("sample", {})
        video = observations.get("video", {})
        sample_id = sample.get("sampleId")
        shot_id = sample.get("shotId")
        asset_path = _resolve_export_path(export_dir, sample.get("assetPath"))
        if asset_path is None:
            unusable.append(_unusable(sample_id=sample_id, shot_id=shot_id, reason="asset_not_found"))
            continue
        frame_count = int(video.get("frameCount") or 0)
        fps = float(video.get("fps") or 0)
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        if frame_count <= 0 or fps <= 0 or width <= 0 or height <= 0:
            unusable.append(_unusable(sample_id=sample_id, shot_id=shot_id, reason="invalid_video_metadata"))
            continue
        shots.append({
            "sessionId": sample.get("sessionId"),
            "shotId": shot_id,
            "sampleId": sample_id,
            "sourceVideo": str(asset_path),
            "assetPath": sample.get("assetPath"),
            "candidateObservationsPath": str(observations_path),
            "frameCount": frame_count,
            "fps": fps,
            "frameWidth": width,
            "frameHeight": height,
            "impact": observations.get("impact", {}),
            "trackmanMatch": observations.get("trackmanMatch", {}),
            "candidateSummary": observations.get("summary", {}),
        })
    payload = {
        "version": "1.0",
        "generatedAt": _utc_now(),
        "sourceExportDir": str(export_dir),
        "sourceAutolabelDir": str(autolabel_dir),
        "shots": shots,
        "unusableSamples": unusable,
        "summary": {
            "usableShots": len(shots),
            "unusableSamples": len(unusable),
            "matchedShots": int((summary.get("alignmentSummary") or {}).get("matchedShots") or len(shots)),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "batch_index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
