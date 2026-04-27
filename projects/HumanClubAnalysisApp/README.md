# HumanClubAnalysisApp

人体与球杆分析 iOS 应用（第一主项目）。

> 状态：75%（代码完成，待真机验证）
> 阻塞：全部真机测试未做、速度计算精度未验证

## 已实现功能

- 相机采集（240fps@1080p）+ LiDAR/手动标定
- Kalman 滤波 + 光流追踪球杆头
- 速度计算（帧间位移 / 实际时间戳 + 运动模糊补偿）
- FFT 音频击球检测 + 挥杆状态机
- 滞后角分析（LRI + 释放点 + 杆面倾角）
- 历史记录、设置、引导流程（49 Swift 文件）

## 目录

- `GolfSwingSpeedApp/Sources`：业务与核心代码
- `GolfSwingSpeedApp/Resources`：资源文件
- `GolfSwingSpeedApp/Tests/Unit`：单元测试

## 数据先行接入（推荐顺序）

1. 在 `../DatasetCollectionPlatform` 完成数据闭环：
   - `python tools/start_session.py ...`
   - `python tools/register_sample.py ...`
   - `python tools/split_dataset.py --domain human_club`
   - `python tools/generate_manifest.py`
2. 在本项目读取导出的 manifest 并启动分析链路。

## 与数据平台集成

- 默认清单路径：`../DatasetCollectionPlatform/exports/consumers/human_club_analysis_app.json`
- 桥接入口：`GolfSwingSpeedApp/Sources/Integrations/DatasetBridge/HumanClubDatasetBridge.swift`
- 环境变量覆盖优先级：`HUMAN_CLUB_MANIFEST_PATH` -> `DATASET_MANIFEST_PATH`

## 工程生成

```bash
xcodegen generate --spec project.yml
```
