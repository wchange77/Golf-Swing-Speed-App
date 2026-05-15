"""生成 TrackNet 球心自动标注候选数据集。

默认只写到新的 output-dir，不修改 iPhone 导出目录、registry 或原始 sidecar。
输出分两层：
- ball_observations.json：逐帧 Top-K 候选、被选轨迹、需复核原因。
- tracknet_labels.csv：仅包含高置信自动确认帧；低置信帧不会污染训练标签。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from lib.registry import read_jsonl
from lib.trackman_alignment import (
    align_shots_and_photos,
    build_shot_groups,
    iso_z,
    load_trackman_photos,
    make_timezone,
    write_json,
)


@dataclass
class BallCandidate:
    frame_index: int
    x: float
    y: float
    radius_px: float
    area: float
    score: float
    source: str
    excluded: bool = False
    exclusion_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload = {
            "frameIndex": self.frame_index,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "radiusPx": round(self.radius_px, 3),
            "area": round(self.area, 3),
            "score": round(self.score, 6),
            "source": self.source,
            "excluded": self.excluded,
        }
        if self.exclusion_reason:
            payload["exclusionReason"] = self.exclusion_reason
        return payload


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_export_path(export_dir: Path, rel: str | None) -> Path | None:
    if not rel:
        return None
    candidates = [export_dir / rel]
    if rel.startswith("ios_export/"):
        candidates.insert(0, export_dir / rel.removeprefix("ios_export/"))
    candidates.append(export_dir / Path(rel).name)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def pick_ball_sample(samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    for sample in samples:
        if sample.get("domain") == "golf_ball_detection":
            return sample
    return samples[0] if samples else None


def load_sidecars(export_dir: Path, sample: dict[str, Any]) -> dict[str, Any]:
    sidecars = (sample.get("metadata") or {}).get("sidecars") or {}
    resolved = {name: resolve_export_path(export_dir, rel) for name, rel in sidecars.items()}
    return {
        "paths": {name: str(path) for name, path in resolved.items() if path is not None},
        "labelCandidates": load_json(resolved.get("labelCandidates")),
        "timeline": load_json(resolved.get("timeline")),
        "quality": load_json(resolved.get("quality")),
        "camera": load_json(resolved.get("camera")),
        "audio": load_json(resolved.get("audio")),
    }


def impact_from_sidecars(sample: dict[str, Any], sidecars: dict[str, Any], fps: float) -> tuple[int, float, str, float]:
    label_candidates = sidecars.get("labelCandidates") or {}
    window = label_candidates.get("swingWindow") if isinstance(label_candidates, dict) else None
    if isinstance(window, dict) and window.get("impactTimeSeconds") is not None:
        impact_time = float(window["impactTimeSeconds"])
        confidence = float(window.get("confidence", 0.4))
        return max(0, int(round(impact_time * fps))), impact_time, str(window.get("source", "label_candidates")), confidence

    ball_candidates = label_candidates.get("ballCandidates") if isinstance(label_candidates, dict) else None
    if isinstance(ball_candidates, list) and ball_candidates:
        frames = [int(row["frameIndex"]) for row in ball_candidates if isinstance(row.get("frameIndex"), int)]
        if frames:
            frame = int(round(sum(frames) / len(frames)))
            return frame, frame / fps, "ball_candidates_average", 0.3

    metadata = sample.get("metadata") or {}
    duration = float(metadata.get("durationSeconds") or 0.0)
    frame_count = int(metadata.get("frameCount") or 0)
    if duration > 0:
        impact_time = duration * 0.65
        return int(round(impact_time * fps)), impact_time, "duration_ratio_fallback", 0.15
    if frame_count > 0:
        frame = int(round(frame_count * 0.65))
        return frame, frame / fps, "frame_count_ratio_fallback", 0.15
    return 0, 0.0, "unknown", 0.0


def open_video(path: Path) -> tuple[cv2.VideoCapture, float, int, int, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if fps <= 0 or total <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError(f"invalid video metadata: {path}")
    return cap, fps, total, width, height


def read_gray(cap: cv2.VideoCapture, frame_index: int) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
    ok, frame = cap.read()
    if not ok:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def build_background(cap: cv2.VideoCapture, frame_indices: list[int]) -> np.ndarray | None:
    frames: list[np.ndarray] = []
    for idx in frame_indices:
        gray = read_gray(cap, idx)
        if gray is not None:
            frames.append(gray)
    if not frames:
        return None
    return np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)


def threshold_motion(diff: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(diff, (5, 5), 0)
    mean = float(np.mean(blur))
    std = float(np.std(blur))
    threshold = max(18.0, mean + 2.2 * std)
    _, binary = cv2.threshold(blur, threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def detect_candidates(
    *,
    frame_index: int,
    gray: np.ndarray,
    prev_gray: np.ndarray | None,
    background: np.ndarray,
    max_ball_area: float,
    max_candidates: int,
) -> tuple[list[BallCandidate], list[dict[str, Any]]]:
    bg_diff = cv2.absdiff(gray, background)
    if prev_gray is not None:
        prev_diff = cv2.absdiff(gray, prev_gray)
        diff = cv2.max(bg_diff, prev_diff)
    else:
        diff = bg_diff
    binary = threshold_motion(diff)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[BallCandidate] = []
    exclusion_zones: list[dict[str, Any]] = []
    h, w = gray.shape[:2]
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area <= 0:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        if area > max_ball_area:
            exclusion_zones.append({
                "x": int(x),
                "y": int(y),
                "width": int(bw),
                "height": int(bh),
                "area": round(area, 3),
                "reason": "large_high_motion_object",
            })
            continue
        if area < 2.0 or bw < 2 or bh < 2:
            continue
        aspect = max(bw / max(bh, 1), bh / max(bw, 1))
        if aspect > 5.0:
            continue
        cx = x + bw / 2.0
        cy = y + bh / 2.0
        if cx < 2 or cy < 2 or cx > w - 2 or cy > h - 2:
            continue
        radius = max(bw, bh) / 2.0
        patch = diff[y : y + bh, x : x + bw]
        motion_score = min(float(np.mean(patch)) / 80.0, 1.5) if patch.size else 0.0
        size_score = 1.0 - min(area / max(max_ball_area, 1.0), 1.0)
        round_score = min(1.0 / aspect, 1.0)
        score = max(0.0, 0.45 * motion_score + 0.35 * size_score + 0.20 * round_score)
        candidates.append(
            BallCandidate(
                frame_index=frame_index,
                x=cx,
                y=cy,
                radius_px=radius,
                area=area,
                score=score,
                source="motion_blob",
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:max_candidates], exclusion_zones


def infer_origin(selected: list[BallCandidate], impact_frame: int) -> dict[str, Any] | None:
    early = [c for c in selected if impact_frame < c.frame_index <= impact_frame + 12]
    if not early:
        return None
    first = early[0]
    return {
        "frameIndex": first.frame_index,
        "x": round(first.x, 3),
        "y": round(first.y, 3),
        "source": "first_selected_launch_candidate",
        "confidence": round(first.score, 6),
    }


def select_track(
    candidates_by_frame: dict[int, list[BallCandidate]],
    *,
    fps: float,
    max_link_px_per_frame: float,
) -> list[BallCandidate]:
    frames = sorted(frame for frame, candidates in candidates_by_frame.items() if candidates)
    if not frames:
        return []

    states: dict[tuple[int, int], tuple[float, tuple[int, int] | None]] = {}
    for cand_idx, candidate in enumerate(candidates_by_frame[frames[0]]):
        states[(frames[0], cand_idx)] = (candidate.score, None)

    for prev_frame, frame in zip(frames, frames[1:]):
        gap = max(frame - prev_frame, 1)
        max_link = max_link_px_per_frame * gap
        for cand_idx, candidate in enumerate(candidates_by_frame[frame]):
            best_score = candidate.score - 0.08 * (gap - 1)
            best_parent: tuple[int, int] | None = None
            for prev_idx, prev_candidate in enumerate(candidates_by_frame[prev_frame]):
                prev_state = states.get((prev_frame, prev_idx))
                if prev_state is None:
                    continue
                dist = math.hypot(candidate.x - prev_candidate.x, candidate.y - prev_candidate.y)
                if dist > max_link:
                    continue
                continuity = 1.0 - min(dist / max_link, 1.0)
                # 球从静止点起飞后应持续远离，不鼓励突然反向回跳。
                transition_score = prev_state[0] + candidate.score + 0.25 * continuity
                if best_parent is None or transition_score > best_score:
                    best_score = transition_score
                    best_parent = (prev_frame, prev_idx)
            states[(frame, cand_idx)] = (best_score, best_parent)

    best_key: tuple[int, int] | None = None
    best_value = -1e9
    for key, value in states.items():
        if value[0] > best_value:
            best_key = key
            best_value = value[0]
    if best_key is None:
        return []

    track: list[BallCandidate] = []
    key: tuple[int, int] | None = best_key
    while key is not None:
        frame, cand_idx = key
        track.append(candidates_by_frame[frame][cand_idx])
        key = states[key][1]
    track.reverse()
    return track


def confirm_track(track: list[BallCandidate], *, min_confirmed_run: int, score_threshold: float) -> dict[int, bool]:
    confirmed: dict[int, bool] = {candidate.frame_index: False for candidate in track}
    if len(track) < min_confirmed_run:
        return confirmed

    high = [candidate for candidate in track if candidate.score >= score_threshold]
    if len(high) < min_confirmed_run:
        return confirmed

    for candidate in track:
        confirmed[candidate.frame_index] = candidate.score >= score_threshold
    return confirmed


def analyze_sample(
    *,
    export_dir: Path,
    sample: dict[str, Any],
    match_summary: dict[str, Any],
    output_dir: Path,
    pre_impact_frames: int,
    launch_frames: int,
    review_frames: int,
    max_candidates: int,
    max_ball_area: float,
    min_confirmed_run: int,
    score_threshold: float,
    dry_run: bool,
) -> dict[str, Any]:
    asset_path = resolve_export_path(export_dir, sample.get("assetPath"))
    if asset_path is None:
        return {"sampleId": sample.get("sampleId"), "status": "error", "reason": "asset_not_found"}

    sidecars = load_sidecars(export_dir, sample)
    cap, fps, total_frames, width, height = open_video(asset_path)
    try:
        impact_frame, impact_time, impact_source, impact_confidence = impact_from_sidecars(sample, sidecars, fps)
        impact_frame = min(max(impact_frame, 0), max(total_frames - 1, 0))
        bg_start = max(impact_frame - pre_impact_frames, 0)
        bg_end = max(impact_frame - 4, bg_start)
        bg_indices = list(range(bg_start, bg_end, max(int(round(fps / 60.0)), 1))) or [max(impact_frame - 1, 0)]
        background = build_background(cap, bg_indices)
        if background is None:
            return {"sampleId": sample.get("sampleId"), "status": "error", "reason": "background_build_failed"}

        start = min(impact_frame + 1, total_frames - 1)
        end = min(impact_frame + max(launch_frames, review_frames), total_frames - 1)
        prev_gray = read_gray(cap, max(impact_frame - 1, 0))
        candidates_by_frame: dict[int, list[BallCandidate]] = {}
        exclusion_by_frame: dict[int, list[dict[str, Any]]] = {}
        for frame_idx in range(start, end + 1):
            gray = read_gray(cap, frame_idx)
            if gray is None:
                continue
            candidates, exclusions = detect_candidates(
                frame_index=frame_idx,
                gray=gray,
                prev_gray=prev_gray,
                background=background,
                max_ball_area=max_ball_area,
                max_candidates=max_candidates,
            )
            candidates_by_frame[frame_idx] = candidates
            exclusion_by_frame[frame_idx] = exclusions
            prev_gray = gray

        track = select_track(candidates_by_frame, fps=fps, max_link_px_per_frame=max(width, height) * 0.04)
        confirmed = confirm_track(track, min_confirmed_run=min_confirmed_run, score_threshold=score_threshold)
        selected_by_frame = {candidate.frame_index: candidate for candidate in track}
        confirmed_count = sum(1 for value in confirmed.values() if value)
        needs_review = confirmed_count < min_confirmed_run
        tracknet_rows = []
        for candidate in track:
            is_confirmed = confirmed.get(candidate.frame_index, False)
            tracknet_rows.append({
                "frame_index": candidate.frame_index,
                "x": round(candidate.x, 3),
                "y": round(candidate.y, 3),
                "visible": 1 if is_confirmed else "",
                "confidence": round(candidate.score, 6),
                "label_source": "auto_motion_prior" if is_confirmed else "auto_candidate_needs_review",
                "needs_review": not is_confirmed,
            })

        relative_sample_dir = Path(str(sample.get("sessionId", "unknown"))) / str(sample.get("shotId") or sample.get("sampleId"))
        sample_out_dir = output_dir / "samples" / relative_sample_dir
        observations_path = sample_out_dir / "ball_observations.json"
        labels_path = sample_out_dir / "tracknet_labels.csv"
        review_path = sample_out_dir / "review_required.json"
        observations = {
            "version": "1.0",
            "generatedAt": utc_now_iso(),
            "nonDestructive": True,
            "sample": {
                "sampleId": sample.get("sampleId"),
                "sessionId": sample.get("sessionId"),
                "shotId": sample.get("shotId"),
                "domain": sample.get("domain"),
                "assetPath": sample.get("assetPath"),
            },
            "video": {"fps": round(fps, 6), "frameCount": total_frames, "width": width, "height": height},
            "trackmanMatch": match_summary,
            "impact": {
                "frameIndex": impact_frame,
                "timeSeconds": round(impact_time, 6),
                "source": impact_source,
                "confidence": round(impact_confidence, 6),
            },
            "priors": {
                "backgroundFrameRange": [bg_start, bg_end],
                "preImpactFrames": pre_impact_frames,
                "launchFrames": launch_frames,
                "reviewFrames": review_frames,
                "maxBallAreaPx": max_ball_area,
                "largeMotionObjectsAreExcluded": True,
            },
            "ballOrigin": infer_origin(track, impact_frame),
            "frames": [],
            "summary": {
                "framesProcessed": len(candidates_by_frame),
                "framesWithCandidates": sum(1 for items in candidates_by_frame.values() if items),
                "selectedTrackLength": len(track),
                "autoConfirmedFrames": confirmed_count,
                "needsReview": needs_review,
            },
        }
        for frame_idx in sorted(candidates_by_frame):
            selected = selected_by_frame.get(frame_idx)
            is_confirmed = bool(selected and confirmed.get(frame_idx, False))
            observations["frames"].append({
                "frameIndex": frame_idx,
                "timeSeconds": round(frame_idx / fps, 6),
                "candidates": [candidate.to_json() for candidate in candidates_by_frame[frame_idx]],
                "exclusionZones": exclusion_by_frame.get(frame_idx, []),
                "selected": selected.to_json() if selected else None,
                "autoConfirmed": is_confirmed,
                "needsReview": not is_confirmed,
            })

        report = {
            "sampleId": sample.get("sampleId"),
            "sessionId": sample.get("sessionId"),
            "shotId": sample.get("shotId"),
            "status": "ok",
            "observationsPath": str(observations_path.relative_to(output_dir)),
            "labelsPath": str(labels_path.relative_to(output_dir)),
            "reviewPath": str(review_path.relative_to(output_dir)) if needs_review else None,
            **observations["summary"],
        }

        if not dry_run:
            sample_out_dir.mkdir(parents=True, exist_ok=True)
            write_json(observations_path, observations)
            with labels_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["frame_index", "x", "y", "visible", "confidence", "label_source", "needs_review"],
                )
                writer.writeheader()
                for row in tracknet_rows:
                    writer.writerow(row)
            if needs_review:
                write_json(review_path, {
                    "sampleId": sample.get("sampleId"),
                    "reason": "insufficient_high_confidence_continuous_track",
                    "minConfirmedRun": min_confirmed_run,
                    "autoConfirmedFrames": confirmed_count,
                    "selectedTrackLength": len(track),
                })
        return report
    finally:
        cap.release()


def build_alignment(export_dir: Path, *, timezone_offset_hours: float, threshold_seconds: float, skip_ocr: bool) -> Any:
    sessions = read_jsonl(export_dir / "sessions.jsonl")
    samples = read_jsonl(export_dir / "samples.jsonl")
    local_tz = make_timezone(timezone_offset_hours)
    shots = build_shot_groups(samples, sessions, local_timezone=local_tz)
    photos = load_trackman_photos(
        export_dir / "trackman.zip",
        timezone_offset_hours=timezone_offset_hours,
        run_ocr=not skip_ocr,
    )
    return align_shots_and_photos(shots, photos, threshold_seconds=threshold_seconds, local_timezone=local_tz)


def write_summary_md(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# TrackNet 自动标注候选生成报告",
        "",
        "## 结论",
        "",
        f"- 匹配 TrackMan 击球数：{payload['alignmentSummary']['matchedShots']}",
        f"- 已处理样本数：{payload['summary']['processedSamples']}",
        f"- 自动确认帧数：{payload['summary']['autoConfirmedFrames']}",
        f"- 需复核样本数：{payload['summary']['reviewSamples']}",
        "",
        "## 依据",
        "",
        "- 只读取 iPhone 导出目录与 TrackMan zip，不写回原始 sidecar。",
        "- 候选检测使用 impact 前背景、逐帧运动差分、小面积 blob 过滤和连续轨迹选择。",
        "- 大面积高速目标会记录为 exclusionZones，避免把手臂、杆身、杆头区域直接当球。",
        "",
        "## 风险",
        "",
        "- 当前仍是高精度低召回策略，低置信帧必须人工复核后才能进入训练集。",
        "- TrackMan 提供物理先验和时间配准，不提供像素级球心真值。",
        "",
        "## 下一步",
        "",
        "1. 人工复核 `review_required.json` 中的样本。",
        "2. 将 `tracknet_labels.csv` 中 `visible=1` 的帧转换为 Gaussian heatmap。",
        "3. 累积人工确认标签后训练 TrackNetV5，并回灌更高质量候选。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 iPhone 视频 + TrackMan 时间配准生成 TrackNet 球心候选标注")
    parser.add_argument("--export-dir", default="DatasetCollectorExport")
    parser.add_argument("--output-dir", default="exports/tracknet_autolabel_priors")
    parser.add_argument("--photo-timezone-offset-hours", type=float, default=8.0)
    parser.add_argument("--threshold-seconds", type=float, default=30.0)
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--start-index", type=int, default=0, help="从已匹配 shot 的第几个开始处理，便于分批续跑")
    parser.add_argument("--max-shots", type=int, default=20)
    parser.add_argument("--pre-impact-frames", type=int, default=36)
    parser.add_argument("--launch-frames", type=int, default=90)
    parser.add_argument("--review-frames", type=int, default=150)
    parser.add_argument("--max-candidates", type=int, default=5)
    parser.add_argument("--max-ball-area", type=float, default=180.0)
    parser.add_argument("--min-confirmed-run", type=int, default=8)
    parser.add_argument("--score-threshold", type=float, default=0.78)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="逐样本输出进度到 stderr")
    args = parser.parse_args(argv)

    export_dir = Path(args.export_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not export_dir.exists():
        raise FileNotFoundError(f"export dir not found: {export_dir}")
    if not (export_dir / "trackman.zip").exists():
        raise FileNotFoundError(f"trackman.zip not found: {export_dir / 'trackman.zip'}")

    alignment = build_alignment(
        export_dir,
        timezone_offset_hours=args.photo_timezone_offset_hours,
        threshold_seconds=args.threshold_seconds,
        skip_ocr=args.skip_ocr,
    )

    reports: list[dict[str, Any]] = []
    start_index = max(args.start_index, 0)
    selected_matches = alignment.matches[start_index : start_index + max(args.max_shots, 0)]
    for offset, match in enumerate(selected_matches, start=1):
        sample = pick_ball_sample(match.shot.sample_records)
        if sample is None:
            reports.append({"status": "skipped", "reason": "no_sample", "shotId": match.shot.shot_id})
            continue
        if args.verbose:
            import sys

            absolute_index = start_index + offset
            print(
                f"[{offset}/{len(selected_matches)} absolute={absolute_index}] "
                f"sample={sample.get('sampleId')} shot={sample.get('shotId')}",
                file=sys.stderr,
                flush=True,
            )
        try:
            reports.append(
                analyze_sample(
                    export_dir=export_dir,
                    sample=sample,
                    match_summary=match.to_summary(),
                    output_dir=output_dir,
                    pre_impact_frames=args.pre_impact_frames,
                    launch_frames=args.launch_frames,
                    review_frames=args.review_frames,
                    max_candidates=args.max_candidates,
                    max_ball_area=args.max_ball_area,
                    min_confirmed_run=args.min_confirmed_run,
                    score_threshold=args.score_threshold,
                    dry_run=args.dry_run,
                )
            )
        except Exception as exc:
            reports.append({
                "status": "error",
                "sampleId": sample.get("sampleId"),
                "shotId": sample.get("shotId"),
                "reason": str(exc),
            })

    summary = {
        "processedSamples": sum(1 for item in reports if item.get("status") == "ok"),
        "errorSamples": sum(1 for item in reports if item.get("status") == "error"),
        "reviewSamples": sum(1 for item in reports if item.get("needsReview")),
        "autoConfirmedFrames": sum(int(item.get("autoConfirmedFrames", 0)) for item in reports),
    }
    payload = {
        "version": "1.0",
        "generatedAt": utc_now_iso(),
        "nonDestructive": True,
        "sourceExportDir": str(export_dir),
        "outputDir": str(output_dir),
        "dryRun": args.dry_run,
        "startIndex": start_index,
        "maxShots": args.max_shots,
        "alignmentSummary": alignment.summary(),
        "summary": summary,
        "samples": reports,
        "unmatchedShots": [shot.to_summary() for shot in alignment.unmatched_shots],
        "unmatchedPhotos": [photo.to_summary() for photo in alignment.unmatched_photos],
    }

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "alignment_summary.json", payload)
        write_summary_md(output_dir / "alignment_summary.md", payload)

    print(json.dumps({
        "outputDir": str(output_dir),
        "dryRun": args.dry_run,
        "alignmentSummary": alignment.summary(),
        "summary": summary,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
