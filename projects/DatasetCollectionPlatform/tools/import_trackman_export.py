from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from lib.registry import read_jsonl
from lib.trackman_alignment import (
    OCR_ENGINES,
    align_shots_and_photos,
    build_shot_groups,
    iso_z,
    load_trackman_photos,
    make_timezone,
    write_json,
)


def _copy_zip_member(zip_path: Path, member_name: str, dst: Path) -> None:
    import zipfile

    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open(member_name) as src, dst.open("wb") as target:
            shutil.copyfileobj(src, target)


def _bundle_dir(output_dir: Path, shot_index: int, shot_id: str, session_id: str) -> Path:
    return output_dir / "collections" / session_id / f"{shot_index:04d}_{shot_id}"


def _photo_output_paths(bundle_dir: Path, archive_name: str) -> tuple[Path, Path]:
    photo_dir = bundle_dir / "trackman"
    photo_path = photo_dir / Path(archive_name).name
    ocr_path = photo_path.with_suffix(".ocr.json")
    return photo_path, ocr_path


def _review_photo_paths(output_dir: Path, archive_name: str) -> tuple[Path, Path]:
    review_dir = output_dir / "review" / "unmatched_photos"
    photo_path = review_dir / Path(archive_name).name
    ocr_path = photo_path.with_suffix(".ocr.json")
    return photo_path, ocr_path


def import_trackman_export(
    export_dir: Path,
    *,
    output_dir: Path,
    timezone_offset_hours: float,
    threshold_seconds: float,
    run_ocr: bool,
    ocr_engine: str,
    dry_run: bool,
) -> dict[str, Any]:
    export_dir = export_dir.resolve()
    trackman_zip = export_dir / "trackman.zip"
    sessions_file = export_dir / "sessions.jsonl"
    samples_file = export_dir / "samples.jsonl"

    if not trackman_zip.exists():
        raise FileNotFoundError(f"trackman.zip not found: {trackman_zip}")
    if not sessions_file.exists():
        raise FileNotFoundError(f"sessions.jsonl not found: {sessions_file}")
    if not samples_file.exists():
        raise FileNotFoundError(f"samples.jsonl not found: {samples_file}")

    sessions = read_jsonl(sessions_file)
    samples = read_jsonl(samples_file)
    local_tz = make_timezone(timezone_offset_hours)

    shots = build_shot_groups(samples, sessions, local_timezone=local_tz)
    photos = load_trackman_photos(
        trackman_zip,
        timezone_offset_hours=timezone_offset_hours,
        run_ocr=run_ocr,
        ocr_engine=ocr_engine,
    )
    result = align_shots_and_photos(
        shots,
        photos,
        threshold_seconds=threshold_seconds,
        local_timezone=local_tz,
    )

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "collections").mkdir(parents=True, exist_ok=True)
        (output_dir / "review" / "unmatched_photos").mkdir(parents=True, exist_ok=True)

        for match in result.matches:
            bundle_dir = _bundle_dir(output_dir, match.match_index, match.shot.shot_id, match.shot.session_id)
            bundle_dir.mkdir(parents=True, exist_ok=True)
            photo_path, ocr_path = _photo_output_paths(bundle_dir, match.photo.archive_name)
            _copy_zip_member(trackman_zip, match.photo.archive_name, photo_path)
            write_json(ocr_path, match.photo.ocr)

            bundle_payload = {
                "bundleId": f"{match.shot.session_id}_{match.shot.shot_id}",
                "matchIndex": match.match_index,
                "sessionId": match.shot.session_id,
                "sessionName": match.shot.session_name,
                "shotId": match.shot.shot_id,
                "capturedAtUtc": iso_z(match.shot.captured_at_utc),
                "capturedAtLocal": match.shot.captured_at_local.isoformat(),
                "match": {
                    "strategy": "time_alignment",
                    "thresholdSeconds": threshold_seconds,
                    "timezoneOffsetHours": timezone_offset_hours,
                    "timeDeltaSeconds": round(match.time_delta_seconds, 6),
                },
                "samples": match.shot.sample_records,
                "trackmanPhotos": [
                    {
                        **match.photo.to_summary(),
                        "relativePath": str(photo_path.relative_to(output_dir).as_posix()),
                        "ocrPath": str(ocr_path.relative_to(output_dir).as_posix()),
                    }
                ],
            }
            write_json(bundle_dir / "bundle.json", bundle_payload)
            write_json(bundle_dir / "sample_records.json", {"samples": match.shot.sample_records})

        review_photos: list[dict[str, Any]] = []
        for photo in result.unmatched_photos:
            photo_path, ocr_path = _review_photo_paths(output_dir, photo.archive_name)
            _copy_zip_member(trackman_zip, photo.archive_name, photo_path)
            write_json(ocr_path, photo.ocr)
            review_photos.append(
                {
                    **photo.to_summary(),
                    "relativePath": str(photo_path.relative_to(output_dir).as_posix()),
                    "ocrPath": str(ocr_path.relative_to(output_dir).as_posix()),
                }
            )

        review_payload = {
            "thresholdSeconds": threshold_seconds,
            "timezoneOffsetHours": timezone_offset_hours,
            "unmatchedShots": [shot.to_summary() for shot in result.unmatched_shots],
            "unmatchedPhotos": review_photos,
        }
        write_json(output_dir / "review" / "review.json", review_payload)

        index_payload = {
            "version": "1.0",
            "generatedAt": None,
            "sourceExportDir": str(export_dir),
            "outputDir": str(output_dir),
            "thresholdSeconds": threshold_seconds,
            "timezoneOffsetHours": timezone_offset_hours,
            "runOcr": run_ocr,
            "ocrEngine": ocr_engine,
            "summary": result.summary(),
            "bundles": [match.to_summary() for match in result.matches],
            "reviewPath": "review/review.json",
        }
        from datetime import datetime, timezone

        index_payload["generatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        write_json(output_dir / "index.json", index_payload)

    return {
        "exportDir": str(export_dir),
        "outputDir": str(output_dir),
        "thresholdSeconds": threshold_seconds,
        "timezoneOffsetHours": timezone_offset_hours,
        "runOcr": run_ocr,
        "ocrEngine": ocr_engine,
        "summary": result.summary(),
        "matchedBundles": len(result.matches),
        "unmatchedShots": len(result.unmatched_shots),
        "unmatchedPhotos": len(result.unmatched_photos),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="将 DatasetCollectorExport 的 TrackMan 照片按时间对齐到样本集合")
    parser.add_argument(
        "--export-dir",
        default="DatasetCollectorExport",
        help="DatasetCollectorExport 目录，默认相对于当前工作目录",
    )
    parser.add_argument(
        "--output-dir",
        default="exports/trackman_alignment",
        help="输出目录，默认写到 exports/trackman_alignment",
    )
    parser.add_argument(
        "--photo-timezone-offset-hours",
        type=float,
        default=8.0,
        help="TrackMan 照片 EXIF 时间按哪个时区解释，默认 Asia/Shanghai(UTC+8)",
    )
    parser.add_argument(
        "--threshold-seconds",
        type=float,
        default=30.0,
        help="照片与样本时间允许的最大匹配偏差",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="跳过 OCR，仅做时间对齐与集合输出",
    )
    parser.add_argument(
        "--ocr-engine",
        choices=sorted(OCR_ENGINES),
        default="auto",
        help="OCR 引擎：auto/paddleocr/rapidocr/pytesseract，默认 auto",
    )
    parser.add_argument("--dry-run", action="store_true", help="只计算结果，不写出文件")
    args = parser.parse_args()

    report = import_trackman_export(
        Path(args.export_dir),
        output_dir=Path(args.output_dir),
        timezone_offset_hours=args.photo_timezone_offset_hours,
        threshold_seconds=args.threshold_seconds,
        run_ocr=not args.skip_ocr,
        ocr_engine=args.ocr_engine,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
