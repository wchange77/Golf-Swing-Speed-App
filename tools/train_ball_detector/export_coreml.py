"""
将训练好的 YOLO 模型导出为 CoreML 格式

用法:
    python export_coreml.py --model runs/golf_ball/train/weights/best.pt

输出:
    GolfBallDetector.mlpackage — 拖入 Xcode 项目即可使用
"""

import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description="导出 CoreML 模型")
    parser.add_argument("--model", required=True, help="训练好的 .pt 模型路径")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--output-name", default="GolfBallDetector")
    args = parser.parse_args()

    model = YOLO(args.model)

    exported = model.export(
        format="coreml",
        nms=True,
        imgsz=args.imgsz,
    )

    output_path = Path(f"{args.output_name}.mlpackage")
    if Path(exported).exists() and Path(exported) != output_path:
        if output_path.exists():
            shutil.rmtree(output_path)
        shutil.move(str(exported), str(output_path))

    print(f"\nCoreML 模型已导出: {output_path}")
    print(f"将 {output_path} 拖入 Xcode 项目的 Resources 目录")
    print(f"Xcode 会自动编译为 .mlmodelc")


if __name__ == "__main__":
    main()
