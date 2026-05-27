from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.trackman_review import (
    FIELD_ORDER,
    FIELD_SPECS,
    apply_trackman_review,
    build_trackman_review_candidate,
    export_trackman_review_templates,
    normalize_corrected_trackman_fields,
    validate_reviewed_trackman_metrics,
)
from render_trackman_review_pages import render_trackman_review_pages


def _ocr_item(text: str) -> dict:
    return {
        "sampleId": "sample_001",
        "shotId": "shot_001",
        "trackmanPhoto": "IMG_001.jpg",
        "trackmanPhotoPath": "/data/IMG_001.jpg",
        "ocrPath": "/work/IMG_001.ocr.json",
        "ocrStatus": "ok",
        "text": text,
        "needsHumanConfirmation": True,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_build_trackman_review_candidate_keeps_ocr_unusable_until_confirmed():
    item = _ocr_item("BALL SPEED\n106.9\nLAUNCH ANGLE\n15.5\nCARRY\n150.5")

    candidate = build_trackman_review_candidate(item)

    assert candidate["sampleId"] == "sample_001"
    assert candidate["shotId"] == "shot_001"
    assert candidate["trackmanPhotoPath"] == "/data/IMG_001.jpg"
    assert candidate["sourceOcrPath"] == "/work/IMG_001.ocr.json"
    assert candidate["metricsUsable"] is False
    assert candidate["reviewStatus"] == "needs_review"
    assert candidate["needsHumanConfirmation"] is True
    assert candidate["ocrText"] == item["text"]
    assert candidate["rawOcrText"] == item["text"]
    assert candidate["candidateFields"]["ballSpeed"]["rawCandidates"] == ["106.9"]


def test_apply_trackman_review_writes_confirmed_metrics():
    candidate = build_trackman_review_candidate(
        _ocr_item("BALL SPEED\n106.9\nLAUNCH ANGLE\n15.5\nCARRY\n150.5")
    )

    reviewed = apply_trackman_review(
        candidate,
        corrected_fields={
            "ballSpeed": {"normalizedValue": 106.9, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 15.5, "normalizedUnit": "deg"},
            "carry": {"normalizedValue": 150.5, "normalizedUnit": "yd"},
        },
        reviewer="human",
    )

    assert reviewed["reviewStatus"] == "accepted"
    assert reviewed["metricsUsable"] is True
    assert reviewed["correctedFields"]["carry"]["normalizedUnit"] == "yd"
    assert reviewed["reviewer"] == "human"
    assert reviewed["reviewedAt"].endswith("Z")


def test_build_trackman_review_candidate_tolerates_ocr_aliases_but_keeps_unusable():
    candidate = build_trackman_review_candidate(
        _ocr_item(
            "停点距离\n"
            "CLUB SPEED\n"
            "LAUNCHANGLE\n"
            "HEIGHT(APEX)\n"
            "CARRY\n"
            "杆头速度\n"
            "起飞角度\n"
            "最高高度\n"
            "落点距离\n"
            "169.8码\n"
            "72.9\n"
            "15.3\n"
            "14.9\n"
            "152.7"
        )
    )

    assert candidate["metricsUsable"] is False
    assert candidate["reviewStatus"] == "needs_review"
    assert candidate["candidateFields"]["launchAngle"]["rawCandidates"]
    assert candidate["candidateFields"]["apex"]["rawCandidates"]
    assert candidate["candidateFields"]["carry"]["rawCandidates"]


def test_build_trackman_review_candidate_exposes_all_twenty_trackman_parameters():
    candidate = build_trackman_review_candidate(
        _ocr_item(
            "杆头速度\n72.9\n"
            "起飞角度\n15.3\n"
            "落点距离\n152.7\n"
            "球路弯曲\n1.3右\n"
            "最高高度\n20.5\n"
            "总旋转值\n4041\n"
            "落点偏侧值\n4.0左\n"
            "停点距离\n169.8\n"
            "击球效率\n1.48\n"
            "攻击角度\n-4.0\n"
            "击球点高度\n10\n"
            "杆面朝向\n-2.3\n"
            "挥杆陡直度\n54.6\n"
            "杆头轨迹\n-0.8\n"
            "动态杆面仰角\n19.1\n"
            "杆面倒旋仰角\n23.2\n"
            "挥杆最低点\n108.3\n"
            "初射球速\n108.3\n"
            "杆面朝向相对杆头轨迹\n4.3左\n"
            "停点偏侧值\n92右"
        )
    )

    assert candidate["fieldOrder"] == [
        "clubSpeed",
        "launchAngle",
        "carry",
        "curve",
        "apex",
        "spinRate",
        "carrySide",
        "total",
        "smashFactor",
        "attackAngle",
        "impactHeight",
        "faceAngle",
        "swingPlane",
        "clubPath",
        "dynamicLoft",
        "spinLoft",
        "lowPointDistance",
        "ballSpeed",
        "faceToPath",
        "totalSide",
    ]
    assert set(candidate["candidateFields"]) == set(candidate["fieldOrder"])
    assert candidate["candidateFields"]["clubSpeed"]["displayNameZh"] == "杆头速度"
    assert candidate["candidateFields"]["clubSpeed"]["normalizedUnit"] == "mph"
    assert candidate["candidateFields"]["curve"]["rawCandidates"] == ["1.3右"]
    assert candidate["candidateFields"]["carrySide"]["rawCandidates"] == ["4.0左"]
    assert candidate["candidateFields"]["faceToPath"]["rawCandidates"] == ["4.3左"]
    assert candidate["candidateFields"]["totalSide"]["rawCandidates"] == ["92右"]


def test_trackman_field_contract_has_exactly_twenty_confirmed_fields():
    expected = [
        ("clubSpeed", "杆头速度", "Club Speed", "mph"),
        ("launchAngle", "起飞角度", "Launch Angle", "deg"),
        ("carry", "落点距离", "Carry", "yd"),
        ("curve", "球路弯曲", "Curve", "yd"),
        ("apex", "最高高度", "Height Apex", "yd"),
        ("spinRate", "总旋转值", "Spin Rate", "rpm"),
        ("carrySide", "落点偏侧值", "Carry Side", "yd"),
        ("total", "停点距离", "Total", "yd"),
        ("smashFactor", "击球效率", "Smash Factor", "ratio"),
        ("attackAngle", "攻击角度", "Attack Angle", "deg"),
        ("impactHeight", "击球点高度", "Impact Height", "mm"),
        ("faceAngle", "杆面朝向", "Face Angle", "deg"),
        ("swingPlane", "挥杆陡直度", "Swing Plane", "deg"),
        ("clubPath", "杆头轨迹", "Club Path", "deg"),
        ("dynamicLoft", "动态杆面仰角", "Dynamic Loft", "deg"),
        ("spinLoft", "杆面倒旋仰角", "Spin Loft", "deg"),
        ("lowPointDistance", "挥杆最低点", "Low Point Distance", "mm"),
        ("ballSpeed", "初射球速", "Ball Speed", "mph"),
        ("faceToPath", "杆面朝向相对杆头轨迹", "Face To Path", "deg"),
        ("totalSide", "停点偏侧值", "Total Side", "yd"),
    ]

    assert len(FIELD_SPECS) == 20
    assert [
        (spec["key"], spec["displayNameZh"], spec["displayNameEn"], spec["normalizedUnit"])
        for spec in FIELD_SPECS
    ] == expected
    assert FIELD_ORDER == [item[0] for item in expected]


def test_normalize_corrected_trackman_fields_preserves_alphanumeric_values():
    normalized = normalize_corrected_trackman_fields(
        {
            "impactHeight": {"reviewedValue": "4U", "normalizedValue": None, "normalizedUnit": "mm"},
            "lowPointDistance": {"rawValue": "5.4A", "normalizedValue": None, "normalizedUnit": "码"},
            "curve": {"rawValue": "R", "normalizedValue": None, "normalizedUnit": "yd", "direction": "right"},
            "carrySide": {"rawValue": "L", "normalizedValue": None, "normalizedUnit": "yd", "direction": "left"},
            "ballSpeed": {"normalizedValue": 108.3, "normalizedUnit": "英里"},
            "launchAngle": {"normalizedValue": 15.3, "normalizedUnit": "度"},
            "empty": {"rawValue": "", "normalizedValue": None, "normalizedUnit": ""},
        }
    )

    assert normalized["impactHeight"]["reviewedValue"] == "4U"
    assert normalized["impactHeight"]["normalizedValue"] is None
    assert normalized["lowPointDistance"]["rawValue"] == "5.4A"
    assert normalized["lowPointDistance"]["normalizedUnit"] == "yd"
    assert normalized["curve"]["rawValue"] == "R"
    assert normalized["curve"]["direction"] == "right"
    assert normalized["carrySide"]["rawValue"] == "L"
    assert normalized["carrySide"]["direction"] == "left"
    assert normalized["ballSpeed"]["normalizedUnit"] == "mph"
    assert normalized["launchAngle"]["normalizedUnit"] == "deg"
    assert normalized["empty"]["rawValue"] == ""


def test_build_trackman_review_candidate_does_not_confuse_carry_and_carry_side():
    candidate = build_trackman_review_candidate(_ocr_item("CARRY SIDE\n12.3右\nCARRY\n150.5"))

    assert candidate["metricsUsable"] is False
    assert candidate["candidateFields"]["carrySide"]["rawCandidates"] == ["12.3右"]
    assert candidate["candidateFields"]["carry"]["rawCandidates"] == ["150.5"]


def test_apply_trackman_review_rejects_empty_corrections():
    candidate = build_trackman_review_candidate(_ocr_item("BALL SPEED\n106.9"))

    with pytest.raises(ValueError, match="corrected_fields"):
        apply_trackman_review(candidate, corrected_fields={}, reviewer="human")


def test_apply_trackman_review_rejects_recognized_field_without_normalized_shape():
    candidate = build_trackman_review_candidate(_ocr_item("BALL SPEED\n106.9"))

    with pytest.raises(ValueError, match="ballSpeed"):
        apply_trackman_review(
            candidate,
            corrected_fields={"ballSpeed": {"normalizedValue": 106.9}},
            reviewer="human",
        )


def test_export_trackman_review_templates_prefills_candidates_but_keeps_unusable(tmp_path: Path):
    candidate = build_trackman_review_candidate(
        _ocr_item(
            "杆头速度\n72.9\n起飞角度\n15.3\n落点距离\n152.7\n"
            "球路弯曲\n1.3右\n最高高度\n20.5\n初射球速\n108.3"
        )
    )
    candidate_path = tmp_path / "candidates/sample_001.trackman_review.json"
    _write_json(candidate_path, candidate)

    report = export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
    )

    output_path = tmp_path / "reviewed/sample_001.trackman_review.json"
    reviewed = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["writtenCount"] == 1
    assert reviewed["reviewStatus"] == "needs_review"
    assert reviewed["metricsUsable"] is False
    assert reviewed["needsHumanConfirmation"] is True
    assert reviewed["correctedFields"]["clubSpeed"] == {
        "normalizedValue": 72.9,
        "normalizedUnit": "mph",
        "sourceRawCandidate": "72.9",
    }
    assert reviewed["correctedFields"]["curve"] == {
        "normalizedValue": 1.3,
        "normalizedUnit": "yd",
        "direction": "right",
        "sourceRawCandidate": "1.3右",
    }
    assert reviewed["correctedFields"]["ballSpeed"]["normalizedValue"] == 108.3
    assert len(reviewed["fieldOrder"]) == 20
    assert reviewed["candidateFields"]["curve"]["rawCandidates"] == ["1.3右"]


def test_export_trackman_review_templates_does_not_overwrite_accepted_reviews(tmp_path: Path):
    candidate = build_trackman_review_candidate(_ocr_item("初射球速\n108.3\n起飞角度\n15.3"))
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    accepted = {
        "sampleId": "sample_001",
        "reviewStatus": "accepted",
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 999.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 15.3, "normalizedUnit": "deg"},
        },
    }
    _write_json(tmp_path / "reviewed/sample_001.trackman_review.json", accepted)

    report = export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    preserved = json.loads((tmp_path / "reviewed/sample_001.trackman_review.json").read_text(encoding="utf-8"))
    assert report["skippedAcceptedCount"] == 1
    assert preserved == accepted


def test_export_trackman_review_templates_uses_accepted_review_as_layout_calibration(tmp_path: Path):
    ocr_path = tmp_path / "ocr/IMG_001.ocr.json"
    _write_json(
        ocr_path,
        {
            "status": "ok",
            "imageSize": {"width": 4096, "height": 3072},
            "lines": [
                {"text": "杆头速度", "left": 1000, "top": 700, "width": 210, "height": 65},
                {"text": "落点距离", "left": 2000, "top": 700, "width": 210, "height": 65},
                {"text": "球路弯曲", "left": 3000, "top": 700, "width": 210, "height": 65},
                {"text": "73.9", "left": 1005, "top": 830, "width": 250, "height": 110},
                {"text": "154.0", "left": 2005, "top": 830, "width": 280, "height": 110},
                {"text": "9.5左", "left": 3005, "top": 830, "width": 280, "height": 110},
                {"text": "142.2", "left": 2005, "top": 990, "width": 220, "height": 90},
            ],
        },
    )
    candidate = build_trackman_review_candidate(
        _ocr_item("杆头速度\n落点距离\n球路弯曲\n154.0\n9.5左\n73.9")
    )
    candidate["sourceOcrPath"] = str(ocr_path)
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    _write_json(
        tmp_path / "reviewed/calibration.trackman_review.json",
        {
            "sampleId": "calibration",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "sourceOcrPath": str(ocr_path),
            "correctedFields": {
                "clubSpeed": {"normalizedValue": 73.9, "normalizedUnit": "英里"},
                "launchAngle": {"normalizedValue": 16.2, "normalizedUnit": "度"},
                "carry": {"normalizedValue": 154.0, "normalizedUnit": "码"},
                "curve": {"normalizedValue": 9.5, "normalizedUnit": "码", "direction": "left"},
                "ballSpeed": {"normalizedValue": 107.9, "normalizedUnit": "英里"},
            },
        },
    )

    report = export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        calibration_reviewed_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    reviewed = json.loads((tmp_path / "reviewed/sample_001.trackman_review.json").read_text(encoding="utf-8"))
    assert report["calibration"]["sourceSampleId"] == "calibration"
    assert reviewed["ocrSelectionCalibration"]["sourceSampleId"] == "calibration"
    assert reviewed["correctedFields"]["clubSpeed"] == {
        "normalizedValue": 73.9,
        "normalizedUnit": "mph",
        "sourceRawCandidate": "73.9",
    }
    assert reviewed["correctedFields"]["carry"] == {
        "normalizedValue": 154.0,
        "normalizedUnit": "yd",
        "sourceRawCandidate": "154.0",
    }
    assert reviewed["correctedFields"]["curve"] == {
        "normalizedValue": 9.5,
        "normalizedUnit": "yd",
        "direction": "left",
        "sourceRawCandidate": "9.5左",
    }


def test_export_trackman_review_templates_calibration_follows_rotated_field_labels(tmp_path: Path):
    calibration_ocr_path = tmp_path / "ocr/calibration.ocr.json"
    rotated_ocr_path = tmp_path / "ocr/rotated.ocr.json"
    _write_json(
        calibration_ocr_path,
        {
            "status": "ok",
            "imageSize": {"width": 4096, "height": 3072},
            "lines": [
                {"text": "杆头速度", "left": 1000, "top": 700, "width": 210, "height": 65},
                {"text": "落点距离", "left": 2000, "top": 700, "width": 210, "height": 65},
                {"text": "球路弯曲", "left": 3000, "top": 700, "width": 210, "height": 65},
                {"text": "73.9", "left": 1005, "top": 830, "width": 250, "height": 110},
                {"text": "154.0", "left": 2005, "top": 830, "width": 280, "height": 110},
                {"text": "9.5左", "left": 3005, "top": 830, "width": 280, "height": 110},
            ],
        },
    )
    _write_json(
        rotated_ocr_path,
        {
            "status": "ok",
            "imageSize": {"width": 3072, "height": 4096},
            "lines": [
                {"text": "杆头速度", "left": 740, "top": 2530, "width": 70, "height": 225},
                {"text": "落点距离", "left": 730, "top": 1150, "width": 70, "height": 225},
                {"text": "球路弯曲", "left": 730, "top": 470, "width": 70, "height": 225},
                {"text": "71.8", "left": 860, "top": 2484, "width": 163, "height": 330},
                {"text": "145.1", "left": 829, "top": 1109, "width": 131, "height": 305},
                {"text": "6.3右", "left": 819, "top": 415, "width": 153, "height": 339},
                {"text": "163.0", "left": 1313, "top": 398, "width": 127, "height": 333},
            ],
        },
    )
    calibration_candidate = build_trackman_review_candidate(_ocr_item("杆头速度\n落点距离\n球路弯曲"))
    calibration_candidate["sourceOcrPath"] = str(calibration_ocr_path)
    candidate = build_trackman_review_candidate(_ocr_item("杆头速度\n落点距离\n球路弯曲"))
    candidate["sourceOcrPath"] = str(rotated_ocr_path)
    _write_json(tmp_path / "candidates/rotated.trackman_review.json", candidate)
    _write_json(
        tmp_path / "reviewed/calibration.trackman_review.json",
        {
            "sampleId": "calibration",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "sourceOcrPath": str(calibration_ocr_path),
            "correctedFields": {
                "clubSpeed": {"normalizedValue": 73.9, "normalizedUnit": "mph"},
                "carry": {"normalizedValue": 154.0, "normalizedUnit": "yd"},
                "curve": {"normalizedValue": 9.5, "normalizedUnit": "yd", "direction": "left"},
            },
        },
    )

    export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        calibration_reviewed_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    reviewed = json.loads((tmp_path / "reviewed/rotated.trackman_review.json").read_text(encoding="utf-8"))
    assert reviewed["correctedFields"]["clubSpeed"]["sourceRawCandidate"] == "71.8"
    assert reviewed["correctedFields"]["carry"]["sourceRawCandidate"] == "145.1"
    assert reviewed["correctedFields"]["curve"]["sourceRawCandidate"] == "6.3右"


def test_export_trackman_review_templates_ignores_direction_on_non_directional_calibration_fields(tmp_path: Path):
    calibration_ocr_path = tmp_path / "ocr/calibration.ocr.json"
    target_ocr_path = tmp_path / "ocr/target.ocr.json"
    _write_json(
        calibration_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "初射球速", "left": 2000, "top": 2630, "width": 220, "height": 70},
                {"text": "107.9", "left": 1950, "top": 2740, "width": 320, "height": 110},
                {"text": "14.3左", "left": 3300, "top": 2690, "width": 300, "height": 120},
            ],
        },
    )
    _write_json(
        target_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "初射球速", "left": 2000, "top": 2630, "width": 220, "height": 70},
                {"text": "108.3", "left": 1950, "top": 2740, "width": 320, "height": 110},
                {"text": "4.3左", "left": 3300, "top": 2690, "width": 300, "height": 120},
            ],
        },
    )
    candidate = build_trackman_review_candidate(_ocr_item("初射球速\n4.3左\n108.3"))
    candidate["sourceOcrPath"] = str(target_ocr_path)
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    _write_json(
        tmp_path / "reviewed/calibration.trackman_review.json",
        {
            "sampleId": "calibration",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "sourceOcrPath": str(calibration_ocr_path),
            "correctedFields": {
                "ballSpeed": {"normalizedValue": 107.9, "normalizedUnit": "英里", "direction": "left"},
            },
        },
    )

    export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        calibration_reviewed_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    reviewed = json.loads((tmp_path / "reviewed/sample_001.trackman_review.json").read_text(encoding="utf-8"))
    assert reviewed["correctedFields"]["ballSpeed"]["sourceRawCandidate"] == "108.3"


def test_export_trackman_review_templates_uses_nearest_repeated_label_when_learning_total(tmp_path: Path):
    calibration_ocr_path = tmp_path / "ocr/calibration.ocr.json"
    target_ocr_path = tmp_path / "ocr/target.ocr.json"
    _write_json(
        calibration_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "停点距离", "left": 700, "top": 650, "width": 190, "height": 55, "confidence": 0.999},
                {"text": "0米", "left": 550, "top": 2530, "width": 120, "height": 55},
                {"text": "停点距离", "left": 3330, "top": 1150, "width": 205, "height": 63, "confidence": 0.990},
                {"text": "173.2", "left": 3290, "top": 1248, "width": 305, "height": 118},
            ],
        },
    )
    _write_json(
        target_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "停点距离", "left": 700, "top": 650, "width": 190, "height": 55, "confidence": 0.999},
                {"text": "22.3", "left": 3200, "top": 2140, "width": 360, "height": 170},
                {"text": "停点距离", "left": 3330, "top": 1150, "width": 205, "height": 63, "confidence": 0.990},
                {"text": "169.8", "left": 3290, "top": 1248, "width": 305, "height": 118},
            ],
        },
    )
    candidate = build_trackman_review_candidate(_ocr_item("停点距离\n22.3\n169.8"))
    candidate["sourceOcrPath"] = str(target_ocr_path)
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    _write_json(
        tmp_path / "reviewed/calibration.trackman_review.json",
        {
            "sampleId": "calibration",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "sourceOcrPath": str(calibration_ocr_path),
            "correctedFields": {
                "total": {"normalizedValue": 173.2, "normalizedUnit": "码"},
            },
        },
    )

    export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        calibration_reviewed_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    reviewed = json.loads((tmp_path / "reviewed/sample_001.trackman_review.json").read_text(encoding="utf-8"))
    assert reviewed["correctedFields"]["total"]["sourceRawCandidate"] == "169.8"


def test_export_trackman_review_templates_prefers_raw_total_candidate_over_ambiguous_repeated_label(tmp_path: Path):
    calibration_ocr_path = tmp_path / "ocr/calibration.ocr.json"
    target_ocr_path = tmp_path / "ocr/target.ocr.json"
    _write_json(
        calibration_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "停点距离", "left": 3330, "top": 1150, "width": 205, "height": 63},
                {"text": "173.2", "left": 3290, "top": 1248, "width": 305, "height": 118},
            ],
        },
    )
    _write_json(
        target_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "停点距离", "left": 3330, "top": 1150, "width": 205, "height": 63},
                {"text": "22.3", "left": 3200, "top": 2140, "width": 360, "height": 170},
                {"text": "169.8", "left": 3290, "top": 1248, "width": 305, "height": 118},
            ],
        },
    )
    candidate = build_trackman_review_candidate(_ocr_item("停点距离\n169.8"))
    candidate["sourceOcrPath"] = str(target_ocr_path)
    candidate["candidateFields"]["total"]["rawCandidates"] = ["169.8"]
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    _write_json(
        tmp_path / "reviewed/calibration.trackman_review.json",
        {
            "sampleId": "calibration",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "sourceOcrPath": str(calibration_ocr_path),
            "correctedFields": {
                "total": {"normalizedValue": 173.2, "normalizedUnit": "码"},
            },
        },
    )

    export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        calibration_reviewed_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    reviewed = json.loads((tmp_path / "reviewed/sample_001.trackman_review.json").read_text(encoding="utf-8"))
    assert reviewed["correctedFields"]["total"]["sourceRawCandidate"] == "169.8"


def test_export_trackman_review_templates_rejects_implausible_calibrated_total_candidate(tmp_path: Path):
    calibration_ocr_path = tmp_path / "ocr/calibration.ocr.json"
    target_ocr_path = tmp_path / "ocr/target.ocr.json"
    _write_json(
        calibration_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "停点距离", "left": 3330, "top": 1150, "width": 205, "height": 63},
                {"text": "173.2", "left": 3290, "top": 1248, "width": 305, "height": 118},
            ],
        },
    )
    _write_json(
        target_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "停点距离", "left": 3330, "top": 1150, "width": 205, "height": 63},
                {"text": "22.3", "left": 3290, "top": 1248, "width": 305, "height": 118},
                {"text": "166.0", "left": 3200, "top": 1400, "width": 200, "height": 90},
            ],
        },
    )
    candidate = build_trackman_review_candidate(_ocr_item("停点距离\n166.0"))
    candidate["sourceOcrPath"] = str(target_ocr_path)
    candidate["candidateFields"]["total"]["rawCandidates"] = ["166.0"]
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    _write_json(
        tmp_path / "reviewed/calibration.trackman_review.json",
        {
            "sampleId": "calibration",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "sourceOcrPath": str(calibration_ocr_path),
            "correctedFields": {
                "total": {"normalizedValue": 173.2, "normalizedUnit": "码"},
            },
        },
    )

    export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        calibration_reviewed_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    reviewed = json.loads((tmp_path / "reviewed/sample_001.trackman_review.json").read_text(encoding="utf-8"))
    assert reviewed["correctedFields"]["total"]["sourceRawCandidate"] == "166.0"


def test_export_trackman_review_templates_leaves_field_empty_when_all_candidates_implausible(tmp_path: Path):
    calibration_ocr_path = tmp_path / "ocr/calibration.ocr.json"
    target_ocr_path = tmp_path / "ocr/target.ocr.json"
    _write_json(
        calibration_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "停点距离", "left": 3330, "top": 1150, "width": 205, "height": 63},
                {"text": "173.2", "left": 3290, "top": 1248, "width": 305, "height": 118},
            ],
        },
    )
    _write_json(
        target_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "停点距离", "left": 3330, "top": 1150, "width": 205, "height": 63},
                {"text": "22.3", "left": 3290, "top": 1248, "width": 305, "height": 118},
                {"text": "5.9左", "left": 3200, "top": 1400, "width": 200, "height": 90},
            ],
        },
    )
    candidate = build_trackman_review_candidate(_ocr_item("停点距离\n5.9左"))
    candidate["sourceOcrPath"] = str(target_ocr_path)
    candidate["candidateFields"]["total"]["rawCandidates"] = ["5.9左"]
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    _write_json(
        tmp_path / "reviewed/calibration.trackman_review.json",
        {
            "sampleId": "calibration",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "sourceOcrPath": str(calibration_ocr_path),
            "correctedFields": {
                "total": {"normalizedValue": 173.2, "normalizedUnit": "码"},
            },
        },
    )

    export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        calibration_reviewed_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    reviewed = json.loads((tmp_path / "reviewed/sample_001.trackman_review.json").read_text(encoding="utf-8"))
    assert reviewed["correctedFields"]["total"] == {"normalizedValue": None, "normalizedUnit": "yd"}


def test_export_trackman_review_templates_learns_calibration_from_close_manual_rounding(tmp_path: Path):
    calibration_ocr_path = tmp_path / "ocr/calibration.ocr.json"
    target_ocr_path = tmp_path / "ocr/target.ocr.json"
    _write_json(
        calibration_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "挥杆陡直度", "left": 1268, "top": 2149, "width": 270, "height": 63},
                {"text": "58.5", "left": 1212, "top": 2269, "width": 384, "height": 168},
            ],
        },
    )
    _write_json(
        target_ocr_path,
        {
            "status": "ok",
            "lines": [
                {"text": "挥杆陡直度", "left": 1268, "top": 2149, "width": 270, "height": 63},
                {"text": "57.2", "left": 1212, "top": 2269, "width": 384, "height": 168},
            ],
        },
    )
    candidate = build_trackman_review_candidate(_ocr_item("挥杆陡直度\n57.2"))
    candidate["sourceOcrPath"] = str(target_ocr_path)
    _write_json(tmp_path / "candidates/sample_001.trackman_review.json", candidate)
    _write_json(
        tmp_path / "reviewed/calibration.trackman_review.json",
        {
            "sampleId": "calibration",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "sourceOcrPath": str(calibration_ocr_path),
            "correctedFields": {
                "swingPlane": {"normalizedValue": 58.9, "normalizedUnit": "度"},
            },
        },
    )

    export_trackman_review_templates(
        candidates_dir=tmp_path / "candidates",
        output_dir=tmp_path / "reviewed",
        calibration_reviewed_dir=tmp_path / "reviewed",
        overwrite_existing=True,
    )

    reviewed = json.loads((tmp_path / "reviewed/sample_001.trackman_review.json").read_text(encoding="utf-8"))
    assert reviewed["correctedFields"]["swingPlane"]["sourceRawCandidate"] == "57.2"


def test_validate_reviewed_trackman_metrics_reports_importable_and_blocked_reviews(tmp_path: Path):
    importable = {
        "sampleId": "sample_ok",
        "shotId": "shot_ok",
        "reviewStatus": "accepted",
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 108.3, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 15.3, "normalizedUnit": "deg"},
            "carry": {"normalizedValue": 152.7, "normalizedUnit": "yd"},
            "apex": {"normalizedValue": 20.5, "normalizedUnit": "yd"},
        },
    }
    unaccepted = {
        "sampleId": "sample_draft",
        "reviewStatus": "needs_review",
        "metricsUsable": False,
        "correctedFields": {},
    }
    missing_required = {
        "sampleId": "sample_missing",
        "reviewStatus": "accepted",
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 108.3, "normalizedUnit": "mph"},
        },
    }
    _write_json(tmp_path / "reviewed/sample_ok.trackman_review.json", importable)
    _write_json(tmp_path / "reviewed/sample_draft.trackman_review.json", unaccepted)
    _write_json(tmp_path / "reviewed/sample_missing.trackman_review.json", missing_required)

    report = validate_reviewed_trackman_metrics(tmp_path / "reviewed")

    statuses = {item["sampleId"]: item["status"] for item in report["items"]}
    assert report["reviewedCount"] == 3
    assert report["importableCount"] == 1
    assert statuses == {
        "sample_ok": "importable",
        "sample_draft": "not_accepted",
        "sample_missing": "missing_required_fields",
    }
    assert report["importableBySample"] == {"sample_ok": str(tmp_path / "reviewed/sample_ok.trackman_review.json")}


def test_validate_reviewed_trackman_metrics_reports_explicit_import_boundaries(tmp_path: Path):
    samples = {
        "accepted": {
            "sampleId": "accepted",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "correctedFields": {
                "ballSpeed": {"normalizedValue": 108.3, "normalizedUnit": "mph"},
                "launchAngle": {"normalizedValue": 15.3, "normalizedUnit": "deg"},
            },
        },
        "rejected": {
            "sampleId": "rejected",
            "reviewStatus": "rejected",
            "metricsUsable": False,
            "correctedFields": {},
        },
        "draft": {
            "sampleId": "draft",
            "reviewStatus": "needs_review",
            "metricsUsable": False,
            "correctedFields": {},
        },
        "unusable": {
            "sampleId": "unusable",
            "reviewStatus": "accepted",
            "metricsUsable": False,
            "correctedFields": {
                "ballSpeed": {"normalizedValue": 108.3, "normalizedUnit": "mph"},
                "launchAngle": {"normalizedValue": 15.3, "normalizedUnit": "deg"},
            },
        },
        "bad_unit": {
            "sampleId": "bad_unit",
            "reviewStatus": "accepted",
            "metricsUsable": True,
            "correctedFields": {
                "ballSpeed": {"normalizedValue": 108.3, "normalizedUnit": "mph"},
                "launchAngle": {"normalizedValue": 15.3, "normalizedUnit": "mph"},
            },
        },
    }
    for sample_id, payload in samples.items():
        _write_json(tmp_path / f"reviewed/{sample_id}.trackman_review.json", payload)

    report = validate_reviewed_trackman_metrics(tmp_path / "reviewed")

    items = {item["sampleId"]: item for item in report["items"]}
    assert report["reviewedCount"] == 5
    assert report["importableCount"] == 1
    assert items["accepted"]["status"] == "importable"
    assert items["accepted"]["nonImportableReason"] is None
    assert items["rejected"]["nonImportableReason"] == "review_rejected"
    assert items["draft"]["nonImportableReason"] == "review_not_accepted"
    assert items["unusable"]["nonImportableReason"] == "metrics_not_usable"
    assert items["bad_unit"]["status"] == "invalid_fields"
    assert items["bad_unit"]["invalidFields"] == ["launchAngle"]
    assert items["bad_unit"]["nonImportableReason"] == "invalid_fields"


def test_validate_reviewed_trackman_metrics_accepts_chinese_unit_aliases(tmp_path: Path):
    reviewed = {
        "sampleId": "sample_ok",
        "shotId": "shot_ok",
        "reviewStatus": "accepted",
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 107.9, "normalizedUnit": "英里"},
            "launchAngle": {"normalizedValue": 16.2, "normalizedUnit": "度"},
            "carry": {"normalizedValue": 154.0, "normalizedUnit": "码"},
            "apex": {"normalizedValue": 20.7, "normalizedUnit": "码"},
        },
    }
    _write_json(tmp_path / "reviewed/sample_ok.trackman_review.json", reviewed)

    report = validate_reviewed_trackman_metrics(tmp_path / "reviewed")

    assert report["importableCount"] == 1
    assert report["items"][0]["status"] == "importable"


def test_render_trackman_review_pages_writes_index_and_candidate_json(tmp_path: Path):
    photo_path = tmp_path / "IMG_001.jpg"
    photo_path.write_bytes(b"fake image bytes")
    report = {
        "items": [
            {
                "sampleId": "sample_001",
                "shotId": "shot_001",
                "trackmanPhoto": "IMG_001.jpg",
                "trackmanPhotoPath": str(photo_path),
                "ocrPath": "/work/IMG_001.ocr.json",
                "ocrStatus": "ok",
                "text": "BALL SPEED\n106.9\nLAUNCH ANGLE\n15.5\nCARRY\n150.5",
                "needsHumanConfirmation": True,
            }
        ]
    }
    report_path = tmp_path / "ocr_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    result = render_trackman_review_pages(report_path, tmp_path / "out")

    assert result["candidateCount"] == 1
    assert (tmp_path / "out/index.html").exists()
    candidate_json_path = tmp_path / "out/candidates/sample_001.trackman_review.json"
    assert candidate_json_path.exists()
    candidate = json.loads(candidate_json_path.read_text(encoding="utf-8"))
    assert candidate["metricsUsable"] is False
    assert candidate["reviewStatus"] == "needs_review"

    html = (tmp_path / "out/candidates/sample_001.html").read_text(encoding="utf-8")
    assert "sample_001" in html
    assert "BALL SPEED" in html
    assert "TrackMan Parameters" in html
    assert "杆头速度" in html
    assert "停点偏侧值" in html
    assert "Candidate Fields" in html
    assert "trackman_assets/IMG_001.jpg" in html


def test_render_trackman_review_pages_uses_safe_file_stems_for_unsafe_sample_ids(tmp_path: Path):
    report = {
        "items": [
            {
                "sampleId": "../escape<script>'\"",
                "shotId": "shot_001",
                "trackmanPhoto": "IMG_001.jpg",
                "trackmanPhotoPath": "",
                "ocrPath": "/work/IMG_001.ocr.json",
                "ocrStatus": "ok",
                "text": "BALL SPEED\n106.9",
                "needsHumanConfirmation": True,
            }
        ]
    }
    report_path = tmp_path / "ocr_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    render_trackman_review_pages(report_path, tmp_path / "out")

    candidate_files = sorted((tmp_path / "out/candidates").glob("*.trackman_review.json"))
    assert len(candidate_files) == 1
    assert candidate_files[0].parent == tmp_path / "out/candidates"
    assert ".." not in candidate_files[0].name
    assert "/" not in candidate_files[0].name
    assert "<" not in candidate_files[0].name
    assert not (tmp_path / "out/escape<script>'\".trackman_review.json").exists()

    candidate = json.loads(candidate_files[0].read_text(encoding="utf-8"))
    assert candidate["sampleId"] == "../escape<script>'\""
    assert candidate["metricsUsable"] is False
    index_html = (tmp_path / "out/index.html").read_text(encoding="utf-8")
    assert "href='candidates/../" not in index_html
    assert "&lt;script&gt;" in index_html


def test_render_trackman_review_pages_does_not_link_unsafe_or_non_image_photo_paths(tmp_path: Path):
    non_image = tmp_path / "secret.txt"
    non_image.write_text("do not expose", encoding="utf-8")
    report = {
        "items": [
            {
                "sampleId": "unsafe_photo",
                "shotId": "shot_001",
                "trackmanPhoto": "unsafe.jpg",
                "trackmanPhotoPath": "javascript:alert(1).jpg",
                "ocrPath": "/work/unsafe.ocr.json",
                "ocrStatus": "ok",
                "text": "BALL SPEED\n106.9",
                "needsHumanConfirmation": True,
            },
            {
                "sampleId": "non_image",
                "shotId": "shot_002",
                "trackmanPhoto": "secret.txt",
                "trackmanPhotoPath": str(non_image),
                "ocrPath": "/work/non_image.ocr.json",
                "ocrStatus": "ok",
                "text": "BALL SPEED\n107.0",
                "needsHumanConfirmation": True,
            },
        ]
    }
    report_path = tmp_path / "ocr_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    render_trackman_review_pages(report_path, tmp_path / "out")

    unsafe_html = (tmp_path / "out/candidates/unsafe_photo.html").read_text(encoding="utf-8")
    assert "javascript:alert(1).jpg" in unsafe_html
    assert "href='javascript:alert(1).jpg'" not in unsafe_html
    assert "src='javascript:alert(1).jpg'" not in unsafe_html

    non_image_html = (tmp_path / "out/candidates/non_image.html").read_text(encoding="utf-8")
    assert str(non_image) in non_image_html
    assert f"href='{non_image}'" not in non_image_html
    assert not (tmp_path / "out/candidates/trackman_assets/secret.txt").exists()


def test_render_trackman_review_pages_cleans_stale_generated_files_on_rerender(tmp_path: Path):
    photo_path = tmp_path / "IMG_001.jpg"
    photo_path.write_bytes(b"fake image bytes")
    first_report = {
        "items": [
            {**_ocr_item("BALL SPEED\n106.9"), "sampleId": "keep", "trackmanPhotoPath": str(photo_path)},
            {**_ocr_item("BALL SPEED\n107.0"), "sampleId": "stale", "trackmanPhotoPath": str(photo_path)},
        ]
    }
    second_report = {
        "items": [
            {**_ocr_item("BALL SPEED\n106.9"), "sampleId": "keep", "trackmanPhotoPath": str(photo_path)}
        ]
    }
    report_path = tmp_path / "ocr_report.json"
    report_path.write_text(json.dumps(first_report, ensure_ascii=False), encoding="utf-8")
    render_trackman_review_pages(report_path, tmp_path / "out")
    assert (tmp_path / "out/candidates/stale.html").exists()
    assert (tmp_path / "out/candidates/trackman_assets/IMG_001.jpg").exists()

    report_path.write_text(json.dumps(second_report, ensure_ascii=False), encoding="utf-8")
    render_trackman_review_pages(report_path, tmp_path / "out")

    assert (tmp_path / "out/candidates/keep.html").exists()
    assert not (tmp_path / "out/candidates/stale.html").exists()
    assert not (tmp_path / "out/candidates/stale.trackman_review.json").exists()
    assert (tmp_path / "out/candidates/trackman_assets/IMG_001.jpg").exists()
