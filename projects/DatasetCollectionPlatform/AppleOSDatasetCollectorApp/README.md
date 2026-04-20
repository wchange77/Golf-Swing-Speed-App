# AppleOSDatasetCollectorApp

用于 iPhone 侧数据采集的 SwiftUI 工程骨架，输出 JSONL 与现有 `DatasetCollectionPlatform` 契约对齐。

## 功能

1. 创建采集会话（`sessions.jsonl`）。
2. 登记样本并按 SHA-256 去重（`samples.jsonl` + `duplicates.jsonl`）。
3. 生成可导出的本地目录（默认在 iOS `Documents/DatasetCollectorExport`）。

## 目录

- `project.yml`：XcodeGen 工程定义
- `DatasetCollectorApp/Sources/Core`：模型、存储、服务
- `DatasetCollectorApp/Sources/Features/Collector`：采集 UI
- `DatasetCollectorApp/Tests/Unit`：服务层单测

## 在 macOS 上生成并部署

```bash
cd projects/DatasetCollectionPlatform/AppleOSDatasetCollectorApp
xcodegen generate --spec project.yml
open DatasetCollectorApp.xcodeproj
```

在 Xcode 中选择真机（例如 iPhone 17 Max）后运行。

## 与 DatasetCollectionPlatform 对接

iOS 导出目录中的 `sessions.jsonl / samples.jsonl / duplicates.jsonl` 字段与
`contracts/session_record.schema.json`、`contracts/sample_record.schema.json` 对齐。

在 Windows 上无法直接编译 iOS 工程，可使用：

```bash
python tools/simulate_ios_workflow.py
```

该脚本会模拟 iOS 采集流程并跑完整数据链路测试。
