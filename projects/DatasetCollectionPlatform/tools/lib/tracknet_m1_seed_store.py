from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from math import hypot
from pathlib import Path
from typing import Any


class SeedValidationError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _field(payload: dict[str, Any], name: str, *, display_name: str | None = None) -> Any:
    field_name = display_name or name
    if name not in payload:
        raise SeedValidationError(f"missing required seed field: {field_name}")
    return payload[name]


def _mapping_field(payload: dict[str, Any], name: str, *, display_name: str | None = None) -> dict[str, Any]:
    field_name = display_name or name
    value = _field(payload, name, display_name=field_name)
    if not isinstance(value, dict):
        raise SeedValidationError(f"seed field must be an object: {field_name}")
    return value


def _int_field(payload: dict[str, Any], name: str, *, display_name: str | None = None) -> int:
    field_name = display_name or name
    value = _field(payload, name, display_name=field_name)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SeedValidationError(f"seed field must be an integer: {field_name}") from exc


def _float_field(payload: dict[str, Any], name: str, *, display_name: str | None = None) -> float:
    field_name = display_name or name
    value = _field(payload, name, display_name=field_name)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SeedValidationError(f"seed field must be numeric: {field_name}") from exc


def _visible_point(payload: dict[str, Any], name: str, *, visible: bool = True) -> dict[str, Any]:
    return {
        "x": _float_field(payload, "x", display_name=f"{name}.x"),
        "y": _float_field(payload, "y", display_name=f"{name}.y"),
        "visible": bool(payload.get("visible", visible)),
    }


class TrackNetM1SeedStore:
    def __init__(self, path: Path | str, shots: list[dict[str, Any]]):
        self.path = Path(path)
        self.shots = [deepcopy(shot) for shot in shots]
        self._shots_by_sample = {str(shot.get("sampleId")): shot for shot in self.shots if shot.get("sampleId")}
        self._seeds_by_sample: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        seeds = payload.get("seeds") if isinstance(payload, dict) else None
        if not isinstance(seeds, list):
            raise SeedValidationError(f"could not locate seeds in {self.path}")
        for seed in seeds:
            sample_id = str(seed.get("sampleId") or "")
            if sample_id:
                self._seeds_by_sample[sample_id] = self._normalize_loaded_seed(seed)

    def save_seed(self, sample_id: str, payload: dict[str, Any], reviewer: str = "web_seed_annotator") -> dict[str, Any]:
        shot = self._shots_by_sample.get(sample_id)
        if shot is None:
            raise SeedValidationError(f"unknown sample: {sample_id}")
        normalized = self._normalize_payload(payload)
        seed_frame = int(normalized["seedFrame"])
        ball = normalized["points"]["ball_center"]
        clubhead = normalized["points"]["clubhead_center"]
        self._validate_seed(shot, seed_frame, ball["x"], ball["y"])
        if clubhead["visible"]:
            self._validate_seed(shot, seed_frame, clubhead["x"], clubhead["y"])
            if not normalized.get("overrideReason") and hypot(clubhead["x"] - ball["x"], clubhead["y"] - ball["y"]) <= 12.0:
                raise SeedValidationError("ball_center and clubhead_center are too close; provide overrideReason to save")
        now = _utc_now()
        existing = self._seeds_by_sample.get(sample_id, {})
        seed = {
            "sampleId": sample_id,
            "sessionId": str(shot.get("sessionId") or ""),
            "shotId": str(shot.get("shotId") or ""),
            "sourceVideo": str(shot.get("sourceVideo") or ""),
            "seedFrame": seed_frame,
            "points": normalized["points"],
            "patches": normalized["patches"],
            "frameIndex": seed_frame,
            "x": ball["x"],
            "y": ball["y"],
            "frameWidth": int(shot.get("frameWidth") or 0),
            "frameHeight": int(shot.get("frameHeight") or 0),
            "fps": float(shot.get("fps") or 0.0),
            "frameCount": int(shot.get("frameCount") or 0),
            "trackman": deepcopy(shot.get("trackmanMatch") or {}),
            "trackmanReviewed": deepcopy(shot.get("trackmanReviewed") or {}),
            "reviewer": reviewer,
            "createdAt": existing.get("createdAt") or now,
            "updatedAt": now,
        }
        if normalized.get("overrideReason"):
            seed["overrideReason"] = normalized["overrideReason"]
        self._seeds_by_sample[sample_id] = seed
        self.write()
        return deepcopy(seed)

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "points" not in payload:
            frame_index = _int_field(payload, "frameIndex")
            x = _float_field(payload, "x")
            y = _float_field(payload, "y")
            ball = {"x": x, "y": y, "visible": True}
            clubhead = {"x": x, "y": y, "visible": False}
        else:
            points = _mapping_field(payload, "points")
            frame_index = _int_field(payload, "seedFrame")
            ball = _visible_point(
                _mapping_field(points, "ball_center", display_name="points.ball_center"),
                "points.ball_center",
                visible=True,
            )
            clubhead = _visible_point(
                _mapping_field(points, "clubhead_center", display_name="points.clubhead_center"),
                "points.clubhead_center",
                visible=False,
            )

        patches = deepcopy(payload.get("patches") or {})
        ball_patch = {"radiusPx": 8, "grid": "3x3", **deepcopy(patches.get("ball_patch") or {})}
        clubhead_patch = {"radiusPx": 18, "grid": "5x5", **deepcopy(patches.get("clubhead_patch") or {})}
        normalized: dict[str, Any] = {
            "seedFrame": frame_index,
            "points": {
                "ball_center": ball,
                "clubhead_center": clubhead,
            },
            "patches": {
                "ball_patch": ball_patch,
                "clubhead_patch": clubhead_patch,
            },
        }
        if payload.get("overrideReason"):
            normalized["overrideReason"] = str(payload["overrideReason"])
        return normalized

    def _normalize_loaded_seed(self, seed: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(seed)
        ball = normalized["points"]["ball_center"]
        loaded = {
            **deepcopy(seed),
            "seedFrame": normalized["seedFrame"],
            "points": normalized["points"],
            "patches": normalized["patches"],
            "frameIndex": normalized["seedFrame"],
            "x": ball["x"],
            "y": ball["y"],
        }
        if normalized.get("overrideReason"):
            loaded["overrideReason"] = normalized["overrideReason"]
        return loaded

    def _validate_seed(self, shot: dict[str, Any], frame_index: int, x: float, y: float) -> None:
        frame_count = int(shot.get("frameCount") or 0)
        frame_width = int(shot.get("frameWidth") or 0)
        frame_height = int(shot.get("frameHeight") or 0)
        if frame_index < 0 or (frame_count > 0 and frame_index >= frame_count):
            raise SeedValidationError(f"seed frame outside video: frameIndex={frame_index}, frameCount={frame_count}")
        if x < 0 or y < 0 or x > frame_width or y > frame_height:
            raise SeedValidationError(f"seed point outside frame: x={x}, y={y}, width={frame_width}, height={frame_height}")

    def seed_for(self, sample_id: str) -> dict[str, Any] | None:
        seed = self._seeds_by_sample.get(sample_id)
        return deepcopy(seed) if seed is not None else None

    def progress(self) -> dict[str, int]:
        total = len(self._shots_by_sample)
        seeded = sum(1 for sample_id in self._shots_by_sample if sample_id in self._seeds_by_sample)
        clubhead_seeded = sum(
            1
            for sample_id in self._shots_by_sample
            if (
                (self._seeds_by_sample.get(sample_id, {}).get("points") or {})
                .get("clubhead_center", {})
                .get("visible")
            )
        )
        return {
            "total": total,
            "seeded": seeded,
            "missing": total - seeded,
            "clubheadSeeded": clubhead_seeded,
            "missingClubhead": total - clubhead_seeded,
        }

    def api_payload(self) -> dict[str, Any]:
        shots = []
        for shot in self.shots:
            sample_id = str(shot.get("sampleId") or "")
            shots.append({
                "sessionId": str(shot.get("sessionId") or ""),
                "shotId": str(shot.get("shotId") or ""),
                "sampleId": sample_id,
                "sourceVideo": str(shot.get("sourceVideo") or ""),
                "frameCount": int(shot.get("frameCount") or 0),
                "fps": float(shot.get("fps") or 0.0),
                "frameWidth": int(shot.get("frameWidth") or 0),
                "frameHeight": int(shot.get("frameHeight") or 0),
                "impact": deepcopy(shot.get("impact") or {}),
                "trackman": deepcopy(shot.get("trackmanMatch") or {}),
                "seed": self.seed_for(sample_id),
            })
        return {"shots": shots, "progress": self.progress()}

    def export(self) -> dict[str, Any]:
        return {
            "version": "1.0",
            "updatedAt": _utc_now(),
            "seeds": [deepcopy(self._seeds_by_sample[sample_id]) for sample_id in sorted(self._seeds_by_sample)],
        }

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.export(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)
