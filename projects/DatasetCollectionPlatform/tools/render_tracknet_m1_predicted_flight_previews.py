from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_variant(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return cleaned.strip("._") or "variant"


def _trajectory_label(sample_id: str) -> str:
    return str(sample_id or "sample").replace("golf_ball_detection_", "")[:12]


def _letterbox_frame(image: np.ndarray, *, cell_size: tuple[int, int]) -> tuple[np.ndarray, float, int, int]:
    cell_w, cell_h = cell_size
    height, width = image.shape[:2]
    canvas = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
    if width <= 0 or height <= 0:
        return canvas, 1.0, 0, 0
    scale = min(cell_w / width, cell_h / height)
    resized_w = max(1, int(round(width * scale)))
    resized_h = max(1, int(round(height * scale)))
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
    offset_x = (cell_w - resized_w) // 2
    offset_y = (cell_h - resized_h) // 2
    canvas[offset_y : offset_y + resized_h, offset_x : offset_x + resized_w] = resized
    return canvas, scale, offset_x, offset_y


def _point_to_cell(frame: dict[str, Any], *, scale: float, offset_x: int, offset_y: int) -> tuple[int, int]:
    return (
        int(round(float(frame.get("x", 0.0)) * scale + offset_x)),
        int(round(float(frame.get("y", 0.0)) * scale + offset_y)),
    )


def _open_captures(predictions: list[dict[str, Any]]) -> list[Any]:
    captures = []
    for prediction in predictions:
        cap = cv2.VideoCapture(str(prediction.get("sourceVideo") or ""))
        if not cap.isOpened():
            raise RuntimeError(f"could not open source video: {prediction.get('sourceVideo')}")
        captures.append(cap)
    return captures


def _read_next_strided_frame(cap: Any, *, stride: int) -> np.ndarray | None:
    image: np.ndarray | None = None
    for index in range(max(1, int(stride))):
        ok, current = cap.read()
        if not ok:
            return image
        if index == 0:
            image = current
    return image


def _draw_polyline(cell: np.ndarray, points: list[tuple[int, int]], color: tuple[int, int, int], thickness: int) -> None:
    if len(points) >= 2:
        cv2.polylines(cell, [np.array(points, dtype=np.int32)], False, color, thickness, cv2.LINE_AA)


def _draw_cell(
    cell: np.ndarray,
    *,
    observed_trail: list[tuple[int, int]],
    predicted_trail: list[tuple[int, int]],
    clubhead_trail: list[tuple[int, int]],
    observed_point: tuple[int, int] | None,
    predicted_point: tuple[int, int] | None,
    clubhead_point: tuple[int, int] | None,
    label: str,
    frame_index: int,
    variant: str,
) -> None:
    _draw_polyline(cell, predicted_trail, (255, 255, 0), 2)
    _draw_polyline(cell, observed_trail, (0, 255, 0), 2)
    _draw_polyline(cell, clubhead_trail, (255, 0, 255), 1)
    if clubhead_point is not None:
        cv2.drawMarker(cell, clubhead_point, (255, 0, 255), cv2.MARKER_TILTED_CROSS, 13, 2, cv2.LINE_AA)
    if predicted_point is not None:
        cv2.circle(cell, predicted_point, 5, (255, 255, 0), 2, cv2.LINE_AA)
    if observed_point is not None:
        cv2.circle(cell, observed_point, 6, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.circle(cell, observed_point, 2, (0, 255, 0), -1, cv2.LINE_AA)
    cv2.rectangle(cell, (0, 0), (cell.shape[1], 30), (0, 0, 0), -1)
    cv2.putText(cell, f"{label} {variant} f{frame_index}", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)


def _prediction_frame_maps(predictions: list[dict[str, Any]]) -> tuple[list[dict[int, dict[str, Any]]], list[dict[int, dict[str, Any]]], list[dict[int, dict[str, Any]]]]:
    observed_maps = []
    predicted_maps = []
    clubhead_maps = []
    for prediction in predictions:
        observed_maps.append({
            int(frame["frameIndex"]): frame
            for frame in prediction.get("frames", [])
            if isinstance(frame, dict) and frame.get("frameIndex") is not None
        })
        predicted_flight = prediction.get("predictedFlight") if isinstance(prediction.get("predictedFlight"), dict) else {}
        predicted_maps.append({
            int(frame["frameIndex"]): frame
            for frame in predicted_flight.get("frames", [])
            if isinstance(frame, dict) and frame.get("frameIndex") is not None
        })
        clubhead_maps.append({
            int(frame["frameIndex"]): frame
            for frame in prediction.get("clubheadTrack", [])
            if isinstance(frame, dict) and frame.get("frameIndex") is not None
        })
    return observed_maps, predicted_maps, clubhead_maps


def render_variant_video(
    prediction_paths: Iterable[Path | str],
    output_path: Path | str,
    *,
    variant: str,
    columns: int = 4,
    cell_size: tuple[int, int] = (480, 270),
    output_fps: float = 60.0,
    frame_stride: int = 4,
    max_output_frames: int | None = None,
) -> dict[str, Any]:
    paths = [Path(path) for path in prediction_paths]
    predictions = [_load_json(path) for path in paths]
    if not predictions:
        raise RuntimeError(f"no prediction trajectories provided for variant {variant}")
    columns = max(1, int(columns))
    rows = int(math.ceil(len(predictions) / columns))
    cell_w, cell_h = cell_size
    output_size = (columns * cell_w, rows * cell_h)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    observed_maps, predicted_maps, clubhead_maps = _prediction_frame_maps(predictions)
    start_frames = [
        min(frame_map) if frame_map else int((prediction.get("seed") or {}).get("frameIndex", 0))
        for frame_map, prediction in zip(predicted_maps, predictions)
    ]
    stride = max(1, int(frame_stride))
    frame_spans = [
        ((max(frame_map) - min(frame_map)) // stride + 1) if frame_map else 1
        for frame_map in predicted_maps
    ]
    output_frames = max(frame_spans)
    if max_output_frames is not None:
        output_frames = min(output_frames, max(0, int(max_output_frames)))

    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), float(output_fps), output_size)
    captures = _open_captures(predictions)
    for cap, start_frame in zip(captures, start_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_frame))
    observed_trails: list[list[tuple[int, int]]] = [[] for _ in predictions]
    predicted_trails: list[list[tuple[int, int]]] = [[] for _ in predictions]
    clubhead_trails: list[list[tuple[int, int]]] = [[] for _ in predictions]
    try:
        for output_index in range(output_frames):
            canvas = np.zeros((output_size[1], output_size[0], 3), dtype=np.uint8)
            for index, (prediction, cap) in enumerate(zip(predictions, captures)):
                frame_index = start_frames[index] + output_index * stride
                image = _read_next_strided_frame(cap, stride=stride)
                if image is None:
                    image = np.zeros((int(prediction.get("frameHeight") or cell_h), int(prediction.get("frameWidth") or cell_w), 3), dtype=np.uint8)
                cell, scale, offset_x, offset_y = _letterbox_frame(image, cell_size=cell_size)
                observed = observed_maps[index].get(frame_index)
                predicted = predicted_maps[index].get(frame_index)
                clubhead = clubhead_maps[index].get(frame_index)
                observed_point = None
                predicted_point = None
                clubhead_point = None
                if observed is not None and observed.get("visible"):
                    observed_point = _point_to_cell(observed, scale=scale, offset_x=offset_x, offset_y=offset_y)
                    observed_trails[index].append(observed_point)
                if predicted is not None and predicted.get("visible"):
                    predicted_point = _point_to_cell(predicted, scale=scale, offset_x=offset_x, offset_y=offset_y)
                    predicted_trails[index].append(predicted_point)
                if clubhead is not None and clubhead.get("visible"):
                    clubhead_point = _point_to_cell(clubhead, scale=scale, offset_x=offset_x, offset_y=offset_y)
                    clubhead_trails[index].append(clubhead_point)
                _draw_cell(
                    cell,
                    observed_trail=observed_trails[index],
                    predicted_trail=predicted_trails[index],
                    clubhead_trail=clubhead_trails[index],
                    observed_point=observed_point,
                    predicted_point=predicted_point,
                    clubhead_point=clubhead_point,
                    label=_trajectory_label(str(prediction.get("sampleId") or paths[index].stem)),
                    frame_index=frame_index,
                    variant=variant,
                )
                row, col = divmod(index, columns)
                x1 = col * cell_w
                y1 = row * cell_h
                canvas[y1 : y1 + cell_h, x1 : x1 + cell_w] = cell
            writer.write(canvas)
    finally:
        for cap in captures:
            cap.release()
        writer.release()

    report = {
        "variant": variant,
        "output": str(output_path),
        "trajectoryCount": len(predictions),
        "framesWritten": output_frames,
        "columns": columns,
        "rows": rows,
        "cellSize": [cell_w, cell_h],
        "outputSize": list(output_size),
        "outputFps": float(output_fps),
        "frameStride": stride,
        "trajectories": [str(path) for path in paths],
    }
    _write_json(output_path.with_suffix(".json"), report)
    return report


def _variant_dirs(predictions_root: Path, variants: Iterable[str] | None) -> list[tuple[str, Path]]:
    if variants is not None:
        return [(variant, predictions_root / variant) for variant in variants]
    return [
        (path.name, path)
        for path in sorted(predictions_root.iterdir())
        if path.is_dir() and (path / "trajectories").exists()
    ]


def _write_index(output_root: Path, report: dict[str, Any]) -> None:
    rows = []
    for video in report["videos"]:
        variant = html.escape(str(video["variant"]))
        href = html.escape(Path(video["output"]).name)
        rows.append(
            "<tr>"
            f"<td>{variant}</td>"
            f"<td><a href=\"{href}\">{href}</a></td>"
            f"<td>{int(video['trajectoryCount'])}</td>"
            f"<td>{int(video['framesWritten'])}</td>"
            f"<td>{html.escape(str(video['outputSize']))}</td>"
            "</tr>"
        )
    body = "\n".join(rows)
    page = f"""<!doctype html>
<meta charset=\"utf-8\">
<title>TrackNet M1 predicted full trajectory previews</title>
<style>
body{{margin:0;background:#101214;color:#e8edf2;font-family:Arial,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px}}
h1{{font-size:24px;margin:0 0 16px}}
table{{border-collapse:collapse;width:100%;margin:16px 0 28px}}
td,th{{border-bottom:1px solid #2c333a;padding:10px;text-align:left}}
video{{display:block;width:100%;max-height:72vh;background:#000;margin:12px 0 30px}}
a{{color:#75d5ff}}
.note{{color:#ffcf70}}
</style>
<main>
<h1>TrackNet M1 predicted full trajectory previews</h1>
<p class=\"note\">Legacy/debug review-only output. Predicted frames are not TrackNetV6 training labels; formal M2 uses video_only_3d and trackman_constrained_3d.</p>
<table><thead><tr><th>Variant</th><th>Video</th><th>Samples</th><th>Frames</th><th>Size</th></tr></thead><tbody>{body}</tbody></table>
{''.join(f'<h2>{html.escape(str(video["variant"]))}</h2><video src="{html.escape(Path(video["output"]).name)}" controls></video>' for video in report["videos"])}
</main>
"""
    (output_root / "index.html").write_text(page, encoding="utf-8")


def render_prediction_previews(
    predictions_root: Path | str,
    output_root: Path | str,
    *,
    variants: Iterable[str] | None = None,
    columns: int = 4,
    cell_size: tuple[int, int] = (480, 270),
    output_fps: float = 60.0,
    frame_stride: int = 4,
    max_output_frames: int | None = None,
) -> dict[str, Any]:
    predictions_root = Path(predictions_root)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    videos = []
    for variant, variant_dir in _variant_dirs(predictions_root, variants):
        paths = sorted((variant_dir / "trajectories").glob("*.json"))
        if not paths:
            continue
        safe_variant = _safe_variant(variant)
        output_path = output_root / f"m1_predicted_full_{safe_variant}_20up.mp4"
        videos.append(render_variant_video(
            paths,
            output_path,
            variant=variant,
            columns=columns,
            cell_size=cell_size,
            output_fps=output_fps,
            frame_stride=frame_stride,
            max_output_frames=max_output_frames,
        ))
    report = {
        "version": "1.0",
        "predictionsRoot": str(predictions_root),
        "outputRoot": str(output_root),
        "videos": videos,
        "index": str(output_root / "index.html"),
    }
    _write_json(output_root / "preview_report.json", report)
    _write_index(output_root, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render review-only predicted full trajectory 20-up previews")
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--variant", action="append", default=[])
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--cell-width", type=int, default=480)
    parser.add_argument("--cell-height", type=int, default=270)
    parser.add_argument("--output-fps", type=float, default=60.0)
    parser.add_argument("--frame-stride", type=int, default=4)
    parser.add_argument("--max-output-frames", type=int)
    args = parser.parse_args(argv)
    report = render_prediction_previews(
        args.predictions_root,
        args.output_root,
        variants=args.variant or None,
        columns=args.columns,
        cell_size=(args.cell_width, args.cell_height),
        output_fps=args.output_fps,
        frame_stride=args.frame_stride,
        max_output_frames=args.max_output_frames,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
