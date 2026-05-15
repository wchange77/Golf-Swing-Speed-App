"""把帧 + 校正后 COCO Keypoints JSON 按 split 导出 COCO 格式, 给 MMPose / 自定义 pose 训练用。

依赖:
- exports/splits/human_club.json
- datasets/registry/frames_index.jsonl
- datasets/annotations/coco_keypoints/{sampleId}/frame_{idx:06d}.json

输出目录 (默认 datasets/processed/human_club):
- {split}/images/{sampleId}__{sha}__frame_{idx:06d}.jpg
- annotations/{split}.json  (COCO Keypoints, single person category)
- manifest.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib.registry import (
    REGISTRY_DIR,
    ROOT,
    annotation_path_for,
    read_jsonl,
)

FRAMES_INDEX_FILE = REGISTRY_DIR / "frames_index.jsonl"
DEFAULT_OUT = ROOT / "datasets" / "processed" / "human_club"
SPLIT_FILE = ROOT / "exports" / "splits" / "human_club.json"

COCO_LABELS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
SKELETON = [
    [16, 14], [14, 12], [17, 15], [15, 13], [12, 13],
    [6, 12], [7, 13], [6, 7], [6, 8], [7, 9],
    [8, 10], [9, 11], [2, 3], [1, 2], [1, 3],
    [2, 4], [3, 5], [4, 6], [5, 7],
]


def _load_splits() -> dict[str, str]:
    if not SPLIT_FILE.exists():
        raise FileNotFoundError(f"split file not found: {SPLIT_FILE} (请先跑 split_dataset.py)")
    data = json.loads(SPLIT_FILE.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for split, ids in (data.get("sampleIds") or {}).items():
        for sid in ids:
            mapping[sid] = split
    return mapping


def _link_or_copy(src: Path, dst: Path, mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if mode == "symlink":
        dst.symlink_to(src.resolve())
    else:
        import shutil
        shutil.copy2(src, dst)


def _pose_label_path(sample_id: str, frame_idx: int) -> Path:
    return annotation_path_for(sample_id, "coco_keypoints", filename=f"frame_{frame_idx:06d}.json")


def _stem(sample_id: str, sha256: str, frame_idx: int) -> str:
    return f"{sample_id}__{sha256[:12]}__frame_{frame_idx:06d}"


def _coco_skeleton() -> list[dict[str, Any]]:
    return [{
        "supercategory": "person",
        "id": 1,
        "name": "person",
        "keypoints": COCO_LABELS,
        "skeleton": SKELETON,
    }]


def _image_entry(image_id: int, filename: str, width: int, height: int) -> dict[str, Any]:
    return {"id": image_id, "file_name": filename, "width": width, "height": height}


def _bbox_from_keypoints(kpts: list[float]) -> list[float]:
    xs, ys = [], []
    for i in range(0, len(kpts), 3):
        x, y, v = kpts[i], kpts[i + 1], kpts[i + 2]
        if v > 0:
            xs.append(x)
            ys.append(y)
    if not xs:
        return [0.0, 0.0, 0.0, 0.0]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return [x0, y0, max(x1 - x0, 1.0), max(y1 - y0, 1.0)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 COCO Keypoints 训练数据集")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--link-mode", choices=["symlink", "copy"], default="symlink")
    parser.add_argument("--image-width", type=int, default=1080)
    parser.add_argument("--image-height", type=int, default=1920)
    args = parser.parse_args(argv)

    split_map = _load_splits()
    frames = [r for r in read_jsonl(FRAMES_INDEX_FILE) if r.get("domain") == "human_club"]
    if not frames:
        print(json.dumps({"framesSeen": 0, "reason": "no frames"}, ensure_ascii=False))
        return 0

    per_split: dict[str, dict[str, list[Any]]] = {
        s: {"images": [], "annotations": []} for s in ("train", "val", "test")
    }
    counts = {"train": 0, "val": 0, "test": 0}
    skipped_unlabeled = 0
    skipped_no_split = 0
    annotation_id_counter = 1
    image_id_counter = 1

    for frame in frames:
        sample_id = frame.get("sampleId")
        split = split_map.get(sample_id)
        if split not in counts:
            skipped_no_split += 1
            continue
        frame_idx = int(frame["frameIndex"])
        sha256 = frame["sha256"]
        label_src = _pose_label_path(sample_id, frame_idx)
        image_src = ROOT / frame["imagePath"]
        if not image_src.exists():
            continue
        if not label_src.exists():
            skipped_unlabeled += 1
            continue

        payload = json.loads(label_src.read_text(encoding="utf-8"))
        keypoints = payload.get("keypoints") or []
        if len(keypoints) != len(COCO_LABELS) * 3:
            skipped_unlabeled += 1
            continue

        stem = _stem(sample_id, sha256, frame_idx)
        image_dst = args.output / split / "images" / f"{stem}.jpg"
        _link_or_copy(image_src, image_dst, args.link_mode)

        image_entry = _image_entry(image_id_counter, f"{stem}.jpg", args.image_width, args.image_height)
        per_split[split]["images"].append(image_entry)
        num_kpts = payload.get("num_keypoints") or sum(1 for i in range(2, len(keypoints), 3) if keypoints[i] > 0)
        per_split[split]["annotations"].append({
            "id": annotation_id_counter,
            "image_id": image_id_counter,
            "category_id": 1,
            "iscrowd": 0,
            "keypoints": keypoints,
            "num_keypoints": int(num_kpts),
            "bbox": _bbox_from_keypoints(keypoints),
            "area": args.image_width * args.image_height,
            "sampleId": sample_id,
            "frameIndex": frame_idx,
            "sha256": sha256,
        })
        image_id_counter += 1
        annotation_id_counter += 1
        counts[split] += 1

    annotations_dir = args.output / "annotations"
    annotations_dir.mkdir(parents=True, exist_ok=True)
    for split, payload in per_split.items():
        coco_doc = {
            "info": {"description": f"human_club keypoints {split}", "version": "1.0"},
            "categories": _coco_skeleton(),
            "images": payload["images"],
            "annotations": payload["annotations"],
        }
        (annotations_dir / f"{split}.json").write_text(
            json.dumps(coco_doc, ensure_ascii=False), encoding="utf-8"
        )

    manifest = {
        "domain": "human_club",
        "output": str(args.output.resolve().relative_to(ROOT)) if args.output.resolve().is_relative_to(ROOT) else str(args.output),
        "linkMode": args.link_mode,
        "counts": counts,
        "skippedUnlabeled": skipped_unlabeled,
        "skippedNoSplit": skipped_no_split,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
