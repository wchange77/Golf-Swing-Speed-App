# iPhone 高尔夫球轨迹绘制与无 TrackMan 优化方案

日期：2026-05-12  
修订说明：本版根据 TrackNet 系列、高速小目标跟踪、单目 3D 球轨迹估计、FastVLM、以及高尔夫球空气动力学/物理模型相关论文与报告重新整理。

## 结论

1. 你提出的流程可行：先用 App 底部圆圈对准球位，短时雷达/LiDAR/姿态标定，随后关闭会影响帧率的传感器，再录制 240fps 视频，录制后离线推理并绘制轨迹。
2. 最优工程路线不是“单模型直接出轨迹”，而是：**球位锚定 + 标定先验 + TrackNetv6 多帧热图追踪 + 运动注意力 + 2D/3D 轨迹反演 + 物理先验约束 + FastVLM 质量审查**。
3. `TrackNetv6` 应作为球轨迹主检测器；`FastVLM` 用于场景理解、质量判断、先验解释和异常轨迹复核，不应作为逐帧主跟踪器。
4. 无 TrackMan 的正式使用场景下，模型优化依赖 iPhone 自采集数据、人工少量复核、主动学习和自动回归评估；TrackMan 只作为离线研究增强或小批量校准真值。

## 文献依据

| 方向 | 文献/报告结论 | 对本方案的要求 |
|---|---|---|
| TrackNet | 高速小目标跟踪适合多帧输入和热图输出 | `TrackNetv6` 输入必须是连续帧滑窗，不应只做单帧检测 |
| TrackNetV4 | 运动注意力图能增强快速体育目标跟踪 | 在 TrackNetv6 前后加入帧差分/运动注意力特征 |
| 单目 3D 球轨迹 | 2D monocular tracking 可通过 canonical 3D 和 reprojection consistency 估计 3D 轨迹 | 先稳定 2D，再做 3D 反演，不直接从单帧估计 carry |
| FastVLM | 高效视觉语言模型适合高分辨率 on-device 场景理解 | 用于质量审查和先验判断，不替代 TrackNetv6 |
| 高尔夫球动力学 | drag、lift、Magnus、reverse Magnus 对轨迹影响明显 | 物理模型要作为约束层，输出置信度和可解释失败原因 |
| Tutelman 高尔夫球飞行分析 | 球飞行由 launch conditions、空气动力、spin decay、wind、smash factor 等共同决定 | 将这些内容转成轨迹先验、异常约束和候选轨迹评分项 |
| Hausdorff/Fréchet 轨迹相似度 | Hausdorff 适合比较点集/曲线形状，Fréchet/DTW 更适合保留时间顺序 | Hausdorff 可用于候选轨迹形状评分，但不能单独作为最终时序轨迹指标 |

参考链接见文末“参考文献”。

## Tutelman 先验知识整理

从 tutelman.com 与高尔夫球飞行相关页面可抽取以下可工程化先验：

| 先验 | 来源页面 | 工程用途 |
|---|---|---|
| 飞行中主要受力是 drag、lift、weight | Ball Weight、Wind、Design Notes p3 | 物理融合层只接受这三类主力项，不引入不可解释虚拟力 |
| drag 与 lift 主要随相对空气速度平方变化 | Ball Weight、Wind | 候选轨迹速度越高，对风和升阻力越敏感；高速 early frames 权重要更高 |
| lift 垂直于相对空气路径和 spin axis，不总是竖直向上 | Wind、Design Notes p3 | 对 slice/hook/侧旋轨迹要允许横向 lift，而不是只拟合竖直抛物线 |
| 过多 lift 会造成 ballooning，向后分量会损失距离 | Wind、Design Notes p3 | 对“早段明显上拱且前进速度快速衰减”的轨迹降低置信度 |
| 真空/无升力轨迹不能代表真实高尔夫球飞行 | Design Notes p3 | 不能用简单抛物线作为最终模型，只能作为下限 baseline |
| spin decay 更接近百分比衰减，约 3.3%-4%/秒 | Spin Decay | 物理模拟中 spin(t) 使用指数衰减或近似百分比衰减 |
| launch conditions 包括球速、方向、spin，是飞行预测入口 | Design Notes p2、3D Launch | `launchEstimate` 应统一表达速度向量、发射角、方位角、spin axis |
| smash factor 是 ball speed / clubhead speed，不是固定 1.5 | Smash Factor | 视觉估计球速和杆速时，用合理区间校验，不把 1.5 当硬常数 |
| impact 到 launch 的 3D 关系受 loft、attack angle、face-to-path、club path 影响 | 3D Launch | 若 FastVLM/人体姿态估计出杆面或挥杆方向，可作为 launch direction 先验 |
| launch angle 与 spin 存在“ridge”，不是越高 launch/越低 spin 就越好 | Launch Optimize、What Matters | 物理融合时使用可行带，而非单点最优；避免过拟合某个参数 |
| ball speed 对 distance 的解释力强，但 launch/spin 在已优化装备上变化影响较平 | What Matters | 无 TrackMan 时，球速估计优先级高于精细 spin 估计 |
| 风影响的是球相对空气速度，顺风和逆风不对称 | Wind | 可选环境输入中加入风速/风向；无风数据时提高 carry 不确定性 |
| 3D ball flight 要考虑水平和竖直分量，slice/hook 由 spin axis 倾斜导致 | Nine Ball Flights、3D Launch | 顶视图轨迹和侧视图轨迹都应被评估，不能只看屏幕 2D 曲线 |
| 轨迹程序要用小步积分计算力和位置 | Design Notes p3、TrajectoWare | `TrajectoryFusionCoordinator` 使用数值积分，而不是一次性闭式距离公式 |

这些先验在本项目中只作为“约束和评分”，不直接覆盖 TrackNetv6 视觉检测结果。原因是视觉轨迹是实测证据，Tutelman 先验是物理合理性边界；两者冲突时应降低置信度并进入复核池。

补充说明：Tutelman 的 `Comparison of Trajectory Programs` 与 `Nine Ball Flights` 说明，球路判断必须同时看起始方向和后段曲率；因此本项目不能只做终点误差比较，而要对整段曲线和时序一致性一起评估。

## 总体流程

```
用户将底部圆圈对准球起始位置
  ↓
短时标定：雷达/LiDAR/IMU/相机姿态
  ↓
关闭影响 240fps 的传感器链路
  ↓
录制完整 240fps 击球视频
  ↓
impact 窗口定位：音频峰值 + 画面突变 + 球位 ROI
  ↓
TrackNetv6 多帧热图追踪
  ↓
运动注意力/帧差分增强
  ↓
2D 轨迹连续化：Kalman + 光流 + 多候选保留
  ↓
2D→3D 反演：相机标定 + canonical 3D + 重投影一致性
  ↓
物理融合：球速/杆头速度/发射角/旋转/drag/lift/Magnus
  ↓
FastVLM 场景与异常审查
  ↓
最终轨迹绘制到视频
```

## 节点计划与要求

### N0：球位圆圈对准

目标：把用户手动对准动作变成可复用的初始条件。

要求：
- 圆圈固定在预览层坐标系内，用户移动手机或微调画面，使球中心落入圆圈。
- 保存圆圈中心、半径、球 ROI、预览层到视频像素的映射。
- 点击拍摄前做一次球存在性检查，避免空 ROI 进入后续流程。

输出：
- `ballAnchorPointPx`
- `ballAnchorRadiusPx`
- `initialBallROI`
- `previewToVideoTransform`
- `alignmentConfidence`

验收标准：
- 用户确认后，球中心应落在圆圈半径 50% 范围内。
- 预览坐标映射到视频帧后误差 <= 5 px。

### N1：短时标定

目标：记录后续 3D 反演和物理融合需要的先验信息。

要求：
- 标定阶段可以启用雷达/LiDAR/IMU。
- 标定完成后必须关闭会降低视频帧率的传感器链路。
- 如果雷达不可用，使用 LiDAR/IMU/手动参数降级。

建议字段：
- `cameraHeightM`
- `cameraPitchDeg`
- `cameraYawDeg`
- `cameraRollDeg`
- `distanceToBallM`
- `ballAnchorWorldEstimate`
- `radarHeightM`
- `radarPitchDeg`
- `radarYawDeg`
- `calibrationSource`
- `calibrationConfidence`

输出：
- `calibration_sidecar.json`

验收标准：
- 标定 sidecar 完整率 100%。
- 标定结束后进入 240fps 录制前，确认实际帧率配置仍为 240fps。

### N2：240fps 视频录制

目标：获得完整击球视频，作为所有视觉推理的唯一主输入。

要求：
- 录制期间不打开会导致帧率下降的雷达/深度链路。
- 保留真实 `presentationTimeStamp`，不要只依赖名义 fps。
- 建议录制击球前 1 秒、击球后 3-5 秒。

输出：
- 原始 `.mov`
- `timeline.json`
- `camera.json`
- `quality.json`

验收标准：
- 实际 fps >= 235。
- 分辨率保持 1920x1080 或更高。
- 击球窗口未被截断。

### N3：Impact 窗口定位

目标：缩小 TrackNetv6 推理窗口，降低误检和计算成本。

输入：
- 音频峰值
- 画面运动突变
- N0 的球 ROI
- 用户点击录制时间

要求：
- 输出主 impact frame 和候选 impact frames。
- 保留不确定性，不要只输出单一硬判断。

输出：
- `impactFrameIndex`
- `impactTimeSeconds`
- `impactWindowFrames`
- `impactConfidence`

验收标准：
- 人工抽检 20 条，impact frame 误差 <= 3 帧。

### N4：TrackNetv6 主轨迹检测

目标：得到击球后高尔夫球的 2D 连续轨迹候选。

要求：
- 输入为连续帧滑窗，例如 3/5/7/9 帧配置可切换。
- 优先在 `initialBallROI` 延展区域推理，再根据轨迹方向扩展 ROI。
- 输出热图，而不是只输出 bbox；小球中心点应由热图峰值和置信度决定。
- 保留多候选轨迹，供后续物理融合筛选。

输出：
- `heatmaps`
- `ballCenterCandidates`
- `tracknetConfidence`
- `candidateTracks`

验收标准：
- 击球后前 10 帧至少命中 7 帧，MVP 阶段至少命中 5 帧。
- 最长连续轨迹段 >= 12 点，MVP 阶段 >= 8 点。

### N5：运动注意力增强

目标：提高高速模糊、遮挡、低可见度场景下的轨迹连续性。

要求：
- 参考 TrackNetV4 思路，使用帧差分、运动注意力图或光流热区作为辅助输入。
- 运动增强不能覆盖原始 TrackNetv6 置信度，必须单独记录贡献。

输出：
- `motionAttentionMap`
- `motionEnhancedCandidates`
- `motionContributionScore`

验收标准：
- 在低置信样本上，轨迹连续率较纯 TrackNetv6 不下降。
- 出现多候选时，运动注意力能帮助保留正确分支。

### N6：2D 轨迹连续化

目标：把逐帧候选点变成连续、可解释的 2D 轨迹。

要求：
- 使用 Kalman/光流做短缺失补点。
- 速度、方向、曲率作为异常过滤条件。
- 保留原始轨迹、平滑轨迹和补点轨迹，便于调试。

输出：
- `raw2DTrajectory`
- `smoothed2DTrajectory`
- `filled2DTrajectory`
- `outlierFrames`

验收标准：
- 重投影到视频帧后无明显漂移。
- 人工抽检 50 条，轨迹贴合通过率 >= 85%。

### N7：2D 到 3D 反演

目标：利用相机标定和轨迹几何，把 2D 图像轨迹估计为 3D 初始轨迹。

要求：
- 先使用 N1 的相机高度、俯仰角、球位锚点和地面平面。
- 使用重投影误差作为优化目标。
- 输出 3D 时必须带置信度，低置信时只展示 2D 轨迹。

输出：
- `estimated3DTrajectory`
- `reprojectionErrorPx`
- `trajectory3DConfidence`

验收标准：
- M1：重投影误差 <= 12 px。
- M2：重投影误差 <= 8 px。
- M3：重投影误差 <= 5 px。

### N8：球速、杆头速度、角度与物理融合

目标：把视觉轨迹和先验知识融合成最终可展示的飞行轨迹。

输入：
- 2D/3D 轨迹
- 标定 sidecar
- 视觉估计球速
- 视觉估计杆头速度
- 发射角/方位角
- 论文中整理的空气动力学和高尔夫先验

要求：
- 使用 drag、lift、Magnus 等物理约束。
- 使用 Tutelman 先验校验 launch conditions、spin decay、smash factor、wind effect 和 trajectory shape。
- 对不满足物理可行区间的轨迹降低置信度，而不是强行修正成“好看”的曲线。
- 保留每个先验对结果的影响权重。

输出：
- `launchEstimate`
- `physicsCorrectedTrajectory`
- `priorContribution`
- `finalTrajectoryConfidence`
- `tutelmanPriorChecks`

验收标准：
- 物理一致性通过率 M1 >= 80%，M2 >= 90%。
- 对异常轨迹能输出可解释失败原因。

### N9：FastVLM 场景与异常审查

目标：用 VLM 做非逐帧主检测的辅助判断。

适合任务：
- 判断画面是否清晰、球是否可能可见。
- 判断拍摄角度、球杆类型、场地类型。
- 解释为什么轨迹可能不可信。
- 对明显违反场景逻辑的轨迹加风险标签。

不适合任务：
- 不作为逐帧球中心真值。
- 不替代 TrackNetv6 热图追踪。

输出：
- `sceneDescription`
- `qualityFlags`
- `trajectoryPlausibility`
- `vlmReasoningSummary`

验收标准：
- VLM 输出只影响置信度和复核队列，不直接覆盖 TrackNetv6 轨迹点。

### N10：轨迹绘制与回放

目标：把最终轨迹稳定叠加到视频流中。

要求：
- 绘制层使用视频帧坐标，不使用预览层坐标。
- 支持显示原始点、平滑点、最终轨迹三种调试层。
- 支持导出分析 JSON 和带轨迹的视频。

输出：
- `trajectory_analysis.json`
- `trajectory_overlay.mov`
- App 内回放叠加层

验收标准：
- 轨迹线与球点无明显错位。
- 100 条人工抽检通过率达到 M3 >= 95%。

### N11：Hausdorff 距离轨迹评分

目标：用几何距离度量比较候选轨迹、物理投影轨迹和人工复核轨迹的形状相似度。

可用场景：
- 比较 `raw2DTrajectory` 与 `physicsCorrectedTrajectory` 重投影后的形状差异。
- 多候选轨迹竞争时，选择与物理投影最接近的候选。
- 自动评估中比较模型轨迹与人工复核轨迹。
- 发现“形状接近但时间错位”的轨迹，再交给 Fréchet/DTW 进一步判断。

推荐算法：
- 使用离散 Hausdorff 距离作为基础：
  - `H(A,B)=max(h(A,B),h(B,A))`
  - `h(A,B)=max_{a in A} min_{b in B} d(a,b)`
- 实际工程使用 `H95` 或 Modified Hausdorff Distance，降低单个误检点的破坏性。
- 对轨迹点按弧长重采样，避免某段帧数密集导致距离偏置。
- 距离单位统一为视频像素，并额外输出归一化距离：`hausdorffPx / ballAnchorRadiusPx`。
- 参考 trajectory clustering 文献，对 Hausdorff 做顺序修正或加时间惩罚，否则它只是“形状相近”而不是“飞行过程相近”。

限制：
- Hausdorff 不关心时间顺序，不能单独判断轨迹方向和速度。
- 对离群点敏感，必须使用百分位或 modified 版本。
- 只能评分“形状是否接近”，不能替代物理模型或 TrackNetv6 置信度。

输出：
- `hausdorffDistancePx`
- `hausdorffP95Px`
- `modifiedHausdorffPx`
- `trajectoryShapeScore`
- `temporalOrderPenalty`

验收标准：
- 人工复核轨迹与最终轨迹的 `hausdorffP95Px` M1 <= 20 px，M2 <= 12 px，M3 <= 8 px。
- 若 Hausdorff 低但时间顺序错误，必须由 `temporalOrderPenalty` 标记。

## 自动优化闭环

### 数据采集与标注

正式使用没有 TrackMan 时，持续优化依赖以下 iPhone 数据：

- 240fps 视频原始帧
- impact 前后窗口
- 初始球位圆圈 ROI
- 标定 sidecar
- TrackNetv6 热图和候选点
- FastVLM 质量标签
- 人工复核的少量关键帧和轨迹点

### 主动学习规则

以下样本自动进入复核池：

1. TrackNetv6 低置信但运动注意力强。
2. 轨迹中断超过 3 帧。
3. 多候选轨迹无法唯一选择。
4. 重投影误差超过阈值。
5. 物理融合判断速度/角度不合理。
6. FastVLM 判断场景不可信。
7. 圆圈初始球位和实际第一帧球点偏差过大。

### 每轮训练与评估

| 轮次 | 数据量 | 训练重点 | 输出 |
|---|---:|---|---|
| R0 | 10-20 条视频 | 端到端 MVP，人工复核轨迹点 | 初始评估集 |
| R1 | 50 条视频 | TrackNetv6 v0.1，击球后前 10 帧召回 | CoreML/ONNX 端侧模型 |
| R2 | 100 条视频 | 困难样本、负样本、运动注意力增强 | v0.2 |
| R3 | 200 条视频 | 多场景、多球杆、多光照泛化 | 内测模型 |

### 自动评估指标

| 指标 | 目标 |
|---|---:|
| 击球后前 10 帧召回率 | M1 >= 60%，M2 >= 75%，M3 >= 85% |
| 轨迹连续率 | M1 >= 50%，M2 >= 70%，M3 >= 80% |
| 2D 重投影误差 | M1 <= 12 px，M2 <= 8 px，M3 <= 5 px |
| 物理一致性通过率 | M1 >= 80%，M2 >= 90%，M3 >= 95% |
| 回放人工通过率 | M1 >= 70%，M2 >= 85%，M3 >= 95% |

## 推荐新增模块

| 模块 | 位置 | 作用 | 优先级 |
|---|---|---|---|
| `BallAnchorAlignmentView` | `GolfBallDetectionApp` | 底部圆圈对准球位 | P0 |
| `CalibrationCaptureCoordinator` | `GolfBallDetectionApp` | 标定并关闭影响帧率的传感器 | P0 |
| `PostShotTrajectoryAnalyzer` | `GolfBallDetectionApp` | 录制后统一分析入口 | P0 |
| `TrackNetV6Runner` | `GolfAnalysisKit` 或 App Core | TrackNetv6 推理封装 | P0 |
| `MotionAttentionPreprocessor` | `GolfAnalysisKit` | 帧差分/运动注意力生成 | P0 |
| `TrajectoryFusionCoordinator` | `GolfAnalysisKit` | 2D/3D/物理/VLM 融合 | P0 |
| `FastVLMSceneReviewer` | `GolfBallDetectionApp` | 场景质量与异常审查 | P1 |
| `TrajectoryEvaluationTool` | `tools/` | 自动回归评估 | P1 |

## 实施里程碑

### 第 1 周：对准与采集协议

- 完成圆圈对准 UI。
- 完成标定 sidecar。
- 完成 240fps 录制前后的帧率验证。

验收：
- 5 条视频完整输出 `calibration_sidecar.json`、`timeline.json`、`camera.json`。
- 实际 fps >= 235。

### 第 2-3 周：TrackNetv6 主轨迹

- 接入 TrackNetv6 推理。
- 支持 impact 窗口滑窗输入。
- 输出热图、候选点和轨迹 JSON。

验收：
- 20 条视频中，至少 14 条有可视轨迹。
- 击球后前 10 帧命中数平均 >= 5。

### 第 4-5 周：运动增强与轨迹融合

- 加入帧差分/运动注意力。
- 接入 Kalman/光流补点。
- 初步接入 2D→3D 反演和重投影误差。

验收：
- 轨迹连续率较纯 TrackNetv6 不下降。
- 重投影误差可自动统计。

### 第 6 周：FastVLM 与物理审查

- FastVLM 输出场景质量标签。
- 物理融合输出最终轨迹置信度。
- 回放层支持最终轨迹与调试轨迹切换。

验收：
- 每条视频输出 `trajectory_analysis.json`。
- 人工抽检 50 条，回放通过率 >= 85%。

## 风险

1. 雷达/LiDAR 与 240fps 视频录制同时运行可能导致帧率下降，因此必须分阶段。
2. FastVLM 不适合作为主轨迹检测器，只能作为辅助审查。
3. 单目 3D 反演存在深度歧义，必须保留置信度和重投影误差。
4. 物理模型会受旋转、风、球类型、击球点影响；无 TrackMan 时只能做概率约束。
5. 如果初始圆圈对准错误，后续 ROI、impact、TrackNetv6 都会被系统性带偏。

## 下一步

1. 先实现 `BallAnchorAlignmentView` 和 `calibration_sidecar.json`。
2. 接入 `TrackNetv6` 推理封装，定义热图输出 JSON 契约。
3. 新增 `PostShotTrajectoryAnalyzer`，串联 impact 窗口、TrackNetv6、轨迹 JSON。
4. 做第一批 10-20 条 iPhone 实拍视频，建立人工复核集。
5. 再接入运动注意力、FastVLM 审查和物理融合。

## 参考文献

1. TrackNet: A Deep Learning Network for Tracking High-speed and Tiny Objects in Sports Applications  
   https://huggingface.co/papers/1907.03698
2. TrackNetV4: Enhancing Fast Sports Object Tracking with Motion Attention Maps  
   https://tracknetv4.github.io/
3. Where Is The Ball: 3D Ball Trajectory Estimation From 2D Monocular Tracking  
   https://cvpr.thecvf.com/virtual/2025/35509
4. FastVLM: Efficient Vision Encoding for Vision Language Models  
   https://machinelearning.apple.com/research/fastvlm-efficient-vision-encoding
5. A review of dynamic models and measurements in golf  
   https://link.springer.com/article/10.1007/s12283-022-00387-0
6. The reverse Magnus effect in golf balls  
   https://link.springer.com/article/10.1007/s12283-020-0318-1
7. Predicting the Flight of a Golf Ball: Comparing a Physics-Based Aerodynamic Model to a Neural Network  
   https://docs.lib.purdue.edu/resec-isea/2022/session05/4/
