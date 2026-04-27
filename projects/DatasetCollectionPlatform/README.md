# DatasetCollectionPlatform

高尔夫挥杆数据集采集/去重/切分/导出平台。为下游两个 iOS App（HumanClubAnalysisApp、GolfBallDetectionApp）和 PiTrac 可行性研究提供训练数据。

## 在整体项目中的位置

```
DatasetCollectionPlatform（本项目）
  ├── 产出 human_club 数据 ──→ HumanClubAnalysisApp（人体+球杆分析，49 Swift 文件，代码完成）
  ├── 产出 golf_ball_detection 数据 ──→ GolfBallDetectionApp（球检测+轨迹，15 Swift 文件，代码完成）
  ├── 产出训练数据 ──→ tools/train_ball_detector（YOLO 训练 → CoreML 导出）
  └── 参考数据 ──→ PiTracIPhoneFeasibilityStudy（可行性研究，已完成）
共享算法库：packages/GolfAnalysisKit（35 文件，61 测试全通过）
开源研究：projects/OpenSourceAnalysis（7 个项目分析，已完成）
```

当前状态：下游 App 代码已完成，等待本平台产出真实训练数据。本平台是整个系统的数据瓶颈。

---

## 数据采集要求

### 采集设备要求

| 项目 | 要求 |
|------|------|
| 设备 | iPhone 17 Pro Max（或支持 240fps 的 iPhone） |
| 帧率 | 240fps @ 1920×1080（慢动作模式） |
| 固定方式 | 三脚架（推荐）或稳定支撑，避免手持抖动 |
| 距离 | 相机距击球位 3-5 米，确保完整挥杆动作在画面内 |
| 光照 | 室内 LED 或室外自然光，避免逆光和强阴影 |
| 背景 | 尽量简洁，避免复杂背景干扰球检测 |

### 两个数据域的采集规格

#### human_club（人体+球杆分析）

- 目标：捕捉完整挥杆动作（准备→上杆→下杆→击球→收杆）
- 文件格式：`.mov` / `.mp4`（240fps 视频）或 `.jpg` / `.png`（关键帧图片）
- 标注格式：COCO JSON — 人体框 + 17 关键点 + 球杆框
- 标注示例：
  ```json
  {
    "images": [{"id": 1, "file_name": "frame_001.jpg", "width": 1920, "height": 1080}],
    "annotations": [
      {"id": 1, "image_id": 1, "category_id": 1, "bbox": [x, y, w, h], "keypoints": [...]}
    ],
    "categories": [{"id": 1, "name": "person", "keypoints": ["nose", "left_eye", ...]}]
  }
  ```
- 元数据必填：`clubType`（driver/iron/wedge/putter）、`handedness`（left/right）、`swingIntensity`（warmup/normal/max）

#### golf_ball_detection（高尔夫球检测）

- 目标：捕捉球在飞行中的位置（击球后 3-5 米范围内）
- 文件格式：`.jpg` / `.png`（从 240fps 视频中提取的帧）
- 标注格式：YOLO TXT — 每行 `class_id cx cy w h`（归一化坐标 0-1）
- 标注示例：
  ```
  0 0.523 0.341 0.015 0.025
  ```
  （class_id=0 表示高尔夫球，cx/cy 为中心点，w/h 为宽高，均相对于图片尺寸归一化）
- 每张图片对应一个同名 `.txt` 文件（如 `frame_001.jpg` → `frame_001.txt`）
- 无球的负样本图片对应空 `.txt` 文件

### 数据量目标

| 阶段 | human_club | golf_ball_detection | 用途 |
|------|-----------|-------------------|------|
| M1 基线 | 50+ 组挥杆视频 | 500+ 帧标注图片 | 首次真机验证 + 首版 YOLO 模型 |
| M2 收敛 | 100+ 组，覆盖多球杆/多场景 | 2000+ 帧，含负样本 | 参数调优 + 精度收敛 |
| M3 发布 | 200+ 组，覆盖全球杆类型 | 5000+ 帧，多光照/多背景 | 生产级模型 |

### 采集场景覆盖要求

为确保模型泛化能力，需覆盖以下维度：

- 球杆类型：driver、3-wood、5-iron、7-iron、PW、SW、putter（至少 4 种）
- 惯用手：right（主要）、left（至少 10%）
- 挥杆强度：warmup、normal、max
- 场景：indoor（室内练习场）、outdoor（户外球场/练习场）
- 光照：indoor_led、sunlight、overcast、mixed
- 背景：简洁墙面、草地、天空、混合

---

## 端到端采集流程

### 路径 A：Python 命令行直接采集

适用于已有图片/视频文件，直接在本地注册到数据集。

#### 1. 创建采集会话

每次采集开始前必须创建会话，记录设备、环境、采集者信息：

```bash
python tools/start_session.py \
  --collector "alice" \
  --session-name "1" \
  --device "iPhone17ProMax" \
  --scene-type indoor \
  --lighting indoor_led \
  --tripod \
  --distance-m 4.0 \
  --latitude 37.3318 \
  --longitude -122.0312 \
  --horizontal-accuracy-m 3.5 \
  --target-domains "human_club,golf_ball_detection" \
  --notes "室内练习场，7号铁为主"
```

输出 `sess_xxxxxxxxxxxx`，后续步骤需要此 ID。

start_session.py 完整参数：

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--collector` | 是 | — | 采集者姓名 |
| `--session-name` | 否 | `""` | 手动会话名称，现场建议使用 `1`、`2`、`3` 递增 |
| `--device` | 是 | — | 设备型号 |
| `--device-profile` | 否 | `iphone17max` | 设备配置文件名（`config/device_profiles/` 下） |
| `--fps` | 否 | `240` | 采集帧率 |
| `--resolution` | 否 | `1920x1080` | 分辨率 |
| `--scene-type` | 否 | `indoor` | 场景类型：indoor / outdoor / mixed |
| `--lighting` | 否 | `indoor_led` | 光照条件 |
| `--tripod` | 否 | `false` | 是否使用三脚架 |
| `--distance-m` | 否 | `0` | 相机到击球位距离（米） |
| `--latitude` / `--longitude` | 否 | — | 当前录制设备 GPS 坐标，必须成对提供 |
| `--horizontal-accuracy-m` | 否 | `0` | GPS 水平精度（米） |
| `--altitude-m` / `--vertical-accuracy-m` | 否 | — | GPS 海拔与垂直精度（米） |
| `--target-domains` | 否 | `human_club,golf_ball_detection` | 目标域（逗号分隔） |
| `--notes` | 否 | `""` | 备注 |

#### 2. 注册样本

单个文件注册：
```bash
python tools/register_sample.py \
  --domain human_club \
  --file /path/to/swing_001.mov \
  --annotation /path/to/swing_001.json \
  --session-id sess_xxxxxxxxxxxx \
  --collector alice \
  --shot-id shot_001 \
  --club-type driver \
  --handedness right \
  --swing-intensity normal \
  --surface grass
```

register_sample.py 完整参数：

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--domain` | 是 | — | `human_club` 或 `golf_ball_detection` |
| `--file` | 是 | — | 样本文件路径 |
| `--session-id` | 是 | — | 所属会话 ID |
| `--annotation` | 否 | `""` | 标注文件路径 |
| `--collector` | 否 | `unknown` | 采集者 |
| `--shot-id` | 否 | `""` | 击球编号 |
| `--take-index` | 否 | `1` | 同一击球的第几次拍摄 |
| `--club-type` | 否 | `unknown` | 球杆类型 |
| `--handedness` | 否 | `unknown` | left / right / unknown |
| `--swing-intensity` | 否 | `unknown` | warmup / normal / max / unknown |
| `--surface` | 否 | `unknown` | 场地表面（grass/mat/indoor） |
| `--fps` | 否 | `240` | 帧率 |
| `--resolution` | 否 | `1920x1080` | 分辨率 |
| `--tags` | 否 | `""` | 标签（逗号分隔） |
| `--metadata-json` | 否 | `""` | 额外元数据 JSON 文件路径 |

批量注册（自动匹配同名标注文件）：
```bash
python tools/register_batch.py \
  --domain golf_ball_detection \
  --input-dir /path/to/images/ \
  --annotation-dir /path/to/labels/ \
  --session-id sess_xxxxxxxxxxxx \
  --collector alice \
  --ext ".jpg,.jpeg,.png,.mp4,.mov" \
  --club-type "7iron" \
  --surface grass
```

自动匹配规则：`frame_001.jpg` → 在 annotation-dir 中查找 `frame_001.json` / `frame_001.txt` / `frame_001.xml`。

重复文件（SHA-256 相同）自动跳过，记录到 `duplicates.jsonl`。

#### 3. 切分数据集

```bash
python tools/split_dataset.py --domain human_club --strategy session --seed 42
python tools/split_dataset.py --domain golf_ball_detection --strategy session --seed 42
```

`--strategy session` 确保同一会话的样本不会跨 train/val/test 泄漏（防止数据泄漏）。

默认比例：train 80% / val 10% / test 10%，可通过 `--train 0.7 --val 0.15 --test 0.15` 自定义。

切分结果写入 `exports/splits/<domain>.json`，同时将文件复制到 `datasets/processed/<domain>/{train,val,test}/`。

#### 4. 导出清单 + 校验

```bash
python tools/generate_manifest.py          # 生成主清单 + 消费者清单
python tools/generate_quality_report.py    # 生成质量报告（JSON + Markdown）
python tools/validate_registry.py --strict # Schema 校验
```

#### 5. 查看数据集状态

```bash
python tools/dataset_stats.py          # 人类可读表格
python tools/dataset_stats.py --json   # JSON 格式
```

### 路径 B：iOS 真机采集 → 导入

适用于使用 DatasetCollectorApp 在 iPhone 上实地采集。

#### 1. iOS 端采集

1. 生成 Xcode 工程：`cd AppleOSDatasetCollectorApp && xcodegen generate --spec project.yml`
2. 在 iPhone 上安装并打开 DatasetCollectorApp
3. 创建采集会话（选择域、设备参数、场景类型）
4. 录制挥杆视频：引导画面 → 人体检测 → 倒计时 → 240fps@1080p 录制 → 自动清晰度验证
5. 在数据浏览器中查看/删除/回放分析已采集样本（支持 12 种 Vision 分析模型）
6. 通过 AirDrop 或 Files 导出 `DatasetCollectorExport/` 目录到 Mac

iOS 导出目录结构：
```
DatasetCollectorExport/
  sessions.jsonl          # 会话记录
  samples.jsonl           # 样本记录
  assets/<domain>/<sha-prefix>/<sha>.<ext>  # 资产文件
```

#### 2. 导入到 Python 平台

```bash
python tools/import_ios_export.py --ios-export-dir /path/to/DatasetCollectorExport
```

自动完成：
- session 导入（跳过已存在的 sessionId，自动补齐缺失字段）
- sample 注册（SHA-256 去重，路径自动映射）
- 资产文件复制到规范路径 `datasets/raw/<domain>/assets/<sha-prefix>/<sha>.<ext>`

#### 3. 后续步骤

同路径 A 的第 3-5 步（切分 → 导出 → 校验）。

### 路径 C：Android 落球点 GPS → 导入

适用于 Android 手机走到落球点后记录高精度 GPS，作为数据集参考测量保存。

1. 打开 `AndroidLandingGpsCollector`，输入与 iOS/CLI 相同的会话名称（如 `1`）。
2. 等待高精度 GPS，点击“记录落球点”。
3. 导出 `landing_points.jsonl`。
4. 在平台导入：

```bash
python tools/import_android_landing_gps.py --android-jsonl /path/to/landing_points.jsonl
```

导入后会按 `sessionName` 找到对应会话，并把落点 GPS 追加到该会话样本的 `metadata.referenceMeasurements`。若同名会话不唯一，导入工具会跳过，避免把参考数据写错样本。

---

## 数据契约（Schema）

所有注册表记录必须通过 JSON Schema (Draft 2020-12) 校验。

### 会话记录 (session_record.schema.json)

必填字段：`sessionId`(sess_开头12位)、`collector`、`device`、`deviceProfile`、`createdAt`(ISO 8601)、`status`(active/closed)、`captureConfig`(fps+resolution)、`environment`(sceneType+lighting+tripod)、`targetDomains`(数组)

可选字段：`sessionName`（现场手动名称）、`location`（当前录制设备 GPS）

### 样本记录 (sample_record.schema.json)

必填字段：`sampleId`、`domain`(human_club/golf_ball_detection)、`sha256`(64位hex)、`hashAlgorithm`(sha256)、`assetPath`、`fileSize`、`sessionId`、`collector`、`device`、`deviceProfile`、`capturedAt`、`sourcePath`、`status`(active/archived)

可选字段：`annotationPath`、`shotId`、`takeIndex`(≥1)、`tags`(数组)、`metadata`(fps/resolution/clubType/handedness/swingIntensity/surface/referenceMeasurements)

参考测量必须保存：测速评估、精度回归和数据集复核依赖 `metadata.referenceMeasurements`，其中可包含雷达/发射监测仪读数、LiDAR/Depth sidecar 关联信息、Android 落球点 GPS 等。

---

## 去重机制

- 每个样本文件在注册时计算 SHA-256 哈希
- 同一域内，SHA-256 相同且 status=active 的样本视为重复
- 重复样本不写入 `samples.jsonl`，而是记录到 `duplicates.jsonl`（含来源、时间、关联的已有 sampleId）
- 跨域的相同文件不视为重复（同一视频可同时用于 human_club 和 golf_ball_detection）

---

## 工具一览

| 工具 | 用途 |
|------|------|
| `start_session.py` | 创建采集会话 |
| `register_sample.py` | 注册单个样本（含去重） |
| `register_batch.py` | 批量注册目录下的样本（直接调用 lib，非 subprocess） |
| `split_dataset.py` | 按会话隔离切分 train/val/test |
| `generate_manifest.py` | 生成数据集清单 + 消费者清单 |
| `generate_quality_report.py` | 生成质量报告（JSON + Markdown），含元数据分布/资产完整性/标注覆盖率 |
| `validate_registry.py` | Schema 校验注册表 |
| `dataset_stats.py` | 数据集统计概览（按域/球杆/惯用手/强度/场地分布） |
| `import_ios_export.py` | 导入 iOS 采集端导出数据 |
| `import_android_landing_gps.py` | 导入 Android 落球点 GPS 到样本参考测量 |
| `validate_apple_project.py` | 校验 iOS 工程结构 |
| `simulate_ios_workflow.py` | 模拟端到端集成测试 |

核心库：`tools/lib/registry.py` — 包含 `register_one_sample()`、SHA-256 计算、JSONL 读写、Schema 校验等所有共享逻辑。

## 目录结构

```
contracts/                    # JSON Schema 契约
  session_record.schema.json
  sample_record.schema.json
  dataset_manifest.schema.json
datasets/
  registry/                   # 注册表（JSONL）
    sessions.jsonl
    samples.jsonl
    duplicates.jsonl
  raw/<domain>/assets/        # 规范化资产存储（SHA-256 前缀分桶）
  raw/<domain>/annotations/   # 标注文件存储
  processed/<domain>/         # 切分后的训练数据
    train/<domain>/images/
    train/<domain>/labels/
    val/...
    test/...
exports/
  dataset_manifest.json       # 主清单
  splits/<domain>.json        # 切分元数据
  consumers/                  # 消费者清单（3 个下游项目各一份）
    human_club_analysis_app.json
    golf_ball_detection_app.json
    pitrac_feasibility_study.json
analysis/
  reports/                    # 质量报告
    quality_report.json
    quality_report.md
tools/
  lib/registry.py             # 核心库
  start_session.py
  register_sample.py
  register_batch.py
  ...
tests/                        # pytest 单元测试（18 项）
  test_registry.py            # 核心库单元测试
  test_tools.py               # 工具链集成测试
AppleOSDatasetCollectorApp/   # iOS 采集端（XcodeGen 工程）
```

## 质量关口

以下全部通过才算数据闭环完成：

1. `python tools/validate_registry.py --strict` — 无 schema 错误
2. `exports/splits/human_club.json` 和 `exports/splits/golf_ball_detection.json` 存在
3. `exports/consumers/` 下三个消费者清单已生成
4. `python tools/validate_apple_project.py` — iOS 工程结构正确
5. `python tools/simulate_ios_workflow.py` — 集成模拟通过
6. `python -m pytest tests/ -v` — 单元测试全部通过（当前 18 项）

## 测试

```bash
# 单元测试
python -m pytest tests/ -v

# 单个测试
python -m pytest tests/test_registry.py::TestRegisterOneSample::test_register_new_sample -v

# 集成模拟
python tools/simulate_ios_workflow.py
```

---

## 采集 Checklist（每次采集前确认）

- [ ] 设备已充电，存储空间充足（每组 240fps 视频约 200-500MB）
- [ ] 三脚架已固定，相机角度覆盖完整挥杆弧线
- [ ] 光照均匀，无强逆光或闪烁
- [ ] 已创建采集会话（`start_session.py` 或 iOS App）
- [ ] 已确认 target-domains 包含所需域
- [ ] 球杆类型、惯用手、挥杆强度等元数据已准备
- [ ] 标注工具已就绪（human_club 用 COCO 标注工具，golf_ball_detection 用 YOLO 标注工具）

## 采集后 Checklist

- [ ] 所有样本已注册（`register_sample.py` 或 `register_batch.py` 或 `import_ios_export.py`）
- [ ] 运行 `dataset_stats.py` 确认数据量和分布
- [ ] 运行 `validate_registry.py --strict` 确认无 schema 错误
- [ ] 切分数据集（`split_dataset.py`）
- [ ] 生成清单和质量报告（`generate_manifest.py` + `generate_quality_report.py`）
- [ ] 检查质量报告中的缺失资产和标注覆盖率
