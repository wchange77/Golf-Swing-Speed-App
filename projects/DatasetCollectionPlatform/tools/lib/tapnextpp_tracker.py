from __future__ import annotations

from dataclasses import dataclass
import importlib
import sys
import types
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class SeedPoint:
    sample_id: str
    frame_index: int
    x: float
    y: float


def install_tapnet_import_shim(tapnet_repo: Path | str) -> None:
    """Allow importing tapnet.tapnext modules without running tapnet/__init__.py.

    The upstream package's top-level __init__ imports TAPVid evaluation modules,
    which pull TensorFlow. TAPNext++ inference only needs tapnet.tapnext.
    """
    repo = Path(tapnet_repo)
    package_dir = repo / "tapnet"
    tapnext_dir = package_dir / "tapnext"
    if not tapnext_dir.exists():
        raise FileNotFoundError(f"tapnet tapnext package not found: {tapnext_dir}")

    tapnet_module = types.ModuleType("tapnet")
    tapnet_module.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
    tapnet_module.__package__ = "tapnet"
    sys.modules["tapnet"] = tapnet_module

    tapnext_module = types.ModuleType("tapnet.tapnext")
    tapnext_module.__path__ = [str(tapnext_dir)]  # type: ignore[attr-defined]
    tapnext_module.__package__ = "tapnet.tapnext"
    sys.modules["tapnet.tapnext"] = tapnext_module


def import_tapnext_modules(tapnet_repo: Path | str) -> tuple[Any, Callable[..., Any]]:
    install_tapnet_import_shim(tapnet_repo)
    tapnext = importlib.import_module("tapnet.tapnext.tapnext_torch")
    tapnext_utils = importlib.import_module("tapnet.tapnext.tapnext_torch_utils")
    return tapnext.TAPNext, tapnext_utils.tracker_certainty


def _frame_needs_review(*, visible: bool, confidence: float, x: float, y: float, width: int, height: int) -> bool:
    if not visible:
        return True
    if confidence < 0.5:
        return True
    if x < 0 or y < 0 or x > width or y > height:
        return True
    return False


def build_tapnextpp_trajectory(
    *,
    shot: dict[str, Any],
    seed: SeedPoint,
    tracks_xy: Sequence[tuple[float, float]],
    occluded: Sequence[bool],
    confidence: Sequence[float] | None,
    checkpoint: Path,
    frame_indices: Sequence[int] | None = None,
    frame_stride: int = 1,
) -> dict[str, Any]:
    source_frame_count = int(shot.get("frameCount") or len(tracks_xy))
    output_frame_indices = list(frame_indices) if frame_indices is not None else list(range(source_frame_count))
    frame_count = len(output_frame_indices)
    width = int(shot.get("frameWidth") or 0)
    height = int(shot.get("frameHeight") or 0)
    frames: list[dict[str, Any]] = []
    for output_index, frame_index in enumerate(output_frame_indices):
        if output_index < len(tracks_xy):
            x, y = tracks_xy[output_index]
            is_occluded = bool(occluded[output_index]) if output_index < len(occluded) else True
            score = float(confidence[output_index]) if confidence is not None and output_index < len(confidence) else (0.0 if is_occluded else 1.0)
        else:
            x, y = 0.0, 0.0
            is_occluded = True
            score = 0.0
        visible = not is_occluded
        frames.append({
            "frameIndex": frame_index,
            "x": round(float(x), 3),
            "y": round(float(y), 3),
            "visible": visible,
            "confidence": round(score, 6),
            "needsReview": _frame_needs_review(visible=visible, confidence=score, x=float(x), y=float(y), width=width, height=height),
            "source": "tapnextpp_seed_tracker",
        })
    return {
        "version": "1.0",
        "sampleId": str(shot.get("sampleId") or seed.sample_id),
        "sessionId": str(shot.get("sessionId") or ""),
        "shotId": str(shot.get("shotId") or ""),
        "sourceVideo": str(shot.get("sourceVideo") or ""),
        "frameCount": frame_count,
        "sourceFrameCount": source_frame_count,
        "fps": float(shot.get("fps") or 0.0),
        "frameWidth": width,
        "frameHeight": height,
        "trackman": shot.get("trackmanMatch", {}),
        "seed": {"frameIndex": seed.frame_index, "x": seed.x, "y": seed.y},
        "sampling": {
            "startFrame": output_frame_indices[0] if output_frame_indices else seed.frame_index,
            "frameStride": int(frame_stride),
            "sampledFrameCount": frame_count,
        },
        "model": {
            "name": "tapnextpp",
            "checkpoint": str(checkpoint),
            "source": "google-deepmind/tapnet",
        },
        "frames": frames,
    }


def frames_needing_review(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    return [frame for frame in trajectory.get("frames", []) if frame.get("needsReview")]


def _device_name(preferred: str | None = None) -> str:
    if preferred:
        return preferred
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def load_tapnextpp_model(
    *,
    tapnet_repo: Path | str,
    checkpoint: Path | str,
    device: str | None = None,
) -> tuple[Any, Callable[..., Any], str]:
    import torch

    device_name = _device_name(device)
    if not device_name.startswith("cuda"):
        raise RuntimeError("TAPNext++ PyTorch implementation requires CUDA in the upstream constructor")
    TAPNext, tracker_certainty = import_tapnext_modules(tapnet_repo)
    model = TAPNext(image_size=(256, 256))
    ckpt = torch.load(Path(checkpoint), map_location="cpu")
    state_dict = ckpt.get("state_dict", ckpt)
    model.load_state_dict({key.replace("tapnext.", ""): value for key, value in state_dict.items()})
    model.to(device_name)
    model.eval()
    return model, tracker_certainty, device_name


def _read_resized_rgb_frame(cap: cv2.VideoCapture, frame_index: int, *, size: tuple[int, int] = (256, 256)) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
    return _read_next_resized_rgb_frame(cap, size=size)


def _read_next_resized_rgb_frame(cap: cv2.VideoCapture, *, size: tuple[int, int] = (256, 256)) -> np.ndarray | None:
    ok, frame = cap.read()
    if not ok:
        return None
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    return frame.astype(np.float32) / 255.0 * 2.0 - 1.0


def _tapnext_point_to_image_xy(point_yx: Any, *, width: int, height: int) -> tuple[float, float]:
    y_256 = float(point_yx[0])
    x_256 = float(point_yx[1])
    return x_256 / 256.0 * width, y_256 / 256.0 * height


class TapNextPPTracker:
    def __init__(
        self,
        *,
        tapnet_repo: Path | str,
        checkpoint: Path | str,
        device: str | None = None,
        use_certainty: bool = False,
        certainty_radius: int = 8,
        confidence_threshold: float = 0.5,
        max_frames_after_seed: int = 240,
        frame_stride: int = 1,
    ):
        self.checkpoint = Path(checkpoint)
        self.model, self.tracker_certainty, self.device = load_tapnextpp_model(
            tapnet_repo=tapnet_repo,
            checkpoint=checkpoint,
            device=device,
        )
        self.use_certainty = use_certainty
        self.certainty_radius = certainty_radius
        self.confidence_threshold = confidence_threshold
        self.max_frames_after_seed = max(0, int(max_frames_after_seed))
        self.frame_stride = max(1, int(frame_stride))

    def __call__(self, shot: dict[str, Any], seed: SeedPoint) -> dict[str, Any]:
        return self.track(shot, seed)

    def track(self, shot: dict[str, Any], seed: SeedPoint) -> dict[str, Any]:
        import torch
        video_path = Path(str(shot.get("sourceVideo") or ""))
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"could not open video for TAPNext++: {video_path}")
        frame_count = int(shot.get("frameCount") or cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(shot.get("frameWidth") or cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(shot.get("frameHeight") or cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if frame_count <= 0 or width <= 0 or height <= 0:
            cap.release()
            raise RuntimeError(f"invalid video metadata for TAPNext++: {video_path}")

        start_frame = max(0, min(int(seed.frame_index), frame_count - 1))
        end_frame = min(frame_count - 1, start_frame + self.max_frames_after_seed)
        frame_indices = list(range(start_frame, end_frame + 1, self.frame_stride))
        query = torch.tensor([[[0.0, float(seed.y) / height * 256.0, float(seed.x) / width * 256.0]]], dtype=torch.float32, device=self.device)
        tracks_xy: list[tuple[float, float]] = []
        occluded: list[bool] = []
        confidence: list[float] = []
        state = None
        if self.frame_stride == 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        try:
            with torch.no_grad():
                for frame_index in frame_indices:
                    if self.frame_stride == 1:
                        frame = _read_next_resized_rgb_frame(cap)
                    else:
                        frame = _read_resized_rgb_frame(cap, frame_index)
                    if frame is None:
                        tracks_xy.append((0.0, 0.0))
                        occluded.append(True)
                        confidence.append(0.0)
                        continue
                    video = torch.from_numpy(frame).to(self.device).view(1, 1, 256, 256, 3)
                    with torch.amp.autocast("cuda", dtype=torch.float16, enabled=self.device.startswith("cuda")):
                        if state is None:
                            pred_tracks, track_logits, visible_logits, state = self.model(video=video, query_points=query)
                        else:
                            pred_tracks, track_logits, visible_logits, state = self.model(video=video, state=state)
                        visible_prob = torch.sigmoid(visible_logits)
                        if self.use_certainty:
                            certainty = self.tracker_certainty(pred_tracks, track_logits, self.certainty_radius)
                            score_tensor = visible_prob * certainty
                        else:
                            score_tensor = visible_prob
                        point = pred_tracks[0, 0, 0].detach().float().cpu().numpy()
                        score = float(score_tensor[0, 0, 0, 0].detach().float().cpu())
                        visible = bool((visible_logits[0, 0, 0, 0] > 0).detach().cpu())
                        if self.use_certainty:
                            visible = score > self.confidence_threshold
                    x, y = _tapnext_point_to_image_xy(point, width=width, height=height)
                    tracks_xy.append((x, y))
                    occluded.append(not visible)
                    confidence.append(score)
        finally:
            cap.release()
        return {
            "tracks_xy": tracks_xy,
            "occluded": occluded,
            "confidence": confidence,
            "frame_indices": frame_indices,
            "frame_stride": self.frame_stride,
        }
