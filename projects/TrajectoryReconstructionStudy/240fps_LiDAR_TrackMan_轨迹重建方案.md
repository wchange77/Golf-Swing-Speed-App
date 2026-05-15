# 240fps + LiDAR + TrackMan 高尔夫球轨迹重建

## 背景

用户拥有三种数据源：iPhone 240fps 视频、LiDAR 标定数据、TrackMan 测量数据。目标是绘制完整高尔夫球飞行轨迹和落点。

**结论：完全可行。三者互补，缺一不可。**

---

## 各数据源贡献与局限

| 数据源 | 贡献 | 局限 |
|--------|------|------|
| TrackMan | 精确发射参数（球速/仰角/旋转）→ 驱动物理模型 | 无空间位置，无法定位轨迹起点 |
| LiDAR | pixelsPerMetre + ballPosition3D → 锚定轨迹到真实空间 | 有效范围 ~5m，仅覆盖击球区 |
| 240fps 视频 | 前 6-20 帧真实球位置 → 验证初始方向 | Driver 约 6-7 帧出画（0.03s），短铁杆约 15-20 帧 |

---

## 数据流（顺序执行）

```
1. 读取 CollectorCameraSidecar → pixelsPerMetre, ballPosition3D
2. 读取 CollectorReferenceMeasurement (TrackMan) → LaunchConditions.from(trackman:)
3. BallTrackingPipeline 处理视频前 10 帧 → impactTimestamp + 初始方向
4. 用视频方向修正 launchDirectionDegrees（若 TrackMan 未提供）
5. TrajectoryPhysicsModel.simulate(launch:) → TrajectoryResult
6. 米制坐标 → 屏幕像素坐标（用 pixelsPerMetre + ballPosition3D）
7. BezierTrajectoryModel 平滑曲线
8. TrajectoryOverlayView 渲染（已有）
9. 叠加 GPS 落点 vs 物理模型预测落点对比
```

---

## 实现计划

### 已有，直接复用

- `packages/GolfAnalysisKit/Sources/GolfAnalysisKit/Trajectory/TrajectoryPhysicsModel.swift` — RK4 物理仿真
- `packages/GolfAnalysisKit/Sources/GolfAnalysisKit/Trajectory/BezierTrajectoryModel.swift` — 曲线平滑
- `packages/GolfAnalysisKit/Sources/GolfAnalysisKit/Tracking/BallTrackingPipeline.swift` — 视频追踪（fps=240）
- `projects/HumanClubAnalysisApp/GolfSwingSpeedApp/Sources/Features/Calibration/LiDARCalibrationManager.swift` — LiDAR 标定
- `projects/GolfBallDetectionApp/GolfBallDetectionApp/Sources/Features/Replay/TrajectoryOverlayView.swift` — 轨迹叠加渲染

### 需要修改（1 处）

`projects/DatasetCollectionPlatform/AppleOSDatasetCollectorApp/DatasetCollectorApp/Sources/Core/Models/DatasetCollectorModels.swift`

在 `CollectorReferenceMeasurement` 中新增：
```swift
let spinAxisTiltDegrees: Double?  // TrackMan spin axis tilt，nil 时按纯后旋处理
```

### 需要新建（3 个文件）

**文件 1：TrackMan 转换器**
`packages/GolfAnalysisKit/Sources/GolfAnalysisKit/Trajectory/TrackManLaunchConverter.swift`

```swift
extension LaunchConditions {
    static func from(
        trackman: CollectorReferenceMeasurement,
        spinAxisTiltDegrees: Double = 0
    ) -> LaunchConditions? {
        guard let ballSpeedMph = trackman.ballSpeedMph,
              let launchAngle = trackman.launchAngleDegrees,
              let spinRate = trackman.spinRateRpm else { return nil }
        let tiltRad = spinAxisTiltDegrees * .pi / 180
        return LaunchConditions(
            ballSpeedMs: ballSpeedMph * 0.44704,
            launchAngleDegrees: launchAngle,
            launchDirectionDegrees: 0,
            backspinRPM: spinRate * cos(tiltRad),
            sidespinRPM: spinRate * sin(tiltRad),
            confidence: 0.95
        )
    }
}
```

**文件 2：轨迹融合协调器**
`projects/GolfBallDetectionApp/GolfBallDetectionApp/Sources/Features/Replay/TrajectoryFusionCoordinator.swift`
- 输入：`CollectorCameraSidecar` + `CollectorReferenceMeasurement` + 视频 URL
- 输出：`(bezierPoints, impactPoint, predictedLanding, gpsLanding?)`
- 约 60-80 行

**文件 3：落点对比视图**
`projects/GolfBallDetectionApp/GolfBallDetectionApp/Sources/Features/Replay/LandingComparisonView.swift`
- 2D 俯视图：物理模型预测落点（蓝色）vs GPS 实测落点（红色）
- 侧视图：轨迹高度曲线
- 约 50 行 SwiftUI Canvas

---

## 精度预期

- TrackMan 球速精度 ±0.5mph，仰角 ±0.5°，旋转 ±50RPM
- 物理模型预测落点误差：Driver ±5-10 码，短铁杆 ±3-5 码
- GPS 落点精度通常 ±3-5m，与物理模型误差量级相当，对比有意义

---

## 验证方法

1. 单元测试：`LaunchConditions.from(trackman:)` 用已知 TrackMan 数值验证转换结果
2. 集成测试：用 `simulate_ios_workflow.py` 验证 sidecar 数据读取
3. 端到端：在 GolfBallDetectionApp 回放界面加载有 TrackMan 数据的样本，确认轨迹和落点正确渲染
