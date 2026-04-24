# 参考代码索引

从四个开源项目中提取的、与轨迹预测直接相关的核心代码文件。

## golf-clip（TypeScript + Python）

| 文件 | 用途 | 移植目标 |
|------|------|---------|
| `trajectory-generator.ts` | Bezier 弹道曲线生成（形状偏移 + 高度乘数） | Swift：快速可视化弹道叠加 |
| `tracer-renderer.ts` | 弹道线渲染（3 层辉光 + 物理缓动 + 路径插值） | Core Graphics / Metal |
| `audio-detector.ts` | 音频击球检测（SuperFlux + 多特征评分 + 衰减比） | Accelerate vDSP |
| `trajectory_physics.py` | 3D 物理弹道（发射参数提取 + 抛物线积分 + 弹道形状分类） | Swift：精确落点预测 |
| `kalman_tracker.py` | 6 状态卡尔曼滤波（含重力加速度 + Mahalanobis 异常检测） | 扩展现有 KalmanFilter2D |
| `landing.py` | 落点估算（音频着陆检测 + 帧边界检测 + 物理回退） | Swift：多方法落点融合 |
| `origin.py` | 球原点检测（YOLO 人体 + 杆身线段 + 杆头颜色 + 多方法共识） | 参考检测管线设计 |

## ClubUp（Swift）

| 文件 | 用途 | 移植目标 |
|------|------|---------|
| `DistanceCalcViewModel.swift` | 环境距离修正（风/海拔/温度/雨）+ 二分搜索选杆 | 直接复用 |
| `Calculation.swift` | 风向系数表 + 球位/坡度因子 + OpenWeather API | 直接复用 |
| `Club.swift` | 球杆数据模型 + 排名体系 + 工厂方法 | 适配 SwiftData |
| `HelperMethods.swift` | 单位转换（码↔米、°F↔°C、mph↔km/h） | 直接复用 |

## GoBirdie-Desktop（JavaScript + Rust）

| 文件 | 用途 | 移植目标 |
|------|------|---------|
| `app.js` | SG 基线表（Tee/Fairway/Rough/Green 4 张）+ `computeStrokesGained()` + `interpolateBaseline()` 线性插值 + Haversine GPS 距离 | Swift：挥杆质量评估 + 距离先验约束 |
| `nlg-engine.js` | NLG 洞察引擎（模板评估 + 严重度/层级排序 + 正面上限控制） | Swift：AI 分析报告生成 |
| `nlg-templates.js` | 35+ 条 NLG 模板（SG 分类诊断 + 中英韩三语 + 随机变体） | 参考模板设计模式 |
| `models.rs` | 数据模型（GolfRound/Scorecard/GolfShot/ClubType/GpsPoint + Haversine 距离） | Swift：数据结构参考 |

## PiTrac（C++ / OpenCV）

| 文件 | 用途 | 移植目标 |
|------|------|---------|
| `golf_ball.h` | 球数据模型（位置/速度/旋转/颜色/标定参数 + 物理常量 Cd=0.2, m=0.04593kg） | Swift：球物理参数参考 |
| `golf_ball.cpp` | 球检测实现（HSV 颜色范围 + 球移动检测 + 多球平均 + 飞行结果输出） | 参考检测逻辑 |
| `gs_results.h` | 测量结果结构（speed_mph/hla_deg/vla_deg/back_spin_rpm/side_spin_rpm） | Swift：结果数据结构 |
| `gs_shot_parameters.h` | 击球参数枚举（BallVelocity/HLA/VLA + 参数选择性平均） | 参考参数管理模式 |
| `gs_calibration.h` | 相机标定（自动标定 + 焦距确定 + 双摄像头位置常量 + 标定板流程） | 参考 iPhone 距离标定 |
| `ball_image_proc.cpp` | 球图像处理核心（HoughCircles 参数调优 + Canny 边缘 + CLAHE 增强 + 椭圆检测） | 参考球检测管线设计 |

## golf_ball（Python / PyTorch — Faster R-CNN 球检测）

| 文件 | 用途 | 移植目标 |
|------|------|---------|
| `demo.py` | Faster R-CNN 推理管线（图像预处理 + 多尺度缩放 + NMS 后处理 + 可视化） | 参考检测管线设计 |
| `trainval_net.py` | 训练管线（VGG16/ResNet backbone + SGD 优化 + checkpoint 保存） | 参考训练流程 |

## Golf_tracker（Python / VisionAgent SDK — Florence2 + SAM2）

| 文件 | 用途 | 移植目标 |
|------|------|---------|
| `Golf_tracker.py` | 完整追踪管线（帧提取 → Florence2 检测 → SAM2 追踪 → 运动过滤 → 指数衰减尾迹渲染） | 参考追踪+可视化方案 |

## Golf-Ball-Tracking-and-Speed-Detection（Python / OpenCV — 颜色追踪 + 速度计算）

| 文件 | 用途 | 移植目标 |
|------|------|---------|
| `ball_tracking_Copy.py` | HSV 颜色球检测 + 触发线速度计算 + 渐变粗细尾迹可视化 | 参考速度计算逻辑 |
