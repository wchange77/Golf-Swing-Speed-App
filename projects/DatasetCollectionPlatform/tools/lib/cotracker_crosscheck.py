from __future__ import annotations

from copy import deepcopy
from math import hypot
from pathlib import Path
import sys
from typing import Any, Sequence

import cv2
import numpy as np


def apply_cotracker_crosscheck(
    trajectory: dict[str, Any],
    *,
    cotracker_frames: Sequence[dict[str, Any]],
    max_distance_px: float,
) -> dict[str, Any]:
    checked = deepcopy(trajectory)
    cotracker_by_frame = {int(frame["frameIndex"]): frame for frame in cotracker_frames}
    first_cotracker_frame = min(cotracker_by_frame) if cotracker_by_frame else None
    for frame in checked.get("frames", []):
        frame_index = int(frame["frameIndex"])
        other = cotracker_by_frame.get(frame_index)
        if other is None:
            if first_cotracker_frame is not None and frame_index < first_cotracker_frame:
                frame["crossCheck"] = {"model": "cotracker3", "status": "not_evaluated_before_cotracker_start"}
                continue
            frame["crossCheck"] = {"model": "cotracker3", "status": "missing"}
            frame["needsReview"] = True
            continue
        other_visible = bool(other.get("visible"))
        distance = hypot(float(frame.get("x", 0.0)) - float(other.get("x", 0.0)), float(frame.get("y", 0.0)) - float(other.get("y", 0.0)))
        if not other_visible:
            status = "cotracker_not_visible"
            frame["needsReview"] = True
        elif distance <= max_distance_px:
            status = "agree"
        else:
            status = "disagree"
            frame["needsReview"] = True
        frame["crossCheck"] = {
            "model": "cotracker3",
            "status": status,
            "distancePx": round(distance, 3),
            "x": round(float(other.get("x", 0.0)), 3),
            "y": round(float(other.get("y", 0.0)), 3),
            "visible": other_visible,
            "confidence": round(float(other.get("confidence", 0.0)), 6),
        }
    checked["crossCheck"] = {
        "model": "cotracker3",
        "maxDistancePx": max_distance_px,
        "framesCompared": len(cotracker_by_frame),
    }
    return checked


def _device_name(preferred: str | None = None) -> str:
    if preferred:
        return preferred
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _fit_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return max_side, max_side
    scale = min(1.0, float(max_side) / float(max(width, height)))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _read_video_rgb(path: Path, *, target_size: tuple[int, int]) -> np.ndarray:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video for CoTracker3: {path}")
    frames: list[np.ndarray] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
            frames.append(frame)
    finally:
        cap.release()
    if not frames:
        raise RuntimeError(f"could not read any frames for CoTracker3: {path}")
    return np.stack(frames, axis=0)


def _window_frame_indices(*, seed_frame: int, frame_count: int, max_frames_after_seed: int, frame_stride: int) -> list[int]:
    if frame_count <= 0:
        return []
    start_frame = max(0, min(int(seed_frame), frame_count - 1))
    end_frame = min(frame_count - 1, start_frame + max(0, int(max_frames_after_seed)))
    return list(range(start_frame, end_frame + 1, max(1, int(frame_stride))))


def _read_video_window_rgb(path: Path, *, frame_indices: Sequence[int], target_size: tuple[int, int]) -> np.ndarray:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video for CoTracker3: {path}")
    frames: list[np.ndarray] = []
    try:
        previous_index: int | None = None
        for frame_index in frame_indices:
            if previous_index is None or frame_index != previous_index + 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
            frames.append(frame)
            previous_index = int(frame_index)
    finally:
        cap.release()
    if not frames:
        raise RuntimeError(f"could not read any seed-window frames for CoTracker3: {path}")
    return np.stack(frames, axis=0)


class CoTracker3Tracker:
    def __init__(
        self,
        *,
        cotracker_repo: Path | str,
        checkpoint: Path | str,
        device: str | None = None,
        input_max_side: int = 512,
        backward_tracking: bool = True,
        max_frames_after_seed: int = 240,
        frame_stride: int = 1,
    ):
        self.cotracker_repo = Path(cotracker_repo)
        self.checkpoint = Path(checkpoint)
        self.device = _device_name(device)
        self.input_max_side = input_max_side
        self.backward_tracking = backward_tracking
        self.max_frames_after_seed = max(0, int(max_frames_after_seed))
        self.frame_stride = max(1, int(frame_stride))
        if str(self.cotracker_repo) not in sys.path:
            sys.path.insert(0, str(self.cotracker_repo))
        from cotracker.predictor import CoTrackerPredictor

        self.model = CoTrackerPredictor(
            checkpoint=str(self.checkpoint),
            offline=True,
            v2=False,
            window_len=60,
        ).to(self.device)
        self.model.eval()

    def __call__(self, shot: dict[str, Any], seed: Any) -> list[dict[str, Any]]:
        return self.track(shot, seed)

    def track(self, shot: dict[str, Any], seed: Any) -> list[dict[str, Any]]:
        import torch

        video_path = Path(str(shot.get("sourceVideo") or ""))
        width = int(shot.get("frameWidth") or 0)
        height = int(shot.get("frameHeight") or 0)
        frame_count = int(shot.get("frameCount") or 0)
        frame_indices = _window_frame_indices(
            seed_frame=int(seed.frame_index),
            frame_count=frame_count,
            max_frames_after_seed=self.max_frames_after_seed,
            frame_stride=self.frame_stride,
        )
        target_w, target_h = _fit_size(width, height, self.input_max_side)
        frames = _read_video_window_rgb(video_path, frame_indices=frame_indices, target_size=(target_w, target_h))
        video = torch.from_numpy(frames).permute(0, 3, 1, 2)[None].float().to(self.device)
        query = torch.tensor(
            [[[0.0, float(seed.x) / max(width, 1) * target_w, float(seed.y) / max(height, 1) * target_h]]],
            dtype=torch.float32,
            device=self.device,
        )
        with torch.no_grad():
            pred_tracks, pred_visibility = self.model(
                video,
                queries=query,
                backward_tracking=self.backward_tracking,
            )
        tracks = pred_tracks[0, :, 0].detach().float().cpu().numpy()
        visibility = pred_visibility[0, :, 0].detach().cpu().numpy()
        output: list[dict[str, Any]] = []
        for frame_index, (point, visible) in zip(frame_indices, zip(tracks, visibility)):
            x = float(point[0]) / max(target_w, 1) * width
            y = float(point[1]) / max(target_h, 1) * height
            is_visible = bool(visible)
            output.append({
                "frameIndex": frame_index,
                "x": round(x, 3),
                "y": round(y, 3),
                "visible": is_visible,
                "confidence": 1.0 if is_visible else 0.0,
            })
        return output


class CoTracker3OnlineTracker:
    def __init__(
        self,
        *,
        cotracker_repo: Path | str,
        checkpoint: Path | str,
        device: str | None = None,
        input_max_side: int = 512,
        max_frames_after_seed: int = 240,
        frame_stride: int = 1,
    ):
        self.cotracker_repo = Path(cotracker_repo)
        self.checkpoint = Path(checkpoint)
        self.device = _device_name(device)
        self.input_max_side = input_max_side
        self.max_frames_after_seed = max(0, int(max_frames_after_seed))
        self.frame_stride = max(1, int(frame_stride))
        if str(self.cotracker_repo) not in sys.path:
            sys.path.insert(0, str(self.cotracker_repo))
        from cotracker.predictor import CoTrackerOnlinePredictor

        self.model = CoTrackerOnlinePredictor(
            checkpoint=str(self.checkpoint),
            offline=False,
            v2=False,
            window_len=16,
        ).to(self.device)
        self.model.eval()

    def __call__(self, shot: dict[str, Any], seed: Any) -> list[dict[str, Any]]:
        return self.track(shot, seed)

    def _frame_to_rgb(self, frame: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)

    def _convert_tracks(self, tracks: Any, visibility: Any, *, frame_indices: Sequence[int], target_size: tuple[int, int], original_size: tuple[int, int]) -> list[dict[str, Any]]:
        target_w, target_h = target_size
        width, height = original_size
        tracks_np = tracks[0, :, 0].detach().float().cpu().numpy()
        visibility_np = visibility[0, :, 0].detach().cpu().numpy()
        output: list[dict[str, Any]] = []
        if len(frame_indices) >= len(tracks_np):
            mapped_frame_indices = list(frame_indices)[: len(tracks_np)]
        else:
            mapped_frame_indices = list(frame_indices) + [int(frame_indices[-1]) + i + 1 for i in range(len(tracks_np) - len(frame_indices))]
        for frame_index, (point, visible) in zip(mapped_frame_indices, zip(tracks_np, visibility_np)):
            x = float(point[0]) / max(target_w, 1) * width
            y = float(point[1]) / max(target_h, 1) * height
            is_visible = bool(visible)
            output.append({
                "frameIndex": int(frame_index),
                "x": round(x, 3),
                "y": round(y, 3),
                "visible": is_visible,
                "confidence": 1.0 if is_visible else 0.0,
            })
        return output

    def track(self, shot: dict[str, Any], seed: Any) -> list[dict[str, Any]]:
        import torch

        video_path = Path(str(shot.get("sourceVideo") or ""))
        width = int(shot.get("frameWidth") or 0)
        height = int(shot.get("frameHeight") or 0)
        frame_count = int(shot.get("frameCount") or 0)
        target_w, target_h = _fit_size(width, height, self.input_max_side)
        seed_frame = int(seed.frame_index)
        frame_indices = _window_frame_indices(
            seed_frame=seed_frame,
            frame_count=frame_count,
            max_frames_after_seed=self.max_frames_after_seed,
            frame_stride=self.frame_stride,
        )
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"could not open video for CoTracker3 online: {video_path}")
        window_frames: list[np.ndarray] = []
        final_tracks = None
        final_visibility = None
        is_first_step = True
        query = torch.tensor([[[0.0, float(seed.x) / max(width, 1) * target_w, float(seed.y) / max(height, 1) * target_h]]], dtype=torch.float32, device=self.device)
        try:
            with torch.no_grad():
                previous_index: int | None = None
                for local_index, frame_index in enumerate(frame_indices):
                    if previous_index is None or frame_index != previous_index + 1:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
                    ok, frame = cap.read()
                    if not ok:
                        break
                    window_frames.append(self._frame_to_rgb(frame, (target_w, target_h)))
                    if local_index % self.model.step == 0 and local_index != 0:
                        chunk_frames = window_frames[-self.model.step * 2 :]
                        chunk = torch.tensor(np.stack(chunk_frames), device=self.device).float().permute(0, 3, 1, 2)[None]
                        tracks, visibility = self.model(
                            chunk,
                            is_first_step=is_first_step,
                            queries=query if is_first_step else None,
                            grid_size=0,
                        )
                        if tracks is not None:
                            final_tracks = tracks.detach().cpu()
                            final_visibility = visibility.detach().cpu()
                        is_first_step = False
                    previous_index = int(frame_index)
                if not window_frames:
                    raise RuntimeError(f"could not read seed or later frames for CoTracker3 online: {video_path}")
                remainder = (len(window_frames) - 1) % self.model.step
                tail_start = max(0, len(window_frames) - remainder - self.model.step - 1)
                chunk_frames = window_frames[tail_start:]
                chunk = torch.tensor(np.stack(chunk_frames), device=self.device).float().permute(0, 3, 1, 2)[None]
                tracks, visibility = self.model(
                    chunk,
                    is_first_step=is_first_step,
                    queries=query if is_first_step else None,
                    grid_size=0,
                )
                if tracks is not None:
                    final_tracks = tracks.detach().cpu()
                    final_visibility = visibility.detach().cpu()
        finally:
            cap.release()
        if final_tracks is None or final_visibility is None:
            raise RuntimeError("CoTracker3 online did not produce tracks")
        return self._convert_tracks(
            final_tracks,
            final_visibility,
            frame_indices=frame_indices,
            target_size=(target_w, target_h),
            original_size=(width, height),
        )
