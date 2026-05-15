# AndroidLandingGpsCollector

最小 Android 落球点 GPS 记录 App。用途是让走到落球点的 Android 手机（例如小米旗舰）输入同一个会话名称 + 第几杆，并保存高精度 GPS 作为数据集参考测量。

## 功能

- 输入 **sessionName**（如 `1`、`2`、`3`）。
- 输入 **takeIndex**（本会话第几杆，1-200）。
- 可选输入 **发射点 GPS**（经纬度手输或"把当前位置设为发射点"），落点记录时自动用 Haversine 算 `carryDistanceMeters` / `totalDistanceMeters`。
- 可选输入风速 m/s、风向 度、气温 摄氏度、文本备注；全部写入 `notes` 供分析侧读。
- 使用系统高精度定位记录落球点。
- 本地保存 `landing_points.jsonl`。
- 通过系统文件选择器导出 JSONL，后续拷贝回 `DatasetCollectionPlatform` 归档或导入。

导出记录包含：`sessionName` / `takeIndex` / `landingLocation` / `teeLocation?` / `carryDistanceMeters?` / `windSpeedMps?` / `windDirectionDegrees?` / `temperatureCelsius?` / `userNotes?` / `referenceMeasurements`。`referenceMeasurements` 结构与 iOS 样本 metadata 对齐，直接可被 `tools/import_android_landing_gps.py` 按 `(sessionName, takeIndex)` 精确合并到对应样本。
