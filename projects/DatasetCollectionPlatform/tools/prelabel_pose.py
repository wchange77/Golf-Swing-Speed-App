"""为 human_club 帧生成 COCO Keypoints 预标注（17 点）。

由于 Python 端没有 VNDetectHumanBodyPoseRequest，我们用采集端 label_candidates.json
中已记录的 humanPoseCandidates 在对应帧上生成占位 keypoints（visible=1, 坐标=图像中心），
供 Label Studio 初始化。真正的坐标靠人工校正，或 macOS 侧离线 Vision 批量推断后覆盖。

输出:
- datasets/raw/human_club/prelabels/{sha256}/frame_{idx:06d}.json
  {"image_id": sha256_frameIdx, "keypoints": [x,y,v, ...17 个], "bbox": null}
- datasets/registry/prelabels_manifest.jsonl 与 prelabel_yolo 共用，带 source=vision_placeholder 区分
"""

from __future__ import annotations

import argparse
import json
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

COCO_KEYPOINT_COUNT = 17


def _load_pose_candidates(sample: dict[str, Any]) -> set[int]:
    sidecars = (sample.get("metadata") or {}).get("sidecars") or {}
    rel = sidecars.get("labelCandidates")
    if not rel:
        return set()
    path = (ROOT / rel).resolve()
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = data.get("humanPoseCandidates") or []
    return {int(c["frameIndex"]) for c in candidates if "frameIndex" in c}


def _placeholder_keypoints(width: int = 1080, height: int = 1920) -> list[float]:
    cx, cy = width / 2, height / 2
    # v=1 表示可见但未精确；校正后应改为 2。
    keypoints: list[float] = []
    for _ in range(COCO_KEYPOINT_COUNT):
        keypoints.extend([cx, cy, 1])
    return keypoints


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="为 human_club 帧生成 COCO Keypoints 占位预标注")
    parser.add_argument("--sample-id")
    parser.add_argument("--image-width", type=int, default=1080)
    parser.add_argument("--image-height", type=int, default=1920)
    args = parser.parse_args(argv)

    ensure_registry_files()
    rows = read_jsonl(FRAMES_INDEX_FILE)
    rows = [r for r in rows if r.get("domain") == "human_club"]
    if args.sample_id:
        rows = [r for r in rows if r.get("sampleId") == args.sample_id]
    if not rows:
        print(json.dumps({"framesWritten": 0, "reason": "no frames"}, ensure_ascii=False))
        return 0

    samples_by_id = {s["sampleId"]: s for s in list_samples("human_club")}
    pose_index = {sid: _load_pose_candidates(s) for sid, s in samples_by_id.items()}
    written = 0
    keypoints_template = _placeholder_keypoints(args.image_width, args.image_height)

    for row in rows:
        sample_id = row.get("sampleId")
        sample = samples_by_id.get(sample_id)
        if sample is None:
            continue
        frame_idx = int(row["frameIndex"])
        if frame_idx not in pose_index.get(sample_id, set()):
            continue
        out_dir = ROOT / "datasets" / "raw" / "human_club" / "prelabels" / row["sha256"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"frame_{frame_idx:06d}.json"
        payload = {
            "image_id": f"{row['sha256']}_{frame_idx:06d}",
            "keypoints": keypoints_template,
            "num_keypoints": COCO_KEYPOINT_COUNT,
            "bbox": None,
            "category_id": 1,
            "source": "placeholder",
            "needsReview": True,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        append_jsonl(PRELABELS_MANIFEST, {
            "sampleId": sample_id,
            "sha256": row["sha256"],
            "frameIndex": frame_idx,
            "source": "vision_placeholder",
            "confidence": 0.3,
            "hasDetection": True,
            "labelPath": str(out_path.relative_to(ROOT)),
            "kind": "coco_keypoints",
        })
        written += 1

    print(json.dumps({"framesWritten": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
