from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from PIL.ExifTags import TAGS

try:
    import pytesseract
    from pytesseract import Output
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None
    Output = None

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover - optional dependency
    RapidOCR = None

try:
    from paddleocr import PaddleOCR
except Exception:  # pragma: no cover - optional dependency
    PaddleOCR = None


TRACKMAN_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
FILENAME_TIME_RE = re.compile(r"IMG_(\d{8})_(\d{6})", re.IGNORECASE)
OCR_ENGINES = {"auto", "paddleocr", "rapidocr", "pytesseract"}


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def format_local_datetime(value: datetime) -> str:
    return value.isoformat()


def make_timezone(offset_hours: float) -> timezone:
    minutes = int(round(offset_hours * 60))
    return timezone(timedelta(minutes=minutes))


def _extract_exif_datetime(image: Image.Image) -> str | None:
    exif = image.getexif()
    if not exif:
        return None
    tags = {TAGS.get(key, key): value for key, value in exif.items()}
    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        raw = tags.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _parse_local_time_from_name(name: str) -> datetime | None:
    match = FILENAME_TIME_RE.search(Path(name).name)
    if not match:
        return None
    return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")


def _local_datetime_from_zipinfo(info: zipfile.ZipInfo) -> datetime:
    return datetime(*info.date_time)


def _resolve_local_datetime(
    *,
    archive_name: str,
    info: zipfile.ZipInfo,
    image: Image.Image,
    local_tz: timezone,
) -> tuple[datetime, str]:
    exif_value = _extract_exif_datetime(image)
    if exif_value:
        try:
            return datetime.strptime(exif_value, "%Y:%m:%d %H:%M:%S").replace(tzinfo=local_tz), "exif"
        except ValueError:
            pass

    name_dt = _parse_local_time_from_name(archive_name)
    if name_dt is not None:
        return name_dt.replace(tzinfo=local_tz), "filename"

    return _local_datetime_from_zipinfo(info).replace(tzinfo=local_tz), "zipinfo"


_RAPID_OCR_ENGINE = None
_PADDLE_OCR_ENGINE = None


def _normalize_paddleocr_result(result: Any) -> list[Any]:
    if not result:
        return []
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], list) and result[0]:
        first = result[0]
        if isinstance(first[0], (list, tuple)) and len(first[0]) == 2:
            return first
    return result if isinstance(result, list) else []


def _ocr_image_with_paddleocr(image: Image.Image) -> dict[str, Any] | None:
    if PaddleOCR is None:
        return None

    global _PADDLE_OCR_ENGINE
    if _PADDLE_OCR_ENGINE is None:
        _PADDLE_OCR_ENGINE = PaddleOCR(
            lang="en",
            use_angle_cls=True,
            show_log=False,
            use_gpu=False,
            det_limit_side_len=2560,
        )

    try:
        rgb = np.array(image.convert("RGB"))
        result = _PADDLE_OCR_ENGINE.ocr(rgb, cls=True)
    except Exception:
        return None

    entries = _normalize_paddleocr_result(result)
    boxes: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for item in entries:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        points = item[0]
        content = item[1]
        if not isinstance(content, (list, tuple)) or len(content) < 2:
            continue
        text = str(content[0]).strip()
        try:
            confidence = float(content[1])
        except (TypeError, ValueError):
            confidence = -1.0
        if not text:
            continue
        xs = [int(round(point[0])) for point in points]
        ys = [int(round(point[1])) for point in points]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        boxes.append(
            {
                "text": text,
                "confidence": confidence,
                "left": left,
                "top": top,
                "width": right - left,
                "height": bottom - top,
                "right": right,
                "bottom": bottom,
                "points": points,
            }
        )
        text_parts.append(text)

    if not boxes:
        return {
            "status": "error",
            "engine": "paddleocr",
            "reason": "no_text_detected",
            "text": "",
            "lines": [],
            "boxes": [],
        }

    size = image.size
    return {
        "status": "ok",
        "engine": "paddleocr",
        "text": "\n".join(text_parts),
        "lines": boxes,
        "boxes": boxes,
        "imageSize": {"width": size[0], "height": size[1]},
    }


def _ocr_image_with_rapidocr(image: Image.Image) -> dict[str, Any] | None:
    if RapidOCR is None:
        return None

    global _RAPID_OCR_ENGINE
    if _RAPID_OCR_ENGINE is None:
        _RAPID_OCR_ENGINE = RapidOCR()

    try:
        rgb = np.array(image.convert("RGB"))
        result, _ = _RAPID_OCR_ENGINE(rgb)
    except Exception:
        return None

    boxes: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for item in result or []:
        if len(item) < 3:
            continue
        points, text, confidence = item[0], str(item[1]).strip(), float(item[2])
        if not text:
            continue
        xs = [int(round(point[0])) for point in points]
        ys = [int(round(point[1])) for point in points]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        boxes.append(
            {
                "text": text,
                "confidence": confidence,
                "left": left,
                "top": top,
                "width": right - left,
                "height": bottom - top,
                "right": right,
                "bottom": bottom,
                "points": points,
            }
        )
        text_parts.append(text)

    size = image.size
    return {
        "status": "ok",
        "engine": "rapidocr_onnxruntime",
        "text": "\n".join(text_parts),
        "lines": boxes,
        "boxes": boxes,
        "imageSize": {"width": size[0], "height": size[1]},
    }


def _ocr_image_with_tesseract(image: Image.Image) -> dict[str, Any] | None:
    if pytesseract is None or Output is None or shutil.which("tesseract") is None:
        return None

    try:
        data = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 6")
        text = pytesseract.image_to_string(image, config="--psm 6").strip()
        boxes: list[dict[str, Any]] = []
        lines: list[dict[str, Any]] = []
        size = image.size
        for index, raw_text in enumerate(data.get("text", [])):
            text_value = str(raw_text).strip()
            if not text_value:
                continue
            left = int(data["left"][index])
            top = int(data["top"][index])
            width = int(data["width"][index])
            height = int(data["height"][index])
            conf_value = data.get("conf", ["-1"])[index]
            try:
                confidence = float(conf_value)
            except (TypeError, ValueError):
                confidence = -1.0
            box = {
                "text": text_value,
                "confidence": confidence,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "right": left + width,
                "bottom": top + height,
            }
            boxes.append(box)
            lines.append(box)

        return {
            "status": "ok",
            "engine": "pytesseract",
            "text": text,
            "lines": lines,
            "boxes": boxes,
            "imageSize": {"width": size[0], "height": size[1]},
        }
    except Exception as exc:  # pragma: no cover - optional external binary failure
        return {
            "status": "error",
            "engine": "pytesseract",
            "reason": str(exc),
            "text": "",
            "lines": [],
            "boxes": [],
        }


def _ocr_image(image: Image.Image, *, engine: str = "auto") -> dict[str, Any]:
    if engine not in OCR_ENGINES:
        raise ValueError(f"unsupported OCR engine: {engine}")

    if engine != "auto":
        engine_map = {
            "paddleocr": ("paddleocr", _ocr_image_with_paddleocr),
            "rapidocr": ("rapidocr_onnxruntime", _ocr_image_with_rapidocr),
            "pytesseract": ("pytesseract", _ocr_image_with_tesseract),
        }
        engine_name, engine_fn = engine_map[engine]
        result = engine_fn(image)
        if result is not None:
            return result
        attempted = [engine_name]
    else:
        attempted = ["paddleocr", "rapidocr_onnxruntime", "pytesseract"]
        for engine_fn in (_ocr_image_with_paddleocr, _ocr_image_with_rapidocr, _ocr_image_with_tesseract):
            result = engine_fn(image)
            if result is not None:
                return result

    return {
        "status": "unavailable",
        "engine": "none",
        "attemptedEngines": attempted,
        "reason": "no_supported_ocr_backend_available",
        "text": "",
        "lines": [],
        "boxes": [],
    }


@dataclass
class TrackmanPhoto:
    archive_name: str
    local_datetime: datetime
    utc_datetime: datetime
    time_source: str
    image_size: tuple[int, int]
    ocr: dict[str, Any]

    def to_summary(self) -> dict[str, Any]:
        return {
            "archiveName": self.archive_name,
            "capturedAtLocal": format_local_datetime(self.local_datetime),
            "capturedAtUtc": iso_z(self.utc_datetime),
            "timeSource": self.time_source,
            "imageSize": {"width": self.image_size[0], "height": self.image_size[1]},
            "ocr": self.ocr,
        }


@dataclass
class TrackmanShotGroup:
    session_id: str
    session_name: str | None
    shot_id: str
    captured_at_utc: datetime
    captured_at_local: datetime
    sample_records: list[dict[str, Any]]

    def to_summary(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "sessionName": self.session_name,
            "shotId": self.shot_id,
            "capturedAtUtc": iso_z(self.captured_at_utc),
            "capturedAtLocal": format_local_datetime(self.captured_at_local),
            "sampleIds": [row["sampleId"] for row in self.sample_records],
            "domains": [row["domain"] for row in self.sample_records],
        }


@dataclass
class TrackmanMatch:
    shot: TrackmanShotGroup
    photo: TrackmanPhoto
    time_delta_seconds: float
    match_index: int = 0

    def to_summary(self) -> dict[str, Any]:
        payload = self.shot.to_summary()
        payload.update({
            "photo": self.photo.to_summary(),
            "timeDeltaSeconds": round(self.time_delta_seconds, 6),
            "matchIndex": self.match_index,
        })
        return payload


@dataclass
class TrackmanAlignmentResult:
    matches: list[TrackmanMatch]
    unmatched_shots: list[TrackmanShotGroup]
    unmatched_photos: list[TrackmanPhoto]
    threshold_seconds: float
    local_timezone: timezone

    def summary(self) -> dict[str, Any]:
        session_stats: dict[str, dict[str, int]] = {}
        for match in self.matches:
            stats = session_stats.setdefault(match.shot.session_id, {"matched": 0, "shots": 0})
            stats["matched"] += 1
        for shot in self.unmatched_shots:
            stats = session_stats.setdefault(shot.session_id, {"matched": 0, "shots": 0})
            stats["shots"] += 1
        for match in self.matches:
            stats = session_stats.setdefault(match.shot.session_id, {"matched": 0, "shots": 0})
            stats["shots"] += 1

        avg_delta = (
            sum(match.time_delta_seconds for match in self.matches) / len(self.matches)
            if self.matches
            else 0.0
        )
        max_delta = max((match.time_delta_seconds for match in self.matches), default=0.0)
        return {
            "thresholdSeconds": self.threshold_seconds,
            "timezoneOffsetHours": round(self.local_timezone.utcoffset(None).total_seconds() / 3600.0, 4)
            if self.local_timezone.utcoffset(None)
            else 0.0,
            "matchedShots": len(self.matches),
            "unmatchedShots": len(self.unmatched_shots),
            "unmatchedPhotos": len(self.unmatched_photos),
            "averageTimeDeltaSeconds": round(avg_delta, 6),
            "maxTimeDeltaSeconds": round(max_delta, 6),
            "sessions": [
                {"sessionId": session_id, **stats}
                for session_id, stats in sorted(session_stats.items(), key=lambda item: item[0])
            ],
        }


def _better_state(candidate: tuple[int, float, int], current: tuple[int, float, int]) -> bool:
    cand_count, cand_cost, cand_priority = candidate
    curr_count, curr_cost, curr_priority = current
    if cand_count != curr_count:
        return cand_count > curr_count
    if abs(cand_cost - curr_cost) > 1e-9:
        return cand_cost < curr_cost
    return cand_priority > curr_priority


def load_trackman_photos(
    zip_path: Path,
    *,
    timezone_offset_hours: float = 8.0,
    run_ocr: bool = True,
    ocr_engine: str = "auto",
) -> list[TrackmanPhoto]:
    local_tz = make_timezone(timezone_offset_hours)
    photos: list[TrackmanPhoto] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename):
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower()
            if ext not in TRACKMAN_IMAGE_EXTENSIONS:
                continue
            try:
                payload = archive.read(info.filename)
                image = Image.open(BytesIO(payload))
                image.load()
            except Exception:
                continue

            local_dt, source = _resolve_local_datetime(
                archive_name=info.filename,
                info=info,
                image=image,
                local_tz=local_tz,
            )
            ocr = _ocr_image(image, engine=ocr_engine) if run_ocr else {
                "status": "skipped",
                "engine": ocr_engine,
                "reason": "disabled_by_flag",
                "text": "",
                "lines": [],
                "boxes": [],
            }
            photos.append(
                TrackmanPhoto(
                    archive_name=info.filename,
                    local_datetime=local_dt,
                    utc_datetime=local_dt.astimezone(timezone.utc),
                    time_source=source,
                    image_size=image.size,
                    ocr=ocr,
                )
            )

    photos.sort(key=lambda photo: photo.utc_datetime)
    return photos


def build_shot_groups(
    samples: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    *,
    local_timezone: timezone,
) -> list[TrackmanShotGroup]:
    session_name_map = {
        str(session.get("sessionId", "")).strip(): str(session.get("sessionName", "")).strip() or None
        for session in sessions
        if str(session.get("sessionId", "")).strip()
    }
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for sample in samples:
        if sample.get("status") != "active":
            continue
        session_id = str(sample.get("sessionId", "")).strip()
        shot_id = str(sample.get("shotId", "")).strip()
        if not session_id or not shot_id:
            continue
        grouped.setdefault((session_id, shot_id), []).append(sample)

    shot_groups: list[TrackmanShotGroup] = []
    for (session_id, shot_id), rows in grouped.items():
        rows_sorted = sorted(
            rows,
            key=lambda row: (
                parse_iso_datetime(str(row.get("capturedAt", "1970-01-01T00:00:00Z"))),
                str(row.get("domain", "")),
                str(row.get("sampleId", "")),
            ),
        )
        captured_at_utc = parse_iso_datetime(str(rows_sorted[0].get("capturedAt", "1970-01-01T00:00:00Z")))
        shot_groups.append(
            TrackmanShotGroup(
                session_id=session_id,
                session_name=session_name_map.get(session_id),
                shot_id=shot_id,
                captured_at_utc=captured_at_utc,
                captured_at_local=captured_at_utc.astimezone(local_timezone),
                sample_records=rows_sorted,
            )
        )

    shot_groups.sort(key=lambda shot: (shot.captured_at_utc, shot.session_id, shot.shot_id))
    return shot_groups


def align_shots_and_photos(
    shots: list[TrackmanShotGroup],
    photos: list[TrackmanPhoto],
    *,
    threshold_seconds: float,
    local_timezone: timezone,
) -> TrackmanAlignmentResult:
    n = len(shots)
    m = len(photos)
    count = [[0] * (m + 1) for _ in range(n + 1)]
    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    parent = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        parent[i][0] = 1
    for j in range(1, m + 1):
        parent[0][j] = 2

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = (count[i - 1][j], cost[i - 1][j], 1)
            left = (count[i][j - 1], cost[i][j - 1], 2)
            if _better_state(left, best):
                best = left
            delta = abs((shots[i - 1].captured_at_utc - photos[j - 1].utc_datetime).total_seconds())
            if delta <= threshold_seconds:
                diag = (count[i - 1][j - 1] + 1, cost[i - 1][j - 1] + delta, 3)
                if _better_state(diag, best):
                    best = diag
            count[i][j], cost[i][j], parent[i][j] = best

    matches: list[TrackmanMatch] = []
    matched_shot_indices: set[int] = set()
    matched_photo_indices: set[int] = set()
    i, j = n, m
    while i > 0 or j > 0:
        action = parent[i][j]
        if action == 3:
            delta = abs((shots[i - 1].captured_at_utc - photos[j - 1].utc_datetime).total_seconds())
            matches.append(
                TrackmanMatch(
                    shot=shots[i - 1],
                    photo=photos[j - 1],
                    time_delta_seconds=delta,
                )
            )
            matched_shot_indices.add(i - 1)
            matched_photo_indices.add(j - 1)
            i -= 1
            j -= 1
        elif action == 1:
            i -= 1
        elif action == 2:
            j -= 1
        else:
            break

    matches.reverse()
    for index, match in enumerate(matches, start=1):
        match.match_index = index

    unmatched_shots = [shot for idx, shot in enumerate(shots) if idx not in matched_shot_indices]
    unmatched_photos = [photo for idx, photo in enumerate(photos) if idx not in matched_photo_indices]

    return TrackmanAlignmentResult(
        matches=matches,
        unmatched_shots=unmatched_shots,
        unmatched_photos=unmatched_photos,
        threshold_seconds=threshold_seconds,
        local_timezone=local_timezone,
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
