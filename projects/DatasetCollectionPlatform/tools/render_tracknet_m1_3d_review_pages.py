from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def _safe_name(value: object, fallback: str = "sample") -> str:
    text = str(value or fallback)
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)
    return cleaned.strip("._") or fallback


def _relpath(path: Path, start: Path) -> str:
    return os.path.relpath(path.absolute(), start.absolute()).replace(os.sep, "/")


def _cell(value: Any) -> str:
    if isinstance(value, float):
        value = round(value, 4)
    return html.escape("" if value is None else str(value))


def _trajectory_stem(path: Path) -> str:
    suffix = ".trajectory_3d.json"
    if path.name.endswith(suffix):
        return path.name[: -len(suffix)]
    return path.stem


def _trajectory_section(payload: dict[str, Any], name: str) -> dict[str, Any]:
    section = payload.get(name)
    return section if isinstance(section, dict) else {}


def _sample_id(path: Path, payload: dict[str, Any]) -> str:
    for section_name in ("videoOnly3d", "trackmanConstrained3d", "stageOneVisibleTracking"):
        section = _trajectory_section(payload, section_name)
        sample_id = section.get("sampleId")
        if isinstance(sample_id, str) and sample_id:
            return sample_id
    sample_id = payload.get("sampleId")
    if isinstance(sample_id, str) and sample_id:
        return sample_id
    return _trajectory_stem(path)


def _frame_list(source: Any) -> list[dict[str, Any]]:
    if not isinstance(source, list):
        return []
    frames: list[dict[str, Any]] = []
    for frame in source:
        if not isinstance(frame, dict) or frame.get("frameIndex") is None:
            continue
        item = dict(frame)
        try:
            item["frameIndex"] = int(item["frameIndex"])
        except (TypeError, ValueError):
            continue
        for key in ("x", "y"):
            if item.get(key) is not None:
                try:
                    item[key] = round(float(item[key]), 3)
                except (TypeError, ValueError):
                    item[key] = None
        item["visible"] = bool(item.get("visible", True))
        item["labelEligible"] = bool(item.get("labelEligible", False))
        frames.append(item)
    return sorted(frames, key=lambda item: item["frameIndex"])


def _load_stage_one(
    payload: dict[str, Any],
    *,
    visible_trajectories_dir: Path | None,
    sample_id: str,
) -> dict[str, Any]:
    for key in ("stageOneVisibleTracking", "visibleTracking"):
        section = payload.get(key)
        if isinstance(section, dict):
            return section
    video = _trajectory_section(payload, "videoOnly3d")
    nested = video.get("stageOneVisibleTracking")
    if isinstance(nested, dict):
        return nested
    if visible_trajectories_dir is None:
        return {}
    candidates = [
        visible_trajectories_dir / f"{sample_id}.json",
        visible_trajectories_dir / f"{_safe_name(sample_id)}.json",
    ]
    for path in candidates:
        if path.exists():
            return _load_json(path)
    return {}


def _source_video(
    *,
    video_only: dict[str, Any],
    trackman: dict[str, Any],
    stage_one: dict[str, Any],
) -> Path | None:
    for source in (video_only.get("sourceVideo"), trackman.get("sourceVideo"), stage_one.get("sourceVideo")):
        if isinstance(source, str) and source:
            return Path(source)
    return None


def _link_video_asset(source_video: Path | None, *, output_dir: Path, sample_file_stem: str) -> Path | None:
    if source_video is None or not source_video.exists():
        return None
    extension = source_video.suffix or ".mov"
    asset = output_dir / "assets" / f"{sample_file_stem}{extension}"
    asset.parent.mkdir(parents=True, exist_ok=True)
    if asset.exists() or asset.is_symlink():
        try:
            if asset.resolve() == source_video.resolve():
                return asset
        except FileNotFoundError:
            pass
        asset.unlink()
    try:
        asset.symlink_to(source_video.resolve())
    except OSError:
        return None
    return asset


def _status(trackman: dict[str, Any]) -> str:
    if not trackman:
        return "not_generated_no_confirmed_trackman"
    return str(trackman.get("status") or "unknown")


def _curve_modeling_status(trackman: dict[str, Any]) -> dict[str, Any]:
    model = trackman.get("model") if isinstance(trackman.get("model"), dict) else {}
    inputs = trackman.get("trackmanInputs") if isinstance(trackman.get("trackmanInputs"), dict) else {}
    if (
        trackman.get("status") == "needs_review"
        and model.get("type") == "trackman_constrained_rk4_drag_magnus_3d"
    ):
        return {
            "status": "trackman_rk4_drag_magnus_modeled",
            "message": "TrackMan-confirmed metrics are modeled through the RK4 drag Magnus trajectory family and compared against visible evidence.",
            "trackmanSideSourceField": inputs.get("sideSourceField"),
        }
    if (
        trackman.get("status") == "needs_review"
        and model.get("type") == "trackman_constrained_endpoint_curve_3d"
        and inputs.get("sideYd") is not None
    ):
        return {
            "status": "trackman_endpoint_curve_modeled",
            "message": "TrackMan carry, apex, and side offset are used to build the review-only 3D endpoint/curve path.",
            "trackmanSideSourceField": inputs.get("sideSourceField"),
        }
    return {
        "status": "not_modeled_gravity_only",
        "message": (
            "Current video-only 3D reconstruction is a gravity-only baseline; "
            "shot curve, sidespin, carry side, and total side are review/QC inputs, not modeled forces yet."
        ),
        "trackmanFieldsForFutureQc": ["curve", "carrySide", "totalSide", "faceToPath"],
    }


def _parameter_statuses(video_only: dict[str, Any]) -> dict[str, Any]:
    params = video_only.get("parameters") if isinstance(video_only.get("parameters"), dict) else {}
    return {
        key: value
        for key, value in params.items()
        if isinstance(value, dict) and "status" in value and "confidence" in value
    }


def _world_points(frames: list[dict[str, Any]]) -> list[dict[str, float | int]]:
    points: list[dict[str, float | int]] = []
    for frame in frames:
        world = frame.get("worldMeters") if isinstance(frame.get("worldMeters"), dict) else {}
        try:
            points.append(
                {
                    "frameIndex": int(frame["frameIndex"]),
                    "x": float(world.get("x", 0.0)),
                    "height": float(world.get("height", 0.0)),
                    "z": float(world.get("z", 0.0)),
                }
            )
        except (TypeError, ValueError):
            continue
    return points


def _plot_data(video_only_frames: list[dict[str, Any]], trackman_frames: list[dict[str, Any]]) -> dict[str, Any]:
    video_points = _world_points(video_only_frames)
    trackman_points = _world_points(trackman_frames)
    return {
        "sideViewPlot": {
            "videoOnly3d": [{"frameIndex": p["frameIndex"], "z": p["z"], "height": p["height"]} for p in video_points],
            "trackmanConstrained3d": [{"frameIndex": p["frameIndex"], "z": p["z"], "height": p["height"]} for p in trackman_points],
        },
        "topViewPlot": {
            "videoOnly3d": [{"frameIndex": p["frameIndex"], "z": p["z"], "x": p["x"]} for p in video_points],
            "trackmanConstrained3d": [{"frameIndex": p["frameIndex"], "z": p["z"], "x": p["x"]} for p in trackman_points],
        },
    }


def _timeline_bounds(*frame_groups: list[dict[str, Any]], launch_frame: Any = None, landing_frame: Any = None) -> dict[str, int]:
    values: list[int] = []
    for frame in (launch_frame, landing_frame):
        try:
            if frame is not None:
                values.append(int(frame))
        except (TypeError, ValueError):
            pass
    for group in frame_groups:
        values.extend(int(frame["frameIndex"]) for frame in group if frame.get("frameIndex") is not None)
    if not values:
        return {"startFrame": 0, "endFrame": 1}
    start = min(values)
    end = max(values)
    if end <= start:
        end = start + 1
    return {"startFrame": start, "endFrame": end}


def _review_data(
    *,
    sample_id: str,
    payload: dict[str, Any],
    stage_one: dict[str, Any],
    video_href: str | None,
    source_video: Path | None,
) -> dict[str, Any]:
    video_only = _trajectory_section(payload, "videoOnly3d")
    trackman = _trajectory_section(payload, "trackmanConstrained3d")
    raw_ball = _frame_list(stage_one.get("ballRawObservedFrames"))
    smooth_ball = _frame_list(stage_one.get("ballSmoothVisibleFrames"))
    clubhead = _frame_list(stage_one.get("clubheadTrackToImpact"))
    video_only_frames = _frame_list(video_only.get("frames"))
    trackman_frames = _frame_list(trackman.get("frames"))
    plot_data = _plot_data(video_only_frames, trackman_frames)
    launch_frame = video_only.get("launchFrame") or stage_one.get("launchFrame")
    landing_frame = video_only.get("landingFrame") or trackman.get("landingFrame")
    fps = stage_one.get("fps") or video_only.get("fps") or trackman.get("fps") or 240.0
    frame_width = stage_one.get("frameWidth") or video_only.get("frameWidth") or trackman.get("frameWidth") or 1920
    frame_height = stage_one.get("frameHeight") or video_only.get("frameHeight") or trackman.get("frameHeight") or 1080
    return {
        "sampleId": sample_id,
        "sourceVideoPath": str(source_video) if source_video is not None else None,
        "videoHref": video_href,
        "fps": fps,
        "frameWidth": frame_width,
        "frameHeight": frame_height,
        "impactWindow": stage_one.get("impactWindow"),
        "lastReliableFrame": stage_one.get("lastReliableFrame"),
        "timeline": _timeline_bounds(
            raw_ball,
            smooth_ball,
            clubhead,
            video_only_frames,
            trackman_frames,
            launch_frame=launch_frame,
            landing_frame=landing_frame,
        ),
        "layers": {
            "clubheadToImpact": clubhead,
            "rawBallObserved": raw_ball,
            "smoothBallVisible": smooth_ball,
            "videoOnly3d": video_only_frames,
            "trackmanConstrained3d": trackman_frames,
        },
        "videoOnly3d": {
            "status": video_only.get("status"),
            "model": video_only.get("model"),
            "qc": video_only.get("qc"),
            "launchFrame": video_only.get("launchFrame"),
            "landingFrame": video_only.get("landingFrame"),
            "landingPointImage": video_only.get("landingPointImage"),
            "parameters": video_only.get("parameters"),
            "parameterStatuses": _parameter_statuses(video_only),
        },
        "trackmanConstrained3d": {
            "status": _status(trackman),
            "reason": trackman.get("reason"),
            "model": trackman.get("model"),
            "trackmanInputs": trackman.get("trackmanInputs"),
            "usedTrackManFields": trackman.get("usedTrackManFields"),
            "missingTrackManFields": trackman.get("missingTrackManFields"),
            "trackmanInputsProvenance": trackman.get("trackmanInputsProvenance"),
            "qc": trackman.get("qc"),
            "landingFrame": trackman.get("landingFrame"),
            "landingPointImage": trackman.get("landingPointImage"),
            "parameters": trackman.get("parameters"),
        },
        **plot_data,
        "curveModelingStatus": _curve_modeling_status(trackman),
        "trainingLabelPolicy": {
            "labelEligible": False,
            "message": "review-only candidate; not TrackNetV6 training truth until manual acceptance",
        },
    }


def _script_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _summary_rows(data: dict[str, Any]) -> str:
    video = data["videoOnly3d"]
    trackman = data["trackmanConstrained3d"]
    trackman_status = str(trackman.get("status") or "")
    comparison_state = (
        "TrackMan comparison unavailable"
        if trackman_status.startswith("unavailable_") or trackman_status.startswith("not_generated")
        else "TrackMan comparison available"
    )
    counts = {
        "clubheadToImpact": len(data["layers"]["clubheadToImpact"]),
        "rawBallObserved": len(data["layers"]["rawBallObserved"]),
        "smoothBallVisible": len(data["layers"]["smoothBallVisible"]),
        "videoOnly3d": len(data["layers"]["videoOnly3d"]),
        "trackmanConstrained3d": len(data["layers"]["trackmanConstrained3d"]),
    }
    rows = [
        ("Video-only status", video.get("status")),
        ("TrackMan status", trackman.get("status")),
        ("TrackMan comparison", comparison_state),
        ("Launch frame", video.get("launchFrame")),
        ("Landing frame", video.get("landingFrame")),
        ("Curve modeling", data["curveModelingStatus"]["status"]),
        ("Impact window", json.dumps(data.get("impactWindow"), ensure_ascii=False)),
        ("Last reliable frame", data.get("lastReliableFrame")),
        ("Counts", json.dumps(counts, ensure_ascii=False)),
        ("Label policy", data["trainingLabelPolicy"]["message"]),
    ]
    return "".join(f"<tr><th>{html.escape(key)}</th><td>{_cell(value)}</td></tr>" for key, value in rows)


def _json_details(title: str, payload: Any, *, open_details: bool = False) -> str:
    opened = " open" if open_details else ""
    dumped = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""
<details{opened}>
  <summary>{html.escape(title)}</summary>
  <pre>{html.escape(dumped)}</pre>
</details>
"""


def _sample_page(
    *,
    data: dict[str, Any],
    prev_href: str | None,
    next_href: str | None,
) -> str:
    video_html = (
        f'<video id="shot-video" src="{html.escape(str(data["videoHref"]))}" controls preload="metadata"></video>'
        if data.get("videoHref")
        else '<div class="missing-video">Source video is not available inside this preview folder.</div>'
    )
    prev_link = f'<a href="{html.escape(prev_href)}">Prev</a>' if prev_href else ""
    next_link = f'<a href="{html.escape(next_href)}">Next</a>' if next_href else ""
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(data["sampleId"])} 3D review</title>
<style>
:root{{color-scheme:dark;--bg:#101315;--panel:#171c20;--line:#2b343b;--text:#e9eef2;--muted:#9daab4;--cyan:#4dd6ff;--green:#55d77a;--yellow:#f2c94c;--magenta:#ff68d4;--orange:#ff9a4d}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif}}
main{{max-width:1380px;margin:0 auto;padding:18px}}
header{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:14px}}
h1{{font-size:22px;line-height:1.15;margin:0}}
h2{{font-size:16px;margin:0 0 10px}}
a{{color:var(--cyan);text-decoration:none}}a:hover{{text-decoration:underline}}
nav{{display:flex;gap:12px;flex-wrap:wrap}}
.viewer{{position:relative;background:#000;border:1px solid var(--line);border-radius:6px;overflow:hidden}}
video{{display:block;width:100%;max-height:78vh;background:#000}}
canvas{{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}}
.toolbar{{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;background:var(--panel);border:1px solid var(--line);border-top:0;border-radius:0 0 6px 6px;padding:10px}}
input[type=range]{{width:100%}}
.legend{{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin:10px 0 16px}}
.legend b{{font-weight:700}}.club{{color:var(--magenta)}}.raw{{color:var(--yellow)}}.smooth{{color:var(--green)}}.video3d{{color:var(--cyan)}}.tm{{color:var(--orange)}}
.grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,420px);gap:14px;margin-top:14px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px;min-width:0}}
table{{width:100%;border-collapse:collapse}}
th,td{{border-bottom:1px solid var(--line);padding:8px 7px;text-align:left;vertical-align:top;font-size:13px}}
th{{color:var(--muted);font-weight:600;width:160px}}
details{{border-top:1px solid var(--line);padding:10px 0}}
details:first-child{{border-top:0}}
summary{{cursor:pointer;color:var(--cyan);font-weight:600}}
pre{{white-space:pre-wrap;overflow:auto;max-height:420px;background:#0d1114;border:1px solid var(--line);border-radius:4px;padding:10px;color:var(--text);font-size:12px}}
.missing-video{{min-height:420px;display:grid;place-items:center;color:var(--muted)}}
@media(max-width:860px){{main{{padding:12px}}header{{display:block}}nav{{margin-top:10px}}.grid{{grid-template-columns:1fr}}.toolbar{{grid-template-columns:1fr}}th{{width:120px}}}}
</style>
<main>
  <header>
    <div>
      <h1>{html.escape(data["sampleId"])}</h1>
      <div class="legend">
        <span><b class="club">magenta</b> clubhead-to-impact</span>
        <span><b class="raw">yellow</b> raw ball evidence</span>
        <span><b class="smooth">green</b> smooth visible ball</span>
        <span><b class="video3d">cyan</b> video-only 3D</span>
        <span><b class="tm">orange</b> TrackMan-constrained 3D</span>
      </div>
    </div>
    <nav>{prev_link}<a href="../index.html">Index</a>{next_link}</nav>
  </header>
  <section class="viewer">{video_html}<canvas id="overlay"></canvas></section>
  <section class="toolbar">
    <span id="frame-label">Frame</span>
    <input id="frame-slider" type="range" min="{int(data["timeline"]["startFrame"])}" max="{int(data["timeline"]["endFrame"])}" value="{int(data["timeline"]["startFrame"])}">
    <span>{_cell(data.get("fps"))} fps</span>
  </section>
  <section class="grid">
    <div class="panel">
      <h2>QC / Status</h2>
      <table><tbody>{_summary_rows(data)}</tbody></table>
    </div>
    <div class="panel">
      {_json_details("Video-only 3D", data["videoOnly3d"], open_details=True)}
      {_json_details("TrackMan-constrained 3D", data["trackmanConstrained3d"], open_details=True)}
      {_json_details("Overlay evidence data", data["layers"])}
      {_json_details("Review data", data)}
    </div>
  </section>
</main>
<script id="review-data" type="application/json">{_script_json(data)}</script>
<script>
const reviewData = JSON.parse(document.getElementById('review-data').textContent);
const video = document.getElementById('shot-video');
const canvas = document.getElementById('overlay');
const ctx = canvas.getContext('2d');
const slider = document.getElementById('frame-slider');
const frameLabel = document.getElementById('frame-label');
const layerSpec = [
  ['clubheadToImpact', '#ff68d4', 5, true],
  ['rawBallObserved', '#f2c94c', 4, false],
  ['smoothBallVisible', '#55d77a', 5, true],
  ['videoOnly3d', '#4dd6ff', 4, true],
  ['trackmanConstrained3d', '#ff9a4d', 4, true],
];

function resizeCanvas() {{
  const width = video && video.videoWidth ? video.videoWidth : Number(reviewData.frameWidth || 1920);
  const height = video && video.videoHeight ? video.videoHeight : Number(reviewData.frameHeight || 1080);
  canvas.width = width;
  canvas.height = height;
  draw(Number(slider.value));
}}

function validPoint(point) {{
  return point && Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y));
}}

function drawLayer(points, color, radius, connect, frameIndex) {{
  const active = points.filter((point) => validPoint(point) && point.visible !== false && Number(point.frameIndex) <= frameIndex);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = connect ? 4 : 2;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  if (connect && active.length > 1) {{
    ctx.beginPath();
    active.forEach((point, index) => {{
      if (index === 0) ctx.moveTo(Number(point.x), Number(point.y));
      else ctx.lineTo(Number(point.x), Number(point.y));
    }});
    ctx.stroke();
  }}
  active.forEach((point) => {{
    ctx.globalAlpha = point.visible === false ? 0.35 : 1.0;
    ctx.beginPath();
    ctx.arc(Number(point.x), Number(point.y), radius, 0, Math.PI * 2);
    ctx.fill();
    if (point.visible === false) {{
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.strokeStyle = color;
    }}
  }});
  ctx.globalAlpha = 1.0;
}}

function draw(frameIndex) {{
  resizeCanvasIfNeeded();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  layerSpec.forEach(([key, color, radius, connect]) => {{
    drawLayer(reviewData.layers[key] || [], color, radius, connect, frameIndex);
  }});
  frameLabel.textContent = `Frame ${{frameIndex}}`;
}}

function resizeCanvasIfNeeded() {{
  if (!canvas.width || !canvas.height) {{
    const width = video && video.videoWidth ? video.videoWidth : Number(reviewData.frameWidth || 1920);
    const height = video && video.videoHeight ? video.videoHeight : Number(reviewData.frameHeight || 1080);
    canvas.width = width;
    canvas.height = height;
  }}
}}

function frameFromVideoTime() {{
  const fps = Number(reviewData.fps || 240);
  return Math.round((video ? video.currentTime : 0) * fps);
}}

slider.addEventListener('input', () => {{
  const frame = Number(slider.value);
  if (video && Number.isFinite(frame)) video.currentTime = Math.max(0, frame / Number(reviewData.fps || 240));
  draw(frame);
}});
if (video) {{
  video.addEventListener('loadedmetadata', resizeCanvas);
  video.addEventListener('timeupdate', () => {{
    const frame = Math.max(Number(slider.min), Math.min(Number(slider.max), frameFromVideoTime()));
    slider.value = String(frame);
    draw(frame);
  }});
}}
resizeCanvas();
</script>
"""


def _index_page(samples: list[dict[str, Any]]) -> str:
    rows = []
    for sample in samples:
        rows.append(
            "<tr>"
            f"<td><a href=\"{html.escape(sample['href'])}\">{html.escape(sample['sampleId'])}</a></td>"
            f"<td>{_cell(sample.get('videoOnlyStatus'))}</td>"
            f"<td>{_cell(sample.get('trackmanStatus'))}</td>"
            f"<td>{_cell(sample.get('rawBallPointCount'))}</td>"
            f"<td>{_cell(sample.get('smoothBallPointCount'))}</td>"
            f"<td>{_cell(sample.get('clubheadPointCount'))}</td>"
            f"<td>{_cell(sample.get('videoOnlyFrameCount'))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>TrackNet M1 3D Reconstruction Review</title>
<style>
:root{{color-scheme:dark;--bg:#101315;--panel:#171c20;--line:#2b343b;--text:#e9eef2;--muted:#9daab4;--cyan:#4dd6ff}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:20px}}
h1{{font-size:24px;margin:0 0 16px}}
a{{color:var(--cyan)}}table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:hidden}}
th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;white-space:nowrap}}
th{{color:var(--muted);font-weight:600;background:#13181c}}
.note{{color:var(--muted);margin:0 0 14px;font-size:13px}}
@media(max-width:760px){{main{{padding:12px}}th,td{{font-size:12px;padding:7px}}}}
</style>
<main>
  <h1>TrackNet M1 3D Reconstruction Review</h1>
  <p class="note">Each row opens a single-sample video review page. All generated tracks are review-only and not training labels.</p>
  <table>
    <thead><tr><th>Sample</th><th>Video-only</th><th>TrackMan</th><th>Raw Ball</th><th>Smooth Ball</th><th>Clubhead</th><th>3D Frames</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</main>
"""


def render_3d_review_pages(
    *,
    trajectories_dir: Path | str,
    output_dir: Path | str,
    visible_trajectories_dir: Path | str | None = None,
) -> dict[str, Any]:
    trajectories_dir = Path(trajectories_dir)
    output_dir = Path(output_dir)
    visible_dir = Path(visible_trajectories_dir) if visible_trajectories_dir is not None else None
    if not trajectories_dir.exists() or not trajectories_dir.is_dir():
        raise ValueError(f"trajectories_dir does not exist or is not a directory: {trajectories_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(trajectories_dir.glob("*.json"))
    sample_records: list[dict[str, Any]] = []
    page_jobs: list[tuple[str, dict[str, Any], str | None, str | None]] = []

    for path in paths:
        payload = _load_json(path)
        sample_id = _sample_id(path, payload)
        sample_file_stem = _safe_name(sample_id)
        stage_one = _load_stage_one(payload, visible_trajectories_dir=visible_dir, sample_id=sample_id)
        video_only = _trajectory_section(payload, "videoOnly3d")
        trackman = _trajectory_section(payload, "trackmanConstrained3d")
        source_video = _source_video(video_only=video_only, trackman=trackman, stage_one=stage_one)
        asset = _link_video_asset(source_video, output_dir=output_dir, sample_file_stem=sample_file_stem)
        video_href = _relpath(asset, output_dir / "samples") if asset is not None else None
        data = _review_data(
            sample_id=sample_id,
            payload=payload,
            stage_one=stage_one,
            video_href=video_href,
            source_video=source_video,
        )
        href = f"samples/{sample_file_stem}.html"
        record = {
            "sampleId": sample_id,
            "href": href,
            "trajectoryPath": str(path),
            "sourceVideo": str(source_video) if source_video is not None else None,
            "videoHref": video_href,
            "videoOnlyStatus": str(video_only.get("status") or "unknown"),
            "trackmanStatus": data["trackmanConstrained3d"]["status"],
            "rawBallPointCount": len(data["layers"]["rawBallObserved"]),
            "smoothBallPointCount": len(data["layers"]["smoothBallVisible"]),
            "clubheadPointCount": len(data["layers"]["clubheadToImpact"]),
            "videoOnlyFrameCount": len(data["layers"]["videoOnly3d"]),
            "trackmanFrameCount": len(data["layers"]["trackmanConstrained3d"]),
            "curveModelingStatus": data["curveModelingStatus"]["status"],
            "labelEligible": False,
        }
        sample_records.append(record)
        page_jobs.append((sample_file_stem, data, href, None))

    samples_dir = output_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    for index, (sample_file_stem, data, _href, _unused) in enumerate(page_jobs):
        prev_href = f"{_safe_name(sample_records[index - 1]['sampleId'])}.html" if index > 0 else None
        next_href = f"{_safe_name(sample_records[index + 1]['sampleId'])}.html" if index + 1 < len(sample_records) else None
        (samples_dir / f"{sample_file_stem}.html").write_text(
            _sample_page(data=data, prev_href=prev_href, next_href=next_href),
            encoding="utf-8",
        )

    (output_dir / "index.html").write_text(_index_page(sample_records), encoding="utf-8")
    report = {
        "version": "1.0",
        "outputDir": str(output_dir),
        "trajectoriesDir": str(trajectories_dir),
        "visibleTrajectoriesDir": str(visible_dir) if visible_dir is not None else None,
        "sampleCount": len(sample_records),
        "samples": sample_records,
    }
    _write_json(output_dir / "review_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Render per-sample M1 3D reconstruction review pages")
    parser.add_argument(
        "--trajectories-dir",
        type=Path,
        default=annotation_root / "work/m1_3d_reconstruction/trajectories",
    )
    parser.add_argument(
        "--visible-trajectories-dir",
        type=Path,
        default=annotation_root / "work/m1_visible_tracking/trajectories",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=annotation_root / "previews/m1_3d_reconstruction_review",
    )
    args = parser.parse_args(argv)
    report = render_3d_review_pages(
        trajectories_dir=args.trajectories_dir,
        visible_trajectories_dir=args.visible_trajectories_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps({"sampleCount": report["sampleCount"], "outputDir": report["outputDir"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
