# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

高尔夫挥杆测速系统，四主项目 + 一个共享 Swift Package 架构，执行顺序遵循"数据先行"原则。

## 项目结构

1. **DatasetCollectionPlatform** (`projects/DatasetCollectionPlatform/`) — 数据采集/去重/切分/导出平台（当前主焦点），含 Python 工具链 + iOS 采集端
2. **HumanClubAnalysisApp** (`projects/HumanClubAnalysisApp/`) — 人体+球杆分析 iOS App（速度/姿态/挥杆链路）
3. **GolfBallDetectionApp** (`projects/GolfBallDetectionApp/`) — 高尔夫球检测+轨迹 iOS App
4. **PiTracIPhoneFeasibilityStudy** (`projects/PiTracIPhoneFeasibilityStudy/`) — PiTrac 在 iPhone 上复现可行性分析
5. **GolfAnalysisKit** (`packages/GolfAnalysisKit/`) — 共享 Swift Package，两个 App 共同依赖

数据流向：DatasetCollectionPlatform 产出数据 → 两个 App 通过 consumer manifest 消费 → PiTrac 研究最后做。

## 平台要求

- iOS 部署目标：17.0
- Swift：5.9
- Xcode：16.4
- XcodeGen：所有 iOS 工程从 `project.yml` 生成 `.xcodeproj`（已 gitignore，不提交）
- Python：3.x，依赖见 `projects/DatasetCollectionPlatform/requirements.txt`（jsonschema, PyYAML, requests）

## 常用命令

### 数据平台（Python）

```bash
cd projects/DatasetCollectionPlatform
pip install -r requirements.txt

# 数据闭环全链路
python tools/start_session.py --collector "alice" --device "iPhone17Max" ...
python tools/register_sample.py --domain human_club --file <path> --session-id <id> ...
python tools/register_batch.py --domain golf_ball_detection --input-dir <dir> ...
python tools/split_dataset.py --domain human_club --strategy session --seed 42
python tools/generate_manifest.py
python tools/generate_quality_report.py
python tools/validate_registry.py --strict

# AppleOS 工程校验（无需 Mac/Xcode）
python tools/validate_apple_project.py
# 模拟 iOS 采集全链路
python tools/simulate_ios_workflow.py
```

### iOS 工程（Swift/Xcode）

```bash
# 生成任一工程（始终从 project.yml 重新生成）
cd projects/DatasetCollectionPlatform/AppleOSDatasetCollectorApp
xcodegen generate --spec project.yml

cd projects/HumanClubAnalysisApp
xcodegen generate --spec project.yml

cd projects/GolfBallDetectionApp
xcodegen generate --spec project.yml
```

### GolfAnalysisKit 测试

```bash
cd packages/GolfAnalysisKit
swift test
# 单个测试
swift test --filter GolfAnalysisKitTests.BallTrackingTests
```

测试文件在 `Tests/GolfAnalysisKitTests/`，覆盖：BallTracking、FrameDifferenceBallDetector、KalmanFilter2D、Session、Trajectory。

### YOLO 球检测模型训练

```bash
cd tools/train_ball_detector
pip install ultralytics coremltools
python train.py --data golf_ball.yaml --epochs 100 --device 0
python export_coreml.py --model runs/golf_ball/train/weights/best.pt
```

### PiTrac 可行性

```bash
python projects/PiTracIPhoneFeasibilityStudy/tools/build_gap_report.py
```

## 架构要点

### GolfAnalysisKit（共享核心算法）

两个 App 的算法核心，模块划分：
- **Detection**：BallDetector 协议 + FrameDifferenceBallDetector + FusedBallDetector
- **Tracking**：KalmanFilter2D/6D + OpticalFlowTracker + BallTrackingPipeline
- **SpeedCalc**：SpeedCalculator + BallSpeedCalculator + SwingPlaneCorrector + MotionBlurAnalyser
- **Trajectory**：LaunchConditionEstimator + EnvironmentModel + TrajectoryPhysicsModel（RK4 积分 + 空气阻力 + Magnus 效应）+ BezierTrajectoryModel + TrajectoryPredictor
- **Session**：SwingSession + SwingSessionStore（JSONL 持久化）+ PersonalStatsCalculator + InsightEngine
- **Analysis**：LagAnalyser + BodyPoseFrame

### 数据平台核心链路

`采集会话 → 样本注册(SHA-256去重) → 会话隔离切分 → 清单导出 → 质量校验`

- 注册表：`datasets/registry/{sessions,samples,duplicates}.jsonl`
- 契约 schema：`contracts/{session_record,sample_record,dataset_manifest}.schema.json`
- 消费者清单：`exports/consumers/{human_club_analysis_app,golf_ball_detection_app,pitrac_feasibility_study}.json`
- 工具库核心：`tools/lib/registry.py`

（以上路径均相对于 `projects/DatasetCollectionPlatform/`）

### iOS 采集端 (AppleOSDatasetCollectorApp)

SwiftUI 架构，240fps@1080p 高速录制 + 12 种 Vision 回放分析模型。

- Core 层：`DatasetCollectorApp/Sources/Core/` — 模型、JSONL 持久化、相机、验证、服务
- Features：`Sources/Features/{Collector,Recording,DataBrowser}/`
- 回放分析使用自定义 AVPlayerLayer（非 SwiftUI VideoPlayer），骨架叠加需 `.up` 方向 + letterbox 坐标映射
- 清晰度验证用像素级 Laplacian 方差（非 CIConvolution3X3）

### 两个消费端 App

- 通过 DatasetBridge 集成：`Sources/Integrations/DatasetBridge/` 读取 consumer manifest
- 环境变量覆盖：`HUMAN_CLUB_MANIFEST_PATH` / `GOLF_BALL_MANIFEST_PATH` / `DATASET_MANIFEST_PATH`
- GolfBallDetectionApp 额外包含 `YOLOBallDetector`（CoreML 推理）和轨迹可视化（TrajectoryOverlayView + FlightDataPanel + VideoReplayView）
- HumanClubAnalysisApp 包含 LiDAR 校准、音频击球检测、挥杆状态机、光流追踪

### iOS App 源码布局约定

三个 iOS 工程统一采用：
```
Sources/
  App/          — @main 入口
  Core/         — 模型、服务、相机、持久化
  Features/     — 按功能域拆分的 View + ViewModel
  Integrations/ — 外部数据桥接（DatasetBridge）
Resources/      — 资源文件
Tests/Unit/     — 单元测试
```

## 质量关口

以下必须全部通过才算数据闭环完成：
1. `validate_registry.py --strict` 无 schema 错误
2. 两个域都有 `exports/splits/<domain>.json`
3. 三个消费者清单已生成
4. `validate_apple_project.py` 通过
5. `simulate_ios_workflow.py` 模拟报告通过

## 工作规范

- 文档统一中文
- 提交信息使用前缀：`feat:` `fix:` `refactor:` `docs:` `test:` `chore:`，说明"改了什么 + 为什么改"
- 先做最小可验证实现，跑回归并记录结果，再扩展
- 任何"可能影响精度"的改动都要附验证记录
- 对阈值、滤波参数等关键常量给出来源说明
- 长任务维护根目录 `上下文压缩入口.md` 确保新会话可快速接续
- 研究文档集中在 `文档/研究/`，项目总览在 `文档/总览/`
