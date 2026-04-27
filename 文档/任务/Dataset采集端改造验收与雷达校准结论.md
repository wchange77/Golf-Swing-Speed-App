# Dataset 采集端改造验收与雷达校准结论

日期：2026-04-24

## 结论

1. `AppleOSDatasetCollectorApp` 高质量采集端改造已形成可回归闭环：采集记录、质量指标、4 类 sidecar、半自动标注候选、双域登记、浏览筛选和测试覆盖均已补齐。
2. 当前数据平台与两个下游项目可以直接读取现有 manifest/消费者清单；但当前仓库真实数据集仍是 0 个样本，只能证明格式、桥接和处理链路可用，不能证明模型训练精度或测速精度。
3. 雷达/发射监测器校准信息应在采集阶段写入。原因是相机-球位-雷达的几何关系、时间同步、设备版本和校准状态后期无法可靠补录。当前实现已写入相机距离、LiDAR/手动校准快照；外部雷达 ground truth 侧车文件应作为下一阶段新增，不应伪造默认值。

## 改进整理表

| 类别 | 本轮改进 | 主要文件 | 输出/字段 | 验收状态 |
|---|---|---|---|---|
| 采集元数据 | 扩展质量、场景、标注、导出、校准字段 | `DatasetCollectorModels.swift` | `qualityPassed`、`actualFPS`、`exportStatus`、`calibrationStatus`、`pixelsPerMetre` | 已通过单测 |
| Sidecar | 每个视频旁生成 4 类侧车文件 | `DatasetCollectorService.swift` | `timeline.json`、`quality.json`、`camera.json`、`label_candidates.json` | 已通过单测 |
| 质量验证 | 新增实际 fps、分辨率、横屏、人体覆盖、bbox 稳定性、曝光比例、击球窗口候选 | `RecordingValidator.swift` | `RecordingQualityMetrics` + `CollectorQualityThresholds.baseline` | 已通过纯函数测试 |
| 采集 UI | 采集前确认杆型、手性、强度、场地、距离等关键字段 | `RecordingGuidanceView.swift`、`DatasetCollectorView.swift` | 避免合格样本关键字段为 `unknown` | 已接入 |
| 双域登记 | 同一视频可登记到 `human_club` 与 `golf_ball_detection`，共享 `shotId`，`takeIndex` 从 1 开始 | `DatasetCollectorService.swift` | 两条样本记录、同一资产哈希、不同 domain purpose | 已通过单测 |
| 半自动标注候选 | 写入挥杆窗口、关键帧、人体姿态候选、球框复核候选 | `DatasetCollectorService.swift` | `label_candidates.json`，状态 `needs_review` | 已通过单测 |
| 数据浏览 | 支持按待复核/合格/不合格/可导出筛选，详情显示质量和 sidecar 状态 | `DataBrowserView.swift`、`SampleDetailView.swift` | `isExportReady`、失败项、sidecar 完整性 | 已接入 |
| 删除清理 | 删除样本时同步清理 sidecar | `JSONLFileStore.swift`、`DatasetCollectorService.swift` | 防止导出目录残留孤儿文件 | 已接入 |
| 下游桥接 | 两个 App 可从源码相对路径定位 DatasetCollectionPlatform manifest | `BallDatasetBridge.swift`、`HumanClubDatasetBridge.swift` | 直接读取消费者清单 | 已通过 Xcode 测试 |
| 编译修复 | 修复球检测 App 已有 Swift 编译问题 | `YOLOBallDetector.swift`、`InsightsDashboardView.swift` | 移除错误 `mutating`；修复 `.accentColor` | 已通过 Xcode 测试 |

## 验证记录

| 验证项 | 命令/方式 | 结果 | 说明 |
|---|---|---|---|
| 采集端真机单测 | `xcodebuild test ... DatasetCollectorApp ... id=00008150-001279CA0EA3401C DEVELOPMENT_TEAM=G335FJTJ35` | 通过 | 物理 iPhone 可编译、安装并运行单测；未执行真实挥杆录制 |
| 采集端模拟器单测 | `xcodebuild test ... DatasetCollectorApp ... iPhone 17 Pro Max` | 5 tests / 0 failures | 覆盖 sidecar、metadata、双域登记、帧率抖动、击球窗口纯函数 |
| Python 注册表 | `python tools/validate_registry.py --strict` | `errors=0` | 当前注册表为空：sessions=0、samples=0 |
| Python 单测 | `python -m pytest tests/ -v` | 18 passed | 工具链回归通过 |
| iOS 流程模拟 | `python tools/simulate_ios_workflow.py` | 通过 | 模拟 1 条 human、1 条 ball、1 条重复事件，manifest 样本数 2 |
| Manifest 解码 | 读取主清单和 3 个消费者清单 | 通过 | 当前清单：`human_club=0`、`golf_ball_detection=0` |
| 球检测下游 | `xcodebuild test ... GolfBallDetectionApp` | 通过 | 新增断言实际读取 `golf_ball_detection_app.json` |
| 人体球杆下游 | `xcodebuild test ... GolfSwingSpeedApp` | 通过 | 新增断言实际读取 `human_club_analysis_app.json` |

## 当前可用性边界

| 问题 | 结论 | 依据 |
|---|---|---|
| 当前数据集能否被平台处理 | 可以 | Schema 校验、切分模拟、manifest 生成、质量报告流程均通过 |
| 当前数据集能否被两个下游项目读取 | 可以 | 两个下游桥接测试均实际解码消费者清单 |
| 当前数据集能否直接训练模型 | 还不够 | 真实样本数为 0，训练仍等待真机采集数据 |
| 当前数据能否验证测速精度 | 还不能 | 没有真实挥杆、雷达/测速仪 ground truth 和同步记录 |

## 雷达校准结论

| 项目 | 结论 |
|---|---|
| 是否应在采集阶段写入 | 应写入，尤其是作为测速 ground truth 的采集会话 |
| 写入位置 | 优先写 session/sample sidecar，例如 `radar_reference.json`；摘要字段写入 `metadata` |
| 是否写进最终 COCO/YOLO 标签 | 不直接写入。COCO/YOLO 仍只表达视觉训练标签，雷达数据作为评估/校准 ground truth |
| 是否阻塞普通视觉数据采集 | 不阻塞。无雷达时标记 `groundTruthStatus=none`，仍可用于人体/球检测训练 |
| 是否阻塞测速基准采集 | 应阻塞。测速基准样本必须有雷达设备、时间同步、放置几何和校准状态 |

建议下一阶段新增 `radar_reference.json`，至少记录：设备型号、固件版本、匿名设备 ID、雷达位置与朝向、相机到击球位距离、雷达到击球位距离、坐标系定义、时间同步方法、同步偏移、校准状态、原始雷达导出路径、球速/杆速/发射角等指标及置信度。

## 风险

1. 质量阈值仍是经验基线，虽然已集中定义并标注来源，但必须用 M1 真机数据重新校准。
2. 当前实机验证只覆盖单测安装运行，不等于完成真实挥杆采集、相机权限、240fps 实拍和 AirDrop/Files 导出验证。
3. 下游 App 仍缺少训练好的 CoreML 球检测模型；桥接可读不等于模型可用。
4. 外部雷达协议和同步方式尚未确定，不能在本轮写入虚假的雷达默认值。

## 下一步

1. 用真机完成 5 组最小真实挥杆采集，导出 `DatasetCollectorExport/` 并跑 `import_ios_export.py`。
2. 为外部雷达新增 `radar_reference.json` sidecar 契约草案，先做手工 JSON 导入，再接设备 SDK/API。
3. 将真实样本跑完 `split_dataset.py`、`generate_manifest.py`、`generate_quality_report.py`，记录质量阈值调参建议。
4. 采集满 M1 数据量后训练首版 YOLO/CoreML，并用雷达 ground truth 建立测速误差基线。
