# DatasetCollectionPlatform（数据先行闭环）

第三主项目，目标是把采集流程固定成可复用的数据产品链路：

`采集会话 -> 样本注册去重 -> 会话隔离切分 -> 清单导出 -> 质量校验 -> 三个消费者直连`

## 1. 收集什么数据

| 域 | 采样对象 | 最低标注 | 关键元数据 |
|---|---|---|---|
| `human_club` | 挥杆人体+球杆视频/图像 | 关键帧框/关键点（按当前模型要求） | `shotId` `takeIndex` `fps` `resolution` `clubType` `handedness` |
| `golf_ball_detection` | 高尔夫球检测样本 | 球框/掩码（按模型格式） | `shotId` `takeIndex` `fps` `resolution` `surface` |

采样会话强制记录：设备、设备档案、场景类型、光照、是否三脚架、目标域。

## 2. 如何保存数据

目录结构固定：

- `datasets/raw/<domain>/assets/<sha-prefix>/<sha>.<ext>` 原始资产（内容哈希归档）
- `datasets/raw/<domain>/annotations/<sha-prefix>/<sha>.<ext>` 对应标注
- `datasets/registry/sessions.jsonl` 采集会话
- `datasets/registry/samples.jsonl` 唯一样本注册表
- `datasets/registry/duplicates.jsonl` 重复登记
- `datasets/processed/<domain>/{train|val|test}/...` 切分后的训练目录
- `exports/dataset_manifest.json` 总清单
- `exports/consumers/*.json` 各消费者专用清单

## 3. 如何直连其他三个项目

- 人体球杆分析 App：`exports/consumers/human_club_analysis_app.json`
- 高尔夫球检测 App：`exports/consumers/golf_ball_detection_app.json`
- PiTrac 可行性研究：`exports/consumers/pitrac_feasibility_study.json`

运行时也支持环境变量覆盖：

- `HUMAN_CLUB_MANIFEST_PATH`
- `GOLF_BALL_MANIFEST_PATH`
- `DATASET_MANIFEST_PATH`（通用回退）

## 4. 快速执行（iPhone 17 Max 采集）

```bash
# 0) 安装依赖
pip install -r requirements.txt

# 1) 建会话（推荐用设备档案）
python tools/start_session.py \
  --collector "alice" \
  --device "iPhone17Max" \
  --device-profile "iphone17max" \
  --ios-version "iOS 26" \
  --app-version "0.3.0" \
  --fps 240 \
  --resolution 1920x1080 \
  --scene-type indoor \
  --lighting indoor_led \
  --tripod \
  --target-domains human_club,golf_ball_detection

# 2) 注册样本（自动 SHA256 去重）
python tools/register_sample.py \
  --domain human_club \
  --file path/to/frame_0001.jpg \
  --annotation path/to/frame_0001.json \
  --session-id <session_id> \
  --shot-id shot_001 \
  --take-index 1 \
  --fps 240 \
  --resolution 1920x1080 \
  --club-type driver \
  --handedness right \
  --swing-intensity normal

# 3) 批量注册
python tools/register_batch.py \
  --domain golf_ball_detection \
  --input-dir path/to/ball_images \
  --annotation-dir path/to/ball_labels \
  --session-id <session_id> \
  --fps 240 \
  --resolution 1920x1080 \
  --surface mat

# 4) 会话隔离切分（默认 strategy=session，降低泄漏）
python tools/split_dataset.py --domain human_club --strategy session --seed 42
python tools/split_dataset.py --domain golf_ball_detection --strategy session --seed 42

# 5) 导出清单 + 质量报告 + 注册表校验
python tools/generate_manifest.py
python tools/generate_quality_report.py
python tools/validate_registry.py --strict
```

## 5. 质量关口（必须全部通过）

1. `validate_registry.py` 通过，且无 schema 错误。
2. 重复率在 `analysis/reports/quality_report.md` 可追踪。
3. 两个域都存在 `exports/splits/<domain>.json`。
4. 三个消费者清单都已生成并可被下游读取。

## 6. 设备档案说明

`config/device_profiles/iphone17max.yaml` 是默认采集档案。  
由于机型规格可能变动，档案被标记为 `specStatus: pending_official_confirmation`，以真机日志为准，不把未验证参数写成硬性结论。
