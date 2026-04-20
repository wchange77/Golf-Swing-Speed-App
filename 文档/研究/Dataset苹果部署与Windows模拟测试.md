# Dataset 平台：Apple OS 部署与 Windows 模拟测试

**日期：** 2026-04-20  
**范围：** `projects/DatasetCollectionPlatform`  
**目标：** 在不具备 macOS/Xcode 的 Windows 环境下，仍然完成 Apple 采集端代码生成与可验证测试。

---

## 1. 本次交付

### 1.1 Apple OS 可部署代码

新增工程：

- `projects/DatasetCollectionPlatform/AppleOSDatasetCollectorApp/project.yml`
- `projects/DatasetCollectionPlatform/AppleOSDatasetCollectorApp/DatasetCollectorApp/Sources/...`

关键能力：

1. 采集会话创建（`sessions.jsonl`）。
2. 样本登记与 SHA-256 去重（`samples.jsonl`、`duplicates.jsonl`）。
3. 与 Dataset 平台 schema 字段对齐（会话、样本、重复事件）。
4. iOS 单测骨架（`DatasetCollectorServiceTests.swift`）。

### 1.2 Windows 端模拟测试代码

新增脚本：

- `projects/DatasetCollectionPlatform/tools/simulate_ios_workflow.py`

作用：

1. 在临时工作目录复制 Dataset 平台。
2. 模拟 iOS 采样输入（含一次重复样本）。
3. 跑完整链路：
   - `start_session.py`
   - `register_sample.py`
   - `split_dataset.py`
   - `generate_manifest.py`
   - `generate_quality_report.py`
   - `validate_registry.py`
4. 生成模拟报告：
   - `analysis/reports/windows_ios_simulation_report.json`
   - `analysis/reports/windows_ios_simulation_report.md`

---

## 2. 为什么在 Windows 用“模拟”而不是直接编译

当前环境不具备：

- `swift` 编译器
- `xcodegen`
- `Xcode` / iOS SDK

因此不能直接在本机编译 iOS App。  
可行方案是：

1. 先生成可在 macOS 直接打开的 Swift/XcodeGen 工程。
2. 在 Windows 执行同契约的流程模拟，验证数据链路与 schema 一致。

---

## 3. Apple OS 部署步骤（到 macOS 后直接执行）

```bash
cd projects/DatasetCollectionPlatform/AppleOSDatasetCollectorApp
xcodegen generate --spec project.yml
open DatasetCollectorApp.xcodeproj
```

在 Xcode 中选择真机并运行后，App 会在 `Documents/DatasetCollectorExport` 写出 JSONL 与资产文件。

---

## 4. 模拟测试验收标准

| 验收项 | 通过条件 |
|---|---|
| 会话写入 | `sessions.jsonl` 至少 1 条 |
| 样本写入 | 两个域均有样本 |
| 去重生效 | `duplicates.jsonl` 至少 1 条 |
| 切分成功 | 两域 `exports/splits/*.json` 存在 |
| 清单生成 | `exports/dataset_manifest.json` 生成 |
| 契约校验 | `validate_registry.py` 错误数为 0 |

---

## 5. 风险与限制

1. 由于 Windows 无 Xcode，本轮不能执行真正的 iOS 编译与真机安装。  
2. 模拟测试验证的是“数据契约兼容性”，不是“摄像头采样质量”。  
3. iPhone 17 Max 机型能力仍需真机日志确认，不能仅依据静态配置。  

---

## 6. 下一步

1. 在 macOS 上实际编译 `AppleOSDatasetCollectorApp`，跑 `DatasetCollectorServiceTests`。  
2. 真机采集一段数据并导入当前 Dataset 平台，确认端到端无人工修补。  
3. 补“相机帧时间戳稳定性”实测章节并回填到研究文档。  

---

## 7. 参考来源

- R39 FileManager: https://developer.apple.com/documentation/foundation/filemanager  
- R40 JSONEncoder: https://developer.apple.com/documentation/foundation/jsonencoder  
- R41 CryptoKit SHA256: https://developer.apple.com/documentation/cryptokit/sha256  
- R42 XCTest: https://developer.apple.com/documentation/xctest  
- R31 JSON Schema Draft 2020-12: https://json-schema.org/draft/2020-12  
- R32 JSON Lines: https://jsonlines.org/  
