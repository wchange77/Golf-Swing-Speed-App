"""从已注册样本中抽帧。

两种模式:
- uniform: 按固定 fps 均匀抽帧。
- impact_window: 从样本 label_candidates 的击球窗口抽 240fps 全帧，其他时间按 fps 稀疏抽。

产出:
- datasets/raw/{domain}/frames/{sha256}/frame_{idx:06d}.jpg
- datasets/registry/frames_index.jsonl  每行 {sampleId, sha256, domain, frameIndex, timeSeconds, role}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2

from lib.registry import (
    REGISTRY_DIR,
    ROOT,
    append_jsonl,
    ensure_registry_files,
    list_samples,
)

FRAMES_INDEX_FILE = REGISTRY_DIR / "frames_index.jsonl"


def _resolve_video(sample: dict[str, Any]) -> Path:
    asset = sample.get("assetPath") or ""
    if not asset:
        raise FileNotFoundError(f"sample {sample.get('sampleId')} has no assetPath")
    path = (ROOT / asset).resolve()
    if not path.exists():
        raise FileNotFoundError(f"video not found: {path}")
    return path


def _resolve_label_candidates(sample: dict[str, Any]) -> Path | None:
    sidecars = (sample.get("metadata") or {}).get("sidecars") or {}
    rel = sidecars.get("labelCandidates")
    if not rel:
        return None
    path = (ROOT / rel).resolve()
    return path if path.exists() else None


def _load_impact_window(label_candidates: Path | None) -> tuple[float, float] | None:
    if label_candidates is None:
        return None
    data = json.loads(label_candidates.read_text(encoding="utf-8"))
    window = data.get("swingWindow")
    if not isinstance(window, dict):
        return None
    start = window.get("startTimeSeconds")
    end = window.get("endTimeSeconds")
    if start is None or end is None or end <= start:
        return None
    return float(start), float(end)


def _open_video(path: Path) -> tuple[cv2.VideoCapture, float, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0 or total <= 0:
        cap.release()
        raise RuntimeError(f"invalid fps/total for {path}")
    return cap, fps, total


def _pick_indices(total: int, fps: float, mode: str, impact_window: tuple[float, float] | None, sample_fps: float) -> list[tuple[int, str]]:
    step = max(int(round(fps / max(sample_fps, 0.1))), 1)
    uniform_indices = {i: "uniform" for i in range(0, total, step)}
    if mode == "uniform" or impact_window is None:
        return sorted((idx, role) for idx, role in uniform_indices.items())
    start_idx = max(int(impact_window[0] * fps), 0)
    end_idx = min(int(impact_window[1] * fps) + 1, total)
    impact = {i: "impact_window" for i in range(start_idx, end_idx)}
    merged: dict[int, str] = dict(uniform_indices)
    merged.update(impact)
    return sorted(merged.items())


def extract_sample(sample: dict[str, Any], *, mode: str, fps: float, output_root: Path, quality: int) -> dict[str, Any]:
    video_path = _resolve_video(sample)
    impact_window = _load_impact_window(_resolve_label_candidates(sample)) if mode == "impact_window" else None

    domain = sample["domain"]
    sha256 = sample["sha256"]
    out_dir = output_root / "datasets" / "raw" / domain / "frames" / sha256
    out_dir.mkdir(parents=True, exist_ok=True)

    cap, video_fps, total = _open_video(video_path)
    try:
        indices = _pick_indices(total, video_fps, mode, impact_window, fps)
        written = 0
        for frame_idx, role in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok:
                continue
            filename = f"frame_{frame_idx:06d}.jpg"
            ok = cv2.imwrite(str(out_dir / filename), frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not ok:
                continue
            append_jsonl(FRAMES_INDEX_FILE, {
                "sampleId": sample["sampleId"],
                "sha256": sha256,
                "domain": domain,
                "frameIndex": frame_idx,
                "timeSeconds": round(frame_idx / video_fps, 6),
                "role": role,
                "imagePath": str((out_dir / filename).relative_to(ROOT)),
            })
            written += 1
    finally:
        cap.release()

    return {
        "sampleId": sample["sampleId"],
        "domain": domain,
        "framesTotal": total,
        "framesWritten": written,
        "mode": mode,
        "impactWindow": impact_window,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从已注册视频样本抽帧供标注 / 训练使用")
    parser.add_argument("--domain", required=True, choices=["human_club", "golf_ball_detection"])
    parser.add_argument("--mode", choices=["uniform", "impact_window"], default="uniform")
    parser.add_argument("--fps", type=float, default=10.0, help="uniform/稀疏抽帧的采样 fps")
    parser.add_argument("--sample-id", help="只处理指定样本 id；否则处理该 domain 全部 active 样本")
    parser.add_argument("--quality", type=int, default=92, help="JPEG 质量 0-100")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    ensure_registry_files()
    if args.sample_id:
        all_samples = list_samples(args.domain)
        samples = [s for s in all_samples if s["sampleId"] == args.sample_id]
        if not samples:
            print(f"sample {args.sample_id} not found in domain {args.domain}", file=sys.stderr)
            return 2
    else:
        samples = list_samples(args.domain)

    if args.dry_run:
        for sample in samples:
            print(json.dumps({"sampleId": sample["sampleId"], "assetPath": sample.get("assetPath")}, ensure_ascii=False))
        return 0

    reports = []
    for sample in samples:
        try:
            reports.append(extract_sample(sample, mode=args.mode, fps=args.fps, output_root=ROOT, quality=args.quality))
        except Exception as exc:
            reports.append({"sampleId": sample.get("sampleId"), "error": str(exc)})
    print(json.dumps({"processed": len(reports), "reports": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
