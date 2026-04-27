# PiTracIPhoneFeasibilityStudy

第四主项目：评估 `PiTrac` 逻辑在 **iPhone 17 Pro Max** 上复现的可行性，并输出可执行迁移路线。

目标不是直接移植 C++/Raspberry Pi 工程，而是进行**能力映射与替代实现设计**：

- PiTrac 的相机/标定/图像分析/服务逻辑 -> iOS AVFoundation + ARKit + Vision + Core ML
- PiTrac 的本地 Web 控制面 -> iOS App 内配置与调试面板
- PiTrac 的硬件控制（灯、外设） -> iPhone 可用能力（闪光灯/帧率/曝光）替代

## 输出物

- `sources/pitrac_source_index.md`：关键源码来源索引（含 URL）
- `analysis/feasibility_matrix.md`：模块复现可行性矩阵
- `analysis/reproduction_plan.md`：分阶段迁移计划
- `config/module_mapping.json`：机器可读映射表
- `tools/build_gap_report.py`：从映射表自动生成 gap 报告

## 快速执行

```bash
python tools/build_gap_report.py
```
