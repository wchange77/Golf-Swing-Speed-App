# AppleOSDatasetCollectorApp

用于 iPhone 侧高尔夫挥杆数据采集的 SwiftUI 工程，输出 JSONL 与现有 `DatasetCollectionPlatform` 契约对齐。

## v2 功能

### 采集流程
1. 创建采集会话（`sessions.jsonl`）。
2. 三步引导录制：摆放手机 → 确认人在画面 → 确认参数 → 倒计时录制。
3. 录制后自动质量验证（帧数、时长、帧率稳定性、人体检测、清晰度、亮度）。
4. 登记样本并按 SHA-256 去重（`samples.jsonl` + `duplicates.jsonl`）。
5. 生成可导出的本地目录（默认在 iOS `Documents/DatasetCollectorExport`）。

### 数据浏览与管理
- 样本列表：按域/会话筛选，显示采集时间、文件大小、杆型/手性。
- 样本详情：视频缩略图 + 完整元数据 + 回放分析入口。
- 左滑删除：从 JSONL 移除记录 + 删除 assets 文件。

### 回放分析（12 种模型）

| 模型 | 说明 | 叠加效果 |
|------|------|---------|
| 人体骨架 2D | VNDetectHumanBodyPoseRequest | 绿色骨架线 + 黄色关节点 |
| 人体骨架 3D | VNDetectHumanBodyPose3DRequest | 骨架线 + 深度颜色编码 |
| 手部关节 | VNDetectHumanHandPoseRequest | 手部 21 点连线（握杆分析）|
| 关节角度 | 基于骨架计算 | 左/右肘、左/右膝、躯干、前倾角度数值 |
| 挥杆阶段 | 基于骨架+运动学 | 自动标注：准备→上杆→顶点→下杆→击球→收杆 |
| 挥杆平面 | 手腕轨迹拟合 | 平面一致性检测，偏离角度显示 |
| 点击追踪 | VNTrackObjectRequest | 点击选择目标逐帧追踪轨迹 |
| 人体分割 | VNGeneratePersonSegmentationRequest (.accurate) | 半透明蒙版覆盖人体区域 |
| 前景分割 | VNGenerateForegroundInstanceMaskRequest | 多实例彩色蒙版 |
| 轨迹检测 | VNDetectTrajectoriesRequest | 抛物线运动物体轨迹 |
| 光流分析 | VNGenerateOpticalFlowRequest | 运动速度热力图 |
| 轮廓检测 | VNDetectContoursRequest | 边缘轮廓（人体+球杆形态）|

### 技术要点
- 240fps @ 1080p 高速录制，支持 LiDAR 深度数据同步采集。
- 回放使用自定义 AVPlayerLayer（非 SwiftUI VideoPlayer），确保骨架叠加精确对齐。
- Vision 分析使用 `.up` 方向（AVAssetImageGenerator 已旋转帧）。
- 清晰度验证使用直接像素 Laplacian 方差（适配 240fps 短曝光帧）。

## 目录

- `project.yml`：XcodeGen 工程定义
- `DatasetCollectorApp/Sources/Core`：模型、存储、服务、相机、验证
- `DatasetCollectorApp/Sources/Features/Collector`：采集 UI
- `DatasetCollectorApp/Sources/Features/Recording`：录制引导、录制、结果、回放分析
- `DatasetCollectorApp/Sources/Features/DataBrowser`：数据浏览与管理
- `DatasetCollectorApp/Tests/Unit`：服务层单测

## 在 macOS 上生成并部署

```bash
cd projects/DatasetCollectionPlatform/AppleOSDatasetCollectorApp
xcodegen generate --spec project.yml
open DatasetCollectorApp.xcodeproj
```

在 Xcode 中选择真机（例如 iPhone 17 Pro Max）后运行。

## 与 DatasetCollectionPlatform 对接

iOS 导出目录中的 `sessions.jsonl / samples.jsonl / duplicates.jsonl` 字段与
`contracts/session_record.schema.json`、`contracts/sample_record.schema.json` 对齐。

在 Windows 上无法直接编译 iOS 工程，可在 `projects/DatasetCollectionPlatform` 目录执行：

```bash
cd projects/DatasetCollectionPlatform
python tools/validate_apple_project.py
python tools/simulate_ios_workflow.py
```

该脚本会模拟 iOS 采集流程并跑完整数据链路测试。
