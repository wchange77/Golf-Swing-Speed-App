# PiTrac 源码来源索引（用于可行性核实）

> 仓库：`https://github.com/PiTracLM/PiTrac`  
> 访问日期：2026-04-20

## 核心入口

- 主 README：
  https://github.com/PiTracLM/PiTrac/blob/main/README.md

## 相机与图像处理核心

- Camera 模块 README：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/LMSourceCode/ImageProcessing/Camera/README.md
- camera_platform.hpp：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/LMSourceCode/ImageProcessing/Camera/camera_platform.hpp
- libcamera_unix_impl.hpp：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/LMSourceCode/ImageProcessing/Camera/infrastructure/unix/libcamera_unix_impl.hpp
- opencv_image_analyzer.cpp：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/LMSourceCode/ImageProcessing/ImageAnalysis/infrastructure/opencv_image_analyzer.cpp

## 标定相关

- CameraCalibration.py：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/CalibrateCameraDistortions/CameraCalibration.py
- generate_charuco_board.py：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/CalibrateCameraDistortions/generate_charuco_board.py
- gs_calibration.cpp：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/LMSourceCode/ImageProcessing/gs_calibration.cpp

## 服务与控制面

- Web API 文档：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/web-server/API_DOCUMENTATION.md
- 服务入口 main.py：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/web-server/main.py
- server.py：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/web-server/server.py
- calibration_manager.py：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/web-server/calibration_manager.py
- camera_detector.py：
  https://github.com/PiTracLM/PiTrac/blob/main/Software/web-server/camera_detector.py

## 测试与文档

- image-analysis-tests workflow：
  https://github.com/PiTracLM/PiTrac/blob/main/.github/workflows/image-analysis-tests.yml
- docs/quickstart：
  https://github.com/PiTracLM/PiTrac/blob/main/docs/quickstart.md
- docs/software/install/build-from-source：
  https://github.com/PiTracLM/PiTrac/blob/main/docs/software/install/build-from-source.md
