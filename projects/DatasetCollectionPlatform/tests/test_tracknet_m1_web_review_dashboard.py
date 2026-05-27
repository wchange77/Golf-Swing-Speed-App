from __future__ import annotations

import json
from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

import render_tracknet_m1_web_review_dashboard


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_render_web_review_dashboard_embeds_all_video_variants_and_qc_rows(tmp_path: Path):
    observed = tmp_path / "previews/m1_sota_tracking/m1_sota_20up_full_trajectory.mp4"
    image_only = tmp_path / "previews/m1_predicted_full_trajectory/m1_predicted_full_image_only_20up.mp4"
    metric = tmp_path / "previews/m1_predicted_full_trajectory/m1_predicted_full_metric_sidecar_20up.mp4"
    for path in (observed, image_only, metric):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
    preview_report = tmp_path / "previews/m1_predicted_full_trajectory/preview_report.json"
    _write_json(preview_report, {
        "videos": [
            {"variant": "image_only", "output": str(image_only), "trajectoryCount": 20, "framesWritten": 301},
            {"variant": "metric_sidecar", "output": str(metric), "trajectoryCount": 20, "framesWritten": 301},
        ],
    })
    qc_report = tmp_path / "previews/m1_predicted_full_trajectory/qc/predicted_flight_qc_report.json"
    _write_json(qc_report, {
        "summary": {"predictionCount": 40, "statusCounts": {"needs_review": 40}},
        "items": [
            {
                "sampleId": "sample_001",
                "variant": "image_only",
                "status": "needs_review",
                "quality": {"fitPointCount": 8, "reprojectionRmsePx": 1.25, "confidence": 0.62},
                "trackmanComparison": {"status": "unavailable_unconfirmed_ocr"},
            }
        ],
    })
    ocr_report = tmp_path / "work/stage1_trackman_ocr/stage1_trackman_ocr_report.json"
    _write_json(ocr_report, {
        "items": [
            {
                "sampleId": "sample_001",
                "trackmanPhoto": "IMG_001.jpg",
                "ocrStatus": "ok",
                "lineCount": 2,
                "needsHumanConfirmation": True,
                "text": "CLUB SPEED\nLAUNCH ANGLE",
            }
        ]
    })
    dashboard_dir = tmp_path / "previews/m1_full_trajectory_review"
    dashboard_dir.mkdir(parents=True)
    (dashboard_dir / "observed_sota_20up.gif").write_bytes(b"gif")
    (dashboard_dir / "predicted_image_only_20up.gif").write_bytes(b"gif")
    (dashboard_dir / "predicted_metric_sidecar_20up.gif").write_bytes(b"gif")
    m2_index = tmp_path / "previews/m1_3d_review/index.html"
    m2_index.parent.mkdir(parents=True)
    m2_index.write_text("<html>M2</html>", encoding="utf-8")

    report = render_tracknet_m1_web_review_dashboard.render_web_review_dashboard(
        output_dir=dashboard_dir,
        observed_video=observed,
        predicted_preview_report=preview_report,
        qc_report=qc_report,
        trackman_ocr_report=ocr_report,
    )

    html = Path(report["index"]).read_text(encoding="utf-8")
    assert html.count("<video") == 3
    assert html.count("<img") == 3
    assert "../m1_sota_tracking/m1_sota_20up_full_trajectory.mp4" in html
    assert "observed_sota_20up.gif" in html
    assert "image_only" in html
    assert "metric_sidecar" in html
    assert "sample_001" in html
    assert "unavailable_unconfirmed_ocr" in html
    assert "TrackMan OCR" in html
    assert "CLUB SPEED" in html
    assert "Legacy/debug preview" in html
    assert "Formal M2 Review" in html
    assert "../m1_3d_review/index.html" in html
