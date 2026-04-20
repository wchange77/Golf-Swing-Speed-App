# Windows 端 iOS 采集流程模拟报告

- 会话 ID: `sess_efc30ee4ffc4`
- 模拟时间(UTC): `2026-04-20T08:15:46.912934+00:00`
- human_club 样本数: 1
- golf_ball_detection 样本数: 1
- 重复样本事件: 1
- 校验错误数: 0
- 总样本数（manifest）: 2
- AppleOS 工程校验: True
- Swift 源码文件数: 7
- Swift 测试文件数: 1

## 命令状态
- `validate_apple_project`: ok
- `start_session`: ok
- `register_samples`: ok
- `split_dataset`: ok
- `generate_manifest`: ok
- `validate_registry`: ok

## 说明
- 该模拟在 Windows 上执行，不依赖 Xcode。
- 目标是验证 Apple 采集端输出字段与 Dataset 平台契约兼容。
