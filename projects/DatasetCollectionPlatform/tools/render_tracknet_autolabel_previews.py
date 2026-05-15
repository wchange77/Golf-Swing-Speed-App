from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _selected_points(observations: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for frame in observations.get("frames", []):
        selected = frame.get("selected")
        if isinstance(selected, dict):
            points.append({
                "frameIndex": int(frame["frameIndex"]),
                "x": float(selected["x"]),
                "y": float(selected["y"]),
                "autoConfirmed": bool(frame.get("autoConfirmed")),
            })
    return points


def _read_frame(cap: cv2.VideoCapture, frame_index: int):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
    ok, frame = cap.read()
    return frame if ok else None


def _draw_overlay(frame, observations: dict[str, Any], frame_index: int, points: list[dict[str, Any]]) -> None:
    current = None
    history = [point for point in points if point["frameIndex"] <= frame_index]
    for point in points:
        if point["frameIndex"] == frame_index:
            current = point
            break

    for prev, nxt in zip(history, history[1:]):
        cv2.line(
            frame,
            (int(round(prev["x"])), int(round(prev["y"]))),
            (int(round(nxt["x"])), int(round(nxt["y"]))),
            (0, 220, 255),
            2,
            cv2.LINE_AA,
        )

    for point in history:
        color = (0, 255, 0) if point["autoConfirmed"] else (0, 165, 255)
        center = (int(round(point["x"])), int(round(point["y"])))
        cv2.circle(frame, center, 9, color, 3, cv2.LINE_AA)
        cv2.line(frame, (center[0] - 18, center[1]), (center[0] + 18, center[1]), color, 2, cv2.LINE_AA)
        cv2.line(frame, (center[0], center[1] - 18), (center[0], center[1] + 18), color, 2, cv2.LINE_AA)

    if current:
        cv2.circle(
            frame,
            (int(round(current["x"])), int(round(current["y"]))),
            16,
            (0, 0, 255),
            4,
            cv2.LINE_AA,
        )

    impact = observations.get("impact", {})
    summary = observations.get("summary", {})
    label = (
        f"frame {frame_index} | impact {impact.get('frameIndex')} | "
        f"track {summary.get('selectedTrackLength')} | confirmed {summary.get('autoConfirmedFrames')}"
    )
    cv2.rectangle(frame, (12, 12), (min(frame.shape[1] - 12, 760), 52), (0, 0, 0), -1)
    cv2.putText(frame, label, (24, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2, cv2.LINE_AA)


def _make_zoom_panel(frame, point: dict[str, Any], *, crop_radius: int = 64, output_size: int = 320):
    h, w = frame.shape[:2]
    cx = int(round(point["x"]))
    cy = int(round(point["y"]))
    left = max(cx - crop_radius, 0)
    right = min(cx + crop_radius, w)
    top = max(cy - crop_radius, 0)
    bottom = min(cy + crop_radius, h)
    crop = frame[top:bottom, left:right]
    if crop.size == 0:
        return np.zeros((output_size, output_size, 3), dtype=np.uint8)
    zoom = cv2.resize(crop, (output_size, output_size), interpolation=cv2.INTER_CUBIC)
    center = (output_size // 2, output_size // 2)
    cv2.circle(zoom, center, 24, (0, 0, 255), 4, cv2.LINE_AA)
    cv2.line(zoom, (center[0] - 44, center[1]), (center[0] + 44, center[1]), (0, 0, 255), 3, cv2.LINE_AA)
    cv2.line(zoom, (center[0], center[1] - 44), (center[0], center[1] + 44), (0, 0, 255), 3, cv2.LINE_AA)
    cv2.putText(zoom, "ZOOM", (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    return zoom


def render_one(observations_path: Path, *, export_dir: Path, output_root: Path, frames_per_sample: int) -> dict[str, Any]:
    observations = _load_json(observations_path)
    sample = observations.get("sample", {})
    asset_path = _resolve_export_path(export_dir, sample.get("assetPath"))
    if asset_path is None:
        return {"status": "error", "path": str(observations_path), "reason": "asset_not_found"}

    points = _selected_points(observations)
    if not points:
        return {"status": "skipped", "path": str(observations_path), "reason": "no_selected_track"}

    cap = cv2.VideoCapture(str(asset_path))
    if not cap.isOpened():
        return {"status": "error", "path": str(observations_path), "reason": "video_open_failed"}

    try:
        if frames_per_sample <= 1 or len(points) <= frames_per_sample:
            chosen = points
        else:
            indexes = [
                round(idx * (len(points) - 1) / (frames_per_sample - 1))
                for idx in range(frames_per_sample)
            ]
            chosen = [points[int(index)] for index in indexes]

        relative = Path(str(sample.get("sessionId", "unknown"))) / str(sample.get("shotId") or sample.get("sampleId"))
        out_dir = output_root / "previews" / relative
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for point in chosen:
            frame_index = int(point["frameIndex"])
            frame = _read_frame(cap, frame_index)
            if frame is None:
                continue
            _draw_overlay(frame, observations, frame_index, points)
            zoom = _make_zoom_panel(frame, point)
            panel_h, panel_w = zoom.shape[:2]
            frame[frame.shape[0] - panel_h - 16 : frame.shape[0] - 16, 16 : 16 + panel_w] = zoom
            out_path = out_dir / f"frame_{frame_index:06d}.jpg"
            cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            written.append(str(out_path.relative_to(output_root)))

        return {
            "status": "ok",
            "sampleId": sample.get("sampleId"),
            "sessionId": sample.get("sessionId"),
            "shotId": sample.get("shotId"),
            "previewImages": written,
        }
    finally:
        cap.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 TrackNet 自动标注候选的可视化预览图")
    parser.add_argument("--export-dir", default="DatasetCollectorExport")
    parser.add_argument("--autolabel-dir", default="exports/tracknet_autolabel_priors")
    parser.add_argument("--frames-per-sample", type=int, default=6)
    parser.add_argument("--max-samples", type=int, default=20)
    args = parser.parse_args()

    export_dir = Path(args.export_dir).resolve()
    autolabel_dir = Path(args.autolabel_dir).resolve()
    observation_paths = sorted(autolabel_dir.glob("samples/*/*/ball_observations.json"))
    if args.max_samples > 0:
        observation_paths = observation_paths[: args.max_samples]

    reports = [
        render_one(
            path,
            export_dir=export_dir,
            output_root=autolabel_dir,
            frames_per_sample=args.frames_per_sample,
        )
        for path in observation_paths
    ]
    payload = {
        "autolabelDir": str(autolabel_dir),
        "previewRoot": str(autolabel_dir / "previews"),
        "processed": len(reports),
        "ok": sum(1 for item in reports if item.get("status") == "ok"),
        "skipped": sum(1 for item in reports if item.get("status") == "skipped"),
        "errors": sum(1 for item in reports if item.get("status") == "error"),
        "samples": reports,
    }
    (autolabel_dir / "preview_index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
