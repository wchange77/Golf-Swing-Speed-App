from __future__ import annotations

import argparse
import html as html_lib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_number(name: str) -> int:
    return int(name.split("_")[1].split(".")[0])


def _valid_sample_id_for_path(sample_id: str) -> bool:
    return bool(sample_id) and "/" not in sample_id and "\\" not in sample_id and ".." not in sample_id


def _safe_sample_dir_name(sample_id: str) -> str:
    if _valid_sample_id_for_path(sample_id):
        return sample_id
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in sample_id)
    return safe.strip("._") or "invalid_sample_id"


def _preview_output_dir(output_root: Path, sample_id: str) -> Path:
    root = output_root.resolve()
    preview_dir = (output_root / _safe_sample_dir_name(sample_id)).resolve()
    if not preview_dir.is_relative_to(root):
        return root / "invalid_sample_id"
    return preview_dir


def render_trajectory_viewer(
    trajectory_path: Path | str,
    output_dir: Path | str,
    *,
    contact_sheet_stride: int = 8,
) -> dict[str, Any]:
    trajectory_path = Path(trajectory_path)
    output_dir = Path(output_dir)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in frames_dir.glob("*.jpg"):
        old_frame.unlink()

    trajectory = _load_json(trajectory_path)
    frame_width = int(trajectory.get("frameWidth") or 0)
    frame_height = int(trajectory.get("frameHeight") or 0)
    seed = trajectory.get("seed", {})
    visible_frames = [frame for frame in trajectory.get("frames", []) if frame.get("visible")]
    xs = [float(seed.get("x", 0.0))] + [float(frame["x"]) for frame in visible_frames]
    ys = [float(seed.get("y", 0.0))] + [float(frame["y"]) for frame in visible_frames]
    x1 = max(0, min(int(min(xs) - 260), int(float(seed.get("x", 0.0)) - 360)))
    x2 = min(frame_width, max(int(max(xs) + 360), int(float(seed.get("x", 0.0)) + 360)))
    y1 = max(0, min(int(min(ys) - 180), 120))
    y2 = min(frame_height, max(int(max(ys) + 140), int(float(seed.get("y", 0.0)) + 100)))

    frame_by_index = {int(frame["frameIndex"]): frame for frame in trajectory.get("frames", [])}
    cap = cv2.VideoCapture(str(trajectory.get("sourceVideo") or ""))
    if not cap.isOpened():
        raise RuntimeError(f"could not open source video: {trajectory.get('sourceVideo')}")
    trail: list[tuple[int, int]] = []
    written: list[str] = []
    try:
        sorted_indices = sorted(frame_by_index)
        if not sorted_indices:
            return {}
        wanted = set(sorted_indices)
        first_index = sorted_indices[0]
        last_index = sorted_indices[-1]
        if first_index > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, first_index)
        current = first_index
        while current <= last_index:
            ok, image = cap.read()
            if not ok:
                break
            if current in wanted:
                frame_payload = frame_by_index[current]
                frame_index = current
                if frame_payload.get("visible"):
                    trail.append((int(round(float(frame_payload["x"]))), int(round(float(frame_payload["y"])))))
                crop = image[y1:y2, x1:x2].copy()
                if len(trail) >= 2:
                    points = np.array([[(x - x1, y - y1) for x, y in trail]], dtype=np.int32)
                    cv2.polylines(crop, points, False, (255, 180, 0), 2, cv2.LINE_AA)
                seed_x = int(round(float(seed.get("x", 0.0)))) - x1
                seed_y = int(round(float(seed.get("y", 0.0)))) - y1
                cv2.drawMarker(crop, (seed_x, seed_y), (0, 255, 255), cv2.MARKER_CROSS, 24, 2)
                if frame_payload.get("visible"):
                    x = int(round(float(frame_payload["x"]))) - x1
                    y = int(round(float(frame_payload["y"]))) - y1
                    cv2.circle(crop, (x, y), 10, (0, 255, 0), 2, cv2.LINE_AA)
                    cv2.circle(crop, (x, y), 2, (0, 255, 0), -1, cv2.LINE_AA)
                elif frame_payload.get("source") in {"impact_occlusion", "occluded_by_clubhead"}:
                    cv2.putText(crop, "clubhead occlusion", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2, cv2.LINE_AA)
                cv2.putText(
                    crop,
                    f"f{frame_index} {frame_payload.get('source', '')}",
                    (20, 34),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                name = f"frame_{frame_index:06d}.jpg"
                cv2.imwrite(str(frames_dir / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 94])
                written.append(name)
            current += 1
    finally:
        cap.release()

    launch_frame = trajectory.get("impact", {}).get("launchFrame")
    sheet_names = []
    for name in written:
        frame_index = _frame_number(name)
        dense_launch = launch_frame is not None and int(launch_frame) - 8 <= frame_index <= int(launch_frame) + 25
        stride_hit = (frame_index - int(seed.get("frameIndex", 0))) % max(1, contact_sheet_stride) == 0
        if dense_launch or stride_hit:
            sheet_names.append(name)
    thumbs = []
    for name in sheet_names:
        image = cv2.imread(str(frames_dir / name))
        if image is not None:
            thumbs.append(cv2.resize(image, (360, 240), interpolation=cv2.INTER_AREA))
    if thumbs:
        cols = 4
        rows = math.ceil(len(thumbs) / cols)
        sheet = np.zeros((rows * 240, cols * 360, 3), dtype=np.uint8)
        for index, image in enumerate(thumbs):
            row, col = divmod(index, cols)
            sheet[row * 240 : (row + 1) * 240, col * 360 : (col + 1) * 360] = image
        cv2.imwrite(str(output_dir / "trajectory_contact_sheet.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])

    title_sample_id = html_lib.escape(str(trajectory.get("sampleId") or ""))
    html = f"""<!doctype html><meta charset=\"utf-8\"><title>{title_sample_id} trajectory</title>
<style>body{{margin:0;background:#111;color:#eee;font-family:sans-serif}}.bar{{position:sticky;top:0;background:#1b1b1b;padding:10px;display:flex;gap:12px;align-items:center}}button{{font-size:16px;padding:6px 10px}}input{{width:60vw}}img{{display:block;max-width:100vw;max-height:calc(100vh - 58px);margin:auto}}code{{color:#9ee}}</style>
<div class=\"bar\"><button id=\"prev\">Prev</button><button id=\"play\">Play</button><button id=\"next\">Next</button><input id=\"range\" type=\"range\" min=\"0\" max=\"{max(0, len(written) - 1)}\" value=\"0\"><code id=\"label\"></code></div><img id=\"frame\">
<script>const frames=[{','.join([repr('frames/' + name) for name in written])}];let i=0,t=null;const img=document.getElementById('frame'),r=document.getElementById('range'),label=document.getElementById('label');function show(n){{i=Math.max(0,Math.min(frames.length-1,n));img.src=frames[i];r.value=i;label.textContent=frames[i];}}prev.onclick=()=>show(i-1);next.onclick=()=>show(i+1);range.oninput=()=>show(+range.value);play.onclick=()=>{{if(t){{clearInterval(t);t=null;play.textContent='Play';}}else{{t=setInterval(()=>show((i+1)%frames.length),80);play.textContent='Pause';}}}};show(0);</script>"""
    (output_dir / "trajectory_viewer.html").write_text(html, encoding="utf-8")
    report = {
        "trajectory": str(trajectory_path),
        "outputDir": str(output_dir),
        "viewer": str(output_dir / "trajectory_viewer.html"),
        "contactSheet": str(output_dir / "trajectory_contact_sheet.jpg"),
        "frames": len(written),
        "crop": [x1, y1, x2, y2],
    }
    (output_dir / "preview_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def render_many(trajectory_paths: Iterable[Path], output_root: Path) -> dict[str, Any]:
    reports = []
    for trajectory_path in trajectory_paths:
        trajectory = _load_json(trajectory_path)
        sample_id = str(trajectory.get("sampleId") or trajectory_path.stem)
        reports.append(render_trajectory_viewer(trajectory_path, _preview_output_dir(output_root, sample_id)))
    index = {"outputRoot": str(output_root), "previews": reports}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "preview_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render HTML/JPEG previews for TrackNet M1 trajectories")
    parser.add_argument("--trajectory", type=Path, action="append", default=[])
    parser.add_argument("--trajectories-dir", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = args.trajectory
    if args.trajectories_dir:
        paths.extend(sorted(args.trajectories_dir.glob("*.json")))
    report = render_many(paths, args.output_root)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
