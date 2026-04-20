# 四大代码项目总览（数据先行）

本仓库已拆分为 4 个主项目，执行顺序遵循 **数据先行** 原则：先做数据闭环，再迭代两个 app，再做 PiTrac 复现验证。

## 项目列表

1. `projects/HumanClubAnalysisApp`  
   人体 + 球杆分析 app（速度/姿态/挥杆链路）。
2. `projects/GolfBallDetectionApp`  
   高尔夫球检测 app（球检测与轨迹）。
3. `projects/DatasetCollectionPlatform`  
   数据采集、去重、切分、导出、质量分析平台（闭环核心）。
4. `projects/PiTracIPhoneFeasibilityStudy`  
   PiTrac 逻辑在 iPhone 17 Pro Max 上复现的可行性分析项目。

## 数据闭环（避免重复采集）

- 采样会话：`tools/start_session.py`
- 去重注册：`tools/register_sample.py` / `tools/register_batch.py`
- 唯一样本切分：`tools/split_dataset.py`（默认 `strategy=session`）
- 导出清单：`tools/generate_manifest.py`
- 质量报告：`tools/generate_quality_report.py`
- 注册表校验：`tools/validate_registry.py`

## 两个 app 的数据对接

- 人体球杆分析 App：`exports/consumers/human_club_analysis_app.json`
- 高尔夫球检测 App：`exports/consumers/golf_ball_detection_app.json`
- 通用回退清单：`exports/dataset_manifest.json`
- 环境变量覆盖：`HUMAN_CLUB_MANIFEST_PATH` / `GOLF_BALL_MANIFEST_PATH` / `DATASET_MANIFEST_PATH`
