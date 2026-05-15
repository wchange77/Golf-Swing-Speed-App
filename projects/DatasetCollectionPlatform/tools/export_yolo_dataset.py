"""把帧 + 校正后 YOLO txt 按 split 导出到 datasets/processed/golf_ball_detection/{split}/{images,labels}。

依赖:
- exports/splits/golf_ball_detection.json (split_dataset.py 产出, sampleIds 区分 train/val/test)
- datasets/registry/frames_index.jsonl (extract_frames.py 产出)
- datasets/annotations/yolo_bbox/{sampleId}/frame_{idx:06d}.txt (import_from_labelstudio.py 产出)

输出目录 (默认 datasets/processed/golf_ball_detection):
- {split}/images/{sampleId}__{sha}__frame_{idx:06d}.jpg  (符号链接，避免占磁盘)
- {split}/labels/{sampleId}__{sha}__frame_{idx:06d}.txt
- golf_ball.yaml (如 --write-yaml 指定，会更新到对齐 tools/train_ball_detector/golf_ball.yaml)
- manifest.json 汇总 per-split 帧数、已标注率、未标注跳过

没有对应 YOLO txt 的帧默认跳过（记入 skipped_unlabeled），除非 --include-unlabeled。
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
DEFAULT_OUT = ROOT / "datasets" / "processed" / "golf_ball_detection"
SPLIT_FILE = ROOT / "exports" / "splits" / "golf_ball_detection.json"


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


def _yolo_label_path(sample_id: str, frame_idx: int) -> Path:
    return annotation_path_for(sample_id, "yolo_bbox", filename=f"frame_{frame_idx:06d}.txt")


def _stem(sample_id: str, sha256: str, frame_idx: int) -> str:
    return f"{sample_id}__{sha256[:12]}__frame_{frame_idx:06d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 YOLO 训练数据集")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--link-mode", choices=["symlink", "copy"], default="symlink")
    parser.add_argument("--include-unlabeled", action="store_true", help="默认跳过无 YOLO txt 的帧")
    parser.add_argument(
        "--write-yaml",
        type=Path,
        default=None,
        help="写入 YOLO dataset yaml 的路径，例 tools/train_ball_detector/golf_ball.yaml",
    )
    args = parser.parse_args(argv)

    split_map = _load_splits()
    frames = [r for r in read_jsonl(FRAMES_INDEX_FILE) if r.get("domain") == "golf_ball_detection"]
    if not frames:
        print(json.dumps({"framesSeen": 0, "reason": "no frames"}, ensure_ascii=False))
        return 0

    counts = {"train": 0, "val": 0, "test": 0}
    skipped_unlabeled = 0
    skipped_no_split = 0
    labeled_samples: set[str] = set()

    for frame in frames:
        sample_id = frame.get("sampleId")
        split = split_map.get(sample_id)
        if split not in counts:
            skipped_no_split += 1
            continue
        frame_idx = int(frame["frameIndex"])
        sha256 = frame["sha256"]
        label_src = _yolo_label_path(sample_id, frame_idx)
        image_src = ROOT / frame["imagePath"]
        if not image_src.exists():
            continue
        has_label = label_src.exists() and label_src.stat().st_size > 0
        if not has_label and not args.include_unlabeled:
            skipped_unlabeled += 1
            continue

        stem = _stem(sample_id, sha256, frame_idx)
        image_dst = args.output / split / "images" / f"{stem}.jpg"
        label_dst = args.output / split / "labels" / f"{stem}.txt"
        _link_or_copy(image_src, image_dst, args.link_mode)
        if has_label:
            _link_or_copy(label_src, label_dst, args.link_mode)
            labeled_samples.add(sample_id)
        else:
            label_dst.parent.mkdir(parents=True, exist_ok=True)
            label_dst.write_text("", encoding="utf-8")
        counts[split] += 1

    manifest = {
        "domain": "golf_ball_detection",
        "output": str(args.output.resolve().relative_to(ROOT)) if args.output.resolve().is_relative_to(ROOT) else str(args.output),
        "linkMode": args.link_mode,
        "counts": counts,
        "skippedUnlabeled": skipped_unlabeled,
        "skippedNoSplit": skipped_no_split,
        "labeledSamples": sorted(labeled_samples),
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.write_yaml is not None:
        yaml_path = args.write_yaml.resolve()
        rel_root = args.output.resolve()
        content = (
            "# 高尔夫球检测数据集配置（由 export_yolo_dataset.py 生成）\n"
            f"path: {rel_root}\n"
            "train: train/images\n"
            "val: val/images\n"
            "test: test/images\n"
            "nc: 1\n"
            "names:\n"
            "  0: golf_ball\n"
        )
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(content, encoding="utf-8")
        manifest["yamlWritten"] = str(yaml_path)

    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
