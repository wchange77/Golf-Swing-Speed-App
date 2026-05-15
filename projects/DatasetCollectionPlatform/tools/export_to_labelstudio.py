"""把抽帧结果 + 预标注打包成 Label Studio 可直接导入的 JSON 任务清单。

针对两种任务:
- golf_ball_detection: RectangleLabels (YOLO bbox)
- human_club: KeyPointLabels (17 点 COCO)

输出:
- exports/labelstudio/{domain}_tasks.json
- exports/labelstudio/{domain}_config.xml 配套的 Label Studio 标注界面模板

依赖 prelabel_yolo.py / prelabel_pose.py 先跑完，frames_index.jsonl 与 prelabels_manifest.jsonl 已就绪。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib.registry import REGISTRY_DIR, ROOT, read_jsonl

FRAMES_INDEX_FILE = REGISTRY_DIR / "frames_index.jsonl"
PRELABELS_MANIFEST = REGISTRY_DIR / "prelabels_manifest.jsonl"

BALL_CONFIG_XML = """<View>
  <Image name=\"image\" value=\"$image\"/>
  <RectangleLabels name=\"bbox\" toName=\"image\">
    <Label value=\"ball\" background=\"#FFA500\"/>
  </RectangleLabels>
</View>
"""

POSE_CONFIG_XML = """<View>
  <Image name=\"image\" value=\"$image\"/>
  <KeyPointLabels name=\"kp\" toName=\"image\" strokeWidth=\"3\">
    <Label value=\"nose\"/><Label value=\"left_eye\"/><Label value=\"right_eye\"/>
    <Label value=\"left_ear\"/><Label value=\"right_ear\"/>
    <Label value=\"left_shoulder\"/><Label value=\"right_shoulder\"/>
    <Label value=\"left_elbow\"/><Label value=\"right_elbow\"/>
    <Label value=\"left_wrist\"/><Label value=\"right_wrist\"/>
    <Label value=\"left_hip\"/><Label value=\"right_hip\"/>
    <Label value=\"left_knee\"/><Label value=\"right_knee\"/>
    <Label value=\"left_ankle\"/><Label value=\"right_ankle\"/>
  </KeyPointLabels>
</View>
"""


def _load_yolo_bbox(path: Path) -> list[tuple[float, float, float, float]]:
    if not path.exists():
        return []
    results: list[tuple[float, float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        _, cx, cy, w, h = parts
        results.append((float(cx), float(cy), float(w), float(h)))
    return results


def _load_coco_keypoints(path: Path) -> list[float] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("keypoints")


def _build_ball_task(frame: dict[str, Any], prelabel: dict[str, Any] | None) -> dict[str, Any]:
    image_uri = (ROOT / frame["imagePath"]).as_uri()
    predictions = []
    if prelabel and prelabel.get("hasDetection"):
        bbox_path = ROOT / prelabel["labelPath"]
        for cx, cy, w, h in _load_yolo_bbox(bbox_path):
            predictions.append({
                "model_version": prelabel.get("source", "vision"),
                "score": float(prelabel.get("confidence", 0.3)),
                "result": [{
                    "from_name": "bbox",
                    "to_name": "image",
                    "type": "rectanglelabels",
                    "value": {
                        "x": max(0.0, (cx - w / 2)) * 100,
                        "y": max(0.0, (cy - h / 2)) * 100,
                        "width": w * 100,
                        "height": h * 100,
                        "rectanglelabels": ["ball"],
                    },
                }],
            })
    return {
        "data": {
            "image": image_uri,
            "sampleId": frame["sampleId"],
            "frameIndex": frame["frameIndex"],
            "sha256": frame["sha256"],
        },
        "predictions": predictions,
    }


def _build_pose_task(frame: dict[str, Any], prelabel: dict[str, Any] | None, width: int, height: int) -> dict[str, Any]:
    image_uri = (ROOT / frame["imagePath"]).as_uri()
    predictions = []
    if prelabel:
        keypoints = _load_coco_keypoints(ROOT / prelabel["labelPath"])
        if keypoints:
            labels = [
                "nose", "left_eye", "right_eye", "left_ear", "right_ear",
                "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                "left_wrist", "right_wrist", "left_hip", "right_hip",
                "left_knee", "right_knee", "left_ankle", "right_ankle",
            ]
            result = []
            for i, label in enumerate(labels):
                x, y, v = keypoints[i * 3 : i * 3 + 3]
                if v <= 0:
                    continue
                result.append({
                    "from_name": "kp",
                    "to_name": "image",
                    "type": "keypointlabels",
                    "value": {
                        "x": (x / max(width, 1)) * 100,
                        "y": (y / max(height, 1)) * 100,
                        "width": 0.5,
                        "keypointlabels": [label],
                    },
                })
            predictions.append({
                "model_version": prelabel.get("source", "placeholder"),
                "score": float(prelabel.get("confidence", 0.3)),
                "result": result,
            })
    return {
        "data": {
            "image": image_uri,
            "sampleId": frame["sampleId"],
            "frameIndex": frame["frameIndex"],
            "sha256": frame["sha256"],
        },
        "predictions": predictions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 Label Studio 任务 JSON")
    parser.add_argument("--domain", required=True, choices=["human_club", "golf_ball_detection"])
    parser.add_argument("--image-width", type=int, default=1080, help="用于 pose keypoint 归一化")
    parser.add_argument("--image-height", type=int, default=1920)
    args = parser.parse_args(argv)

    frames = [r for r in read_jsonl(FRAMES_INDEX_FILE) if r.get("domain") == args.domain]
    prelabels = {(r.get("sha256"), int(r.get("frameIndex", -1))): r for r in read_jsonl(PRELABELS_MANIFEST)}
    tasks = []
    for frame in frames:
        key = (frame.get("sha256"), int(frame.get("frameIndex", -1)))
        prelabel = prelabels.get(key)
        if args.domain == "golf_ball_detection":
            tasks.append(_build_ball_task(frame, prelabel))
        else:
            tasks.append(_build_pose_task(frame, prelabel, args.image_width, args.image_height))

    out_dir = ROOT / "exports" / "labelstudio"
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = out_dir / f"{args.domain}_tasks.json"
    tasks_path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path = out_dir / f"{args.domain}_config.xml"
    config_path.write_text(
        BALL_CONFIG_XML if args.domain == "golf_ball_detection" else POSE_CONFIG_XML,
        encoding="utf-8",
    )
    print(json.dumps({"tasks": len(tasks), "tasksFile": str(tasks_path.relative_to(ROOT)), "configFile": str(config_path.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
