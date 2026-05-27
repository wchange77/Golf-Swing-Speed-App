from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _safe_name(value: Any, fallback: str = "sample") -> str:
    raw = str(value or fallback)
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw).strip("._")
    return safe or fallback


def _frames(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return [frame for frame in value if isinstance(frame, dict)] if isinstance(value, list) else []


def _frame_map(frames: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(frame["frameIndex"]): frame for frame in frames if frame.get("frameIndex") is not None}


def _has_point(frame: dict[str, Any] | None) -> bool:
    return bool(frame) and frame.get("x") is not None and frame.get("y") is not None and bool(frame.get("visible", True))


def _point(frame: dict[str, Any]) -> tuple[int, int]:
    return int(round(float(frame["x"]))), int(round(float(frame["y"])))


def _draw_polyline(image: np.ndarray, points: list[tuple[int, int]], color: tuple[int, int, int], thickness: int) -> None:
    if len(points) >= 2:
        cv2.polylines(image, [np.array(points, dtype=np.int32)], False, color, thickness, cv2.LINE_AA)


def _draw_marker(image: np.ndarray, frame: dict[str, Any] | None, color: tuple[int, int, int], radius: int) -> None:
    if _has_point(frame):
        cv2.circle(image, _point(frame), radius, color, 2, cv2.LINE_AA)


def _timeline(payload: dict[str, Any]) -> tuple[int, int] | None:
    indices: list[int] = []
    for key in ("ballRawObservedFrames", "ballSmoothVisibleFrames", "clubheadTrackToImpact"):
        indices.extend(int(frame["frameIndex"]) for frame in _frames(payload, key) if frame.get("frameIndex") is not None)
    if not indices:
        return None
    return min(indices), max(indices)


def _render_video(payload: dict[str, Any], output_path: Path) -> dict[str, Any] | None:
    source_video = Path(str(payload.get("sourceVideo") or ""))
    if not source_video.exists():
        return None
    timeline = _timeline(payload)
    if timeline is None:
        return None
    start, end = timeline
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        return None
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or payload.get("frameWidth") or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or payload.get("frameHeight") or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or payload.get("fps") or 24.0)
    if width <= 0 or height <= 0:
        cap.release()
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), max(1.0, fps), (width, height))
    if not writer.isOpened():
        cap.release()
        return None
    raw_map = _frame_map(_frames(payload, "ballRawObservedFrames"))
    smooth_map = _frame_map(_frames(payload, "ballSmoothVisibleFrames"))
    club_map = _frame_map(_frames(payload, "clubheadTrackToImpact"))
    raw_trail: list[tuple[int, int]] = []
    smooth_trail: list[tuple[int, int]] = []
    club_trail: list[tuple[int, int]] = []
    frames_written = 0
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        for frame_index in range(start, end + 1):
            ok, image = cap.read()
            if not ok:
                break
            raw = raw_map.get(frame_index)
            smooth = smooth_map.get(frame_index)
            club = club_map.get(frame_index)
            if _has_point(raw):
                raw_trail.append(_point(raw))
            if _has_point(smooth):
                smooth_trail.append(_point(smooth))
            if _has_point(club):
                club_trail.append(_point(club))
            _draw_polyline(image, raw_trail, (0, 255, 255), 2)
            _draw_polyline(image, smooth_trail, (0, 255, 0), 3)
            _draw_polyline(image, club_trail, (255, 0, 255), 2)
            _draw_marker(image, raw, (0, 255, 255), 8)
            _draw_marker(image, smooth, (0, 255, 0), 10)
            _draw_marker(image, club, (255, 0, 255), 10)
            cv2.rectangle(image, (0, 0), (width, 34), (0, 0, 0), -1)
            cv2.putText(image, f"{payload.get('sampleId')} f{frame_index}", (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
            writer.write(image)
            frames_written += 1
    finally:
        writer.release()
        cap.release()
    if frames_written == 0 or not output_path.exists() or output_path.stat().st_size == 0:
        return None
    return {"path": str(output_path), "framesWritten": frames_written, "sizeBytes": output_path.stat().st_size}


def _page_payload(payload: dict[str, Any], video_relpath: str | None) -> dict[str, Any]:
    return {
        "sampleId": payload.get("sampleId"),
        "shotId": payload.get("shotId"),
        "sessionId": payload.get("sessionId"),
        "sourceVideo": payload.get("sourceVideo"),
        "videoPreview": video_relpath,
        "rawBall": _frames(payload, "ballRawObservedFrames"),
        "smoothBall": _frames(payload, "ballSmoothVisibleFrames"),
        "clubhead": _frames(payload, "clubheadTrackToImpact"),
        "impactWindow": payload.get("impactWindow"),
        "launchFrame": payload.get("launchFrame"),
        "lastReliableFrame": payload.get("lastReliableFrame"),
        "qc": payload.get("qc"),
        "trainingLabelPolicy": payload.get("trainingLabelPolicy"),
    }


def _sample_page(payload: dict[str, Any], *, video_relpath: str | None) -> str:
    data = json.dumps(_page_payload(payload, video_relpath), ensure_ascii=False, indent=2)
    sample_id = html.escape(str(payload.get("sampleId") or "sample"))
    video = f'<video src="{html.escape(video_relpath)}" controls playsinline></video>' if video_relpath else '<p class="muted">source video missing or preview unavailable</p>'
    return f'''<!doctype html>
<meta charset="utf-8">
<title>{sample_id} visible tracking</title>
<style>
body{{margin:0;background:#101315;color:#e9eef2;font-family:Arial,Helvetica,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:18px}}
header{{display:flex;justify-content:space-between;gap:12px;align-items:center}}
a{{color:#4dd6ff}}
video{{display:block;width:100%;background:#000;border:1px solid #2b343b;border-radius:6px;margin:12px 0}}
.toolbar{{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0;color:#cbd5dc}}
pre{{white-space:pre-wrap;background:#171c20;border:1px solid #2b343b;padding:12px;border-radius:6px;max-height:420px;overflow:auto}}
.muted{{color:#9daab4}}
</style>
<main>
<header><h1>{sample_id}</h1><a href="index.html">Index</a></header>
<div class="toolbar">
<label><input type="checkbox" checked data-layer="rawBall"> raw ball</label>
<label><input type="checkbox" checked data-layer="smoothBall"> smooth ball</label>
<label><input type="checkbox" checked data-layer="clubhead"> clubhead</label>
<label><input type="checkbox" checked data-layer="impactWindow"> impactWindow</label>
<label><input type="checkbox" checked data-layer="launchFrame"> launchFrame</label>
<label><input type="checkbox" checked data-layer="lastReliableFrame"> lastReliableFrame</label>
</div>
{video}
<p class="muted">All automatic, invisible, occluded, smoothed, and model-derived frames remain labelEligible=false until explicit human acceptance.</p>
<pre id="payload"></pre>
<script>
window.VISIBLE_TRACKING_DATA = {data};
document.getElementById('payload').textContent = JSON.stringify(window.VISIBLE_TRACKING_DATA, null, 2);
</script>
</main>
'''


def _index_page(rows: list[dict[str, Any]]) -> str:
    rendered = []
    for row in rows:
        rendered.append(
            "<tr>"
            f"<td><a href='{html.escape(row['href'])}'>{html.escape(row['sampleId'])}</a></td>"
            f"<td>{html.escape(str(row['status']))}</td>"
            f"<td>{html.escape(str(row['issueCount']))}</td>"
            f"<td>{html.escape(str(row.get('sourceVideo') or ''))}</td>"
            "</tr>"
        )
    return f'''<!doctype html>
<meta charset="utf-8">
<title>M1 Visible Tracking Review</title>
<style>body{{font-family:Arial,Helvetica,sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}th{{background:#f6f6f6}}</style>
<h1>M1 Visible Tracking Review</h1>
<table><thead><tr><th>Sample</th><th>Status</th><th>Issues</th><th>Video</th></tr></thead><tbody>{''.join(rendered)}</tbody></table>
'''


def render_visible_review_pages(
    *,
    visible_trajectories_dir: Path | str,
    output_dir: Path | str,
    copy_or_link_video: str = "link",
    max_samples: int | None = None,
) -> dict[str, Any]:
    visible_trajectories_dir = Path(visible_trajectories_dir)
    output_dir = Path(output_dir)
    if not visible_trajectories_dir.exists() or not visible_trajectories_dir.is_dir():
        raise FileNotFoundError(f"visible trajectories directory does not exist: {visible_trajectories_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(visible_trajectories_dir.glob("*.json"))
    if max_samples is not None:
        paths = paths[: max(0, int(max_samples))]

    rows: list[dict[str, Any]] = []
    generated_pages: list[str] = []
    generated_videos: list[str] = []
    missing_videos: list[str] = []
    status_counts: dict[str, int] = {}
    for path in paths:
        payload = _read_json(path)
        sample_id = _safe_name(payload.get("sampleId") or path.stem)
        status = str((payload.get("qc") or {}).get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        video_output = output_dir / "videos" / f"{sample_id}.mp4"
        video_info = _render_video(payload, video_output)
        video_relpath = f"videos/{sample_id}.mp4" if video_info else None
        if video_info:
            generated_videos.append(str(video_output))
        else:
            missing_videos.append(sample_id)
        page_path = output_dir / f"{sample_id}.html"
        _write_text(page_path, _sample_page(payload, video_relpath=video_relpath))
        generated_pages.append(str(page_path))
        rows.append(
            {
                "sampleId": sample_id,
                "href": f"{sample_id}.html",
                "status": status,
                "issueCount": len((payload.get("qc") or {}).get("issues") or []),
                "sourceVideo": payload.get("sourceVideo"),
            }
        )
    _write_text(output_dir / "index.html", _index_page(rows))
    report = {
        "version": "1.0",
        "visibleTrajectoriesDir": str(visible_trajectories_dir),
        "outputDir": str(output_dir),
        "copyOrLinkVideo": copy_or_link_video,
        "sampleCount": len(rows),
        "generatedPages": generated_pages,
        "generatedVideos": generated_videos,
        "missingVideos": missing_videos,
        "statusCounts": status_counts,
    }
    _write_json(output_dir / "visible_review_report.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Render per-sample M1 visible tracking review pages")
    parser.add_argument("--visible-trajectories-dir", type=Path, default=annotation_root / "work/m1_visible_tracking/trajectories")
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "previews/m1_visible_tracking")
    parser.add_argument("--copy-or-link-video", choices=("link", "copy"), default="link")
    parser.add_argument("--max-samples", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = render_visible_review_pages(
        visible_trajectories_dir=args.visible_trajectories_dir,
        output_dir=args.output_dir,
        copy_or_link_video=args.copy_or_link_video,
        max_samples=args.max_samples,
    )
    print(json.dumps({"sampleCount": report["sampleCount"], "outputDir": report["outputDir"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
