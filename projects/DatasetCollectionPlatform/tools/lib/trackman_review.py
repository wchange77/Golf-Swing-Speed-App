from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


FIELD_SPECS = [
    {
        "key": "clubSpeed",
        "displayNameZh": "杆头速度",
        "displayNameEn": "Club Speed",
        "normalizedUnit": "mph",
        "aliases": ("CLUB SPEED", "CLUBSPEED", "杆头速度"),
    },
    {
        "key": "launchAngle",
        "displayNameZh": "起飞角度",
        "displayNameEn": "Launch Angle",
        "normalizedUnit": "deg",
        "aliases": ("LAUNCH ANGLE", "LAUNCHANGLE", "起飞角度", "发射角"),
    },
    {
        "key": "carry",
        "displayNameZh": "落点距离",
        "displayNameEn": "Carry",
        "normalizedUnit": "yd",
        "aliases": ("CARRY", "落点距离"),
    },
    {
        "key": "curve",
        "displayNameZh": "球路弯曲",
        "displayNameEn": "Curve",
        "normalizedUnit": "yd",
        "aliases": ("CURVE", "球路弯曲"),
    },
    {
        "key": "apex",
        "displayNameZh": "最高高度",
        "displayNameEn": "Height Apex",
        "normalizedUnit": "yd",
        "aliases": ("HEIGHT (APEX)", "HEIGHT(APEX)", "APEX", "最高高度"),
    },
    {
        "key": "spinRate",
        "displayNameZh": "总旋转值",
        "displayNameEn": "Spin Rate",
        "normalizedUnit": "rpm",
        "aliases": ("SPIN RATE", "SPINRATE", "TOTAL SPIN", "总旋转值", "总旋转", "倒旋"),
    },
    {
        "key": "carrySide",
        "displayNameZh": "落点偏侧值",
        "displayNameEn": "Carry Side",
        "normalizedUnit": "yd",
        "aliases": ("CARRY SIDE", "CARRYSIDE", "落点偏侧值", "落点偏侧"),
    },
    {
        "key": "total",
        "displayNameZh": "停点距离",
        "displayNameEn": "Total",
        "normalizedUnit": "yd",
        "aliases": ("TOTAL", "停点距离"),
    },
    {
        "key": "smashFactor",
        "displayNameZh": "击球效率",
        "displayNameEn": "Smash Factor",
        "normalizedUnit": "ratio",
        "aliases": ("SMASH FACTOR", "SMASHFACTOR", "击球效率"),
    },
    {
        "key": "attackAngle",
        "displayNameZh": "攻击角度",
        "displayNameEn": "Attack Angle",
        "normalizedUnit": "deg",
        "aliases": ("ATTACK ANGLE", "ATTACKANGLE", "攻击角度"),
    },
    {
        "key": "impactHeight",
        "displayNameZh": "击球点高度",
        "displayNameEn": "Impact Height",
        "normalizedUnit": "mm",
        "aliases": ("IMPACT HEIGHT", "IMPACTHEIGHT", "击球点高度"),
    },
    {
        "key": "faceAngle",
        "displayNameZh": "杆面朝向",
        "displayNameEn": "Face Angle",
        "normalizedUnit": "deg",
        "aliases": ("FACE ANGLE", "FACEANGLE", "杆面朝向"),
    },
    {
        "key": "swingPlane",
        "displayNameZh": "挥杆陡直度",
        "displayNameEn": "Swing Plane",
        "normalizedUnit": "deg",
        "aliases": ("SWING PLANE", "SWINGPLANE", "挥杆陡直度"),
    },
    {
        "key": "clubPath",
        "displayNameZh": "杆头轨迹",
        "displayNameEn": "Club Path",
        "normalizedUnit": "deg",
        "aliases": ("CLUB PATH", "CLUBPATH", "杆头轨迹"),
    },
    {
        "key": "dynamicLoft",
        "displayNameZh": "动态杆面仰角",
        "displayNameEn": "Dynamic Loft",
        "normalizedUnit": "deg",
        "aliases": ("DYNAMIC LOFT", "DYNAMICLOFT", "动态杆面仰角"),
    },
    {
        "key": "spinLoft",
        "displayNameZh": "杆面倒旋仰角",
        "displayNameEn": "Spin Loft",
        "normalizedUnit": "deg",
        "aliases": ("SPIN LOFT", "SPINLOFT", "杆面倒旋仰角"),
    },
    {
        "key": "lowPointDistance",
        "displayNameZh": "挥杆最低点",
        "displayNameEn": "Low Point Distance",
        "normalizedUnit": "mm",
        "aliases": ("LOW POINT DISTANCE", "LOWPOINTDIST", "LOW POINT DIST", "挥杆最低点"),
    },
    {
        "key": "ballSpeed",
        "displayNameZh": "初射球速",
        "displayNameEn": "Ball Speed",
        "normalizedUnit": "mph",
        "aliases": ("BALL SPEED", "BALLSPEED", "初射球速", "球速"),
    },
    {
        "key": "faceToPath",
        "displayNameZh": "杆面朝向相对杆头轨迹",
        "displayNameEn": "Face To Path",
        "normalizedUnit": "deg",
        "aliases": ("FACE TO PATH", "FACETOPATH", "杆面朝向相对杆头轨迹"),
    },
    {
        "key": "totalSide",
        "displayNameZh": "停点偏侧值",
        "displayNameEn": "Total Side",
        "normalizedUnit": "yd",
        "aliases": ("TOTAL SIDE", "TOTALSIDE", "停点偏侧值", "停点偏侧"),
    },
]

FIELD_ALIASES = {spec["key"]: tuple(spec["aliases"]) for spec in FIELD_SPECS}
FIELD_META = {spec["key"]: spec for spec in FIELD_SPECS}
FIELD_ORDER = [spec["key"] for spec in FIELD_SPECS]
DIRECTIONAL_FIELDS = {"curve", "carrySide", "faceToPath", "totalSide"}
FIELD_VALUE_RANGES = {
    "clubSpeed": (40.0, 130.0),
    "launchAngle": (-10.0, 50.0),
    "carry": (50.0, 280.0),
    "curve": (0.0, 100.0),
    "apex": (0.0, 100.0),
    "spinRate": (500.0, 10000.0),
    "carrySide": (0.0, 120.0),
    "total": (80.0, 320.0),
    "smashFactor": (0.5, 2.0),
    "attackAngle": (-30.0, 30.0),
    "impactHeight": (-100.0, 100.0),
    "faceAngle": (-30.0, 30.0),
    "swingPlane": (20.0, 90.0),
    "clubPath": (-30.0, 30.0),
    "dynamicLoft": (0.0, 70.0),
    "spinLoft": (0.0, 80.0),
    "lowPointDistance": (-300.0, 300.0),
    "ballSpeed": (50.0, 220.0),
    "faceToPath": (-30.0, 30.0),
    "totalSide": (0.0, 150.0),
}
UNIT_ALIASES = {
    "mph": {"mph", "英里", "英里/小时", "英里每小时"},
    "deg": {"deg", "degree", "degrees", "度", "°"},
    "yd": {"yd", "yard", "yards", "码"},
    "rpm": {"rpm", "转/分", "转每分", "转/分钟"},
    "ratio": {"ratio", "无", "倍"},
    "mm": {"mm", "毫米"},
}

_VALUE_RE = re.compile(r"-?\d+(?:\.\d+)?\s*(?:左|右|[LRlr])?(?![A-KM-QS-Z_a-km-qs-z铁])")
_LABEL_NORMALIZE_RE = re.compile(r"[\s_:/\\|()\[\]{}.-]+")
_RAW_VALUE_RE = re.compile(r"(?P<value>-?\d+(?:\.\d+)?)(?P<direction>左|右|[LRlr])?")
_DIRECTION_MAP = {
    "左": "left",
    "L": "left",
    "l": "left",
    "右": "right",
    "R": "right",
    "r": "right",
}


def _canonical_unit(value: Any, expected_unit: str | None = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return str(expected_unit or "")
    normalized = raw.lower()
    for unit, aliases in UNIT_ALIASES.items():
        if raw in aliases or normalized in aliases:
            return unit
    return raw


def _field_center(line: dict[str, Any]) -> tuple[float, float]:
    left = float(line.get("left") or 0.0)
    top = float(line.get("top") or 0.0)
    width = float(line.get("width") or 0.0)
    height = float(line.get("height") or 0.0)
    return left + width / 2.0, top + height / 2.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_label(value: str) -> str:
    return _LABEL_NORMALIZE_RE.sub("", value).lower()


def _alias_matches_line(line: str, alias: str) -> bool:
    normalized_line = _normalize_label(line)
    normalized_alias = _normalize_label(alias)
    if not normalized_alias:
        return False
    if not _values_in_line(line):
        return normalized_line == normalized_alias
    return normalized_alias in normalized_line


def _best_field_for_label_line(line: str) -> str | None:
    matches: list[tuple[int, str]] = []
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if _alias_matches_line(line, alias):
                matches.append((len(_normalize_label(alias)), field))
    if not matches:
        return None
    return max(matches)[1]


def _is_known_label(line: str) -> bool:
    return _best_field_for_label_line(line) is not None


def _values_in_line(line: str) -> list[str]:
    if line.lstrip().startswith("#"):
        return []
    if "铁" in line and not any(unit in line for unit in ("码", "度", "毫米", "转/分")):
        return []
    return [value.replace(" ", "") for value in _VALUE_RE.findall(line)]


def _append_unique(values: list[str], candidates: list[str]) -> None:
    for value in candidates:
        if value not in values:
            values.append(value)


def _block_candidates(text: str, *, limit: int = 4) -> dict[str, list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict[str, list[str]] = {key: [] for key in FIELD_ORDER}
    index = 0
    while index < len(lines):
        field = _best_field_for_label_line(lines[index])
        if field is None or _values_in_line(lines[index]):
            index += 1
            continue

        labels: list[str] = []
        cursor = index
        while cursor < len(lines):
            current_field = _best_field_for_label_line(lines[cursor])
            if current_field is None or _values_in_line(lines[cursor]):
                break
            if current_field not in labels:
                labels.append(current_field)
            cursor += 1

        values: list[str] = []
        value_cursor = cursor
        while value_cursor < len(lines) and len(values) < len(labels) + 3:
            if _is_known_label(lines[value_cursor]) and not _values_in_line(lines[value_cursor]):
                break
            values.extend(_values_in_line(lines[value_cursor]))
            value_cursor += 1

        if len(labels) >= 2 and values:
            for label_index, label in enumerate(labels):
                if label_index < len(values):
                    _append_unique(result[label], [values[label_index]])
        index = max(cursor, index + 1)
    return {key: value[:limit] for key, value in result.items()}


def _values_after_label(text: str, field: str, *, limit: int = 4) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if _best_field_for_label_line(line) != field:
            continue

        values = _values_in_line(line)
        if values:
            return values[:limit]

        following: list[str] = []
        for next_line in lines[index + 1 :]:
            if _is_known_label(next_line):
                break
            following.extend(_values_in_line(next_line))
            if len(following) >= limit:
                return following[:limit]
        if following:
            return following[:limit]

        fallback: list[str] = []
        for next_line in lines[index + 1 : index + 1 + limit * 3]:
            fallback.extend(_values_in_line(next_line))
            if len(fallback) >= limit:
                return fallback[:limit]
        return fallback
    return []


def build_trackman_review_candidate(ocr_item: dict[str, Any]) -> dict[str, Any]:
    text = str(ocr_item.get("text") or "")
    block_candidates = _block_candidates(text)
    candidate_fields = {
        key: {
            "displayNameZh": str(FIELD_META[key]["displayNameZh"]),
            "displayNameEn": str(FIELD_META[key]["displayNameEn"]),
            "normalizedUnit": str(FIELD_META[key]["normalizedUnit"]),
            "rawCandidates": (block_candidates.get(key) or _values_after_label(text, key)),
            "reviewed": False,
        }
        for key in FIELD_ORDER
    }
    return {
        "version": "1.0",
        "sampleId": ocr_item.get("sampleId"),
        "shotId": ocr_item.get("shotId"),
        "trackmanPhoto": ocr_item.get("trackmanPhoto"),
        "trackmanPhotoPath": ocr_item.get("trackmanPhotoPath"),
        "sourceOcrPath": ocr_item.get("ocrPath"),
        "ocrStatus": ocr_item.get("ocrStatus"),
        "reviewStatus": "needs_review",
        "metricsUsable": False,
        "fieldOrder": FIELD_ORDER,
        "candidateFields": candidate_fields,
        "correctedFieldTemplate": {
            key: {"normalizedValue": None, "normalizedUnit": candidate_fields[key]["normalizedUnit"]}
            for key in FIELD_ORDER
        },
        "ocrText": text,
        "rawOcrText": text,
        "needsHumanConfirmation": True,
    }


def _validate_corrected_fields(corrected_fields: dict[str, Any]) -> None:
    if not isinstance(corrected_fields, dict) or not corrected_fields:
        raise ValueError("corrected_fields must contain at least one confirmed metric")
    for field, value in corrected_fields.items():
        if field not in FIELD_ALIASES:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"{field} correction must be an object")
        if value.get("normalizedValue") is None or not value.get("normalizedUnit"):
            raise ValueError(f"{field} correction requires normalizedValue and normalizedUnit")


def apply_trackman_review(
    candidate: dict[str, Any],
    *,
    corrected_fields: dict[str, Any],
    reviewer: str,
) -> dict[str, Any]:
    _validate_corrected_fields(corrected_fields)
    return {
        **deepcopy(candidate),
        "reviewStatus": "accepted",
        "metricsUsable": True,
        "correctedFields": deepcopy(corrected_fields),
        "needsHumanConfirmation": False,
        "reviewer": reviewer,
        "reviewedAt": _utc_now(),
    }


def _parse_candidate_value(raw_value: Any, normalized_unit: str) -> dict[str, Any]:
    item: dict[str, Any] = {"normalizedValue": None, "normalizedUnit": _canonical_unit(normalized_unit)}
    if raw_value is None:
        return item
    match = _RAW_VALUE_RE.search(str(raw_value).strip())
    if not match:
        return item
    item["normalizedValue"] = float(match.group("value"))
    direction = match.group("direction")
    if direction:
        item["direction"] = _DIRECTION_MAP[direction]
    item["sourceRawCandidate"] = str(raw_value)
    return item


def normalize_corrected_trackman_fields(corrected_fields: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in corrected_fields.items():
        if not isinstance(value, dict):
            normalized[key] = value
            continue
        field = deepcopy(value)
        expected = str(FIELD_META.get(str(key), {}).get("normalizedUnit") or "")
        field["normalizedUnit"] = _canonical_unit(field.get("normalizedUnit"), expected)
        normalized[key] = field
    return normalized


def _line_value(line: dict[str, Any]) -> str | None:
    values = _values_in_line(str(line.get("text") or ""))
    return values[0] if values else None


def _line_numeric(line: dict[str, Any]) -> float | None:
    raw = _line_value(line)
    if raw is None:
        return None
    match = _RAW_VALUE_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group("value"))
    except ValueError:
        return None


def _line_direction(line: dict[str, Any]) -> str | None:
    raw = _line_value(line)
    if raw is None:
        return None
    parsed = _parse_candidate_value(raw, "")
    direction = parsed.get("direction")
    return str(direction) if direction else None


def _raw_value_in_field_range(field: str, raw_value: Any) -> bool:
    if raw_value is None or field not in FIELD_VALUE_RANGES:
        return True
    match = _RAW_VALUE_RE.search(str(raw_value))
    if not match:
        return False
    try:
        value = float(match.group("value"))
    except ValueError:
        return False
    lower, upper = FIELD_VALUE_RANGES[field]
    return lower <= value <= upper


def _first_plausible_raw_candidate(field: str, raw_candidates: list[Any]) -> Any | None:
    for raw_candidate in raw_candidates:
        if _raw_value_in_field_range(field, raw_candidate):
            return raw_candidate
    return None


def _read_ocr_lines(path_value: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path_value:
        return [], {}
    path = Path(str(path_value))
    if not path.exists():
        return [], {}
    try:
        payload = _read_json(path)
    except Exception:
        return [], {}
    lines = payload.get("lines")
    if not isinstance(lines, list):
        return [], payload
    return [line for line in lines if isinstance(line, dict)], payload


def _numeric_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [line for line in lines if _line_numeric(line) is not None]


def _distance_sq(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _find_field_label_line(lines: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
    matches = [line for line in lines if _best_field_for_label_line(str(line.get("text") or "")) == field]
    if not matches:
        return None
    return max(matches, key=lambda line: float(line.get("confidence") or 0.0))


def _vector_between(source: dict[str, Any], target: dict[str, Any]) -> tuple[float, float]:
    source_center = _field_center(source)
    target_center = _field_center(target)
    return target_center[0] - source_center[0], target_center[1] - source_center[1]


def _infer_trackman_ocr_selection_calibration(reviewed_dir: Path | str | None) -> dict[str, Any] | None:
    if reviewed_dir is None:
        return None
    reviewed_dir = Path(reviewed_dir)
    if not reviewed_dir.exists():
        return None
    for review_path in sorted(reviewed_dir.glob("*.trackman_review.json")):
        try:
            review = _read_json(review_path)
        except Exception:
            continue
        if review.get("reviewStatus") != "accepted" or review.get("metricsUsable") is not True:
            continue
        corrected_fields = review.get("correctedFields")
        if not isinstance(corrected_fields, dict):
            continue
        lines, ocr_payload = _read_ocr_lines(review.get("sourceOcrPath"))
        values = _numeric_lines(lines)
        if not values:
            continue

        anchors: dict[str, dict[str, Any]] = {}
        offsets: dict[str, dict[str, Any]] = {}
        used_line_ids: set[int] = set()
        for field in FIELD_ORDER:
            corrected = corrected_fields.get(field)
            if not isinstance(corrected, dict) or corrected.get("normalizedValue") is None:
                continue
            try:
                target = float(corrected.get("normalizedValue"))
            except (TypeError, ValueError):
                continue
            direction = corrected.get("direction") if field in DIRECTIONAL_FIELDS else None
            matches: list[dict[str, Any]] = []
            for line in values:
                if id(line) in used_line_ids:
                    continue
                numeric = _line_numeric(line)
                if numeric is None or abs(numeric - target) > 0.051:
                    continue
                parsed = _parse_candidate_value(_line_value(line), str(FIELD_META[field]["normalizedUnit"]))
                if direction and parsed.get("direction") != direction:
                    continue
                matches.append(line)
            if not matches:
                continue
            line = max(matches, key=lambda item: float(item.get("confidence") or 0.0))
            used_line_ids.add(id(line))
            center = _field_center(line)
            label = _find_field_label_line(lines, field)
            anchors[field] = {
                "x": center[0],
                "y": center[1],
                "sourceRawCandidate": _line_value(line),
                "normalizedUnit": str(FIELD_META[field]["normalizedUnit"]),
            }
            if label is not None:
                dx, dy = _vector_between(label, line)
                offsets[field] = {
                    "dx": dx,
                    "dy": dy,
                    "sourceRawCandidate": _line_value(line),
                    "normalizedUnit": str(FIELD_META[field]["normalizedUnit"]),
                }
        if anchors:
            return {
                "version": "1.0",
                "sourceSampleId": review.get("sampleId"),
                "sourceReviewPath": str(review_path),
                "sourceOcrPath": str(review.get("sourceOcrPath") or ""),
                "imageSize": ocr_payload.get("imageSize") if isinstance(ocr_payload.get("imageSize"), dict) else None,
                "anchors": anchors,
                "offsetsFromLabel": offsets,
            }
    return None


def _calibrated_candidate_for_field(
    candidate: dict[str, Any],
    field: str,
    calibration: dict[str, Any] | None,
) -> str | None:
    if not calibration:
        return None
    lines, _ = _read_ocr_lines(candidate.get("sourceOcrPath"))
    values = _numeric_lines(lines)
    if not values:
        return None
    offsets = calibration.get("offsetsFromLabel")
    if isinstance(offsets, dict) and field in offsets:
        label = _find_field_label_line(lines, field)
        offset = offsets.get(field)
        if label is not None and isinstance(offset, dict):
            try:
                label_center = _field_center(label)
                target = (label_center[0] + float(offset["dx"]), label_center[1] + float(offset["dy"]))
                best_line = min(values, key=lambda line: _distance_sq(_field_center(line), target))
                return _line_value(best_line)
            except (KeyError, TypeError, ValueError):
                pass
        if label is not None:
            label_center = _field_center(label)
            same_direction_values: list[tuple[float, dict[str, Any]]] = []
            for line in values:
                center = _field_center(line)
                dx = center[0] - label_center[0]
                dy = center[1] - label_center[1]
                distance = max(abs(dx), abs(dy))
                if distance <= 0:
                    continue
                same_direction_values.append((distance, line))
            if same_direction_values:
                return _line_value(min(same_direction_values, key=lambda item: item[0])[1])

    anchors = calibration.get("anchors")
    if not isinstance(anchors, dict) or field not in anchors:
        return None
    anchor = anchors[field]
    try:
        anchor_point = (float(anchor["x"]), float(anchor["y"]))
    except (KeyError, TypeError, ValueError):
        return None
    best_line = min(values, key=lambda line: _distance_sq(_field_center(line), anchor_point))
    return _line_value(best_line)


def build_trackman_review_template(
    candidate: dict[str, Any],
    *,
    ocr_selection_calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_fields = candidate.get("candidateFields") if isinstance(candidate.get("candidateFields"), dict) else {}
    field_order = candidate.get("fieldOrder") if isinstance(candidate.get("fieldOrder"), list) else FIELD_ORDER
    corrected_fields: dict[str, Any] = {}
    for key in field_order:
        meta = FIELD_META.get(str(key), {})
        field = candidate_fields.get(key) if isinstance(candidate_fields.get(key), dict) else {}
        unit = str(field.get("normalizedUnit") or meta.get("normalizedUnit") or "")
        raw_candidates = field.get("rawCandidates") if isinstance(field.get("rawCandidates"), list) else []
        raw_value = _calibrated_candidate_for_field(candidate, str(key), ocr_selection_calibration)
        if raw_value is None or not _raw_value_in_field_range(str(key), raw_value):
            raw_value = _first_plausible_raw_candidate(str(key), raw_candidates)
        if raw_value is None and raw_candidates and str(key) not in FIELD_VALUE_RANGES:
            raw_value = raw_candidates[0]
        corrected_fields[str(key)] = _parse_candidate_value(raw_value, unit)

    template = {
        "version": "1.0",
        "sampleId": candidate.get("sampleId"),
        "shotId": candidate.get("shotId"),
        "trackmanPhoto": candidate.get("trackmanPhoto"),
        "trackmanPhotoPath": candidate.get("trackmanPhotoPath"),
        "sourceCandidatePath": candidate.get("sourceCandidatePath"),
        "sourceOcrPath": candidate.get("sourceOcrPath"),
        "reviewStatus": "needs_review",
        "metricsUsable": False,
        "needsHumanConfirmation": True,
        "fieldOrder": list(field_order),
        "candidateFields": deepcopy(candidate_fields),
        "correctedFields": corrected_fields,
        "reviewInstructions": (
            "Edit correctedFields from the TrackMan image, then set reviewStatus to accepted, "
            "metricsUsable to true, and reviewer to your name. OCR candidates are never used as truth automatically."
        ),
    }
    if ocr_selection_calibration:
        template["ocrSelectionCalibration"] = {
            "version": ocr_selection_calibration.get("version"),
            "sourceSampleId": ocr_selection_calibration.get("sourceSampleId"),
            "sourceReviewPath": ocr_selection_calibration.get("sourceReviewPath"),
        }
    return template


def _existing_review_is_accepted(path: Path) -> bool:
    try:
        existing = _read_json(path)
    except Exception:
        return False
    return existing.get("metricsUsable") is True or existing.get("reviewStatus") == "accepted"


def export_trackman_review_templates(
    *,
    candidates_dir: Path | str,
    output_dir: Path | str,
    calibration_reviewed_dir: Path | str | None = None,
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    candidates_dir = Path(candidates_dir)
    output_dir = Path(output_dir)
    if not candidates_dir.exists() or not candidates_dir.is_dir():
        raise ValueError(f"candidates_dir does not exist or is not a directory: {candidates_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    skipped_existing: list[str] = []
    skipped_accepted: list[str] = []
    calibration = _infer_trackman_ocr_selection_calibration(calibration_reviewed_dir)
    for candidate_path in sorted(candidates_dir.glob("*.trackman_review.json")):
        candidate = _read_json(candidate_path)
        candidate["sourceCandidatePath"] = str(candidate_path)
        output_path = output_dir / candidate_path.name
        if output_path.exists():
            if _existing_review_is_accepted(output_path):
                skipped_accepted.append(str(output_path))
                continue
            if not overwrite_existing:
                skipped_existing.append(str(output_path))
                continue
        template = build_trackman_review_template(candidate, ocr_selection_calibration=calibration)
        _write_json(output_path, template)
        written.append(str(output_path))

    return {
        "version": "1.0",
        "candidatesDir": str(candidates_dir),
        "outputDir": str(output_dir),
        "candidateCount": len(list(candidates_dir.glob("*.trackman_review.json"))),
        "writtenCount": len(written),
        "skippedExistingCount": len(skipped_existing),
        "skippedAcceptedCount": len(skipped_accepted),
        "written": written,
        "skippedExisting": skipped_existing,
        "skippedAccepted": skipped_accepted,
        "calibration": calibration,
    }


def _field_error(corrected_fields: dict[str, Any], field: str) -> str | None:
    expected_unit = str(FIELD_META[field]["normalizedUnit"])
    value = corrected_fields.get(field)
    if not isinstance(value, dict):
        return f"{field} missing"
    if value.get("normalizedValue") is None:
        return f"{field} normalizedValue missing"
    if _canonical_unit(value.get("normalizedUnit"), expected_unit) != expected_unit:
        return f"{field} normalizedUnit must be {expected_unit}"
    return None


def validate_reviewed_trackman_metrics(reviewed_dir: Path | str) -> dict[str, Any]:
    reviewed_dir = Path(reviewed_dir)
    if not reviewed_dir.exists() or not reviewed_dir.is_dir():
        raise ValueError(f"reviewed_dir does not exist or is not a directory: {reviewed_dir}")

    def item(
        path: Path,
        sample_id: str,
        status: str,
        *,
        errors: list[str] | None = None,
        missing_fields: list[str] | None = None,
        invalid_fields: list[str] | None = None,
        non_importable_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "path": str(path),
            "sampleId": sample_id,
            "status": status,
            "errors": errors or [],
            "missingFields": missing_fields or [],
            "invalidFields": invalid_fields or [],
            "nonImportableReason": non_importable_reason,
        }

    items: list[dict[str, Any]] = []
    importable_by_sample: dict[str, str] = {}
    required_fields = ("ballSpeed", "launchAngle")
    for path in sorted(reviewed_dir.glob("*.trackman_review.json")):
        try:
            reviewed = _read_json(path)
        except Exception as exc:
            items.append(item(path, path.stem, "invalid_json", errors=[str(exc)], non_importable_reason="invalid_json"))
            continue
        sample_id = str(reviewed.get("sampleId") or path.name[: -len(".trackman_review.json")])
        corrected_fields = reviewed.get("correctedFields") if isinstance(reviewed.get("correctedFields"), dict) else {}
        review_status = reviewed.get("reviewStatus")
        if review_status != "accepted":
            reason = "review_rejected" if review_status == "rejected" else "review_not_accepted"
            items.append(item(path, sample_id, "not_accepted", non_importable_reason=reason))
            continue
        if reviewed.get("metricsUsable") is not True:
            items.append(item(path, sample_id, "not_accepted", non_importable_reason="metrics_not_usable"))
            continue

        errors: list[str] = []
        missing_fields: list[str] = []
        invalid_fields: list[str] = []
        for field in required_fields:
            value = corrected_fields.get(field)
            if not isinstance(value, dict) or value.get("normalizedValue") is None:
                missing_fields.append(field)
            elif _field_error(corrected_fields, field) is not None:
                invalid_fields.append(field)
        errors.extend(f"{field} missing" for field in missing_fields)
        errors.extend(f"{field} invalid" for field in invalid_fields)
        if missing_fields:
            items.append(
                item(
                    path,
                    sample_id,
                    "missing_required_fields",
                    errors=errors,
                    missing_fields=missing_fields,
                    invalid_fields=invalid_fields,
                    non_importable_reason="missing_required_fields",
                )
            )
            continue
        if invalid_fields:
            items.append(
                item(
                    path,
                    sample_id,
                    "invalid_fields",
                    errors=errors,
                    invalid_fields=invalid_fields,
                    non_importable_reason="invalid_fields",
                )
            )
            continue
        items.append(item(path, sample_id, "importable"))
        importable_by_sample[sample_id] = str(path)

    return {
        "version": "1.0",
        "reviewedDir": str(reviewed_dir),
        "reviewedCount": len(items),
        "importableCount": len(importable_by_sample),
        "importableBySample": importable_by_sample,
        "items": items,
    }
