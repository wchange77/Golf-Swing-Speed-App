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


def _relpath(path: Path, start: Path) -> str:
    return os.path.relpath(path.resolve(), start.resolve()).replace(os.sep, "/")


def _cell(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _safe_variant(value: object) -> str:
    text = str(value or "variant")
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
    return cleaned.strip("._") or "variant"


def _video_card(*, title: str, src: str, meta: dict[str, Any], fallback_src: str | None = None) -> str:
    rows = "".join(
        f"<dt>{_cell(key)}</dt><dd>{_cell(value)}</dd>"
        for key, value in meta.items()
        if value is not None
    )
    fallback = f'<img class="browser-preview" src="{html.escape(fallback_src)}" alt="{html.escape(title)} animation">' if fallback_src else ""
    return f"""
<section class="video-panel">
  <div class="panel-head">
    <h2>{html.escape(title)}</h2>
    <dl>{rows}</dl>
  </div>
  {fallback}
  <video src="{html.escape(src)}" controls preload="metadata"></video>
</section>
"""


def _qc_table(qc_report: dict[str, Any]) -> str:
    rows = []
    for item in qc_report.get("items", []):
        quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
        comparison = item.get("trackmanComparison") if isinstance(item.get("trackmanComparison"), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{_cell(item.get('sampleId'))}</td>"
            f"<td>{_cell(item.get('variant'))}</td>"
            f"<td>{_cell(item.get('status'))}</td>"
            f"<td>{_cell(quality.get('fitPointCount'))}</td>"
            f"<td>{_cell(quality.get('reprojectionRmsePx'))}</td>"
            f"<td>{_cell(quality.get('confidence'))}</td>"
            f"<td>{_cell(comparison.get('status'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _trackman_ocr_section(trackman_ocr_report: dict[str, Any] | None) -> str:
    if not trackman_ocr_report:
        return ""
    rows = []
    for item in trackman_ocr_report.get("items", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_cell(item.get('sampleId'))}</td>"
            f"<td>{_cell(item.get('trackmanPhoto'))}</td>"
            f"<td>{_cell(item.get('ocrStatus'))}</td>"
            f"<td>{_cell(item.get('lineCount'))}</td>"
            f"<td>{_cell(item.get('needsHumanConfirmation'))}</td>"
            f"<td><details><summary>OCR</summary><pre>{html.escape(str(item.get('text') or ''))}</pre></details></td>"
            "</tr>"
        )
    return f"""
  <section class="video-panel">
    <div class="panel-head"><h2>TrackMan OCR</h2></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Sample</th><th>Photo</th><th>Status</th><th>Lines</th><th>Needs Confirm</th><th>Text</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
  </section>
"""


def _summary_cards(qc_report: dict[str, Any], preview_report: dict[str, Any]) -> str:
    summary = qc_report.get("summary") if isinstance(qc_report.get("summary"), dict) else {}
    videos = preview_report.get("videos") if isinstance(preview_report.get("videos"), list) else []
    cards = [
        ("Predictions", summary.get("predictionCount")),
        ("Status", json.dumps(summary.get("statusCounts", {}), ensure_ascii=False)),
        ("Videos", len(videos) + 1),
    ]
    return "".join(f"<div class=\"metric\"><span>{html.escape(label)}</span><strong>{_cell(value)}</strong></div>" for label, value in cards)


def _html_page(
    *,
    videos_html: str,
    qc_rows: str,
    summary_html: str,
    qc_json_href: str,
    qc_md_href: str,
    predicted_index_href: str | None,
    m2_review_href: str | None,
    trackman_ocr_html: str,
) -> str:
    predicted_link = f"<a href=\"{html.escape(predicted_index_href)}\">Predicted Index</a>" if predicted_index_href else ""
    m2_link = f"<a href=\"{html.escape(m2_review_href)}\">Formal M2 Review</a>" if m2_review_href else ""
    return f"""<!doctype html>
<meta charset="utf-8">
<title>TrackNet M1 Full Trajectory Review</title>
<style>
:root{{color-scheme:dark;--bg:#101315;--panel:#171c20;--line:#2b343b;--text:#e9eef2;--muted:#9daab4;--green:#55d77a;--cyan:#4dd6ff;--magenta:#ff68d4}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif}}
main{{max-width:1440px;margin:0 auto;padding:20px}}
header{{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:16px}}
h1{{font-size:26px;line-height:1.1;margin:0}}
h2{{font-size:18px;margin:0}}
a{{color:var(--cyan)}}
.links{{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted)}}
.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:14px 0 18px}}
.metric{{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px;min-width:0}}
.metric span{{display:block;color:var(--muted);font-size:12px;margin-bottom:6px}}
.metric strong{{display:block;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.legend{{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);margin:0 0 16px}}
.legend b{{font-weight:700}}
.observed{{color:var(--green)}}.predicted{{color:var(--cyan)}}.club{{color:var(--magenta)}}
.video-panel{{background:var(--panel);border:1px solid var(--line);border-radius:6px;margin:0 0 18px;overflow:hidden}}
.panel-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding:12px 14px;border-bottom:1px solid var(--line)}}
dl{{display:grid;grid-template-columns:auto auto;gap:4px 10px;margin:0;color:var(--muted);font-size:12px}}
dd{{margin:0;color:var(--text)}}
video{{display:block;width:100%;max-height:78vh;background:#000}}
.browser-preview{{display:block;width:100%;background:#000}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:hidden}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;font-size:13px;white-space:nowrap}}
th{{color:var(--muted);font-weight:600;background:#13181c;position:sticky;top:0}}
.table-wrap{{max-height:70vh;overflow:auto;border-radius:6px;margin-top:10px}}
details summary{{cursor:pointer;color:var(--cyan)}}
pre{{white-space:pre-wrap;margin:8px 0 0;max-height:260px;overflow:auto;color:var(--text);background:#0d1114;border:1px solid var(--line);border-radius:4px;padding:8px}}
@media(max-width:760px){{main{{padding:12px}}header,.panel-head{{display:block}}.metrics{{grid-template-columns:1fr}}th,td{{font-size:12px;padding:7px}}}}
</style>
<main>
  <header>
    <div>
      <h1>TrackNet M1 Full Trajectory Review</h1>
      <div class="legend"><span><b class="observed">green</b> observed ball</span><span><b class="predicted">cyan</b> predicted ball</span><span><b class="club">magenta</b> clubhead</span></div>
    </div>
    <nav class="links"><a href="{html.escape(qc_json_href)}">QC JSON</a><a href="{html.escape(qc_md_href)}">QC Markdown</a>{m2_link}{predicted_link}</nav>
  </header>
  <p class="legend">Legacy/debug preview videos below are review aids only. Formal M2 uses video_only_3d and trackman_constrained_3d.</p>
  <section class="metrics">{summary_html}</section>
  {videos_html}
  <section class="video-panel">
    <div class="panel-head"><h2>QC / TrackMan Status</h2></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Sample</th><th>Variant</th><th>Status</th><th>Fit Points</th><th>RMSE px</th><th>Confidence</th><th>TrackMan</th></tr></thead>
        <tbody>{qc_rows}</tbody>
      </table>
    </div>
  </section>
  {trackman_ocr_html}
</main>
"""


def render_web_review_dashboard(
    *,
    output_dir: Path | str,
    observed_video: Path | str,
    predicted_preview_report: Path | str,
    qc_report: Path | str,
    trackman_ocr_report: Path | str | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    observed_video = Path(observed_video)
    predicted_preview_report = Path(predicted_preview_report)
    qc_report = Path(qc_report)
    trackman_ocr_report = Path(trackman_ocr_report) if trackman_ocr_report is not None else None
    preview_payload = _load_json(predicted_preview_report)
    qc_payload = _load_json(qc_report)
    ocr_payload = _load_json(trackman_ocr_report) if trackman_ocr_report is not None and trackman_ocr_report.exists() else None

    video_cards = [
        _video_card(
            title="Observed SOTA 20-up",
            src=_relpath(observed_video, output_dir),
            meta={"variant": "observed_sota", "samples": 20},
            fallback_src="observed_sota_20up.gif" if (output_dir / "observed_sota_20up.gif").exists() else None,
        )
    ]
    for video in preview_payload.get("videos", []):
        if not isinstance(video, dict):
            continue
        output = Path(str(video.get("output") or ""))
        variant = _safe_variant(video.get("variant"))
        fallback_path = output_dir / f"predicted_{variant}_20up.gif"
        video_cards.append(_video_card(
            title=f"Legacy/debug preview {video.get('variant')}",
            src=_relpath(output, output_dir),
            meta={
                "variant": video.get("variant"),
                "samples": video.get("trajectoryCount"),
                "frames": video.get("framesWritten"),
                "size": video.get("outputSize"),
            },
            fallback_src=fallback_path.name if fallback_path.exists() else None,
        ))

    predicted_index = Path(preview_payload.get("index")) if preview_payload.get("index") else None
    m2_review_index = output_dir.parent / "m1_3d_review/index.html"
    page = _html_page(
        videos_html="\n".join(video_cards),
        qc_rows=_qc_table(qc_payload),
        summary_html=_summary_cards(qc_payload, preview_payload),
        qc_json_href=_relpath(qc_report, output_dir),
        qc_md_href=_relpath(qc_report.with_suffix(".md"), output_dir),
        predicted_index_href=_relpath(predicted_index, output_dir) if predicted_index is not None else None,
        m2_review_href=_relpath(m2_review_index, output_dir) if m2_review_index.exists() else None,
        trackman_ocr_html=_trackman_ocr_section(ocr_payload),
    )
    index_path = output_dir / "index.html"
    index_path.write_text(page, encoding="utf-8")
    report = {
        "index": str(index_path),
        "observedVideo": str(observed_video),
        "predictedPreviewReport": str(predicted_preview_report),
        "qcReport": str(qc_report),
        "trackmanOcrReport": str(trackman_ocr_report) if trackman_ocr_report else None,
        "videoCount": len(video_cards),
        "qcRows": len(qc_payload.get("items", [])),
        "ocrRows": len(ocr_payload.get("items", [])) if ocr_payload else 0,
    }
    _write_json(output_dir / "dashboard_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Render a single static web dashboard for TrackNet M1 full trajectory review")
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "previews/m1_full_trajectory_review")
    parser.add_argument("--observed-video", type=Path, default=annotation_root / "previews/m1_sota_tracking/m1_sota_20up_full_trajectory.mp4")
    parser.add_argument("--predicted-preview-report", type=Path, default=annotation_root / "previews/m1_predicted_full_trajectory/preview_report.json")
    parser.add_argument("--qc-report", type=Path, default=annotation_root / "previews/m1_predicted_full_trajectory/qc/predicted_flight_qc_report.json")
    parser.add_argument("--trackman-ocr-report", type=Path, default=annotation_root / "work/stage1_trackman_ocr/stage1_trackman_ocr_report.json")
    args = parser.parse_args(argv)
    report = render_web_review_dashboard(
        output_dir=args.output_dir,
        observed_video=args.observed_video,
        predicted_preview_report=args.predicted_preview_report,
        qc_report=args.qc_report,
        trackman_ocr_report=args.trackman_ocr_report,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
