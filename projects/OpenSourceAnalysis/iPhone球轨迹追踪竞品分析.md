# iPhone 高尔夫球轨迹追踪 — 竞品分析与技术拆解

> 目标：分析市面上 iPhone 端高尔夫球轨迹追踪的两大技术路线，拆解闭源商业 App 和新发现的开源项目，给出复现路径。
> 日期：2026-04-22

## 一、市场上的两大技术路线

### 路线 A：手机端发射监测器（Launch Monitor）

手机放在球后方地面上（距球 30-60cm），利用高速相机追踪击球瞬间和球的初始飞行，推算球速、发射角、飞行距离。

代表产品：GolfTrak、GolfBoy

```
手机放球后方 → 实时球检测 → 击球检测（球消失/位置突变/音频）
  → 240fps 缓冲区回溯 → 击球后 2-5 帧球追踪
  → 像素位移 × 标定系数 / 帧间时间 = 球速
  → atan2(垂直位移, 水平位移) = 发射角
  → 物理模型外推 → carry 距离 + 落点
```

### 路线 B：视频弹道叠加（Shot Tracer）

录制击球视频后，逐帧检测球位置，连接成轨迹线叠加到视频上。

代表产品：Shot Tracer、Golf Shot Tracer - Auto Track、ShotCatch

```
录制视频（30/240fps）→ 逐帧球检测（背景差分/YOLO/CNN）
  → Kalman Filter 帧间关联 → 处理遮挡/模糊/丢失
  → 离散点 → 样条/Bezier 曲线拟合（物理约束：重力抛物线）
  → 视频帧上渲染轨迹线（辉光效果、渐变色）
```

### 两种路线技术对比

| 维度 | 路线 A（发射监测器） | 路线 B（弹道叠加） |
|------|-------------------|-------------------|
| 手机位置 | 球后方地面（~50cm） | 侧面/后方三脚架（3-10m） |
| 核心输出 | 球速、发射角、carry 距离 | 视频上的可视化轨迹线 |
| 实时性 | 击球后 1-2 秒出结果 | 录制后处理（5-30 秒） |
| 球检测难度 | 低（球近、像素大） | 高（球远、3-10 像素） |
| 距离标定 | 简单（手机到球距离已知） | 复杂（需 LiDAR 或参考物） |
| 精度 | 球速 ±5-10%，距离 ±10-15% | 轨迹形状准确，距离不精确 |
| 用户体验 | 需弯腰放手机 | 架好三脚架即可 |
| 适合场景 | 练习场测速 | 社交分享、挥杆回顾 |

## 二、闭源商业 App 深度拆解

### 2.1 GolfTrak — 手机端发射监测器

**产品定位**：将 iPhone 变成发射监测器，无需额外硬件。

**使用流程**：
1. 手机放在球后方地面（距球约 30-60cm），摄像头朝向球和目标方向
2. App 进入"等待击球"模式，实时监控球的位置
3. 击球瞬间：检测到球消失/运动 → 触发高速录制回放分析
4. 分析击球后前几帧中球的位置 → 计算球速、发射角、飞行方向
5. 结合物理模型推算 carry 距离和落点

**技术原理拆解**：

```
┌─────────────────────────────────────────────────────────┐
│  相机视角：球在画面中央偏下，目标方向在画面上方              │
│  距离：手机到球 ~50cm → 球在画面中约 50-100 像素直径        │
│  帧率：240fps 慢动作模式（iPhone 15 Pro+ 支持）            │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第一步：实时球检测                                        │
│  方案 A：YOLO CoreML 模型（精确但耗电）                    │
│  方案 B：传统 CV — 白色圆形检测（HoughCircles + 颜色过滤） │
│  方案 C：模板匹配（球在固定位置，简单高效）                 │
│  输出：球的像素坐标 (x, y) + 半径 r                        │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第二步：击球检测（impact detection）                      │
│  触发条件（任一满足）：                                     │
│    1. 球消失：连续 2+ 帧检测不到球                          │
│    2. 位置突变：帧间位移 > 阈值（球被击出）                 │
│    3. 音频触发：击球声能量峰值（参考 golf-clip SuperFlux）  │
│  240fps 缓冲区：持续缓存最近 0.5-1 秒的帧（120-240 帧）    │
│  触发后：回溯缓冲区，找到击球前最后一帧和击球后第一帧       │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第三步：击球后球追踪（关键 2-5 帧）                       │
│  @ 240fps，球速 150mph → 每帧移动 ~28cm                    │
│  在 50cm 距离下，28cm ≈ 画面宽度的 30-50%                  │
│  追踪方法：                                                │
│    帧 1：球刚离开原位，位移小，容易检测                     │
│    帧 2-3：球快速移动，可能有运动模糊                       │
│    帧 4-5：球可能已出画面（取决于发射角）                   │
│  Kalman Filter 预测 + 搜索窗口缩小                         │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第四步：像素位移 → 实际物理量                              │
│                                                            │
│  距离标定（关键步骤）：                                     │
│    已知：手机到球距离 d（~50cm，可用 LiDAR 精确测量）       │
│    已知：相机焦距 f（iPhone 内参）                          │
│    换算：实际位移 = 像素位移 × d / (f × 像素密度)          │
│                                                            │
│  球速计算：                                                │
│    v = Σ(帧间实际位移) / Σ(帧间时间)                       │
│    帧间时间 = 1/240 = 4.17ms                               │
│    多帧回归拟合提高精度                                     │
│                                                            │
│  发射角计算：                                               │
│    水平发射角(HLA) = atan2(横向位移, 纵向位移)             │
│    垂直发射角(VLA) = atan2(垂直位移, 水平位移)             │
│    注意：需要 3D 重建或假设球在特定平面内运动               │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第五步：物理模型外推                                      │
│  输入：球速 v, 发射角 θ, 旋转率 ω（查表估算）             │
│  弹道方程：空气阻力 + Magnus 效应 + 重力                   │
│  4 阶 Runge-Kutta 积分，dt=0.001s                          │
│  环境修正：风速、海拔、温度（参考 ClubUp 公式）            │
│  输出：carry 距离、total 距离、最高点、飞行时间             │
└─────────────────────────────────────────────────────────┘
```

**复现关键点**：
- 手机放球后方 vs 本项目 3-5m 侧面 → 视角不同，但球追踪原理相同
- GolfTrak 手机离球很近（~50cm），像素分辨率高，球大；本项目 3-5m 远，球更小
- LiDAR 可精确测量手机到球距离，解决标定问题
- 核心算法链：球检测 → 击球检测 → 帧间追踪 → 像素→距离转换 → 物理模型
- 本仓库已有大部分基础：SpeedCalculator（速度计算）、KalmanFilter2D（追踪）、SwingAudioDetector（击球检测）

**精度预期**：
| 参数 | GolfTrak 估计精度 | 本项目（3-5m）估计精度 |
|------|------------------|---------------------|
| 球速 | ±3-5%（球近、像素大） | ±5-10%（球远、像素小） |
| 发射角 | ±1-2°（多帧拟合） | ±2-4°（深度信息不足） |
| carry 距离 | ±5-10% | ±10-20% |
| 侧偏方向 | ±2-3° | ±3-5° |

### 2.2 Shot Tracer — 视频弹道叠加

**产品定位**：录制击球视频后自动检测球轨迹，叠加彩色弹道线，用于社交分享和挥杆分析。

**使用流程**：
1. 用手机录制击球视频（建议三脚架固定，侧面视角）
2. 录制完成后，App 自动或手动标记击球区域
3. 逐帧检测球的位置，连接成轨迹线
4. 在视频上叠加彩色弹道线（辉光效果），可导出分享

**技术原理拆解**：

```
┌─────────────────────────────────────────────────────────┐
│  录制视频                                                │
│  推荐：240fps 慢动作（球更清晰）或 30fps 普通（文件小）   │
│  三脚架固定 → 背景稳定 → 运动检测更容易                   │
│  手持 → 需要帧间配准（光流/特征点匹配）                   │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第一步：击球区域定位                                      │
│  自动方案：                                                │
│    1. 全帧运动检测 → 找到运动最剧烈的区域                  │
│    2. 人体检测 → 杆头区域 → 球原点                         │
│    3. 音频击球检测 → 定位击球帧                            │
│  手动方案：用户点击球的初始位置                             │
│  参考：golf-clip origin.py（YOLO 人体 + 杆身 + 杆头颜色） │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第二步：逐帧球检测                                        │
│                                                            │
│  方法 A — 传统 CV（Shot Tracer 早期版本可能使用）：        │
│    背景差分（帧间差 or MOG2）→ 运动区域                    │
│    → 形态学滤波（开运算去噪）                              │
│    → 小圆形物体筛选（面积、圆度、亮度）                    │
│    优点：快速、无需训练                                     │
│    缺点：背景复杂时误检多                                   │
│                                                            │
│  方法 B — AI 检测（现代版本）：                            │
│    YOLO/CNN 球检测模型 → 每帧定位球                        │
│    训练数据：Roboflow 高尔夫球数据集                       │
│    导出：CoreML 格式 → iPhone 端推理                       │
│    优点：鲁棒性强                                          │
│    缺点：需要训练数据、模型体积                             │
│                                                            │
│  方法 C — 混合方案（推荐）：                               │
│    YOLO 周期性检测（每 5-10 帧）→ 初始化/重置              │
│    + 帧间追踪（光流/模板匹配）→ 中间帧                     │
│    参考：本仓库 TrackingPipeline 的四层架构                 │
│                                                            │
│  难点：球在远处可能只有 3-10 像素，天空背景下白球容易检测， │
│  草地背景下困难。运动模糊在 240fps 下可缓解。              │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第三步：帧间关联与追踪                                    │
│                                                            │
│  Kalman Filter（参考 golf-clip kalman_tracker.py）：       │
│    状态向量：[x, y, vx, vy, ax, ay]（6 状态，含加速度）   │
│    预测模型：匀加速运动 + 重力（ay = -g）                  │
│    更新：检测到球时修正状态                                 │
│    Mahalanobis 距离异常检测：排除误检                      │
│                                                            │
│  处理丢失帧：                                              │
│    连续 N 帧未检测到 → 用 Kalman 预测填充                  │
│    超过阈值 → 标记轨迹中断                                 │
│                                                            │
│  处理遮挡：                                                │
│    球经过树木/建筑时可能被遮挡                              │
│    物理约束：球必须沿抛物线运动 → 用物理模型桥接遮挡段     │
└──────────────────────────┬──────────────────────────────┘
                           ↓
┌──────────────────────────┴──────────────────────────────┐
│  第四步：轨迹平滑与渲染                                    │
│                                                            │
│  曲线拟合：                                                │
│    检测到的离散点 → Bezier 曲线拟合                        │
│    参考 golf-clip trajectory-generator.ts：                │
│      二次 Bezier：B(t) = (1-t)²P0 + 2(1-t)tP1 + t²P2    │
│      形状偏移：模拟 draw/fade 的渐进弯曲                   │
│      高度乘数：low=0.15, medium=0.25, high=0.35           │
│                                                            │
│  渲染叠加（参考 golf-clip tracer-renderer.ts）：           │
│    3 层辉光效果：                                          │
│      外层：宽线 + 低透明度（辉光）                         │
│      中层：中等线宽 + 中等透明度                           │
│      内层：细线 + 高亮度（核心轨迹）                       │
│    物理缓动：球速快时轨迹密，慢时轨迹疏                    │
│    颜色渐变：起点→终点颜色过渡                             │
│    iPhone 实现：Core Graphics 或 Metal shader              │
└─────────────────────────────────────────────────────────┘
```

**复现关键点**：
- 球检测是核心难点：远距离下球只有 3-10 像素
- 背景对比度很重要：天空背景下白球容易检测，草地背景下困难
- 本仓库已有 golf-clip 的 trajectory-generator.ts 和 tracer-renderer.ts 可直接参考
- Ultralytics YOLO → CoreML 导出可直接用于 iPhone 端球检测
- 本仓库 TrackingPipeline 的四层追踪架构（YOLO + Vision + 光流 + Kalman）可扩展用于球追踪

### 2.3 其他商业 App

| App | 类型 | 技术特点 | 复现价值 |
|-----|------|---------|---------|
| Golf Shot Tracer - Auto Track | 弹道叠加 | MWM/Spark 出品，AI 自动检测 | YOLO 方案验证 |
| ShotCatch | 弹道叠加 | iPhone 15 兼容性问题 | 警示：需测试新设备 |
| Rapsodo MLM1 | 硬件+App | 专用硬件雷达+手机相机融合 | 硬件精度上限参考 |
| GolfBoy | 发射监测器 | 2025 新版，纯手机方案 | 新兴竞品 |
| 高尔夫击球轨迹 | 弹道叠加 | 中文 App Store | 国内市场参考 |

## 三、新发现的开源项目深度拆解

### 3.1 rucv/golf_ball — CNN 球检测 + Kalman 追踪

**仓库**：`github.com/rucv/golf_ball`
**论文**：arXiv:2012.09393 "Efficient Golf Ball Detection and Tracking Based on CNNs and Kalman Filter"
**语言**：Python（PyTorch 1.0）
**复现价值**：⭐⭐⭐⭐⭐

**技术架构**：

```
基于 jwyang/faster-rcnn.pytorch 的 Faster R-CNN 实现

模型选择：
  backbone: VGG16 或 ResNet-101
  检测头: Faster R-CNN（RPN + ROI Pooling + 分类回归）
  类别: pascal_voc 21 类（可替换为高尔夫球单类）

训练管线：
  trainval_net.py
    → 数据加载: roibatchLoader（支持 VOC/COCO 格式）
    → 优化器: SGD（lr=0.001, momentum=0.9, weight_decay=0.0005）
    → 训练: 默认 20 epochs，每 100 iter 显示 loss
    → 保存: models/faster_rcnn_{session}_{epoch}_{step}.pth

推理管线：
  demo.py
    → 加载预训练模型
    → 图像预处理: 减均值 + 多尺度缩放（保持最大边 ≤ MAX_SIZE）
    → 前向推理: RPN → ROI → 分类 + 回归
    → NMS 后处理（阈值 0.3）
    → 可视化: vis_detections（置信度 > 0.5 画框）
    → 支持 webcam 实时检测

关键模块：
  lib/model/faster_rcnn/   — VGG16/ResNet backbone
  lib/model/rpn/           — Region Proposal Network
  lib/roi_data_layer/      — 数据加载 + mini-batch 采样
  lib/model/roi_layers/    — ROI Align/Pooling + NMS
```

**论文核心方法（两阶段检测）**：

```
第一阶段：候选区域提取
  传统 CV 方法（非 RPN）：
    1. 帧间差分 → 运动区域
    2. 形态学滤波 → 去噪
    3. 连通域分析 → 候选区域
  优点：大幅减少 CNN 需要处理的区域数量

第二阶段：CNN 分类
  对每个候选区域：
    裁剪 + 缩放到固定大小 → CNN → 是否为球（二分类）
  CNN 架构：轻量级（论文中为自定义小网络，非 Faster R-CNN）

追踪：
  Kalman Filter 帧间关联
  处理遮挡和丢失帧
```

**对本项目的复现路径**：

```
方案 A（直接使用 Faster R-CNN）：
  1. 下载 Roboflow 高尔夫球数据集（VOC 格式）
  2. 修改 trainval_net.py 的类别为 ['__background__', 'golf_ball']
  3. 训练 ResNet-101 backbone
  4. 导出 → CoreML（需要 coremltools 转换 PyTorch → CoreML）

方案 B（推荐：使用 YOLO 替代）：
  1. Roboflow 数据集 → YOLO 格式
  2. YOLO11 训练: yolo train data=golf_ball.yaml model=yolo11n.pt epochs=100
  3. 导出: model.export(format='coreml')
  4. 集成到 GolfBallDetectionApp

方案 B 优势：
  - YOLO 比 Faster R-CNN 快 10-50 倍
  - Ultralytics 原生支持 CoreML 导出
  - 官方 iOS App (ultralytics/yolo-ios-app) 提供完整推理框架
  - YOLO11n 模型仅 ~6MB，适合移动端
```

### 3.2 jjmlovesgit/Golf_tracker — VisionAgent Florence2 + SAM2

**仓库**：`github.com/jjmlovesgit/Golf_tracker`
**语言**：Python（VisionAgent SDK + OpenCV + Gradio）
**复现价值**：⭐⭐⭐

**技术架构**：

```
核心管线（Golf_tracker.py）：

1. 帧提取
   T.extract_frames_and_timestamps(input_path, fps=output_fps)
   → 按指定 FPS 提取视频帧和时间戳

2. 视频目标追踪
   T.florence2_sam2_video_tracking("Ball", frames)
   → Florence2 模型：开放词汇目标检测（文本 "Ball" → 检测框）
   → SAM2 模型：视频目标分割追踪（跨帧关联）
   → 输出：每帧的检测列表 [{bbox, score, label}, ...]

3. 运动过滤
   filter_moving_objects(tracks, confidence_thresh, move_thresh)
   → 过滤低置信度检测（默认阈值 0.99，非常严格）
   → 过滤静止物体（帧间位移 < move_thresh）
   → 使用欧氏距离判断是否移动

4. 轨迹可视化
   指数衰减尾迹：alpha = exp(-0.2 × age)
   → 新检测点不透明，旧检测点逐渐透明
   → 橙色圆点（半径 4px）叠加到帧上
   → cv2.addWeighted 混合

5. 视频输出
   T.save_video(annotated_frames, output_path, fps=output_fps)

Gradio UI 参数：
  output_fps: 1-30（默认 15）
  movement_thresh: 0.001-0.05（默认 0.001，高灵敏度）
  confidence_thresh: 0.0-1.0（默认 0.99，极严格）
  trace_tail_len: 5-100（默认 30）
```

**优缺点分析**：

| 方面 | 评价 |
|------|------|
| 开放词汇检测 | Florence2 无需训练即可检测 "Ball"，零样本能力强 |
| 视频追踪 | SAM2 提供像素级分割追踪，精度高 |
| 依赖 | 需要 VisionAgent API key（LandingAI 云服务），不可离线 |
| 速度 | 云端推理，延迟高，不适合实时 |
| iPhone 移植 | Florence2/SAM2 模型太大，无法直接在 iPhone 上运行 |

**对本项目的借鉴价值**：
- 指数衰减尾迹可视化方案（`alpha = exp(-0.2 × age)`）可直接用于轨迹渲染
- 运动过滤逻辑（置信度 + 位移阈值）可参考
- Florence2 的开放词汇检测思路：未来 Apple 可能提供类似的 on-device 模型
- 不建议直接移植：云端依赖 + 模型体积不适合 iPhone

### 3.3 natterman12/Golf-Ball-Tracking-and-Speed-Detection — 经典 CV 追踪 + 速度计算

**仓库**：`github.com/natterman12/Golf-Ball-Tracking-and-Speed-Detection`
**语言**：Python（OpenCV + imutils）
**复现价值**：⭐⭐⭐

**技术架构**：

```
核心管线（ball_tracking_Copy.py）：

1. 颜色空间球检测
   HSV 颜色范围：绿色球 H(29-64), S(86-255), V(6-255)
   → GaussianBlur(11,11) 去噪
   → cv2.inRange(hsv, greenLower, greenUpper) 颜色掩码
   → erode(2次) + dilate(2次) 形态学滤波
   → findContours → 最大轮廓 → minEnclosingCircle
   → 输出：球心坐标 (x, y) + 半径 r

2. 速度计算（触发线方法）
   定义 ROI 矩形区域，包含两条垂直触发线
   已知两线间距离 = 12 ft
   球经过第一条线 → 记录 tim1
   球经过第二条线 → 记录 tim2
   速度 = 12 ft / (tim2 - tim1)

   关键代码：
     if x <= coord[1][0]:  # 球进入第一条线
         tim1 = time.time()
     if x <= coord[0][0]:  # 球经过第二条线
         tim2 = time.time()
         speed = dist / (tim2 - tim1)  # ft/s

3. 轨迹可视化
   deque 缓存历史位置（默认 64 帧）
   线条粗细：thickness = sqrt(buffer / (i+1)) × 1.5
   → 新点粗、旧点细，形成渐变尾迹
```

**优缺点分析**：

| 方面 | 评价 |
|------|------|
| 简单直接 | 纯 OpenCV，无需 AI 模型，代码 ~170 行 |
| 颜色依赖 | 只能检测绿色球，白色高尔夫球需修改 HSV 范围 |
| 速度计算 | 触发线方法需要固定相机 + 已知物理距离 |
| 精度 | 使用 time.time() 计时，精度受系统调度影响 |
| 鲁棒性 | 背景中有绿色物体会误检 |

**对本项目的借鉴价值**：
- 速度计算的"触发线"思路：可改为"已知 LiDAR 距离的两个参考点"
- 轨迹可视化的渐变粗细方案（`sqrt(buffer/i) × 1.5`）
- HSV 颜色检测作为 YOLO 的补充方案（低光环境下 YOLO 可能失效）
- 不建议直接移植：颜色检测方案不够鲁棒，速度计算方法不适用于高尔夫场景

### 3.4 Ultralytics YOLO → CoreML 管线（关键工具链）

**不是单一仓库，而是一套完整的训练→部署管线**。

```
训练端（Mac/PC/云端）：
  pip install ultralytics

  # 准备数据（Roboflow 导出 YOLO 格式）
  # golf_ball.yaml:
  #   train: ./train/images
  #   val: ./valid/images
  #   nc: 1
  #   names: ['golf_ball']

  # 训练
  yolo train data=golf_ball.yaml model=yolo11n.pt epochs=100 imgsz=640

  # 导出 CoreML
  from ultralytics import YOLO
  model = YOLO('runs/detect/train/weights/best.pt')
  model.export(format='coreml', nms=True)
  # 输出: best.mlpackage（~6MB for YOLO11n）

部署端（iPhone）：
  参考 ultralytics/yolo-ios-app：
    1. 将 .mlpackage 拖入 Xcode 项目
    2. 使用 Vision VNCoreMLRequest 加载模型
    3. 每帧推理 → 检测框 + 置信度 + 类别
    4. 后处理：NMS + 置信度过滤

  性能预期（iPhone 17 Pro Max，Neural Engine）：
    YOLO11n: ~5ms/帧 → 200fps 推理能力
    YOLO11s: ~8ms/帧 → 125fps
    YOLO11m: ~15ms/帧 → 66fps
    240fps 视频逐帧分析完全可行
```

### 3.5 Roboflow 高尔夫球数据集

多个预标注数据集可用于训练球检测模型：

| 数据集 | 图片数 | 格式 | 特点 |
|--------|--------|------|------|
| golf-ball-detection | ~500+ | VOC/YOLO/CreateML | 多角度、多背景 |
| golfball | ~300+ | VOC/YOLO | 草地/天空背景 |
| golf-ball-detector | ~200+ | YOLO | 练习场场景 |

**CreateML 格式**可直接用于 Apple CreateML 训练（无需 Python），但 YOLO 训练效果通常更好。

### 3.6 已有四个项目中与球追踪相关的代码

| 项目 | 相关代码 | 用途 |
|------|---------|------|
| golf-clip | `kalman_tracker.py` | 6 状态 Kalman（含重力 + Mahalanobis 异常检测） |
| golf-clip | `trajectory_physics.py` | 3D 物理弹道（发射参数提取 + 抛物线积分） |
| golf-clip | `landing.py` | 落点估算（音频+帧边界+物理回退） |
| golf-clip | `trajectory-generator.ts` | Bezier 弹道曲线生成 |
| golf-clip | `tracer-renderer.ts` | 3 层辉光轨迹渲染 |
| PiTrac | `golf_ball.cpp` | 球检测（HSV + 移动检测 + 多球平均） |
| PiTrac | `ball_image_proc.cpp` | HoughCircles + Canny + CLAHE 球图像处理 |
| PiTrac | `gs_calibration.h` | 相机标定（像素→距离系数） |

## 四、学术论文

### "Efficient Golf Ball Detection and Tracking Based on CNNs and Kalman Filter"

**论文**：arXiv:2012.09393
**配套代码**：rucv/golf_ball（见 3.1 节）

**核心贡献**：
1. 两阶段检测：传统 CV 候选区域提取 → CNN 分类，比纯 CNN 快 5-10 倍
2. Kalman Filter 帧间追踪：处理遮挡和丢失帧
3. 在高尔夫转播画面上验证：球在画面中仅 3-8 像素

**与本项目的关系**：
- 论文场景（转播画面）与本项目（3-5m 手机录制）不同
- 但"小目标检测 + Kalman 追踪"的方法论完全适用
- 两阶段方法可减少 iPhone 端计算量：先运动检测缩小搜索范围，再 YOLO 精确检测

## 五、复现路线图

### 阶段 1：球检测能力（对标 Shot Tracer 核心）

```
目标：在 240fps 视频中逐帧检测高尔夫球

步骤：
  1. 数据准备
     Roboflow 高尔夫球数据集 → YOLO 格式
     + 自采数据（DatasetCollectionPlatform 采集）
     + 数据增强（模糊、缩放、旋转、亮度变化）

  2. 模型训练
     YOLO11n 训练（~100 epochs）
     验证指标：mAP@0.5 > 0.85, mAP@0.5:0.95 > 0.60

  3. CoreML 导出
     model.export(format='coreml', nms=True)
     → best.mlpackage（~6MB）

  4. iPhone 集成
     GolfBallDetectionApp 中集成 VNCoreMLRequest
     240fps 视频逐帧推理（YOLO11n ~5ms/帧，完全可行）

  5. 验证
     在练习场实拍视频上测试检测率
     目标：天空背景 > 95%，草地背景 > 80%

需要的参考代码：
  - rucv/golf_ball 的模型架构参考
  - Roboflow 数据集
  - ultralytics/yolo-ios-app 的 CoreML 推理框架
```

### 阶段 2：球追踪 + 速度计算（对标 GolfTrak 核心）

```
目标：追踪击球后球的初始飞行，计算球速和发射角

步骤：
  1. 击球检测
     本仓库 SwingAudioDetector（音频）
     + 球位置突变检测（视觉）
     + golf-clip SuperFlux 多特征评分增强
     → 精确 impact timestamp（±4ms @ 240fps）

  2. 击球后球追踪
     扩展 KalmanFilter2D → 6 状态（加入加速度/重力）
     参考 golf-clip kalman_tracker.py
     追踪击球后 2-10 帧（8-42ms）中球的位置
     Mahalanobis 距离异常检测排除误检

  3. 距离标定
     LiDAR 测量手机到球的距离（pre-shot）
     iPhone 相机内参（焦距、像素密度）
     像素位移 × 距离 / (焦距 × 像素密度) = 实际位移
     参考 PiTrac gs_calibration.h 的标定流程

  4. 球速计算
     多帧位移序列 → 线性回归拟合速度
     参考本仓库 SpeedCalculator 的 regressionSpeed() 方法
     3D 修正：SwingPlaneCorrector 的思路扩展到球运动

  5. 发射角计算
     垂直位移 / 水平位移 → atan2 → 垂直发射角
     横向位移 / 纵向位移 → atan2 → 水平发射角
     LiDAR 深度信息辅助 3D 重建

需要的参考代码：
  - golf-clip kalman_tracker.py（6 状态 Kalman）
  - PiTrac gs_calibration.h（标定系数）
  - 本仓库 SpeedCalculator + KalmanFilter2D
```

### 阶段 3：轨迹预测 + 可视化（对标 Shot Tracer 输出）

```
目标：从球速+发射角预测完整飞行轨迹，叠加到视频上

步骤：
  1. 弹道计算
     方案 A（快速可视化）：golf-clip Bezier 模型
     方案 B（精确预测）：3D 物理模型（空气阻力 + Magnus）
     参考 轨迹预测可借鉴分析.md 第 2.4 节

  2. 环境修正
     ClubUp 环境修正公式（风/海拔/温度/雨）
     物理模型中直接调整空气密度 ρ
     OpenWeather API 获取实时天气

  3. 距离约束
     GoBirdie SG 基线表 + ClubUp 球杆距离库
     预测距离应在球杆类型的 ±20% 范围内
     超出范围 → 降低置信度

  4. 轨迹渲染
     参考 golf-clip tracer-renderer.ts
     3 层辉光效果（Core Graphics 或 Metal）
     物理缓动 + 颜色渐变
     叠加到原始视频帧上

需要的参考代码：
  - golf-clip trajectory-generator.ts + tracer-renderer.ts
  - golf-clip trajectory_physics.py
  - ClubUp DistanceCalcViewModel.swift
  - GoBirdie app.js（SG 基线表）
```

### 阶段 4：融合方案（本项目独有优势）

```
目标：结合间接推算和直接追踪，实现更高精度

融合策略：
  间接推算（杆头速度 × Smash Factor → 球速）
    + 直接追踪（球初始飞行 2-5 帧 → 球速）
    → 加权融合（按各自置信度）
    → 更高精度的球速和发射角

  人体姿态分析（Vision 3D Pose）
    → 挥杆质量评估
    → 攻击角推算 → 修正发射角
    → 杆面角推算 → 修正侧旋方向

  历史数据积累
    → 个性化 Smash Factor（不同球杆）
    → 个性化旋转率模型
    → 个性化距离模型

本项目已有的独特优势：
  ✅ SpeedCalculator — 杆头速度（四种方法融合）
  ✅ SwingPlaneCorrector — 3D 挥杆几何恢复
  ✅ LagAnalyser — 杆身前倾/释放角度
  ✅ TrackingPipeline — 四层追踪架构
  ✅ SwingAudioDetector — 音频击球检测
  ✅ DatasetCollectionPlatform — 数据采集闭环
  ✅ Vision 3D Pose — 17 个 3D 关节点
  ✅ LiDAR — 距离标定 + 深度信息
```

## 六、对本项目的建议

### 短期（1-2 周）
- 用 Ultralytics YOLO11n + Roboflow 数据集训练球检测 CoreML 模型
- 集成到 GolfBallDetectionApp，验证 240fps 逐帧检测能力
- 目标：天空背景检测率 > 95%

### 中期（2-4 周）
- 在 PostCaptureAnalysisEngine 中增加击球后球追踪（前 2-10 帧 @ 240fps）
- 扩展 KalmanFilter2D 为 6 状态（加入重力加速度）
- LiDAR 距离标定 → 像素位移 → 实际球速
- 目标：球速估算精度 ±10%

### 长期（1-2 月）
- 实现完整物理弹道模型（空气阻力 + Magnus 效应）
- 融合间接推算（杆头速度 × Smash Factor）和直接追踪（球初始飞行）
- 环境修正集成（ClubUp 公式 + OpenWeather API）
- 轨迹可视化渲染（3 层辉光 + 物理缓动）
- 目标：carry 距离预测精度 ±15%

