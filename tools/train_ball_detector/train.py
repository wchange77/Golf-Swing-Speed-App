"""
高尔夫球检测 YOLO 模型训练脚本

用法:
    pip install ultralytics
    python train.py --data golf_ball.yaml --epochs 100

数据集准备:
    1. 从 Roboflow 下载高尔夫球标注数据集 (YOLO 格式)
    2. 或用 DatasetCollectorApp 采集 240fps 视频后逐帧标注
    3. 目录结构:
       datasets/golf_ball/
         train/images/  train/labels/
         val/images/    val/labels/
         test/images/   test/labels/
"""

import argparse
from pathlib import Path

from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description="训练高尔夫球检测 YOLO 模型")
    parser.add_argument("--model", default="yolo11n.pt", help="预训练模型")
    parser.add_argument("--data", default="golf_ball.yaml", help="数据集配置")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0", help="GPU 设备号，cpu 则填 cpu")
    parser.add_argument("--project", default="runs/golf_ball")
    parser.add_argument("--name", default="train")
    args = parser.parse_args()

    model = YOLO(args.model)

    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        # 数据增强 — 模拟高速运动场景
        hsv_h=0.015,
        hsv_s=0.5,
        hsv_v=0.3,
        degrees=5.0,
        translate=0.1,
        scale=0.3,
        mosaic=1.0,
        mixup=0.1,
        # 运动模糊通过离线增强实现，此处不设置
    )

    # 验证
    metrics = model.val()
    print(f"\nmAP@0.5: {metrics.box.map50:.4f}")
    print(f"mAP@0.5:0.95: {metrics.box.map:.4f}")

    best_path = Path(args.project) / args.name / "weights" / "best.pt"
    print(f"\n最佳模型: {best_path}")
    print(f"运行 export_coreml.py 导出 CoreML 模型")


if __name__ == "__main__":
    main()
