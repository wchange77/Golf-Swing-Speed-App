"""对 extract_frames.py 输出的帧做 YOLO bbox 预标注。

支持两个源:
- vision: 读取样本 label_candidates.json 的 ballCandidates 产出占位 bbox（固定中心 + 尺寸启发式），
  仅用于 Label Studio 初始化，不用于训练。
- ultralytics: 使用本地 ultralytics 权重推理生成 YOLO txt。权重路径通过 --weights 传入。

输出:
- datasets/raw/{domain}/prelabels/{sha256}/frame_{idx:06d}.txt (YOLO 归一化格式)
- datasets/registry/prelabels_manifest.jsonl 每行 {sampleId, sha256, frameIndex, source, confidence, hasDetection}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lib.registry import (
    REGISTRY_DIR,
    ROOT,
    append_jsonl,
    ensure_registry_files,
    list_samples,
    read_jsonl,
)

FRAMES_INDEX_FILE = REGISTRY_DIR / "frames_index.jsonl"
PRELABELS_MANIFEST = REGISTRY_DIR / "prelabels_manifest.jsonl"


def _load_frames_for(domain: str, sample_id: str | None) -> list[dict[str, Any]]:
    rows = read_jsonl(FRAMES_INDEX_FILE)
    if not rows:
        return []
    rows = [r for r in rows if r.get("domain") == domain]
    if sample_id:
        rows = [r for r in rows if r.get("sampleId") == sample_id]
    return rows


def _load_ball_candidates(sample: dict[str, Any]) -> dict[int, dict[str, Any]]:
    sidecars = (sample.get("metadata") or {}).get("sidecars") or {}
    rel = sidecars.get("labelCandidates")
    if not rel:
        return {}
    path = (ROOT / rel).resolve()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = data.get("ballCandidates") or []
    mapped: dict[int, dict[str, Any]] = {}
    for entry in candidates:
        idx = entry.get("frameIndex")
        if isinstance(idx, int):
            mapped[idx] = entry
    return mapped


def _write_yolo_txt(path: Path, detections: list[tuple[int, float, float, float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for cls, cx, cy, w, h in detections:
            handle.write(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")


def _vision_placeholder_bbox() -> tuple[int, float, float, float, float]:
    # 不做真实检测，居中放一个 6% 的方块，仅供 Label Studio 初始化。
    return (0, 0.5, 0.5, 0.06, 0.06)


def run_vision(samples: list[dict[str, Any]], frames: list[dict[str, Any]]) -> int:
    written = 0
    samples_by_id = {s["sampleId"]: s for s in samples}
    for frame in frames:
        sample_id = frame.get("sampleId")
        sample = samples_by_id.get(sample_id)
        if sample is None:
            continue
        candidates = _load_ball_candidates(sample)
        frame_idx = int(frame["frameIndex"])
        out_dir = ROOT / "datasets" / "raw" / frame["domain"] / "prelabels" / frame["sha256"]
        out_path = out_dir / f"frame_{frame_idx:06d}.txt"
        candidate = candidates.get(frame_idx)
        detections = [_vision_placeholder_bbox()] if candidate is not None else []
        _write_yolo_txt(out_path, detections)
        append_jsonl(PRELABELS_MANIFEST, {
            "sampleId": sample_id,
            "sha256": frame["sha256"],
            "frameIndex": frame_idx,
            "source": "vision",
            "confidence": 0.4 if candidate is not None else 0.0,
            "hasDetection": bool(detections),
            "labelPath": str(out_path.relative_to(ROOT)),
        })
        written += 1
    return written


def run_ultralytics(samples: list[dict[str, Any]], frames: list[dict[str, Any]], weights: Path, conf: float) -> int:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        print(f"ultralytics 未安装: {exc}", file=sys.stderr)
        return 0
    model = YOLO(str(weights))
    written = 0
    for frame in frames:
        image_path = ROOT / frame["imagePath"]
        if not image_path.exists():
            continue
        result = model.predict(source=str(image_path), conf=conf, verbose=False)
        if not result:
            continue
        boxes = result[0].boxes
        detections: list[tuple[int, float, float, float, float]] = []
        max_conf = 0.0
        if boxes is not None and boxes.xywhn is not None:
            xywhn = boxes.xywhn.cpu().numpy()
            classes = boxes.cls.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            for (cx, cy, w, h), cls, c in zip(xywhn, classes, confs):
                detections.append((int(cls), float(cx), float(cy), float(w), float(h)))
                max_conf = max(max_conf, float(c))
        frame_idx = int(frame["frameIndex"])
        out_dir = ROOT / "datasets" / "raw" / frame["domain"] / "prelabels" / frame["sha256"]
        out_path = out_dir / f"frame_{frame_idx:06d}.txt"
        _write_yolo_txt(out_path, detections)
        append_jsonl(PRELABELS_MANIFEST, {
            "sampleId": frame["sampleId"],
            "sha256": frame["sha256"],
            "frameIndex": frame_idx,
            "source": "ultralytics",
            "confidence": max_conf,
            "hasDetection": bool(detections),
            "labelPath": str(out_path.relative_to(ROOT)),
            "weights": str(weights),
        })
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="为 golf_ball_detection 帧生成 YOLO 预标注")
    parser.add_argument("--source", choices=["vision", "ultralytics"], default="vision")
    parser.add_argument("--weights", type=Path, help="ultralytics 权重 .pt，仅 --source=ultralytics 必填")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--sample-id")
    args = parser.parse_args(argv)

    ensure_registry_files()
    frames = _load_frames_for("golf_ball_detection", args.sample_id)
    samples = list_samples("golf_ball_detection")
    if not frames:
        print("没有可用帧，请先跑 extract_frames.py")
        return 0

    if args.source == "vision":
        written = run_vision(samples, frames)
    else:
        if args.weights is None or not args.weights.exists():
            parser.error("--source=ultralytics 需要有效 --weights 路径")
        written = run_ultralytics(samples, frames, args.weights.resolve(), args.conf)
    print(json.dumps({"source": args.source, "framesWritten": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
