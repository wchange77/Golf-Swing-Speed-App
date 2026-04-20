# 基于 LiDAR 的场景校准 — 技术研究报告

**日期：** 2026-03-29
**范围：** ARKit场景扫描、3D身体姿势、球杆测量、每米像素校准
**目标设备：** iPhone 13 Pro+（需要 LiDAR）、iOS 17+

---

## 1. ARKit场景扫描进行校准

### 1.1 ARWorldTrackingConfiguration 与 LiDAR 场景重建

ARKit 使用 LiDAR 扫描仪创建物理环境的多边形网格。扫描仪无需用户移动即可从大范围内检索深度信息。 ARKit 将其转换为一系列形成网格的顶点，并划分为多个 `ARMeshAnchor` 实例。

**配置设置：**```迅速import ARKit
import RealityKit

class CalibrationARSessionManager: NSObject, ObservableObject, ARSessionDelegate {
    let arView = ARView(frame: .zero)

    func startSession() {
        let configuration = ARWorldTrackingConfiguration()

        // Enable LiDAR scene reconstruction with classification
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.meshWithClassification) {
            configuration.sceneReconstruction = .meshWithClassification
        }

        // Enable plane detection (ground plane)
        configuration.planeDetection = [.horizontal, .vertical]

        // Enable scene depth from LiDAR
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
            configuration.frameSemantics.insert(.smoothedSceneDepth)
        }

        // Enable person segmentation (useful for isolating golfer)
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.personSegmentationWithDepth) {
            configuration.frameSemantics.insert(.personSegmentationWithDepth)
        }

        arView.session.delegate = self
        arView.session.run(configuration)
    }

    func pauseSession() {
        arView.session.pause()
    }
}
```
**`sceneReconstruction` 的关键选项：**
- `.mesh` — 没有分类的基本网格
- `.meshWithClassification` — 带有地板/墙壁/天花板/桌子/座位/窗户/门标签的网格
- 使用`.meshWithClassification`进行高尔夫校准，以可靠地识别地平面

**网格分类类型（`ARMeshClassification`）：**
- `.floor` — 地面（对于校准至关重要）
- `.wall`、`.ceiling`、`.table`、`.seat`、`.window`、`.door`、`.none`

### 1.2 通过 ARKit 平面检测进行地平面检测

ARKit 将平面检测为`ARPlaneAnchor` 对象。对于高尔夫校准，地平面是主要目标。```迅速// ARSessionDelegate method — called when a new plane is detected
func session(_ session: ARSession, didAdd anchors: [ARAnchor]) {
    for anchor in anchors {
        if let planeAnchor = anchor as? ARPlaneAnchor {
            if planeAnchor.alignment == .horizontal {
                // This is a horizontal plane (likely the ground)
                let center = planeAnchor.center        // simd_float3 in anchor's local space
                let extent = planeAnchor.extent        // simd_float3 (width, 0, length) in metres
                let transform = planeAnchor.transform  // simd_float4x4 world transform

                // Ground plane Y coordinate in world space
                let groundY = transform.columns.3.y

                print("Ground plane at Y=\(groundY)m, extent: \(extent.x)m x \(extent.z)m")
            }
        }
    }
}

// Called when ARKit refines a previously detected plane
func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) {
    for anchor in anchors {
        if let planeAnchor = anchor as? ARPlaneAnchor,
           planeAnchor.alignment == .horizontal {
            // Plane refined — update ground plane reference
            // As user moves, ARKit improves plane detection accuracy
        }
    }
}
```
**地平面法线向量提取：**```迅速func groundPlaneNormal(from planeAnchor: ARPlaneAnchor) -> simd_float3 {
    // The plane's local Y-axis in world space is its normal
    let localUp = simd_float4(0, 1, 0, 0)
    let worldNormal = planeAnchor.transform * localUp
    return simd_normalize(simd_float3(worldNormal.x, worldNormal.y, worldNormal.z))
}
```
### 1.3 光线投射 — 用户点击获取 3D 世界坐标

光线投射从 2D 屏幕点发射一条光线穿过 AR 场景，以找到与现实世界表面的交点。这取代了已弃用的`hitTest` API。

**使用 ARView (RealityKit)：**```迅速import UIKit
import ARKit
import RealityKit

class CalibrationViewController: UIViewController {
    var arView: ARView!
    var tappedPoints: [simd_float3] = []

    override func viewDidLoad() {
        super.viewDidLoad()
        arView = ARView(frame: view.bounds)
        view.addSubview(arView)

        let tapGesture = UITapGestureRecognizer(target: self, action: #selector(handleTap(_:)))
        arView.addGestureRecognizer(tapGesture)

        startARSession()
    }

    func startARSession() {
        let config = ARWorldTrackingConfiguration()
        config.planeDetection = [.horizontal]
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
            config.frameSemantics.insert(.smoothedSceneDepth)
        }
        arView.session.run(config)
    }

    @objc func handleTap(_ sender: UITapGestureRecognizer) {
        let tapLocation = sender.location(in: arView)

        // Create raycast query from tap point
        guard let query = arView.makeRaycastQuery(
            from: tapLocation,
            allowing: .estimatedPlane,  // or .existingPlaneGeometry for detected planes only
            alignment: .any
        ) else { return }

        // Perform the raycast
        guard let result = arView.session.raycast(query).first else {
            print("No surface found at tap location")
            return
        }

        // Extract 3D world position from the result
        let worldTransform = result.worldTransform
        let position = simd_float3(
            worldTransform.columns.3.x,
            worldTransform.columns.3.y,
            worldTransform.columns.3.z
        )

        tappedPoints.append(position)
        print("Tapped point at world position: \(position) metres")

        // Place a visual marker at the tapped location
        let marker = ModelEntity(
            mesh: .generateSphere(radius: 0.01),
            materials: [SimpleMaterial(color: .red, isMetallic: false)]
        )
        let anchor = AnchorEntity(world: worldTransform)
        anchor.addChild(marker)
        arView.scene.addAnchor(anchor)
    }
}
```
**光线投射目标选项：**
|目标|描述 |使用案例|
|--------|-------------|----------|
| `.existingPlaneGeometry` |仅检测到平面 |当平面检测正在运行并且您想要精确的平面命中时 |
| @@代码1@@ |无限扩展检测到的平面 |点击超出检测到的平面边界 |
| `.estimatedPlane` | ARKit 在没有检测到的情况下也能估计飞机 |无需启用平面检测即可工作 |

**对齐选项：**
|对齐|描述 |
|------------|-------------|
| `.horizontal` |地面、桌子|
| `.vertical` |墙壁|
| `.any` |两者 |

### 1.4 计算两个 3D 点之间的真实距离

由于 ARKit 以米为单位，因此距离计算是简单的欧几里德距离：```迅速func distanceBetween(_ a: simd_float3, _ b: simd_float3) -> Float {
    return simd_distance(a, b)  // Returns distance in metres
}

// Example: After user taps two points
let pointA = tappedPoints[0]  // e.g. club head position
let pointB = tappedPoints[1]  // e.g. grip position
let clubLength = distanceBetween(pointA, pointB)
print("Club length: \(clubLength) metres (\(clubLength * 100) cm)")
```
**点之间的 3D 矢量（用于角度计算）：**```迅速func vectorBetween(_ from: simd_float3, _ to: simd_float3) -> simd_float3 {
    return to - from
}

func angleBetweenVectors(_ a: simd_float3, _ b: simd_float3) -> Float {
    let dotProduct = simd_dot(simd_normalize(a), simd_normalize(b))
    return acos(simd_clamp(dotProduct, -1.0, 1.0))  // Returns radians
}
```
### 1.5 导出每米像素比例因子

每米像素比例因子随距相机的距离而变化。它是从相机的固有矩阵导出的。

**相机内在方法：**```迅速func pixelsPerMetre(at distanceMetres: Float, from frame: ARFrame) -> Float {
    // Camera intrinsics: 3x3 matrix
    // [fx  0  cx]
    // [0  fy  cy]
    // [0   0   1]
    // fx, fy = focal length in pixels
    // cx, cy = principal point (image center) in pixels

    let intrinsics = frame.camera.intrinsics
    let focalLengthPixels = intrinsics[0][0]  // fx (horizontal focal length)

    // Pinhole camera model: pixels_per_metre = focal_length_px / distance_m
    return focalLengthPixels / distanceMetres
}

// Example usage during calibration:
func calculateScaleFactor(frame: ARFrame, groundDistance: Float) {
    let ppm = pixelsPerMetre(at: groundDistance, from: frame)
    print("At \(groundDistance)m: \(ppm) pixels per metre")
    print("1 pixel = \(1.0 / ppm * 100) cm")

    // For 240fps tracking, this tells us position error per pixel
    // At 2.5m distance with ~1900px focal length:
    // ppm ≈ 760 px/m → 1 pixel ≈ 1.3mm
}
```
**使用 LiDAR 深度 + 光线投射实现精确距离：**```迅速func calibrateScaleFactor(arView: ARView, frame: ARFrame) {
    // Raycast from screen center to ground plane
    let screenCenter = CGPoint(x: arView.bounds.midX, y: arView.bounds.midY)

    guard let query = arView.makeRaycastQuery(
        from: screenCenter,
        allowing: .existingPlaneGeometry,
        alignment: .horizontal
    ) else { return }

    guard let result = arView.session.raycast(query).first else { return }

    // Distance from camera to ground
    let cameraPosition = frame.camera.transform.columns.3
    let groundPosition = result.worldTransform.columns.3
    let distance = simd_distance(
        simd_float3(cameraPosition.x, cameraPosition.y, cameraPosition.z),
        simd_float3(groundPosition.x, groundPosition.y, groundPosition.z)
    )

    let ppm = pixelsPerMetre(at: distance, from: frame)

    // Camera image resolution
    let imageWidth = CVPixelBufferGetWidth(frame.capturedImage)
    let imageHeight = CVPixelBufferGetHeight(frame.capturedImage)

    print("Camera resolution: \(imageWidth)x\(imageHeight)")
    print("Distance to ground: \(distance)m")
    print("Scale: \(ppm) px/m at ground level")
}
```
**重要提示：** 图像中的每米像素比例并不是恒定的 - 它随深度而变化。靠近相机的物体显得更大。对于高尔夫挥杆用例，比例因子应在**挥杆平面距离**（大致为球杆头移动的位置）计算，通常距离相机 2-3 米。

---

## 2. 用于地址位置分析的 3D 身体姿势

### 2.1 VNDetectHumanBodyPose3DRequest — 关节名称和坐标空间

在 iOS 17 (WWDC23) 中引入。返回相对于根关节具有 **17 个关节**（以米为单位）的 3D 骨架。

**17 个关节的完整列表 (`VNHumanBodyPose3DObservation.JointName`)：**

| ＃|联名|身体组|
|---|-----------|------------|
| 1 | @@代码1@@ |头|
| 2 | `.centerHead` |头|
| 3 | `.centerShoulder` |躯干|
| 4 | `.leftShoulder` |躯干/左臂|
| 5 | `.rightShoulder` |躯干/右臂|
| 6 | `.spine` |躯干|
| 7 | `.root` |躯干（臀部中心）|
| 8 | `.leftHip` |躯干/左腿|
| 9 | `.rightHip` |躯干/右腿|
| 10 | 10 `.leftElbow` |左臂|
| 11 | 11 `.leftWrist` |左臂|
| 12 | 12 `.rightElbow` |右臂|
| 13 | `.rightWrist` |右臂|
| 14 | 14 `.leftKnee` |左腿|
| 15 | 15 `.leftAnkle` |左腿|
| 16 | 16 `.rightKnee` |右腿|
| 17 | 17 `.rightAnkle` |右腿|

**联合组名（`JointsGroupName`）：**
- `.head` — 顶头、中心头
- `.torso` — centerShoulder、leftShoulder、rightShoulder、spine、root、leftHip、rightHip
- `.leftArm` — 左肩、左肘、左手腕
- `.rightArm` — 右肩、右肘、右手腕
- `.leftLeg` — 左髋、左膝、左脚踝
- `.rightLeg` — 右髋、右膝、右脚踝
- `.all` — 所有 17 个关节

**坐标空间：**
- 位置以**米**为单位，相对于**根关节**（臀部中心）作为原点
- 左/右相对于**人**（而不是相机/图像）
- 观察中的`cameraOriginMatrix`提供相机相对于人的位置，对于将关节位置转换为相机/世界空间很有用
- 使用 LiDAR：真实的公制位置。不带 LiDAR：假设参考高度为 1.8m

### 2.2 提取肩部、肘部、手腕位置```迅速import Vision

func analyzeBodyPose(from image: CGImage) async throws -> BodyPoseData? {
    let request = VNDetectHumanBodyPose3DRequest()
    let handler = VNImageRequestHandler(cgImage: image, orientation: .up)

    try handler.perform([request])

    guard let observation = request.results?.first else {
        print("No body detected")
        return nil
    }

    // Body height (true metric with LiDAR, else 1.8m reference)
    let bodyHeight = observation.bodyHeight
    let heightTechnique = observation.heightEstimation
    print("Body height: \(bodyHeight)m (technique: \(heightTechnique))")

    // Extract key joints for golf address position
    let rightShoulder = try observation.recognizedPoint(.rightShoulder)
    let rightElbow = try observation.recognizedPoint(.rightElbow)
    let rightWrist = try observation.recognizedPoint(.rightWrist)
    let leftShoulder = try observation.recognizedPoint(.leftShoulder)
    let leftElbow = try observation.recognizedPoint(.leftElbow)
    let leftWrist = try observation.recognizedPoint(.leftWrist)
    let spine = try observation.recognizedPoint(.spine)
    let root = try observation.recognizedPoint(.root)
    let centerShoulder = try observation.recognizedPoint(.centerShoulder)

    // Joint positions are simd_float4x4 transforms relative to root
    // Extract position from the transform's translation column
    let rightWristPos = simd_float3(
        rightWrist.position.columns.3.x,
        rightWrist.position.columns.3.y,
        rightWrist.position.columns.3.z
    )

    let leftWristPos = simd_float3(
        leftWrist.position.columns.3.x,
        leftWrist.position.columns.3.y,
        leftWrist.position.columns.3.z
    )

    print("Right wrist position (relative to root): \(rightWristPos) metres")
    print("Left wrist position (relative to root): \(leftWristPos) metres")

    // Local position — relative to parent joint (elbow is parent of wrist)
    let rightWristLocal = rightWrist.localPosition
    print("Right wrist (relative to elbow): \(rightWristLocal)")

    // Camera origin matrix — camera position relative to person
    let cameraMatrix = observation.cameraOriginMatrix
    print("Camera position: \(cameraMatrix.columns.3)")

    return BodyPoseData(
        rightWrist: rightWristPos,
        leftWrist: leftWristPos,
        spine: extractPosition(spine),
        root: simd_float3(0, 0, 0),  // root is the origin
        bodyHeight: bodyHeight
    )
}

private func extractPosition(_ point: VNHumanBodyRecognizedPoint3D) -> simd_float3 {
    return simd_float3(
        point.position.columns.3.x,
        point.position.columns.3.y,
        point.position.columns.3.z
    )
}
```
**将 3D 关节投影回 2D 图像坐标：**```迅速func project3DJointTo2D(
    observation: VNHumanBodyPose3DObservation,
    jointName: VNHumanBodyPose3DObservation.JointName
) throws -> CGPoint {
    // The observation can project back to 2D normalised coordinates
    let point2D = try observation.pointInImage(jointName)
    // Returns VNRecognizedPoint with x,y in Vision normalised coords (0..1, bottom-left origin)
    return VNImagePointForNormalizedPoint(
        CGPoint(x: point2D.x, y: point2D.y),
        Int(imageWidth),
        Int(imageHeight)
    )
}
```
### 2.3 将身体姿态与 LiDAR 深度数据相结合

当 LiDAR 可用时，来自 VNDetectHumanBodyPose3DRequest 的身体姿势位置已经位于度量空间中。但是，您可以与 LiDAR 深度交叉引用以获得更高的精度：```迅速func getDepthAtJoint(
    frame: ARFrame,
    jointScreenPosition: CGPoint,
    imageSize: CGSize
) -> Float? {
    guard let sceneDepth = frame.smoothedSceneDepth ?? frame.sceneDepth else {
        return nil
    }

    let depthMap = sceneDepth.depthMap
    let depthWidth = CVPixelBufferGetWidth(depthMap)   // 256
    let depthHeight = CVPixelBufferGetHeight(depthMap)  // 192

    // Scale from camera image coordinates to depth map coordinates
    let scaleX = Float(depthWidth) / Float(imageSize.width)
    let scaleY = Float(depthHeight) / Float(imageSize.height)

    let depthX = Int(Float(jointScreenPosition.x) * scaleX)
    let depthY = Int(Float(jointScreenPosition.y) * scaleY)

    guard depthX >= 0, depthX < depthWidth,
          depthY >= 0, depthY < depthHeight else {
        return nil
    }

    CVPixelBufferLockBaseAddress(depthMap, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }

    let bytesPerRow = CVPixelBufferGetBytesPerRow(depthMap)
    guard let baseAddress = CVPixelBufferGetBaseAddress(depthMap)?
        .assumingMemoryBound(to: Float32.self) else {
        return nil
    }

    let index = depthY * bytesPerRow / MemoryLayout<Float32>.stride + depthX
    return baseAddress[index]  // Distance in metres
}
```
**用于过滤不可靠读数的置信图：**```迅速func getDepthConfidence(
    frame: ARFrame,
    depthX: Int,
    depthY: Int
) -> ARConfidenceLevel? {
    guard let confidenceMap = frame.smoothedSceneDepth?.confidenceMap ??
                              frame.sceneDepth?.confidenceMap else {
        return nil
    }

    CVPixelBufferLockBaseAddress(confidenceMap, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(confidenceMap, .readOnly) }

    let bytesPerRow = CVPixelBufferGetBytesPerRow(confidenceMap)
    guard let baseAddress = CVPixelBufferGetBaseAddress(confidenceMap)?
        .assumingMemoryBound(to: UInt8.self) else {
        return nil
    }

    let index = depthY * bytesPerRow + depthX
    let value = baseAddress[index]

    // 0 = low, 1 = medium, 2 = high
    return ARConfidenceLevel(rawValue: Int(value))
}
```
### 2.4 2-3m 处 3D 身体姿势的准确性和局限性

**使用激光雷达 (iPhone 13 Pro)：**
- 关节位置采用真实公制比例（米）
- `bodyHeight` 反映测量高度，而不是 1.8m 回退高度
- 位置精度：2-3m距离处的主要关节约为2-5cm
- 手腕检测对于高尔夫至关重要 - 它是跟踪的最远端关节（没有手/手指）

**没有激光雷达：**
- 回落至 1.8m 参考高度假设
- 所有指标值均基于此假设进行缩放
- 如果高尔夫球手身高 1.7m 或 1.9m，则所有测量值均存在比例误差

**已知限制：**
- **仅限单个人** — 仅检测最近/最突出的人
- **没有手或手指关节** - 手腕是每只手臂上的最后一个跟踪点
- **无球杆检测** - 身体姿势不跟踪所持物体
- **遮挡敏感性** - 身体后面的关节可能会以较低的精度进行估计
- **仅 17 个关节** — 无脊柱细分，无足部方向
- **处理成本** — 3D 姿势比 2D 更昂贵；适合静态校准，不适合240fps
- **距离范围** — 最佳距离为 1.5-4m；超过 4m 精度会下降

---

## 3. 从瞄准位置测量球杆

### 3.1 检测地址处的球杆头（静态）

在瞄准位置，球杆头静止不动并搁在地面上。这是检测的理想时间——没有运动模糊。

**策略：自定义核心 ML 模型（推荐）**

对于生产，使用 Create ML 在高尔夫球杆头图像上训练 YOLO 模型：```迅速import Vision
import CoreML

func detectClubHead(in image: CGImage) async throws -> CGRect? {
    // Load custom-trained club head detection model
    guard let model = try? VNCoreMLModel(
        for: GolfClubHeadDetector(configuration: .init()).model
    ) else {
        print("Failed to load club head model")
        return nil
    }

    let request = VNCoreMLRequest(model: model)
    request.imageCropAndScaleOption = .scaleFill

    let handler = VNImageRequestHandler(cgImage: image, orientation: .up)
    try handler.perform([request])

    guard let results = request.results as? [VNRecognizedObjectObservation],
          let bestResult = results.first else {
        return nil
    }

    // Returns bounding box in Vision normalised coordinates (0..1, bottom-left origin)
    print("Club head detected with confidence: \(bestResult.confidence)")
    return bestResult.boundingBox
}
```
**策略：轮廓检测（后备/原型）**

对于 ML 模型训练之前的早期原型设计：```迅速import Vision

func detectClubHeadViaContours(in image: CGImage) throws -> CGPoint? {
    let contourRequest = VNDetectContoursRequest()
    contourRequest.contrastAdjustment = 2.0
    contourRequest.detectsDarkOnLight = true

    let handler = VNImageRequestHandler(cgImage: image, orientation: .up)
    try handler.perform([contourRequest])

    guard let contours = contourRequest.results?.first else {
        return nil
    }

    // Filter contours by area and position (club head is near bottom of frame)
    // This requires heuristics based on expected club head size and position
    // Not recommended for production — use ML model instead

    return nil // Placeholder — requires significant heuristic tuning
}
```
**策略：用户引导点击（最简单，当前实施）**

当前的`ManualCalibrationView.swift` 使用手动敲击——用户在屏幕上敲击球杆头。这是最简单、最可靠的校准方法：```迅速// User taps club head location on camera preview
// Convert tap to 3D via raycasting (see Section 1.3)
// This is already partially implemented in ManualCalibrationView
```
### 3.2 从 LiDAR 深度获取球杆头 3D 位置

一旦球杆头位于 2D 位置（通过 ML 检测或用户点击），检索其 3D 位置：```迅速func getClubHead3DPosition(
    screenPosition: CGPoint,
    arView: ARView,
    frame: ARFrame
) -> simd_float3? {

    // Method 1: Raycast from screen position to ground plane
    // Best when club head is resting on the ground at address
    if let query = arView.makeRaycastQuery(
        from: screenPosition,
        allowing: .existingPlaneGeometry,
        alignment: .horizontal
    ) {
        if let result = arView.session.raycast(query).first {
            let pos = result.worldTransform.columns.3
            return simd_float3(pos.x, pos.y, pos.z)
        }
    }

    // Method 2: Use LiDAR depth map directly
    // Better when club head is elevated (e.g. during waggle)
    let imageSize = CGSize(
        width: CVPixelBufferGetWidth(frame.capturedImage),
        height: CVPixelBufferGetHeight(frame.capturedImage)
    )

    guard let depthMetres = getDepthAtJoint(
        frame: frame,
        jointScreenPosition: screenPosition,
        imageSize: imageSize
    ) else {
        return nil
    }

    // Unproject 2D + depth to 3D using camera intrinsics
    let intrinsics = frame.camera.intrinsics
    let fx = intrinsics[0][0]
    let fy = intrinsics[1][1]
    let cx = intrinsics[2][0]
    let cy = intrinsics[2][1]

    // Convert screen position to camera image coordinates
    // (accounting for any preview scaling)
    let imgX = Float(screenPosition.x)  // adjust for preview-to-image mapping
    let imgY = Float(screenPosition.y)

    // Unproject using pinhole model
    let x = (imgX - cx) * depthMetres / fx
    let y = (imgY - cy) * depthMetres / fy
    let z = depthMetres

    // This is in camera-local coordinates
    // Transform to world coordinates using camera transform
    let cameraTransform = frame.camera.transform
    let cameraPoint = simd_float4(x, y, z, 1.0)
    let worldPoint = cameraTransform * cameraPoint

    return simd_float3(worldPoint.x, worldPoint.y, worldPoint.z)
}
```
### 3.3 计算球杆长度（手腕到球杆头 3D 距离）```迅速struct ClubCalibrationData {
    let clubHeadPosition: simd_float3   // From LiDAR/raycast
    let leadWristPosition: simd_float3  // From body pose (left wrist for right-handed)
    let trailWristPosition: simd_float3 // From body pose (right wrist for right-handed)
    let groundPlaneY: Float             // From plane detection

    /// Club length from lead wrist to club head (metres)
    var clubLength: Float {
        simd_distance(leadWristPosition, clubHeadPosition)
    }

    /// Shaft vector from grip to club head
    var shaftVector: simd_float3 {
        simd_normalize(clubHeadPosition - leadWristPosition)
    }

    /// Grip midpoint (between lead and trail wrists)
    var gripCenter: simd_float3 {
        (leadWristPosition + trailWristPosition) / 2.0
    }
}

func measureClub(
    bodyPose: BodyPoseData,
    clubHeadWorldPos: simd_float3,
    groundY: Float,
    isRightHanded: Bool
) -> ClubCalibrationData {
    // For a right-handed golfer:
    // Lead hand (lower on grip) = left hand
    // Trail hand (upper on grip) = right hand
    let leadWrist = isRightHanded ? bodyPose.leftWrist : bodyPose.rightWrist
    let trailWrist = isRightHanded ? bodyPose.rightWrist : bodyPose.leftWrist

    // NOTE: Body pose positions are relative to root (hip center)
    // Must transform to world coordinates using cameraOriginMatrix
    // if comparing with ARKit world-space club head position

    return ClubCalibrationData(
        clubHeadPosition: clubHeadWorldPos,
        leadWristPosition: leadWrist,
        trailWristPosition: trailWrist,
        groundPlaneY: groundY
    )
}
```
### 3.4 计算杆底角（轴与地平面）

杆底角是球杆杆身与地面之间的角度。对于标准熨斗，该角度通常为 60-65 度。```迅速func calculateLieAngle(calibration: ClubCalibrationData) -> Float {
    // Shaft vector from wrist down to club head
    let shaft = calibration.shaftVector

    // Ground plane normal (pointing up)
    let groundNormal = simd_float3(0, 1, 0)

    // Ground plane tangent (project shaft onto ground plane)
    // The shaft direction projected onto the horizontal plane
    let shaftHorizontal = simd_float3(shaft.x, 0, shaft.z)

    // Lie angle = angle between shaft and its horizontal projection
    // = 90 - angle between shaft and ground normal
    let angleToVertical = acos(simd_dot(simd_normalize(shaft), groundNormal))
    let lieAngle = Float.pi / 2.0 - angleToVertical

    let lieAngleDegrees = lieAngle * 180.0 / Float.pi
    print("Lie angle: \(lieAngleDegrees) degrees")

    return lieAngleDegrees
}
```
### 3.5 从地址位置估计挥杆平面

挥杆平面由三点定义：脊椎角度、手部位置和球杆头位置。```迅速func estimateSwingPlane(
    bodyPose: BodyPoseData,
    clubHeadPosition: simd_float3
) -> (normal: simd_float3, angle: Float) {
    // Three points define the swing plane:
    // 1. Spine/shoulder center
    // 2. Hand position (wrist midpoint)
    // 3. Club head position

    let shoulder = bodyPose.spine  // or centerShoulder
    let hands = (bodyPose.leftWrist + bodyPose.rightWrist) / 2.0
    let clubHead = clubHeadPosition

    // Two vectors in the plane
    let v1 = hands - shoulder
    let v2 = clubHead - shoulder

    // Plane normal = cross product of the two vectors
    let planeNormal = simd_normalize(simd_cross(v1, v2))

    // Swing plane angle relative to ground
    // = angle between plane normal and horizontal
    let groundNormal = simd_float3(0, 1, 0)
    let angleToGround = acos(abs(simd_dot(planeNormal, groundNormal)))
    let swingPlaneAngle = Float.pi / 2.0 - angleToGround

    let angleDegrees = swingPlaneAngle * 180.0 / Float.pi
    print("Estimated swing plane angle: \(angleDegrees) degrees from horizontal")

    return (normal: planeNormal, angle: angleDegrees)
}
```
**这些校准值在跟踪期间成为卡尔曼滤波器约束：**
- 球杆头必须位于检测到的手腕的 `clubLength` 范围内
- 球杆头应大致保持在挥杆平面上（有一些偏差）
- 击球时，球杆头应靠近地平面 Y

---

## 4. 主要约束和限制

### 4.1 激光雷达硬件规格

|物业 |价值|
|----------|--------|
|帧率| 60 Hz（与 240fps 相机相比）|
|分辨率| 256 x 192 像素 |
|范围 | 0.2 - 5.0 米 |
|技术 | dToF（直接飞行时间）|

**为什么激光雷达无法追踪摆动：**
- 在 60Hz 频率下，100mph 的球杆头在 LiDAR 框架之间移动约 0.75 米
- 256x192 分辨率对于亚厘米球杆头跟踪来说太粗糙
- LiDAR仅适用于地址位置的**静态校准**

### 4.2 LiDAR 仅在静态校准期间

校准工作流程应该是：
1. **使用 LiDAR + 平面检测启动 ARKit 会话**
2. **高尔夫球手站在瞄准位置** — 静态位置，球杆放在地面上
3. **通过ARKit平面检测检测地平面**
4. **在当前帧上运行 3D 身体姿势**
5. **检测/点击球杆头**位置
6. **计算校准值：** 球杆长度、杆底角、挥杆平面、每米像素
7. **暂停 ARKit 会话**
8. **切换到 AVCaptureSession** 进行 240fps 捕获

### 4.3 iPhone 13 Pro 具体注意事项

- 有 LiDAR 扫描仪（与 12 Pro 相同的硬件）
- 支持 ARWorldTrackingConfiguration 和 sceneReconstruction
- 支持`.smoothedSceneDepth`帧语义
- 摄像头：1920x1440，最高 240fps（实际 fps 可能有所不同 — 报告为 162-200fps）
- A15 仿生芯片 — 足以进行捕获后处理，但在持续负载下会出现热节流
- `VNDetectHumanBodyPose3DRequest` 需要 iOS 17+（适用于 iPhone 13 Pro）

### 4.4 ARKit Session 和 AVCaptureSession 共存

**它们不能同时运行。**这是 iOS 的一个基本限制。

当您启动 AVCaptureSession 时，任何正在运行的 ARSession 都会停止。当您启动 ARSession 时，任何正在运行的 AVCaptureSession 都会停止。

**高尔夫应用程序的推荐工作流程：**```┌─────────────────────────────────────────┐
│  Phase 1: CALIBRATION (ARKit)           │
│  - ARWorldTrackingConfiguration         │
│  - LiDAR scene depth                    │
│  - Plane detection                      │
│  - 3D body pose analysis                │
│  - Club measurement                     │
│  - Store calibration data               │
│  - Pause ARSession                      │
└────────────────┬────────────────────────┘
                 │ ~0.3-0.5s switch time
┌────────────────▼────────────────────────┐
│  Phase 2: CAPTURE (AVFoundation)        │
│  - AVCaptureSession at 240fps           │
│  - Audio detection for swing trigger    │
│  - High-speed video capture             │
│  - Use stored calibration values        │
│  - No LiDAR/ARKit available             │
└─────────────────────────────────────────┘
```
**切换时间（由社区衡量）：**
- ARKit → AVCaptureSession：~0.3 秒（使用 AVCaptureVideoDataOutput）
- 需要从 AVCaptureSession 中删除前 ~5 帧（它们是黑暗的）
- 总过渡：约 0.5 秒可见屏幕冻结
- 切换期间 0.05 弧度（~3 度）方向漂移

**保存和恢复 ARKit 状态：**```迅速// Before switching to AVCaptureSession
func saveARState(session: ARSession, completion: @escaping (ARWorldMap?) -> Void) {
    session.getCurrentWorldMap { worldMap, error in
        if let map = worldMap {
            // Store for potential later re-calibration
            completion(map)
        } else {
            completion(nil)
        }
        session.pause()
    }
}

// Later, if you need to re-enter ARKit
func restoreARState(arView: ARView, worldMap: ARWorldMap) {
    let config = ARWorldTrackingConfiguration()
    config.initialWorldMap = worldMap
    config.planeDetection = [.horizontal]
    arView.session.run(config, options: [])
}
```
---

## 5. 完整的校准流程 — Swift 代码

### 5.1 完整的 ARKit 校准会话设置```迅速import ARKit
import RealityKit
import Vision
import Combine

@Observable
class LiDARCalibrationManager: NSObject, ARSessionDelegate {

    // MARK: - Published State
    var isCalibrating = false
    var groundPlaneDetected = false
    var bodyPoseDetected = false
    var calibrationComplete = false
    var statusMessage = "Initialising..."

    // MARK: - Calibration Results
    var groundPlaneY: Float = 0
    var groundPlaneNormal: simd_float3 = simd_float3(0, 1, 0)
    var clubLength: Float = 0          // metres
    var lieAngle: Float = 0            // degrees
    var swingPlaneAngle: Float = 0     // degrees
    var pixelsPerMetreAtSwingPlane: Float = 0
    var distanceToGolfer: Float = 0    // metres

    // MARK: - Internal
    private var arView: ARView?
    private var detectedGroundAnchor: ARPlaneAnchor?
    private var latestFrame: ARFrame?

    // MARK: - Setup

    func configureARView(_ arView: ARView) {
        self.arView = arView
        arView.session.delegate = self
    }

    func startCalibration() {
        guard let arView else { return }

        let config = ARWorldTrackingConfiguration()

        // Ground plane detection
        config.planeDetection = [.horizontal]

        // LiDAR scene depth
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
            config.frameSemantics.insert(.smoothedSceneDepth)
        }

        // Scene reconstruction (for mesh classification)
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.meshWithClassification) {
            config.sceneReconstruction = .meshWithClassification
        }

        arView.session.run(config, options: [.resetTracking, .removeExistingAnchors])
        isCalibrating = true
        statusMessage = "Scanning ground plane..."
    }

    func stopCalibration() {
        arView?.session.pause()
        isCalibrating = false
    }

    // MARK: - ARSessionDelegate

    func session(_ session: ARSession, didAdd anchors: [ARAnchor]) {
        for anchor in anchors {
            if let plane = anchor as? ARPlaneAnchor,
               plane.alignment == .horizontal {
                detectedGroundAnchor = plane
                groundPlaneY = plane.transform.columns.3.y
                groundPlaneDetected = true
                statusMessage = "Ground detected. Position golfer at address."
            }
        }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        latestFrame = frame
    }

    // MARK: - Depth Reading

    func depthAtScreenPoint(_ point: CGPoint) -> Float? {
        guard let frame = latestFrame,
              let sceneDepth = frame.smoothedSceneDepth ?? frame.sceneDepth else {
            return nil
        }

        let depthMap = sceneDepth.depthMap
        let depthW = CVPixelBufferGetWidth(depthMap)
        let depthH = CVPixelBufferGetHeight(depthMap)

        let imgW = CVPixelBufferGetWidth(frame.capturedImage)
        let imgH = CVPixelBufferGetHeight(frame.capturedImage)

        // Scale from image coordinates to depth map coordinates
        let dx = Int(Float(point.x) / Float(imgW) * Float(depthW))
        let dy = Int(Float(point.y) / Float(imgH) * Float(depthH))

        guard dx >= 0, dx < depthW, dy >= 0, dy < depthH else { return nil }

        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(depthMap)
        guard let base = CVPixelBufferGetBaseAddress(depthMap)?
            .assumingMemoryBound(to: Float32.self) else { return nil }

        let index = dy * bytesPerRow / MemoryLayout<Float32>.stride + dx
        return base[index]
    }

    // MARK: - Raycast from Screen Tap

    func worldPosition(fromScreenPoint point: CGPoint) -> simd_float3? {
        guard let arView else { return nil }

        guard let query = arView.makeRaycastQuery(
            from: point,
            allowing: .existingPlaneGeometry,
            alignment: .horizontal
        ) else { return nil }

        guard let result = arView.session.raycast(query).first else { return nil }

        let col3 = result.worldTransform.columns.3
        return simd_float3(col3.x, col3.y, col3.z)
    }

    // MARK: - 3D Body Pose

    func analyzeBodyPose() async -> BodyPoseResult? {
        guard let frame = latestFrame else { return nil }

        let pixelBuffer = frame.capturedImage
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)

        let context = CIContext()
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else {
            return nil
        }

        let request = VNDetectHumanBodyPose3DRequest()
        let handler = VNImageRequestHandler(cgImage: cgImage, orientation: .right)

        do {
            try handler.perform([request])
        } catch {
            print("Body pose failed: \(error)")
            return nil
        }

        guard let obs = request.results?.first else {
            statusMessage = "No person detected. Stand at address."
            return nil
        }

        bodyPoseDetected = true

        // Extract wrist positions
        let lw = try? obs.recognizedPoint(.leftWrist)
        let rw = try? obs.recognizedPoint(.rightWrist)
        let sp = try? obs.recognizedPoint(.spine)
        let cs = try? obs.recognizedPoint(.centerShoulder)

        func pos(_ p: VNHumanBodyRecognizedPoint3D?) -> simd_float3? {
            guard let p else { return nil }
            return simd_float3(
                p.position.columns.3.x,
                p.position.columns.3.y,
                p.position.columns.3.z
            )
        }

        return BodyPoseResult(
            leftWrist: pos(lw),
            rightWrist: pos(rw),
            spine: pos(sp),
            centerShoulder: pos(cs),
            bodyHeight: obs.bodyHeight,
            cameraOriginMatrix: obs.cameraOriginMatrix
        )
    }

    // MARK: - Pixels Per Metre

    func calculatePixelsPerMetre(atDistance distance: Float) -> Float {
        guard let frame = latestFrame else { return 0 }
        let fx = frame.camera.intrinsics[0][0]
        return fx / distance
    }

    // MARK: - Complete Calibration

    func performFullCalibration(
        clubHeadScreenPoint: CGPoint,
        isRightHanded: Bool
    ) async -> Bool {

        // 1. Get club head 3D position via raycast
        guard let clubHead3D = worldPosition(fromScreenPoint: clubHeadScreenPoint) else {
            statusMessage = "Could not locate club head in 3D"
            return false
        }

        // 2. Analyze body pose
        guard let pose = await analyzeBodyPose() else {
            statusMessage = "Could not detect body pose"
            return false
        }

        // 3. Determine lead/trail wrist
        guard let leadWrist = isRightHanded ? pose.leftWrist : pose.rightWrist,
              let trailWrist = isRightHanded ? pose.rightWrist : pose.leftWrist,
              let spine = pose.spine else {
            statusMessage = "Missing joint data"
            return false
        }

        // NOTE: Body pose positions are relative to root joint.
        // Club head position is in ARKit world space.
        // Must transform body pose to world space using cameraOriginMatrix
        // before comparing. This is a simplification — in production,
        // use the full transform chain.

        // 4. Calculate club length
        clubLength = simd_distance(leadWrist, clubHead3D)

        // 5. Calculate lie angle
        let shaftVec = simd_normalize(clubHead3D - leadWrist)
        let angleToVert = acos(simd_dot(shaftVec, simd_float3(0, 1, 0)))
        lieAngle = (Float.pi / 2.0 - angleToVert) * 180.0 / Float.pi

        // 6. Estimate swing plane
        let hands = (leadWrist + trailWrist) / 2.0
        let v1 = hands - spine
        let v2 = clubHead3D - spine
        let planeNorm = simd_normalize(simd_cross(v1, v2))
        let groundAngle = acos(abs(simd_dot(planeNorm, simd_float3(0, 1, 0))))
        swingPlaneAngle = (Float.pi / 2.0 - groundAngle) * 180.0 / Float.pi

        // 7. Calculate pixels-per-metre at swing plane distance
        guard let frame = latestFrame else { return false }
        let camPos = frame.camera.transform.columns.3
        distanceToGolfer = simd_distance(
            simd_float3(camPos.x, camPos.y, camPos.z),
            hands
        )
        pixelsPerMetreAtSwingPlane = calculatePixelsPerMetre(atDistance: distanceToGolfer)

        statusMessage = "Calibration complete"
        calibrationComplete = true

        print("""
        === Calibration Results ===
        Club length: \(clubLength * 100) cm
        Lie angle: \(lieAngle)°
        Swing plane: \(swingPlaneAngle)° from horizontal
        Distance to golfer: \(distanceToGolfer) m
        Scale: \(pixelsPerMetreAtSwingPlane) px/m
        1 pixel ≈ \(1.0 / pixelsPerMetreAtSwingPlane * 1000) mm
        """)

        return true
    }
}

// MARK: - Data Types

struct BodyPoseResult {
    let leftWrist: simd_float3?
    let rightWrist: simd_float3?
    let spine: simd_float3?
    let centerShoulder: simd_float3?
    let bodyHeight: Float
    let cameraOriginMatrix: simd_float4x4
}
```
### 5.2 ARView 的 SwiftUI 集成```迅速import SwiftUI
import ARKit
import RealityKit

struct ARCalibrationView: UIViewRepresentable {
    let calibrationManager: LiDARCalibrationManager

    func makeUIView(context: Context) -> ARView {
        let arView = ARView(frame: .zero)
        calibrationManager.configureARView(arView)

        let tapGesture = UITapGestureRecognizer(
            target: context.coordinator,
            action: #selector(Coordinator.handleTap(_:))
        )
        arView.addGestureRecognizer(tapGesture)

        return arView
    }

    func updateUIView(_ uiView: ARView, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(manager: calibrationManager)
    }

    class Coordinator: NSObject {
        let manager: LiDARCalibrationManager

        init(manager: LiDARCalibrationManager) {
            self.manager = manager
        }

        @objc func handleTap(_ sender: UITapGestureRecognizer) {
            guard let arView = sender.view as? ARView else { return }
            let point = sender.location(in: arView)

            // User taps club head position
            Task {
                await manager.performFullCalibration(
                    clubHeadScreenPoint: point,
                    isRightHanded: true
                )
            }
        }
    }
}
```
---

## 6. 坐标空间总结

|数据来源|坐标空间 |单位 |产地 |
|------------|-----------------|--------|--------|
| ARKit 世界追踪 |世界空间|米|会话开始位置 |
| AR飞机锚|世界空间（通过变换）|米|锚定中心|
| ARKit 光线投射结果 |世界空间（worldTransform）|米|交点|
| ARFrame.sceneDepth |深度图 (256x192) |米 (Float32) |距相机的每像素距离 |
| ARCamera.intrinsics | ARCamera.intrinsics |像素空间 |像素（焦距）|相机传感器|
| VNDetectHumanBodyPose3D 请求 |局部骨架|米|根关节（髋中心）|
| | VNHumanBodyRecognizedPoint3D.position | VNHumanBodyRecognizedPoint3D.position |局部骨架|米|根关节|
| VNHumanBodyRecognizedPoint3D.localPosition | VNHumanBodyRecognizedPoint3D.localPosition |父-联合-本地|米|家长联名|
|相机原点矩阵 |相机到骨骼|米|相机相对于人的位置|

**关键：用于将身体姿势与 ARKit 位置进行比较的坐标变换链：**```Body pose (root-relative) → cameraOriginMatrix → Camera space → ARFrame.camera.transform → World space
```
---

## 7. 参考文献

-[ARWorldTrackingConfiguration — Apple 开发者](https://developer.apple.com/documentation/arkit/arworldtrackingconfiguration)
-[可视化重建场景并与之交互 — Apple Developer](https://developer.apple.com/documentation/ARKit/visualizing-and-interacting-with-a-reconstructed-scene)
-[sceneReconstruction 属性 — Apple 开发者](https://developer.apple.com/documentation/arkit/arworldtrackingconfiguration/scenereconstruction)
-[VNDetectHumanBodyPose3DRequest — Apple 开发者](https://developer.apple.com/documentation/vision/vndetecthumanbodypose3drequest)
-[VNHumanBodyPose3DObservation.JointName — Apple 开发者](https://developer.apple.com/documentation/vision/vnhumanbodypose3dobservation/jointname)
-[使用视觉检测 3D 人体姿势 — Apple Developer](https://developer.apple.com/documentation/Vision/detecting-human-body-poses-in-3d-with-vision)
-[探索视觉中的 3D 身体姿势和人物分割 — WWDC23](https://developer.apple.com/videos/play/wwdc2023/111241/)
-[放置对象并处理 3D 交互 — Apple Developer](https://developer.apple.com/documentation/arkit/world_tracking/placing_objects_and_handling_3d_interaction)
-[ARDepthData — Apple 开发者](https://developer.apple.com/documentation/arkit/ardepthdata)
-[ARCamera — 苹果开发者](https://developer.apple.com/documentation/arkit/arcamera)
-[跟踪和可视化平面 — Apple Developer](https://developer.apple.com/documentation/arkit/arkit_in_ios/content_anchors/tracking_and_visualizing_planes)
-[ARKit 和 AVFoundation 切换时序 — Medium](https://rockyshikoku.medium.com/how-many-seconds-does-it-take-to-switch-between-arkit-and-avfoundation-5b8eebcadf2c)
-[LiDAR 深度读取 — Medium](https://rockyshikoku.medium.com/obtain-the-distance-in-meters-from-scenedepth-ardepthdata-which-measures-the-distance-between-f900f10d4161)
-[WWDC23 3D 身体姿势分析 — 中](https://medium.com/@frentebw/wwdc2023-apples-new-vision-framework-with-3d-detection-9335051d7acd)
-[ARKit 911 场景重建 — Medium](https://medium.com/macoclock/arkit-911-scene-reconstruction-with-a-lidar-scanner-57ff0a8b247e)
-[ARKit LiDAR 点云 — Medium](https://medium.com/@ivkuznetsov/arkit-lidar-building-point-clouds-in-swift-2c9b7eb88b03)
-[SwiftUI 应用程序中的 ARKit — gfrigerio.com](https://www.gfrigerio.com/arkit-in-a-swiftui-app/)
-[Apple 开发者论坛 — ARKit + AVCaptureSession](https://developer.apple.com/forums/thread/677731)

## 核实注释（2026-04-20）

### 已核实（含来源）
- ARKit 世界跟踪、场景重建、raycast 路径：R05-R07。
- Vision 3D 人体姿态请求入口：R08-R09。
- 与相机时间轴对齐的帧时间戳来源：R10。

### 详细检查与注释
- 文档中“2-3m 下姿态绝对误差固定范围”类断言需标记为“待实测”，官方文档通常不给固定精度承诺。
- “地址位球杆头检测”目前更多依赖算法设计与数据质量，不应写成“已保证”。
- 建议把“校准失败回退策略”从建议级提升为必选流程。

### 待补研究内容
- 增加“raycast 失败与重试”状态机图。
- 增加“标定置信度评分”公式与阈值。
- 增加“姿态 + 深度融合误差”实测章节。
