# AndroidLandingGpsCollector

最小 Android 落球点 GPS 记录 App。用途是让走到落球点的 Android 手机输入同一个会话名称，并保存高精度 GPS 作为数据集参考测量。

## 功能

- 输入会话名称，如 `1`、`2`、`3`。
- 使用系统高精度定位记录落球点。
- 本地保存 `landing_points.jsonl`。
- 通过系统文件选择器导出 JSONL，后续拷贝回 `DatasetCollectionPlatform` 归档或导入。

导出记录包含 `sessionName`、`landingLocation` 和 `referenceMeasurements`，字段与 iOS 样本 metadata 中的参考测量结构对齐。
