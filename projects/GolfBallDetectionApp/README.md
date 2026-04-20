# GolfBallDetectionApp

高尔夫球检测 iOS 应用（第二主项目）。

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
