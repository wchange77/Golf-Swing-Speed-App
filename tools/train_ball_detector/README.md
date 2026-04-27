# 高尔夫球检测模型训练

## 环境准备

```bash
pip install ultralytics coremltools
```

## 数据集

YOLO 格式，目录结构：

```
datasets/golf_ball/
  train/images/   train/labels/
  val/images/     val/labels/
  test/images/    test/labels/
```

标注格式（每行）：`class_id cx cy w h`（归一化坐标）

数据来源：
- Roboflow 公开高尔夫球数据集
- DatasetCollectorApp 采集的 240fps 视频逐帧标注
- 建议增强：运动模糊、缩放（模拟 3-20 像素小球）、亮度变化

## 训练

```bash
python train.py --data golf_ball.yaml --epochs 100 --device 0
```

验证指标目标：mAP@0.5 > 0.85

## 导出 CoreML

```bash
python export_coreml.py --model runs/golf_ball/train/weights/best.pt
```

输出 `GolfBallDetector.mlpackage`，拖入 Xcode 项目 Resources 目录。

## 备选：COCO 预训练

不训练自定义模型时，可直接用 COCO 预训练的 YOLO（`sports ball` 类别 index 32）：

```bash
python export_coreml.py --model yolo11n.pt
```

iOS 端 `YOLOBallDetector` 的 `targetLabels` 设为 `["sports ball"]` 即可。
