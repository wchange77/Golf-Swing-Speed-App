# golf-clip 项目分析（iPhone 17 Pro Max 可用性评估）

> 仓库：`elicoon/golf-clip`
> 语言：TypeScript (React/Vite) + Python (FastAPI)
> 定位：Browser + Mac Desktop app，将 iPhone 高尔夫录像转为带弹道追踪的 YouTube-ready 剪辑

## 一、项目概述

golf-clip 是一个客户端优先的高尔夫视频处理工具，核心流程：

```
视频 → FFmpeg 音频提取 → 带通滤波(1-8kHz) → 瞬态检测
    → 7 特征加权评分 → 去重(25s 窗口)
    → YOLO 人体检测 → 杆身线段 + 杆头检测 → 击球原点
    → 用户标记落点 → 物理弹道生成 → Bezier 平滑
    → WebCodecs 导出带弹道叠加的 MP4
```

### 技术栈

| 层 | 浏览器端 | 桌面端（已暂停） |
|----|---------|----------------|
| 前端 | TypeScript, React 18, Vite, Zustand | — |
| 音频处理 | FFmpeg WASM, Essentia.js | librosa, OpenCV |
| 视频导出 | WebCodecs API, mp4-muxer | OpenCV |
| 弹道 | 物理模型 + 二次 Bezier | — |
| 检测 | — | YOLO (ultralytics) |

## 二、核心算法详解

### 2.1 音频击球检测

**原理**：高尔夫击球声在 1000-8000Hz 频段有显著能量特征，属于尖锐瞬态信号。

**算法流程**：
1. FFmpeg 提取音频 → 44100Hz 采样率
2. 带通滤波（1000-8000Hz），中心频率 4500Hz
3. SuperFluxExtractor 瞬态检测（帧大小 2048，跳步 256）
4. 对每个检测到的 onset 提取窗口特征：
   - **频谱质心** (SpectralCentroidTime)：击球声质心通常较高
   - **频谱平坦度** (Flatness)：击球声频谱较平坦
   - **onset 强度**：峰值高度
   - **衰减比** (decayRatio)：真实击球衰减快（比值低），空挥衰减慢（比值高）
5. 25 秒最小间隔去重（高尔夫挥杆间隔）
6. 多特征加权置信度评分

**关键参数**：
```
frequencyLow: 1000 Hz
frequencyHigh: 8000 Hz
minStrikeInterval: 25.0 秒
sensitivity: 0.5 (阈值范围 0.02-0.10)
frameSize: 2048
hopSize: 256
combine: 20ms（双 onset 合并阈值）
```

### 2.2 球原点检测（YOLO + 杆身/杆头分析）

**桌面端 Python 实现**（`apps/desktop/backend/detection/`）：
1. YOLO 人体检测定位挥杆者
2. 线段检测识别杆身方向
3. 杆头颜色分析定位击球点
4. 综合评分确定球的起始位置

**涉及模块**：
- `origin.py` — 球原点定位主逻辑
- `pipeline.py` — 检测流水线编排
- `detection_scorer.py` — 多特征评分
- `kalman_tracker.py` — 卡尔曼滤波追踪
- `flow_tracker.py` — 光流追踪
- `perspective.py` — 透视变换
- `ball_template.py` — 球模板匹配

### 2.3 物理弹道生成

**算法**：二次 Bezier 曲线，控制点计算使曲线在 t=0.5 处精确通过顶点。

```
B(t) = (1-t)²·P0 + 2(1-t)t·P1 + t²·P2

其中 P1 = 2·apex - 0.5·(P0 + P2)
```

**弹道参数**：
| 参数 | 选项 | 值 |
|------|------|-----|
| 高度 | low / medium / high | 弧高乘数 0.15 / 0.25 / 0.35 |
| 弹道形状 | hook / draw / straight / fade / slice | 横向偏移 -0.15 ~ +0.15 |
| 飞行时间 | 用户配置 | 秒 |
| 采样密度 | 固定 | 60 点/秒 |

**坐标系**：归一化 0-1 坐标，默认原点 (0.5, 0.85)（画面底部中央）。

## 三、iPhone 17 Pro Max 可用性评估

### 3.1 可直接移植的算法/理论

| 算法 | 可用性 | 移植难度 | 说明 |
|------|--------|---------|------|
| 音频击球检测逻辑 | ✅ 可用 | 中 | 算法逻辑清晰，需替换 Essentia.js → Apple Accelerate/vDSP |
| 带通滤波 (1-8kHz) | ✅ 可用 | 低 | vDSP 原生支持 |
| 频谱分析（质心、平坦度） | ✅ 可用 | 低 | Accelerate FFT 原生支持 |
| 衰减比计算 | ✅ 可用 | 低 | 纯数学，直接移植 |
| 25s 去重窗口 | ✅ 可用 | 极低 | 简单时间戳比较 |
| 物理弹道模型 | ✅ 可用 | 低 | 纯数学 Bezier 曲线，直接翻译为 Swift |
| 弹道形状参数 | ✅ 可用 | 极低 | 常量表直接复用 |
| YOLO 人体检测 | ✅ 可用 | 中 | CoreML 转换 YOLO 模型，或直接用 Vision VNDetectHumanBodyPoseRequest |
| 卡尔曼滤波追踪 | ✅ 可用 | 低 | 标准算法，Swift 实现成熟 |
| 多特征加权评分 | ✅ 可用 | 低 | 纯逻辑，直接移植 |

### 3.2 需要平台适配的部分

| 原始技术 | iPhone 替代方案 | 适配工作量 |
|---------|---------------|-----------|
| Essentia.js (WASM) | Apple Accelerate + vDSP + AVAudioEngine | 中等 — 需重写音频处理管线 |
| WebCodecs API | AVFoundation AVAssetWriter | 中等 — API 不同但概念相似 |
| FFmpeg WASM 音频提取 | AVAssetReader + AVAudioMix | 低 — AVFoundation 原生支持 |
| YOLO (ultralytics Python) | Vision framework / CoreML | 低 — Apple 已有成熟方案 |
| Canvas 2D 弹道渲染 | Core Graphics / Metal | 低 — CG 路径绘制更高效 |
| Zustand 状态管理 | SwiftUI @Observable | 不适用 — 架构不同 |
| React 组件 | SwiftUI View | 不适用 — 需重写 UI |

### 3.3 不可直接使用的部分

- **WebCodecs 导出管线**：浏览器特有 API，需完全替换为 AVFoundation
- **Essentia.js WASM 模块**：需替换为 Apple 原生音频分析框架
- **Supabase 反馈服务**：后端特定，与 iPhone 端无关
- **Playwright E2E 测试**：浏览器测试框架，不适用

## 四、与本仓库对接建议

### 4.1 → AppleOSDatasetCollectorApp

**音频击球检测** 可集成到采集端，实现自动标记挥杆事件：
- 在 240fps 录制时同步录音
- 实时音频分析检测击球时刻
- 自动在 JSONL 中标记 `strike_timestamp`
- 用于后续自动裁剪训练数据片段

**实现路径**：
```swift
// AVAudioEngine 实时音频分析
let audioEngine = AVAudioEngine()
let inputNode = audioEngine.inputNode
inputNode.installTap(onBus: 0, bufferSize: 2048, format: nil) { buffer, time in
    // 1. 带通滤波 1000-8000Hz (vDSP)
    // 2. 瞬态检测 (能量包络 + 峰值检测)
    // 3. 频谱特征提取 (FFT → 质心 + 平坦度)
    // 4. 衰减比计算
    // 5. 置信度评分 → 触发标记
}
```

### 4.2 → GolfBallDetectionApp

**物理弹道模型** 可用于球轨迹预测和验证：
- 检测到球后，用 Bezier 模型预测飞行路径
- 与实际检测轨迹对比，评估检测精度
- 弹道形状参数（draw/fade/slice）可作为训练标签

**球原点检测思路** 可参考：
- YOLO 人体检测 → Vision VNDetectHumanBodyPoseRequest（已有）
- 杆身线段检测 → VNDetectContoursRequest
- 杆头区域定位 → 结合骨架关键点推算

### 4.3 → DatasetCollectionPlatform

**自动裁剪逻辑** 可用于数据采集自动化：
- 音频检测击球 → 自动确定片段起止时间
- 25s 去重窗口 → 避免重复采集
- 置信度评分 → 自动质量筛选

## 五、深度可行性分析

### 5.1 音频击球检测 — 代码逻辑中文逐行解读

#### 核心检测流程（`audio-detector.ts` → `detectStrikes()`）

```
输入：Float32Array 音频数据（必须 44100Hz）
  ↓
第一步：带通滤波
  调用 essentia.BandPass(信号, 带宽=7000, 中心频率=4500, 采样率=44100)
  目的：只保留 1000-8000Hz 的击球声频段，过滤掉人声、风声、环境噪音
  ↓
第二步：瞬态检测
  调用 essentia.SuperFluxExtractor(滤波信号, combine=20ms, 帧大小=2048, 跳步=256, ...)
  输出：一组 onset 时间戳（秒）
  原理：SuperFlux 算法检测频谱能量的突然增加，对打击声特别敏感
  ↓
第三步：25 秒去重
  遍历 onset 列表，如果两个 onset 间隔 < 25 秒，丢弃后者
  依据：正常高尔夫挥杆间隔至少 25 秒（走位、准备、挥杆）
  ↓
第四步：窗口特征提取（对每个通过去重的 onset）
  取 onset 前后各 1024 个采样点（约 23ms）作为分析窗口
  计算四个特征：
    a) 频谱质心 = essentia.SpectralCentroidTime(窗口)
       含义：声音的"亮度"，击球声质心约 3500Hz
    b) 频谱平坦度 = essentia.Flatness(窗口)
       含义：频谱的均匀程度，击球声在 0.1-0.6 之间
    c) RMS 能量 = essentia.RMS(窗口)
       含义：声音响度，真实击球 RMS 通常 > 0.01
    d) 衰减比 = calculateDecayRatio(...)
       含义：onset 后 50-100ms 的能量 / onset 后 0-25ms 的能量
       击球声衰减快（比值低 < 0.4），空挥声衰减慢（比值高 > 0.6）
  ↓
第五步：置信度评分
  confidence = 质心分 × 0.30 + 衰减分 × 0.30 + 能量分 × 0.25 + 平坦度分 × 0.15
  只保留 confidence > 0.3 的检测结果
```

#### 置信度评分规则中文翻译

| 特征 | 权重 | 评分规则 | 理想值 |
|------|------|---------|--------|
| 频谱质心 | 30% | 距离 3500Hz 越近分越高，偏差 > 3000Hz 则为 0 | ~3500 Hz |
| 衰减比 | 30% | 衰减比越低分越高（decayScore = 1 - decayRatio） | < 0.4 |
| RMS 能量 | 25% | RMS / 0.1，上限 1.0 | > 0.1 |
| 频谱平坦度 | 15% | 0.1-0.6 之间满分，两端线性衰减 | 0.1 ~ 0.6 |

#### 衰减比计算规则中文翻译

```
峰值窗口：onset 后 0-25ms（约 1103 个采样点）
衰减窗口：onset 后 50-100ms（约 2205 个采样点）
衰减比 = RMS(衰减窗口) / RMS(峰值窗口)

解读：
  衰减比 < 0.3 → 非常尖锐的瞬态，极可能是真实击球
  衰减比 0.3-0.5 → 较快衰减，可能是击球
  衰减比 0.5-0.7 → 中等衰减，可能是空挥或其他声音
  衰减比 > 0.7 → 缓慢衰减，很可能不是击球（风声、人声等）
```

### 5.2 弹道生成 — 代码逻辑中文逐行解读

#### 核心生成流程（`trajectory-generator.ts` → `generateTrajectory()`）

```
输入：落点坐标(归一化 0-1)、配置(高度/形状/飞行时间)、可选原点/顶点
  ↓
第一步：确定原点
  默认原点 = (0.5, 0.85)，即画面底部中央
  如果用户标记了击球位置，使用用户标记的坐标
  ↓
第二步：计算顶点
  顶点.x = (原点.x + 落点.x) / 2  ← 水平中点
  顶点.y = min(原点.y, 落点.y) - 高度乘数
  高度乘数：low=0.15, medium=0.25, high=0.35
  ↓
第三步：计算 Bezier 控制点
  控制点 = 2 × 顶点 - 0.5 × (原点 + 落点)
  这个公式保证曲线在 t=0.5 时精确通过顶点
  ↓
第四步：采样曲线点
  采样数 = max(30, 飞行时间 × 60)
  对 t = 0 到 1 均匀采样：
    x(t) = (1-t)²×原点.x + 2(1-t)t×(控制点.x + 形状偏移×t) + t²×落点.x
    y(t) = (1-t)²×原点.y + 2(1-t)t×控制点.y + t²×落点.y
  注意：形状偏移随 t 线性增加，模拟 draw/fade 的渐进弯曲
```

#### 弹道形状参数中文翻译

| 英文 | 中文 | 偏移值 | 含义 |
|------|------|--------|------|
| hook | 左曲球 | -0.15 | 球大幅向左弯曲（右手球员） |
| draw | 小左曲 | -0.08 | 球轻微向左弯曲 |
| straight | 直球 | 0 | 球直线飞行 |
| fade | 小右曲 | +0.08 | 球轻微向右弯曲 |
| slice | 右曲球 | +0.15 | 球大幅向右弯曲 |

| 英文 | 中文 | 弧高乘数 | 含义 |
|------|------|---------|------|
| low | 低弹道 | 0.15 | 铁杆/低飞球 |
| medium | 中弹道 | 0.25 | 标准弹道 |
| high | 高弹道 | 0.35 | 高飞球/挖起杆 |

### 5.3 移植风险清单

#### 高风险

| 风险 | 描述 | 影响 | 缓解方案 |
|------|------|------|---------|
| Essentia.js 无 iOS 等价物 | Essentia 是 C++ 库的 WASM 移植，iOS 没有直接等价物 | 音频检测管线需完全重写 | 用 Apple Accelerate (vDSP) 重实现带通滤波 + FFT + RMS；SuperFlux 算法需手写（约 200 行 Swift） |
| SuperFlux 算法复杂度 | SuperFlux 不是简单的能量阈值检测，它比较相邻帧的频谱差异 | 简单替代可能漏检或误检 | 可先用简化版（能量包络 + 峰值检测），再逐步优化到 SuperFlux |
| 44100Hz 采样率硬依赖 | 原始代码明确要求 44100Hz，其他采样率会导致 Essentia 异常 | iPhone 录制时音频采样率可能不同 | AVAudioEngine 可配置输出格式为 44100Hz，或在检测前重采样 |

#### 中风险

| 风险 | 描述 | 影响 | 缓解方案 |
|------|------|------|---------|
| 实时 vs 离线处理 | 原始代码是离线处理整段音频，iPhone 需要实时检测 | 延迟和内存模型不同 | AVAudioEngine installTap 提供实时缓冲区，但需要流式版本的 onset 检测 |
| 240fps 录制时的音频同步 | 高速录制时音频和视频时间戳可能有微小偏移 | 击球时刻标记可能偏移几帧 | 用 CMSampleBuffer 的 presentationTimeStamp 精确对齐 |
| 户外环境噪音 | 原始代码在受控环境测试，高尔夫球场有风声、鸟叫、其他球员声音 | 误检率可能升高 | 带通滤波已经过滤大部分环境噪音；可增加自适应阈值 |
| 弹道模型过于简化 | 二次 Bezier 不考虑空气阻力、Magnus 效应、风力 | 弹道形状与真实飞行有偏差 | 作为可视化足够；如需精确物理模型需引入 TrackMan 级别的弹道方程 |

#### 低风险

| 风险 | 描述 | 缓解方案 |
|------|------|---------|
| 频谱质心目标值 3500Hz 可能不适用所有球杆 | 铁杆 vs 木杆击球声频谱不同 | 可按球杆类型调整目标质心 |
| 25 秒去重窗口可能过长 | 练习场连续击球间隔可能 < 25 秒 | 提供可配置参数，练习场模式缩短到 10-15 秒 |
| 衰减比窗口固定 | 50-100ms 衰减窗口可能不适用所有击球类型 | 可增加自适应窗口长度 |

### 5.4 边界条件分析

| 场景 | 原始代码行为 | 是否需要处理 |
|------|------------|------------|
| 空音频数据 | 抛出异常 "Audio data cannot be empty" | ✅ 已处理 |
| 非 44100Hz 采样率 | 打印警告但继续执行 | ⚠️ 需要在 iOS 端强制重采样 |
| 分析窗口 < 256 采样点 | 跳过该 onset | ✅ 已处理 |
| 分析窗口 < 100 采样点 | 跳过该 onset | ✅ 已处理 |
| Essentia 算法异常 | 使用默认值（centroid=3500, flatness=0.3, rms=0.1） | ⚠️ 默认值可能导致误检 |
| 衰减窗口不足 | 返回 0.5（中间值） | ✅ 合理降级 |
| peakRms ≤ 0 或非有限数 | 返回 0.5 | ✅ 已处理 |
| 置信度 ≤ 0.3 | 丢弃该检测 | ✅ 已处理 |
| 空 onset 向量 | 捕获异常，返回空数组 | ✅ 已处理 |
| 弹道坐标超出 0-1 范围 | clamp 到 [0, 1] | ✅ 已处理 |

## 六、关键代码文件索引

| 文件 | 内容 | 移植价值 |
|------|------|---------|
| `apps/browser/src/lib/audio-detector.ts` | 音频击球检测完整实现 | ⭐⭐⭐⭐⭐ |
| `apps/browser/src/lib/trajectory-generator.ts` | 物理弹道生成 | ⭐⭐⭐⭐⭐ |
| `apps/browser/src/lib/tracer-renderer.ts` | 弹道渲染（Canvas 2D） | ⭐⭐⭐ |
| `apps/browser/src/lib/canvas-compositor.ts` | 视频帧合成 | ⭐⭐ |
| `apps/desktop/backend/detection/origin.py` | 球原点检测 | ⭐⭐⭐⭐ |
| `apps/desktop/backend/detection/pipeline.py` | 检测流水线 | ⭐⭐⭐ |
| `apps/desktop/backend/detection/kalman_tracker.py` | 卡尔曼追踪 | ⭐⭐⭐⭐ |
| `apps/desktop/backend/detection/flow_tracker.py` | 光流追踪 | ⭐⭐⭐ |
| `apps/browser/src/stores/processingStore.ts` | 数据模型定义 | ⭐⭐⭐ |
