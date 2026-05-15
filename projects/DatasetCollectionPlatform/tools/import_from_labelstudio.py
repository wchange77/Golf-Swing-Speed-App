"""把 Label Studio 导出的 JSON 回写到项目标注目录 + 更新 annotations.jsonl。

约定:
- export_to_labelstudio.py 把 sampleId / frameIndex / sha256 塞进了 task.data，本工具以此回查 sample。
- 输出目录走 registry.annotation_path_for：
  - golf_ball_detection: datasets/annotations/yolo_bbox/{sampleId}/frame_{idx:06d}.txt
  - human_club:          datasets/annotations/coco_keypoints/{sampleId}/frame_{idx:06d}.json
- annotations.jsonl 按 (sampleId, kind) upsert，framesLabeled 根据实际写出的帧数累计。

Label Studio 导出格式支持两种:
- 单任务列表:  [{data: {...}, annotations: [{result: [...]}]}]
- export JSON 列表（Task JSON）两种都按 annotations[].result 解析。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from lib.registry import (
    REGISTRY_DIR,
    ROOT,
    annotation_path_for,
    read_jsonl,
    upsert_annotation_record,
    utc_now_iso,
)

FRAMES_INDEX_FILE = REGISTRY_DIR / "frames_index.jsonl"

COCO_LABELS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
COCO_LABEL_INDEX = {name: i for i, name in enumerate(COCO_LABELS)}

CLASS_MAP = {"ball": 0}


def _iter_tasks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tasks", "items", "data"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
    raise ValueError("无法从 Label Studio 导出中定位任务列表")


def _best_annotation(task: dict[str, Any]) -> list[dict[str, Any]]:
    annotations = task.get("annotations") or []
    if not annotations:
        return []
    preferred = [a for a in annotations if not a.get("was_cancelled") and not a.get("ground_truth", False) is False]
    pool = preferred or annotations
    pool_sorted = sorted(pool, key=lambda a: a.get("updated_at") or a.get("created_at") or "")
    return pool_sorted[-1].get("result") or []


def _write_yolo(sample_id: str, frame_idx: int, results: list[dict[str, Any]]) -> Path:
    lines: list[str] = []
    for item in results:
        if item.get("type") != "rectanglelabels":
            continue
        value = item.get("value") or {}
        labels = value.get("rectanglelabels") or []
        if not labels:
            continue
        cls = CLASS_MAP.get(labels[0])
        if cls is None:
            continue
        x_pct = float(value.get("x", 0.0)) / 100.0
        y_pct = float(value.get("y", 0.0)) / 100.0
        w_pct = float(value.get("width", 0.0)) / 100.0
        h_pct = float(value.get("height", 0.0)) / 100.0
        cx = max(0.0, min(1.0, x_pct + w_pct / 2))
        cy = max(0.0, min(1.0, y_pct + h_pct / 2))
        w = max(0.0, min(1.0, w_pct))
        h = max(0.0, min(1.0, h_pct))
        if w <= 0 or h <= 0:
            continue
        lines.append(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

    out_path = annotation_path_for(sample_id, "yolo_bbox", filename=f"frame_{frame_idx:06d}.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return out_path


def _write_pose(
    sample_id: str,
    frame_idx: int,
    sha256: str,
    results: list[dict[str, Any]],
    image_width: int,
    image_height: int,
) -> Path:
    keypoints: list[float] = [0.0] * (len(COCO_LABELS) * 3)
    num_kpts = 0
    for item in results:
        if item.get("type") != "keypointlabels":
            continue
        value = item.get("value") or {}
        labels = value.get("keypointlabels") or []
        if not labels:
            continue
        label = labels[0]
        idx = COCO_LABEL_INDEX.get(label)
        if idx is None:
            continue
        x_pct = float(value.get("x", 0.0)) / 100.0
        y_pct = float(value.get("y", 0.0)) / 100.0
        abs_x = x_pct * max(image_width, 1)
        abs_y = y_pct * max(image_height, 1)
        keypoints[idx * 3 + 0] = abs_x
        keypoints[idx * 3 + 1] = abs_y
        keypoints[idx * 3 + 2] = 2.0
        num_kpts += 1

    payload = {
        "image_id": f"{sha256}_{frame_idx:06d}",
        "keypoints": keypoints,
        "num_keypoints": num_kpts,
        "bbox": None,
        "category_id": 1,
        "source": "labelstudio",
    }
    out_path = annotation_path_for(sample_id, "coco_keypoints", filename=f"frame_{frame_idx:06d}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out_path


def _frames_total_by_sample(domain: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in read_jsonl(FRAMES_INDEX_FILE):
        if row.get("domain") != domain:
            continue
        sid = row.get("sampleId")
        if sid:
            counts[sid] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回写 Label Studio 导出的标注到项目注册表")
    parser.add_argument("--input", type=Path, required=True, help="Label Studio 导出的 JSON 文件")
    parser.add_argument("--domain", required=True, choices=["human_club", "golf_ball_detection"])
    parser.add_argument("--image-width", type=int, default=1080, help="pose 反归一化用")
    parser.add_argument("--image-height", type=int, default=1920)
    parser.add_argument("--annotator", default="labelstudio", help="写入 annotations.jsonl 的 annotator 字段")
    args = parser.parse_args(argv)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    tasks = _iter_tasks(payload)

    kind = "yolo_bbox" if args.domain == "golf_ball_detection" else "coco_keypoints"
    per_sample_frames: dict[str, set[int]] = defaultdict(set)
    per_sample_sha: dict[str, str] = {}
    written_files = 0
    skipped_tasks = 0

    for task in tasks:
        data = task.get("data") or {}
        sample_id = data.get("sampleId")
        frame_idx = data.get("frameIndex")
        sha256 = data.get("sha256") or ""
        if not sample_id or frame_idx is None:
            skipped_tasks += 1
            continue
        frame_idx = int(frame_idx)
        results = _best_annotation(task)
        if not results:
            skipped_tasks += 1
            continue

        if kind == "yolo_bbox":
            _write_yolo(sample_id, frame_idx, results)
        else:
            _write_pose(sample_id, frame_idx, sha256, results, args.image_width, args.image_height)

        per_sample_frames[sample_id].add(frame_idx)
        per_sample_sha.setdefault(sample_id, sha256)
        written_files += 1

    frames_totals = _frames_total_by_sample(args.domain)
    now = utc_now_iso()
    for sample_id, frames in per_sample_frames.items():
        upsert_annotation_record({
            "sampleId": sample_id,
            "sha256": per_sample_sha.get(sample_id, ""),
            "domain": args.domain,
            "kind": kind,
            "framesTotal": int(frames_totals.get(sample_id, len(frames))),
            "framesLabeled": len(frames),
            "annotator": args.annotator,
            "source": "labelstudio",
            "updatedAt": now,
        })

    report = {
        "domain": args.domain,
        "kind": kind,
        "tasksSeen": len(tasks),
        "skippedTasks": skipped_tasks,
        "filesWritten": written_files,
        "samples": len(per_sample_frames),
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
