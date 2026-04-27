# PiTrac -> iPhone 复现差距报告

- 目标设备: iPhone 17 Pro Max
- 来源仓库: https://github.com/PiTracLM/PiTrac

| 模块 | 可行性 | 风险 | iOS 目标实现 |
|---|---|---|---|
| camera_pipeline | replaceable | medium | AVFoundation |
| image_analysis | replaceable | medium | Vision+CoreML+Metal |
| calibration | partial | medium | iOS guided calibration + offline calibration utils |
| hardware_io | not_equivalent | high | no direct equivalent |
| web_control_plane | replaceable | medium | in-app configuration and diagnostics |

## 高风险项
- hardware_io: 需替代方案，不可 1:1 复现
