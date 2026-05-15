# 开源高尔夫项目分析（iPhone 17 Pro Max 可用性评估）

分析 GitHub 开源高尔夫项目，评估其理论和代码在 iPhone 17 Pro Max 上的直接可用性。

## 项目列表

| 项目 | 仓库 | 语言 | 定位 | iPhone 可用性 |
|------|------|------|------|--------------|
| golf-clip | `elicoon/golf-clip` | TypeScript + Python | 击球检测 + 弹道追踪 + 视频剪辑 | ⭐⭐⭐⭐ 算法可移植 |
| GoBirdie-Desktop | `nicechester/GoBirdie-Desktop` | Rust + JavaScript | 高尔夫数据分析（Strokes Gained、散布图） | ⭐⭐⭐⭐⭐ 配套 iOS 端可直接参考 |
| ClubUp | `phillt3/ClubUp` | Swift (SwiftUI) | 环境距离修正 + 选杆推荐 | ⭐⭐⭐⭐⭐ 原生 iOS App，可直接复用 |
| PiTrac | `PiTracLM/PiTrac` | C++ (OpenCV) | DIY 发射监测器（球速/发射角/旋转率） | ⭐⭐⭐ 理论可参考，硬件方案不可移植 |
| golf_ball | `rucv/golf_ball` | Python (PyTorch) | Faster R-CNN 高尔夫球检测（学术论文配套） | ⭐⭐⭐⭐ 模型架构可参考，建议用 YOLO 替代 |
| Golf_tracker | `jjmlovesgit/Golf_tracker` | Python (VisionAgent) | Florence2 + SAM2 视频目标追踪 | ⭐⭐⭐ 追踪思路可参考，云端依赖不可移植 |
| Golf-Ball-Tracking-and-Speed-Detection | `natterman12/Golf-Ball-Tracking-and-Speed-Detection` | Python (OpenCV) | HSV 颜色追踪 + 触发线速度计算 | ⭐⭐⭐ 速度计算逻辑可参考 |
| GolfShotTracer | `jonibek95/GolfShotTracer` | Python (YOLOv5) | 高尔夫球检测 + 物理弹道 + OpenCV 叠加 | ⭐⭐⭐ 公式与流程参考 |
| GolfShotTracer-iOS | `MaxenceMottard/GolfShotTracer-iOS` | SwiftUI + Vision/CoreML | iOS 视频逐帧球检测原型 | ⭐⭐⭐ 原型参考，已归档 |
| android-shot-tracer | `SangerZ/android-shot-tracer` | Kotlin (CameraX/Compose) | Android 拍摄与分析 UI 骨架 | ⭐⭐ 产品骨架参考 |
| GolfTracer | `Hyvok/GolfTracer` | Python (OpenCV/PyAV/LightGlue) | 音频击球帧 + 稳定化 + 手工标注 + 样条渲染 | ⭐⭐⭐⭐ 后处理链路强参考 |
| tracknetv5-golf | `carnhy/tracknetv5-golf` | Python (PyTorch) | 3 帧热图球检测 + 候选关联 + 主动学习 | ⭐⭐⭐⭐⭐ Mac 离线训练/推理强参考 |
| TrackNetV6 | `Gi-gigi/TrackNetV6` | Python (PyTorch) | TrackNetV6 热图模型 + 视频 demo | ⭐⭐⭐⭐ 模型结构参考 |
| TrackNet-Data-Annotator | `bsraigur/TrackNet-Data-Annotator` | Python (Tkinter/OpenCV) | TrackNet 逐帧球心标注 | ⭐⭐⭐ 标注流程参考 |
| OpenTrace | `jewbetcha/opentrace` | TypeScript + Python | 手工轨迹点 + Bezier 渲染 + 远端视频合成 | ⭐⭐⭐⭐ 产品交互与渲染参考 |

## 与本仓库四大项目的关联

```
golf-clip
  ├── 音频击球检测 ──────→ HumanClubAnalysisApp（挥杆事件触发）
  ├── YOLO 球原点定位 ───→ GolfBallDetectionApp（球检测）
  ├── 物理弹道模型 ──────→ GolfBallDetectionApp（球轨迹预测）
  └── 视频剪辑流程 ──────→ DatasetCollectionPlatform（自动裁剪采集片段）

GoBirdie-Desktop（+ GoBirdie iOS）
  ├── Strokes Gained ───→ HumanClubAnalysisApp（挥杆质量评估）
  ├── 击球散布分析 ──────→ HumanClubAnalysisApp（精度分析）
  ├── 球杆分析 ─────────→ HumanClubAnalysisApp（球杆表现追踪）
  ├── GPS 击球追踪 ─────→ DatasetCollectionPlatform（场景元数据）
  └── NLG 洞察引擎 ─────→ HumanClubAnalysisApp（AI 分析报告）

ClubUp
  ├── 环境距离修正 ──────→ HumanClubAnalysisApp（真实距离计算）
  ├── 选杆推荐算法 ──────→ HumanClubAnalysisApp（智能选杆）
  └── 天气 API 集成 ────→ HumanClubAnalysisApp（实时环境数据）

PiTrac
  ├── 球速计算原理 ──────→ HumanClubAnalysisApp（像素→距离标定）
  ├── 3D 三角测量 ──────→ GolfBallDetectionApp（发射角/方位角分解）
  ├── 相机标定流程 ──────→ DatasetCollectionPlatform（标定数据采集）
  └── 旋转率经验 ────────→ 验证查表法合理性（直接测量不可行）
```

## 可用性评级说明

- ⭐⭐⭐⭐⭐：代码可直接复用或仅需少量适配（同语言/同平台）
- ⭐⭐⭐⭐：核心算法/理论可移植，需要平台适配（跨语言但逻辑清晰）
- ⭐⭐⭐：部分理论可参考，代码需大幅重写
- ⭐⭐：仅理论参考价值
- ⭐：不适用

## 详细分析文档

- [golf-clip 分析](golf-clip分析.md)
- [GoBirdie-Desktop 分析](GoBirdie-Desktop分析.md)
- [ClubUp 分析](ClubUp分析.md)
- [PiTrac 分析](PiTrac分析.md)

## 专题分析

- [轨迹预测可借鉴分析](轨迹预测可借鉴分析.md) — 3-5 米距离球轨迹预测场景下，四个项目 + 本仓库代码的可借鉴内容
- [iPhone 球轨迹追踪竞品分析](iPhone球轨迹追踪竞品分析.md) — 闭源商业 App（GolfTrak/Shot Tracer）+ 新开源项目技术拆解与复现路径
- [补充开源项目可用性分析](补充开源项目可用性分析-2026-05.md) — golf-clip、两个 GolfShotTracer、android-shot-tracer、Hyvok/GolfTracer、TrackNet、OpenTrace 的可复用部分与风险

## 参考代码

- [reference_code/](reference_code/) — 从四个项目中提取的核心可借鉴代码文件（[索引](reference_code/README.md)）

## 本地仓库

- [repos/](repos/) — 已下载的项目源码（.gitignore 排除，不提交）
