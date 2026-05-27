from __future__ import annotations

import json
from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from render_trackman_review_pages import render_trackman_review_pages


def test_trackman_review_page_warns_ocr_is_candidate_only(tmp_path: Path):
    report_path = tmp_path / "ocr_report.json"
    report_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "sampleId": "sample_001",
                        "shotId": "shot_001",
                        "trackmanPhoto": "IMG_001.jpg",
                        "trackmanPhotoPath": "",
                        "ocrPath": "/work/IMG_001.ocr.json",
                        "ocrStatus": "ok",
                        "text": "BALL SPEED\n106.9",
                        "needsHumanConfirmation": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    render_trackman_review_pages(report_path, tmp_path / "out")

    html = (tmp_path / "out/candidates/sample_001.html").read_text(encoding="utf-8")
    assert "OCR candidate only until human confirmation" in html
    assert "reviewStatus" in html
    assert "metricsUsable" in html
