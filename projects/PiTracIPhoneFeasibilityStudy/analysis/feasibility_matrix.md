# PiTrac -> iPhone 17 Pro Max 可行性矩阵

| PiTrac 模块 | 代表来源 | iPhone 复现结论 | 复现路径 | 风险等级 |
|---|---|---|---|---|
| Camera/libcamera 抽象 | Camera README / libcamera_unix_impl.hpp | 可复现（替代） | AVFoundation 捕获管线 | 中 |
| OpenCV 图像分析 | opencv_image_analyzer.cpp | 可复现（替代） | Vision + Core ML + Metal 性能优化 | 中 |
| Charuco 标定工具链 | CameraCalibration.py / generate_charuco_board.py | 部分可复现 | iOS 端引导标定 + 离线校正工具 | 中 |
| Web Server 控制面 | web-server/main.py / server.py | 需架构改写 | 原生 App 设置页 + 本地调试页 | 中 |
| 硬件外设控制（灯/板级） | 硬件文档与服务脚本 | 不可等价复现 | 使用 iPhone 闪光灯/曝光/帧率策略替代 | 高 |
| 配置管理与测试体系 | config_manager.py / workflows | 可复现 | iOS 配置模型 + XCTest + CI | 低 |

## 结论摘要

- **软件逻辑大部分可复现**，但需要“同等功能、不同实现”的替代设计。
- **硬件耦合能力无法 1:1 复现**（尤其外设控制），应以移动端可用能力重构。
- 建议先做最小可行链路：采集 -> 标定 -> 检测 -> 结果输出。
