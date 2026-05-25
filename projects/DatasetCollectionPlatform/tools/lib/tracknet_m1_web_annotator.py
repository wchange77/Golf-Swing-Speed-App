from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import cv2

from lib.tracknet_m1_reviewed_alignment import ReviewedAlignmentError, load_reviewed_alignment
from lib.tracknet_m1_seed_store import SeedValidationError, TrackNetM1SeedStore


class AnnotationValidationError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_task_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tasks", "items", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise AnnotationValidationError(f"Could not locate tasks in {path}")


def _load_video_shots(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    shots = payload.get("shots") if isinstance(payload, dict) else None
    if not isinstance(shots, list):
        return []
    return [deepcopy(shot) for shot in shots]


def _safe_path_segment(value: object, fallback: str) -> str:
    text = str(value or fallback).strip() or fallback
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)
    cleaned = cleaned.strip("._") or fallback
    if cleaned in {".", ".."} or ".." in cleaned:
        cleaned = fallback
    return cleaned[:120]


def _contained_child(root: Path, *parts: str) -> Path:
    root_resolved = root.resolve()
    child = root.joinpath(*parts).resolve()
    if not child.is_relative_to(root_resolved):
        raise AnnotationValidationError(f"unsafe frame path outside {root}")
    return child


def _task_key(task: dict[str, Any]) -> tuple[str, int]:
    data = task.get("data") or {}
    return str(data.get("sample_id") or ""), int(data.get("frame_index"))


def _task_id(task: dict[str, Any], used: set[str]) -> str:
    sample_id, frame_index = _task_key(task)
    base = f"{sample_id}__{frame_index}"
    task_id = base
    counter = 2
    while task_id in used:
        task_id = f"{base}__{counter}"
        counter += 1
    used.add(task_id)
    return task_id


def _parse_task_id(task_id: str) -> tuple[str, int] | None:
    if "__" not in task_id:
        return None
    sample_id, frame = task_id.rsplit("__", 1)
    if not sample_id:
        return None
    try:
        return sample_id, int(frame)
    except ValueError:
        return None


def _image_uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise AnnotationValidationError(f"Only file:// frame URIs are supported: {uri}")
    return Path(unquote(parsed.path))


def _choice_result(choice: str) -> dict[str, Any]:
    return {
        "from_name": "visibility",
        "to_name": "image",
        "type": "choices",
        "value": {"choices": [choice]},
    }


def _json_response(payload: Any, status: int = 200) -> tuple[int, dict[str, str], bytes]:
    return (
        status,
        {"Content-Type": "application/json; charset=utf-8"},
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


class AnnotationStore:
    def __init__(
        self,
        tasks_path: Path | str,
        export_path: Path | str,
        batch_index_path: Path | str | None = None,
        seed_path: Path | str | None = None,
        alignment_candidates_path: Path | str | None = None,
        reviewed_alignment_path: Path | str | None = None,
        accepted_only: bool = False,
    ):
        self.tasks_path = Path(tasks_path)
        self.export_path = Path(export_path)
        self.alignment_candidates_path = Path(alignment_candidates_path) if alignment_candidates_path is not None else None
        self.reviewed_alignment_path = Path(reviewed_alignment_path) if reviewed_alignment_path is not None else None
        batch_path = Path(batch_index_path) if batch_index_path is not None else None
        self.video_shots = _load_video_shots(batch_path)
        if accepted_only:
            if self.reviewed_alignment_path is None or not self.reviewed_alignment_path.exists():
                raise AnnotationValidationError("accepted-only requires an existing reviewed alignment file")
            try:
                reviewed = load_reviewed_alignment(self.reviewed_alignment_path)
            except ReviewedAlignmentError as exc:
                raise AnnotationValidationError(str(exc)) from exc
            accepted_sample_ids = {str(pair.get("sampleId")) for pair in reviewed.accepted_pairs}
            self.video_shots = [shot for shot in self.video_shots if str(shot.get("sampleId")) in accepted_sample_ids]
        self.seed_store = TrackNetM1SeedStore(seed_path, self.video_shots) if seed_path is not None else None
        self._video_shots_by_sample = {str(shot.get("sampleId")): shot for shot in self.video_shots if shot.get("sampleId")}
        self._frame_root = self.export_path.parent / "frames"
        self.tasks = deepcopy(_load_task_list(self.tasks_path))
        self._ids_by_key: dict[tuple[str, int], str] = {}
        self._tasks_by_id: dict[str, dict[str, Any]] = {}
        self._used_ids: set[str] = set()
        for task in self.tasks:
            self._register_task(task)
        if self.export_path.exists():
            self._merge_existing_export()

    def _register_task(self, task: dict[str, Any]) -> str:
        task_id = _task_id(task, self._used_ids)
        task["_web_annotator_id"] = task_id
        self._ids_by_key[_task_key(task)] = task_id
        self._tasks_by_id[task_id] = task
        return task_id

    def _merge_existing_export(self) -> None:
        for exported in _load_task_list(self.export_path):
            task_id = self._ids_by_key.get(_task_key(exported))
            if not task_id:
                task = deepcopy(exported)
                self.tasks.append(task)
                self._register_task(task)
                continue
            target = self._tasks_by_id[task_id]
            for key in ("annotations", "created_at", "updated_at", "completed_by", "updated_by"):
                if key in exported:
                    target[key] = exported[key]

    def api_payload(self) -> dict[str, Any]:
        tasks = [self._task_payload(task) for task in self.tasks]
        shots: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in tasks:
            key = (item["sessionId"], item["shotId"], item["sampleId"])
            shot = shots.setdefault(key, {
                "sessionId": item["sessionId"],
                "shotId": item["shotId"],
                "sampleId": item["sampleId"],
                "total": 0,
                "reviewed": 0,
            })
            shot["total"] += 1
            if item["annotation"] is not None:
                shot["reviewed"] += 1
        return {
            "tasks": tasks,
            "shots": list(shots.values()),
            "videoShots": self._video_shot_payloads(),
            "seedProgress": self.seed_store.progress() if self.seed_store is not None else None,
            "progress": self.progress(),
        }

    def _video_shot_payloads(self) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        reviewed_by_sample: dict[str, set[int]] = {}
        for task in self.tasks:
            annotation = self._current_annotation(task)
            if annotation is None:
                continue
            data = task.get("data") or {}
            sample_id = str(data.get("sample_id") or "")
            try:
                frame_index = int(data.get("frame_index"))
            except (TypeError, ValueError):
                continue
            reviewed_by_sample.setdefault(sample_id, set()).add(frame_index)
        for shot in self.video_shots:
            sample_id = str(shot.get("sampleId") or "")
            payloads.append({
                "sessionId": str(shot.get("sessionId") or ""),
                "shotId": str(shot.get("shotId") or ""),
                "sampleId": sample_id,
                "frameCount": int(shot.get("frameCount") or 0),
                "fps": float(shot.get("fps") or 0.0),
                "frameWidth": int(shot.get("frameWidth") or 0),
                "frameHeight": int(shot.get("frameHeight") or 0),
                "sourceVideo": str(shot.get("sourceVideo") or ""),
                "impact": deepcopy(shot.get("impact") or {}),
                "trackman": deepcopy(shot.get("trackmanMatch") or {}),
                "reviewed": len(reviewed_by_sample.get(sample_id, set())),
                "seed": self.seed_store.seed_for(sample_id) if self.seed_store is not None else None,
            })
        return payloads


    def video_shots_payload(self) -> dict[str, Any]:
        if self.seed_store is not None:
            return self.seed_store.api_payload()
        return {"shots": self._video_shot_payloads(), "progress": {"total": len(self.video_shots), "seeded": 0, "missing": len(self.video_shots)}}

    def save_seed(self, sample_id: str, payload: dict[str, Any], reviewer: str = "web_seed_annotator") -> dict[str, Any]:
        if self.seed_store is None:
            raise AnnotationValidationError("seed store is not configured")
        try:
            return self.seed_store.save_seed(sample_id, payload, reviewer=reviewer)
        except SeedValidationError as exc:
            raise AnnotationValidationError(str(exc)) from exc

    def _alignment_source_payload(self) -> dict[str, Any]:
        if self.reviewed_alignment_path is not None and self.reviewed_alignment_path.exists():
            return json.loads(self.reviewed_alignment_path.read_text(encoding="utf-8"))
        if self.alignment_candidates_path is not None and self.alignment_candidates_path.exists():
            return json.loads(self.alignment_candidates_path.read_text(encoding="utf-8"))
        return {
            "version": "1.0",
            "pairs": [],
            "unmatchedVideos": [],
            "unmatchedTrackmanPhotos": [],
        }

    def alignment_payload(self) -> dict[str, Any]:
        source = self._alignment_source_payload()
        pairs = []
        for pair in source.get("pairs") or []:
            item = deepcopy(pair)
            item.setdefault("reviewStatus", "needs_review")
            item.setdefault("trackmanDataStatus", "partial")
            item.setdefault("metricsUsable", False)
            item.setdefault("correctedFields", {})
            item.setdefault("extraFields", {})
            pairs.append(item)
        return {
            "version": str(source.get("version") or "1.0"),
            "pairs": pairs,
            "unmatchedVideos": deepcopy(source.get("unmatchedVideos") or []),
            "unmatchedTrackmanPhotos": deepcopy(source.get("unmatchedTrackmanPhotos") or []),
        }

    def save_alignment_review(
        self,
        sample_id: str,
        payload: dict[str, Any],
        reviewer: str = "web_alignment_reviewer",
    ) -> dict[str, Any]:
        if self.reviewed_alignment_path is None:
            raise AnnotationValidationError("reviewed alignment path is not configured")
        reviewed = self.alignment_payload()
        target: dict[str, Any] | None = None
        for pair in reviewed["pairs"]:
            if str(pair.get("sampleId") or "") == sample_id:
                target = pair
                break
        if target is None:
            raise AnnotationValidationError(f"unknown alignment sample: {sample_id}")

        allowed_fields = {
            "reviewStatus",
            "trackmanDataStatus",
            "metricsUsable",
            "correctedFields",
            "extraFields",
            "rejectReason",
        }
        for key in allowed_fields:
            if key in payload:
                target[key] = deepcopy(payload[key])
        target["reviewer"] = reviewer
        target["reviewedAt"] = _utc_now()

        self.reviewed_alignment_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.reviewed_alignment_path.with_suffix(self.reviewed_alignment_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(reviewed, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            load_reviewed_alignment(tmp_path)
        except ReviewedAlignmentError as exc:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise AnnotationValidationError(str(exc)) from exc
        os.replace(tmp_path, self.reviewed_alignment_path)
        return deepcopy(target)

    def progress(self) -> dict[str, int]:
        progress = {"total": len(self.tasks), "reviewed": 0, "visible": 0, "notVisible": 0, "skipped": 0}
        for task in self.tasks:
            annotation = self._current_annotation(task)
            if annotation is None:
                continue
            progress["reviewed"] += 1
            state = annotation["state"]
            if state == "visible":
                progress["visible"] += 1
            elif state == "not_visible":
                progress["notVisible"] += 1
            elif state == "skip":
                progress["skipped"] += 1
        return progress

    def save_annotation(self, task_id: str, payload: dict[str, Any], reviewer: str = "web_annotator") -> dict[str, Any]:
        task = self._tasks_by_id.get(task_id)
        if task is None:
            task = self._create_video_frame_task(task_id)
        state = str(payload.get("state") or "")
        if state == "visible":
            data = task["data"]
            frame_width = int(data["frame_width"])
            frame_height = int(data["frame_height"])
            x = float(payload["x"])
            y = float(payload["y"])
            if x < 0 or y < 0 or x > frame_width or y > frame_height:
                raise AnnotationValidationError(
                    f"annotation outside frame: x={x}, y={y}, width={frame_width}, height={frame_height}"
                )
            result = [
                {
                    "from_name": "ball_center",
                    "to_name": "image",
                    "type": "keypointlabels",
                    "value": {
                        "x": x / max(frame_width, 1) * 100.0,
                        "y": y / max(frame_height, 1) * 100.0,
                        "keypointlabels": ["ball"],
                    },
                },
                _choice_result("visible"),
            ]
        elif state in {"not_visible", "skip"}:
            result = [_choice_result(state)]
        else:
            raise AnnotationValidationError(f"unsupported annotation state: {state}")

        now = _utc_now()
        task["annotations"] = [{
            "was_cancelled": False,
            "created_at": task.get("created_at") or now,
            "updated_at": now,
            "completed_by": reviewer,
            "result": result,
        }]
        task["created_at"] = task.get("created_at") or now
        task["updated_at"] = now
        task["completed_by"] = reviewer
        task["updated_by"] = reviewer
        self.write_export()
        current = self._current_annotation(task)
        if current is None:
            raise AnnotationValidationError("annotation was not saved")
        return current

    def _create_video_frame_task(self, task_id: str) -> dict[str, Any]:
        parsed = _parse_task_id(task_id)
        if parsed is None:
            raise AnnotationValidationError(f"unknown task id: {task_id}")
        sample_id, frame_index = parsed
        shot = self._video_shots_by_sample.get(sample_id)
        if shot is None:
            raise AnnotationValidationError(f"unknown task id: {task_id}")
        self._validate_video_frame_index(shot, frame_index)
        image_path = self._video_frame_file_path(shot, frame_index)
        self._ensure_frame_file(shot, frame_index, image_path)
        task = {
            "data": {
                "image": image_path.resolve().as_uri(),
                "sample_id": sample_id,
                "session_id": str(shot.get("sessionId") or ""),
                "shot_id": str(shot.get("shotId") or ""),
                "frame_index": frame_index,
                "frame_width": int(shot.get("frameWidth") or 0),
                "frame_height": int(shot.get("frameHeight") or 0),
                "source_video": str(shot.get("sourceVideo") or ""),
                "trackman": deepcopy(shot.get("trackmanMatch") or {}),
            },
            "predictions": [],
        }
        self.tasks.append(task)
        registered_id = self._register_task(task)
        if registered_id != task_id:
            self._tasks_by_id[task_id] = task
        return task

    def _validate_video_frame_index(self, shot: dict[str, Any], frame_index: int) -> None:
        frame_count = int(shot.get("frameCount") or 0)
        if frame_index < 0 or (frame_count > 0 and frame_index >= frame_count):
            raise AnnotationValidationError(f"frame outside video: frame={frame_index}, frameCount={frame_count}")

    def _video_frame_file_path(self, shot: dict[str, Any], frame_index: int) -> Path:
        session_id = _safe_path_segment(shot.get("sessionId"), "unknown_session")
        shot_id = _safe_path_segment(shot.get("shotId"), "unknown_shot")
        return _contained_child(self._frame_root, session_id, shot_id, f"frame_{frame_index:06d}.jpg")

    def _ensure_frame_file(self, shot: dict[str, Any], frame_index: int, path: Path) -> None:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = self._read_video_frame(shot, frame_index)
        if frame is None:
            path.write_bytes(b"")
            return
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])

    def _read_video_frame(self, shot: dict[str, Any], frame_index: int):
        video_path = Path(str(shot.get("sourceVideo") or ""))
        cap = cv2.VideoCapture(str(video_path))
        try:
            if not cap.isOpened():
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
            ok, frame = cap.read()
            return frame if ok else None
        finally:
            cap.release()

    def video_frame_jpeg(self, sample_id: str, frame_index: int) -> bytes:
        shot = self._video_shots_by_sample.get(sample_id)
        if shot is None:
            raise AnnotationValidationError(f"unknown video sample: {sample_id}")
        self._validate_video_frame_index(shot, frame_index)
        frame = self._read_video_frame(shot, frame_index)
        if frame is None:
            raise AnnotationValidationError(f"could not read video frame: sample={sample_id}, frame={frame_index}")
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise AnnotationValidationError(f"could not encode video frame: sample={sample_id}, frame={frame_index}")
        return buffer.tobytes()

    def export_tasks(self) -> list[dict[str, Any]]:
        exported = []
        for task in self.tasks:
            clean = {key: deepcopy(value) for key, value in task.items() if key != "_web_annotator_id"}
            exported.append(clean)
        return exported

    def write_export(self) -> None:
        self.export_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.export_path.with_suffix(self.export_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.export_tasks(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.export_path)

    def frame_path(self, task_id: str) -> Path:
        task = self._tasks_by_id.get(task_id)
        if task is None:
            raise AnnotationValidationError(f"unknown task id: {task_id}")
        path = _image_uri_to_path(str(task["data"]["image"]))
        if not path.exists():
            raise AnnotationValidationError(f"frame file missing: {path}")
        return path

    def _task_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        data = task["data"]
        return {
            "id": task["_web_annotator_id"],
            "sampleId": data["sample_id"],
            "sessionId": data["session_id"],
            "shotId": data["shot_id"],
            "frameIndex": int(data["frame_index"]),
            "frameWidth": int(data["frame_width"]),
            "frameHeight": int(data["frame_height"]),
            "sourceVideo": data.get("source_video"),
            "trackman": data.get("trackman") or {},
            "candidate": self._candidate_payload(task),
            "annotation": self._current_annotation(task),
            "frameUrl": f"/frame/{task['_web_annotator_id']}",
        }

    def _candidate_payload(self, task: dict[str, Any]) -> dict[str, Any] | None:
        predictions = task.get("predictions") or []
        if not predictions:
            return None
        prediction = predictions[0]
        for result in prediction.get("result") or []:
            if result.get("type") == "keypointlabels":
                return {
                    "score": prediction.get("score"),
                    "modelVersion": prediction.get("model_version"),
                    "value": result.get("value") or {},
                }
        return None

    def _current_annotation(self, task: dict[str, Any]) -> dict[str, Any] | None:
        annotations = [item for item in task.get("annotations", []) if not item.get("was_cancelled")]
        if not annotations:
            return None
        annotations.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "")
        results = annotations[-1].get("result") or []
        choices: set[str] = set()
        keypoint: dict[str, Any] | None = None
        for result in results:
            if result.get("type") == "choices":
                for choice in (result.get("value") or {}).get("choices") or []:
                    choices.add(str(choice))
            if result.get("type") == "keypointlabels":
                value = result.get("value") or {}
                if "ball" in (value.get("keypointlabels") or []):
                    keypoint = value
        if "skip" in choices:
            return {"state": "skip"}
        if "not_visible" in choices:
            return {"state": "not_visible"}
        if keypoint is not None:
            data = task["data"]
            return {
                "state": "visible",
                "x": float(keypoint["x"]) / 100.0 * int(data["frame_width"]),
                "y": float(keypoint["y"]) / 100.0 * int(data["frame_height"]),
            }
        return None


class AnnotatorHttpApp:
    def __init__(self, store: AnnotationStore, asset_dir: Path | str):
        self.store = store
        self.asset_dir = Path(asset_dir)

    def handle(self, method: str, request_path: str, body: bytes) -> tuple[int, dict[str, str], bytes]:
        try:
            if method == "GET" and request_path == "/api/tasks":
                return _json_response(self.store.api_payload())
            if method == "GET" and request_path == "/api/export":
                return _json_response(self.store.export_tasks())
            if method == "GET" and request_path == "/api/video-shots":
                return _json_response(self.store.video_shots_payload())
            if method == "GET" and request_path == "/api/alignment":
                return _json_response(self.store.alignment_payload())
            if method == "PUT" and request_path.startswith("/api/alignment/"):
                sample_id = unquote(request_path.removeprefix("/api/alignment/"))
                payload = json.loads(body.decode("utf-8") or "{}")
                pair = self.store.save_alignment_review(sample_id, payload)
                return _json_response({"pair": pair})
            if method == "PUT" and request_path.startswith("/api/seeds/"):
                sample_id = unquote(request_path.removeprefix("/api/seeds/"))
                payload = json.loads(body.decode("utf-8") or "{}")
                seed = self.store.save_seed(sample_id, payload)
                progress = self.store.seed_store.progress() if self.store.seed_store is not None else None
                return _json_response({"seed": seed, "progress": progress})
            if method == "PUT" and request_path.startswith("/api/annotations/"):
                task_id = unquote(request_path.removeprefix("/api/annotations/"))
                payload = json.loads(body.decode("utf-8") or "{}")
                annotation = self.store.save_annotation(task_id, payload)
                return _json_response({"annotation": annotation, "progress": self.store.progress()})
            return _json_response({"error": "not found"}, status=404)
        except AnnotationValidationError as exc:
            return _json_response({"error": str(exc)}, status=400)
        except json.JSONDecodeError as exc:
            return _json_response({"error": f"invalid json: {exc.msg}"}, status=400)
