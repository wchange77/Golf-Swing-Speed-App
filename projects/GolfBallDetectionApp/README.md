# GolfBallDetectionApp

高尔夫球检测 iOS 应用（第二主项目）。

> 状态：70%（代码完成，待 CoreML 模型 + 真机验证）
> 阻塞：无训练好的 CoreML 模型（依赖 DatasetCollectionPlatform 产出数据后训练）

## 已实现功能

- YOLO CoreML 检测器集成（模型槽位就绪，待模型文件）
- 相机管线 + 检测视图
- 轨迹叠加（TrajectoryOverlayView）+ 飞行数据面板（FlightDataPanel）+ 视频回放（VideoReplayView）
- 历史记录 + 洞察仪表盘
- DatasetBridge 数据集桥接（15 Swift 文件）

## 目录

- `GolfBallDetectionApp/Sources`：检测相关代码
- `GolfBallDetectionApp/Resources`：资源
- `GolfBallDetectionApp/Tests/Unit`：单元测试

## 数据先行接入（推荐顺序）

1. 在 `../DatasetCollectionPlatform` 完成数据闭环：
   - `python tools/start_session.py ...`
   - `python tools/register_sample.py --domain golf_ball_detection ...`
   - `python tools/split_dataset.py --domain golf_ball_detection`
   - `python tools/generate_manifest.py`
2. 在本项目刷新清单并运行检测流程。

## 与数据平台集成

- 默认清单路径：`../DatasetCollectionPlatform/exports/consumers/golf_ball_detection_app.json`
- 桥接入口：`GolfBallDetectionApp/Sources/Integrations/DatasetBridge/BallDatasetBridge.swift`
- 环境变量覆盖优先级：`GOLF_BALL_MANIFEST_PATH` -> `DATASET_MANIFEST_PATH`

## 工程生成

```bash
xcodegen generate --spec project.yml
```
