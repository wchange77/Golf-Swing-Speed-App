# GoBirdie-Desktop 项目分析（iPhone 17 Pro Max 可用性评估）

> 仓库：`nicechester/GoBirdie-Desktop`（桌面端）+ `nicechester/GoBirdie`（iOS 端）
> 语言：Rust (Tauri 2) + JavaScript（桌面）/ Swift (SwiftUI)（iOS）
> 定位：高尔夫数据分析平台 — Garmin 手表 & Apple Watch 数据解析 + Strokes Gained 分析

## 一、项目概述

GoBirdie 是一个双端高尔夫分析系统：

- **GoBirdie iOS**：iPhone + Apple Watch 端，GPS 实时距离、击球追踪、记分卡、MultipeerConnectivity 同步
- **GoBirdie Desktop**：Tauri 2 桌面端，FIT 文件解析、Strokes Gained 分析、击球散布热力图、NLG 洞察引擎

### 技术栈

| 组件 | 桌面端 | iOS 端 |
|------|--------|--------|
| 框架 | Tauri 2 + Vite | SwiftUI (iOS 18+/watchOS 11+) |
| 后端 | Rust (fitparser, sled) | Swift Package (GoBirdieCore) |
| 前端 | Vanilla JS + Tailwind | SwiftUI + MapLibre |
| 数据 | sled 嵌入式 KV | JSON 文件持久化 |
| 同步 | MTP (USB) | MultipeerConnectivity (BT+WiFi P2P) |
| 地图 | Leaflet | MapLibre |
| 课程数据 | — | OpenStreetMap Overpass API + GolfCourseAPI |

## 二、核心算法详解

### 2.1 Strokes Gained 分析

基于 Mark Broadie《Every Shot Counts》方法论，使用单差点业余基线。

**核心公式**：
```
SG = expected_strokes_before - (1 + expected_strokes_after)
```

**基线数据表**（单差点业余水平）：

| 球位 | 距离范围 | 示例数据点 |
|------|---------|-----------|
| Tee | 100-600 码 | 100码→2.72杆, 250码→3.28杆, 400码→3.90杆 |
| Fairway | 20-275 码 | 50码→2.61杆, 150码→3.15杆, 250码→3.78杆 |
| Rough | 20-250 码 | 50码→2.78杆, 150码→3.36杆（比 fairway +0.15~0.2 罚杆） |
| Green | 1-90 英尺 | 3ft→1.07推, 10ft→1.58推, 30ft→2.03推 |

**分类逻辑**：
- **Off the Tee**：第一杆且 par ≥ 4
- **Approach**：非推杆且距离 ≥ 50 码
- **Short Game**：非推杆且距离 < 50 码
- **Putting**：推杆

**球位判定**：
- 第一杆 → tee
- 推杆 → green
- 距离 < 50 码 → fairway（短杆区域）
- 第二杆且 fairway_hit → fairway，否则 → rough

**插值算法**：线性插值，在基线表相邻数据点之间计算期望杆数。

### 2.2 击球散布热力图

按距离到果岭分桶（0-50, 51-100, 101-150, 151-200, 200+ 码），5×5 方向×距离网格：
- 方向维度：左偏 / 略左 / 直线 / 略右 / 右偏
- 距离维度：短 / 略短 / 标准 / 略长 / 长
- 每个格子显示击球次数和平均 SG

### 2.3 NLG 规则引擎

~35 条双语（英/韩）洞察模板，按严重度和层级排序：

**架构**：
```
NLG_TEMPLATES[] → condition(ctx) 评估 → 触发模板 → 随机选择变体 → 排序输出
```

**严重度**：critical > warning > positive > info
**层级**：Tier 1（最重要）→ Tier 4（次要）

**示例规则**：
| 规则 | 条件 | 严重度 |
|------|------|--------|
| SG_PUTTING_CRITICAL | putting SG < -1.5 | critical/T1 |
| SG_APPROACH_STRONG | approach SG > 1.0 | positive/T1 |
| HIGH_FIR_LOW_GIR | FIR ≥ 55% 且 GIR < 35% | critical/T2 |
| THREE_PUTTS | 3 推 ≥ 2 次 | critical/T2 |

**输出控制**：最多 6 条洞察，正面最多 2 条，其余为 critical/warning/info。

### 2.4 GPS 距离计算

Haversine 公式（Rust 实现）：
```rust
distance = R × 2 × atan2(√a, √(1-a))
// R = 6,371,000 米
// a = sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlon/2)
```

Garmin 坐标转换：semicircles → degrees，系数 = 180 / 2³¹

### 2.5 球杆分析

- 偏差倾向（mis-shot tendency）：方向偏差统计
- 距离一致性评级：★★★ 到 ☆☆☆
- 平均 SG per club
- 球杆分类：tee / fairway_wood / iron / wedge / putt

## 三、iPhone 17 Pro Max 可用性评估

### 3.1 可直接复用的代码/理论

| 算法/模块 | 可用性 | 来源 | 移植难度 |
|----------|--------|------|---------|
| Strokes Gained 基线表 | ✅ 直接复用 | `app.js` SG_BASELINE_* | 极低 — 常量表 |
| SG 计算公式 | ✅ 直接复用 | `app.js` computeStrokesGained | 低 — 纯逻辑 |
| 插值算法 | ✅ 直接复用 | `app.js` interpolateBaseline | 极低 — 10 行代码 |
| NLG 规则模板 | ✅ 可参考 | `nlg-templates.js` | 中 — 需翻译为中文模板 |
| NLG 引擎架构 | ✅ 可参考 | `nlg-engine.js` | 低 — 模式清晰 |
| Haversine 距离 | ✅ 直接复用 | `models.rs` GpsPoint | 极低 — 标准算法 |
| 球杆分类体系 | ✅ 直接复用 | `models.rs` ClubType | 低 — 枚举映射 |
| 击球散布分析 | ✅ 可参考 | `app.js` 散布图逻辑 | 中 — 需适配数据源 |
| 方向偏差计算 | ✅ 可参考 | `app.js` deviation/bearing | 低 — 三角函数 |

### 3.2 iOS 端（GoBirdie）可直接参考的架构

GoBirdie iOS 端本身就是 Swift 原生 App（iOS 18+），以下模块可直接参考：

| 模块 | 路径 | 参考价值 |
|------|------|---------|
| 数据模型 | `GoBirdieCore/Sources/Models/` | Round, Shot, Club, GpsPoint 模型设计 |
| 存储层 | `GoBirdieCore/Sources/Storage/` | RoundStore, CourseStore JSON 持久化 |
| 距离引擎 | `GoBirdieCore/Sources/Distance/` | DistanceEngine GPS 距离计算 |
| 课程数据 | `GoBirdieCore/Sources/OSM/` | Overpass API 课程获取 + 缓存 |
| 地图视图 | `GoBirdie/Views/Map/` | MapLibre 集成、击球线绘制 |
| 击球追踪 | `GoBirdie/RoundSession.swift` | 活跃回合状态机 |
| Watch 同步 | `GoBirdie/ConnectivityService.swift` | WatchConnectivity 桥接 |
| P2P 同步 | `GoBirdie/SyncServer.swift` | MultipeerConnectivity 实现 |

### 3.3 需要适配的部分

| 原始实现 | iPhone 适配方案 |
|---------|---------------|
| FIT 文件解析 (Rust fitparser) | 不需要 — 我们用自己的数据采集 |
| sled 数据库 | SwiftData 或 JSON 文件 |
| Leaflet 地图 | MapKit 或 MapLibre (已有 iOS 参考) |
| Tailwind CSS UI | SwiftUI 原生 |
| Garmin MTP 同步 | 不需要 — 直接 iPhone 采集 |

### 3.4 不适用的部分

- Garmin FIT 文件解析（我们不用 Garmin 设备）
- MTP USB 通信（桌面特有）
- Tauri 框架相关代码

## 四、与本仓库对接建议

### 4.1 → HumanClubAnalysisApp

**Strokes Gained 模块**（优先级最高）：
- 将 SG 基线表和计算逻辑移植为 Swift 模块
- 结合挥杆视频分析结果，为每次击球计算 SG
- 实现 NLG 洞察引擎的中文版本

```swift
// Swift 移植示例
struct StrokesGainedEngine {
    static let baselineTee: [(Double, Double)] = [
        (100, 2.72), (150, 2.85), (200, 3.06), (250, 3.28),
        (300, 3.50), (400, 3.90), (500, 4.33), (600, 4.80)
    ]
    // ... fairway, rough, green 基线表

    static func expectedStrokes(distance: Double, lie: Lie) -> Double {
        interpolate(table: baseline(for: lie), distance: distance)
    }

    static func strokesGained(distBefore: Double, lieBefore: Lie,
                               distAfter: Double, lieAfter: Lie) -> Double {
        expectedStrokes(distance: distBefore, lie: lieBefore)
            - 1.0
            - expectedStrokes(distance: distAfter, lie: lieAfter)
    }
}
```

**击球散布分析**：
- 结合 GPS 数据和视频分析，生成方向×距离散布图
- 球杆偏差倾向分析

### 4.2 → DatasetCollectionPlatform

**GPS 元数据扩展**：
- 参考 GoBirdie 的 Shot 数据模型，在采集样本中增加 GPS 坐标
- 参考 Overpass API 集成，自动获取球场信息
- 参考 MultipeerConnectivity 实现设备间数据同步

### 4.3 → GolfBallDetectionApp

**距离验证**：
- 用 GPS 计算的实际距离验证视觉检测的球飞行距离
- Haversine 公式作为 ground truth

## 五、关键代码文件索引

| 文件 | 内容 | 移植价值 |
|------|------|---------|
| `web/js/app.js` (SG_BASELINE_*) | Strokes Gained 基线数据表 | ⭐⭐⭐⭐⭐ |
| `web/js/app.js` (computeStrokesGained) | SG 完整计算逻辑 | ⭐⭐⭐⭐⭐ |
| `web/js/nlg-templates.js` | 35 条双语洞察模板 | ⭐⭐⭐⭐ |
| `web/js/nlg-engine.js` | NLG 引擎（评估+排序+输出） | ⭐⭐⭐⭐ |
| `src-tauri/src/models.rs` | 数据模型 + GPS + 球杆分类 | ⭐⭐⭐⭐ |
| `src-tauri/src/parser.rs` | FIT 文件解析 | ⭐⭐（仅参考） |
| GoBirdie iOS `GoBirdieCore/` | Swift 原生数据模型和存储 | ⭐⭐⭐⭐⭐ |
| GoBirdie iOS `RoundSession.swift` | 回合状态机 | ⭐⭐⭐⭐ |
| GoBirdie iOS `SyncServer.swift` | MultipeerConnectivity | ⭐⭐⭐ |

## 六、深度可行性分析

### 6.1 Strokes Gained 计算 — 代码逻辑中文逐行解读

#### 核心计算流程（`app.js` → `computeStrokesGained()`）

```
输入：一个完整的 round 对象（包含 scorecard、hole_scores、shots）
  ↓
第一步：遍历每个洞的每一杆
  对 scorecard.hole_scores 中的每个洞：
    取出该洞所有击球 shots[]
    确定果岭位置 = 最后一杆的目的地坐标（shots[最后].to）
  ↓
第二步：计算每一杆的距离
  击球前距离 distBefore = 击球起点到果岭的距离（米→码）
  击球后距离 distAfter = 击球落点到果岭的距离（最后一杆 = 0）
  距离转换：metersToYards()，果岭上用英尺（码 × 3）
  ↓
第三步：判定球位（lie）
  击球前球位 lieBefore：
    第 1 杆 → "tee"（发球台）
    推杆 → "green"（果岭）
    距离 < 50 码 → "fairway"（短杆区域统一按球道处理）
    第 2 杆且 fairway_hit=true → "fairway"
    其他 → "rough"（长草）
  击球后球位 lieAfter：
    最后一杆 → "holed"（进洞）
    下一杆是推杆 → "green"
    其他 → "fairway"（简化处理）
  ↓
第四步：查表获取期望杆数
  expBefore = expectedStrokes(distBefore, lieBefore)
  expAfter = expectedStrokes(distAfter, lieAfter)
  查表使用线性插值（interpolateBaseline）
  ↓
第五步：计算 Strokes Gained
  SG = expBefore - 1 - expAfter
  含义：这一杆相对于基线水平"赚了"或"亏了"多少杆
    SG > 0 → 这一杆表现优于基线（赚杆）
    SG < 0 → 这一杆表现劣于基线（丢杆）
    SG ≈ 0 → 这一杆表现与基线持平
  ↓
第六步：分类汇总
  每一杆归入四个类别之一：
    off_tee：第 1 杆且 par ≥ 4（开球）
    putting：推杆
    short_game：非推杆且距离 < 50 码（短杆）
    approach：其他（进攻果岭）
  按类别累加 SG 值，得到四维分析结果
```

#### 线性插值算法中文解读（`interpolateBaseline()`）

```
输入：基线表 table[]（距离-期望杆数对）、目标距离 dist
  ↓
边界处理：
  距离 ≤ 表中最小值 → 返回最小值对应的期望杆数
  距离 ≥ 表中最大值 → 返回最大值对应的期望杆数（截断，不外推）
  ↓
插值计算：
  找到 dist 落在哪两个相邻数据点之间 [d1, s1] 和 [d2, s2]
  比例 t = (dist - d1) / (d2 - d1)
  结果 = s1 + t × (s2 - s1)
```

### 6.2 SG 基线数据表可靠性分析

#### 数据来源

基线表声称基于 Mark Broadie《Every Shot Counts》方法论，使用"单差点业余"（single-digit handicap）水平。

#### 基线表完整中文翻译

**发球台基线（SG_BASELINE_TEE）**：

| 距离（码） | 期望杆数 | 含义 |
|-----------|---------|------|
| 100 | 2.72 | 100 码 par 3，单差点球员平均 2.72 杆完成 |
| 150 | 2.85 | 150 码 par 3，平均 2.85 杆 |
| 200 | 3.06 | 200 码，刚超过 3 杆（开始需要 bogey 预算） |
| 250 | 3.28 | 250 码 par 4，平均 3.28 杆 |
| 300 | 3.50 | 300 码 par 4，平均 3.50 杆 |
| 400 | 3.90 | 400 码 par 4，接近 4 杆（标准 par） |
| 500 | 4.33 | 500 码 par 5，平均 4.33 杆 |
| 600 | 4.80 | 600 码 par 5，接近 5 杆 |

**球道基线（SG_BASELINE_FAIRWAY）**：

| 距离（码） | 期望杆数 | 与发球台差异 |
|-----------|---------|------------|
| 50 | 2.61 | — |
| 100 | 2.85 | 与发球台 100 码相同（2.72 vs 2.85 = +0.13） |
| 150 | 3.15 | 比发球台 150 码多 0.30 杆 |
| 200 | 3.46 | 比发球台 200 码多 0.40 杆 |
| 250 | 3.78 | 比发球台 250 码多 0.50 杆 |

**长草基线（SG_BASELINE_ROUGH）**：

| 距离（码） | 期望杆数 | 比球道罚杆 |
|-----------|---------|----------|
| 50 | 2.78 | +0.17 |
| 100 | 3.04 | +0.19 |
| 150 | 3.36 | +0.21 |
| 200 | 3.69 | +0.23 |
| 250 | 4.03 | +0.25 |

**果岭基线（SG_BASELINE_GREEN）**：

| 距离（英尺） | 期望推杆数 | 含义 |
|------------|----------|------|
| 1 | 1.00 | 1 英尺 = 必进（tap-in） |
| 3 | 1.07 | 3 英尺 ≈ 93% 一推进 |
| 5 | 1.24 | 5 英尺 ≈ 76% 一推进 |
| 10 | 1.58 | 10 英尺 ≈ 42% 一推进 |
| 20 | 1.84 | 20 英尺 ≈ 16% 一推进 |
| 30 | 2.03 | 30 英尺 ≈ 开始需要 3 推预算 |
| 60 | 2.36 | 60 英尺 ≈ 长推，2-3 推 |
| 90 | 2.55 | 90 英尺 ≈ 超长推 |

#### 可靠性风险

| 风险 | 描述 | 影响 | 缓解方案 |
|------|------|------|---------|
| 基线水平假设 | 表中数据基于"单差点业余"（约 5-9 差点），不适用于高差点或职业球员 | 对 20+ 差点球员，SG 值会系统性偏负（因为基线太高） | 提供多档基线（初学者/中级/高级），或允许用户自定义基线 |
| 数据来源不透明 | 代码注释仅说"single-digit"，未引用具体数据集或论文页码 | 无法验证数据准确性 | 交叉验证：与 PGA Tour ShotLink 公开数据、Arccos 统计对比 |
| 球道 vs 发球台差异 | 发球台 100 码 = 2.72 杆，球道 100 码 = 2.85 杆，差 0.13 杆 | 发球台有 tee 的优势（球架高、可选球位），差异合理 | 无需修改，差异符合实际 |
| 长草罚杆固定 | 长草比球道固定多 0.15-0.25 杆，不区分轻度/重度长草 | 深长草（buried lie）的实际罚杆远大于 0.25 | 可增加"深长草"基线表，罚杆 0.5-1.0 |
| 果岭单位转换 | 代码中 `distYards * 3` 将码转英尺，但实际果岭距离通常直接用英尺/米测量 | 如果输入已经是英尺，会被错误地乘以 3 | 需确保输入单位一致，建议在接口层明确标注单位 |
| 表外距离截断 | 超出表范围的距离返回边界值（不外推） | 发球台 > 600 码返回 4.80，但实际 700 码应 > 5.0 | 对极端距离增加外推逻辑，或标记为"超出基线范围" |

### 6.3 NLG 规则引擎 — 全部模板中文翻译

#### 引擎架构中文解读

```
输入：分析上下文对象 ctx（包含 SG 分类值、统计数据、心率等）
  ↓
第一步：遍历 ~35 条模板
  每条模板有：
    code — 唯一标识符
    condition(ctx) — 触发条件函数
    severity — 严重度（critical/warning/positive/info）
    tier — 层级（1=最重要 → 4=次要）
    messages — 多语言消息变体数组（英/韩）
  ↓
第二步：评估条件
  对每条模板调用 condition(ctx)
  如果返回 true → 从 messages 中随机选一条变体
  如果抛异常（数据缺失）→ 静默跳过
  ↓
第三步：排序
  先按 tier 升序（1 优先于 4）
  同 tier 内按 severity 排序：critical > warning > positive > info
  ↓
第四步：输出控制
  最多输出 6 条洞察
  正面消息（positive）最多 2 条
  其余为 critical/warning/info
```

#### 全部 35 条规则中文翻译

**Tier 1 — 关键 SG 弱项（critical）**

| 代码 | 触发条件 | 中文含义 |
|------|---------|---------|
| SG_PUTTING_CRITICAL | 推杆 SG < -1.5 | 推杆严重丢杆：今天在果岭上丢了 X 杆，是最需要改善的领域 |
| SG_APPROACH_CRITICAL | 进攻 SG < -1.5 | 进攻果岭严重丢杆：铁杆打不上果岭，距离控制是差距所在 |
| SG_OFF_TEE_CRITICAL | 开球 SG < -1.5 | 开球严重丢杆：偏离球道的开球让你整轮都在救球 |
| SG_SHORT_GAME_CRITICAL | 短杆 SG < -1.0 | 短杆严重丢杆：50 码以内的击球决定成败，需要加强练习 |

**Tier 1 — 关键 SG 强项（positive）**

| 代码 | 触发条件 | 中文含义 |
|------|---------|---------|
| SG_PUTTING_STRONG | 推杆 SG > +1.0 | 推杆出色：今天在果岭上赚了 X 杆，精英级表现 |
| SG_APPROACH_STRONG | 进攻 SG > +1.0 | 铁杆出色：进攻果岭赚了 X 杆，持续打到旗杆附近 |
| SG_TOTAL_POSITIVE | 总 SG > +2.0 | 全面出色：总共赚了 X 杆，全方位强势表现 |

**Tier 2 — 关联分析**

| 代码 | 触发条件 | 中文含义 |
|------|---------|---------|
| HIGH_FIR_LOW_GIR | FIR ≥ 55% 且 GIR < 35% | 开球好但铁杆差：上了球道却打不上果岭，进攻距离控制是短板 |
| LOW_FIR_HIGH_GIR | FIR < 35% 且 GIR ≥ 50% | 开球差但铁杆好：铁杆在弥补开球的不足，如果两者都好会更强 |
| THREE_PUTTS | 3 推 ≥ 2 次 | 三推过多：每次三推都是直接浪费一杆，长推距离控制需加强 |
| GOOD_SCRAMBLING | 救球率 ≥ 50% 且 GIR < 45% | 救球出色：虽然上果岭率低，但短杆救了很多杆 |
| POOR_SCRAMBLING | 救球率 < 25% 且 GIR < 45% | 救球糟糕：错过果岭后无法救回，短杆需大量练习 |
| HIGH_STRESS_POOR_SG | 平均压力 > 55 且总 SG < -1.0 | 高压低表现：高压力与差表现往往相伴，需要赛前准备和球场管理 |
| HIGH_HR_LATE_ROUND | 后 9 洞心率 > 前 9 洞 + 8 bpm | 后半程心率升高：疲劳或压力可能影响了后半程表现 |
| BODY_BATTERY_LOW | 结束时体力 < 20% | 体力耗尽：结束时已经精疲力竭，下次比赛前需要充分恢复 |
| BODY_BATTERY_DRAIN_HIGH | 体力消耗 > 40% | 体力消耗大：高强度的一轮，需要优先恢复 |
| FRONT_BACK_SPLIT_WORSE | 后 9 洞 > 前 9 洞 + 4 杆 | 后半程崩盘：后 9 洞比前 9 洞多 X 杆，疲劳或注意力下降 |
| FRONT_BACK_SPLIT_BETTER | 前 9 洞 > 后 9 洞 + 3 杆 | 后半程逆袭：后 9 洞比前 9 洞好 X 杆，热身后找到节奏 |
| PAR3_STRUGGLES | Par 3 平均超标 > 0.8 | Par 3 挣扎：短洞的铁杆精度需要提高 |
| PAR5_SCORING | Par 5 平均超标 > 0.5 | Par 5 未利用：得分洞没有抓到鸟，球场管理和短杆需改善 |
| PAR5_BIRDIE_MACHINE | Par 5 平均低于标准 0.3+ | Par 5 得分机器：长洞是你的强项，距离和球场管理出色 |
| CONSECUTIVE_BOGEYS | 连续 bogey ≥ 3 | 连续 bogey：动量杀手，一个坏球滚雪球，需要损害控制和重置 |

**Tier 3 — 球杆分析**

| 代码 | 触发条件 | 中文含义 |
|------|---------|---------|
| WORST_CLUB_SG | 最差球杆平均 SG < -0.3 | 最弱球杆：X 杆是今天最弱的球杆，需要针对性练习 |
| BEST_CLUB_SG | 最佳球杆平均 SG > +0.2 | 最强球杆：X 杆是今天最强的球杆，压力下可以依赖 |
| DRIVER_INCONSISTENT | 开球杆距离标准差 > 30 码 | 开球杆不稳定：距离波动大，牺牲一点距离换取一致性 |
| DRIVER_RIGHT_BIAS | 开球杆平均偏差 > +12° | 开球杆右偏：推球或推切模式，检查瞄准和杆面角度 |
| DRIVER_LEFT_BIAS | 开球杆平均偏差 < -12° | 开球杆左偏：拉球或勾球模式，检查握杆压力和挥杆路径 |
| IRONS_RIGHT_BIAS | 铁杆偏差 > +15° | 铁杆右偏：系统性推球/切球，需要在练习场解决 |
| IRONS_LEFT_BIAS | 铁杆偏差 < -15° | 铁杆左偏：系统性拉球/勾球，检查起杆和是否 over-the-top |
| WEDGE_INCONSISTENT | 挖起杆距离标准差 > 15 码 | 挖起杆不稳定：距离不一致，精确掌握挖起杆距离是最高回报的练习 |
| WEDGE_STRONG | 挖起杆平均 SG > +0.15 | 挖起杆出色：100 码以内距离控制好，创造鸟推机会 |

**Tier 3 — 散布模式**

| 代码 | 触发条件 | 中文含义 |
|------|---------|---------|
| APPROACH_SHORT_PATTERN | 进攻短了 > 55% | 进攻偏短：大多数业余球员都少拿一号杆，加一号杆 |
| APPROACH_LONG_PATTERN | 进攻长了 > 45% | 进攻偏长：肾上腺素或风可能增加了距离，检查码数 |
| DISPERSION_TIGHT | 整体散布角 < 12° 且进攻 ≥ 4 杆 | 散布紧凑：可重复的挥杆，一致性好 |

**Tier 4 — 次要观察**

| 代码 | 触发条件 | 中文含义 |
|------|---------|---------|
| ONE_PUTTS_HIGH | 一推进 ≥ 4 次 | 一推进多：近距离推杆稳定，真正的得分资产 |
| PUTTING_DISTANCE_CONTROL | 0 次三推且总推杆数合理 | 推杆距离控制好：零三推，长推距离控制出色 |
| DISTANCE_WALKED | 步行 > 8 km | 步行距离远：高尔夫比想象中更消耗体力 |
| ALTITUDE_RANGE | 高度变化 > 30m | 海拔变化大：高度影响球飞行，上坡打更远下坡打更近 |
| SWING_TEMPO_FAST | 平均节奏 < 2.5:1 | 挥杆节奏快：稍微延长顶点停顿可能改善一致性 |
| SWING_TEMPO_GOOD | 节奏 2.8-3.5:1 | 挥杆节奏理想：好节奏是稳定击球的基础 |
| ROUND_DURATION_LONG | 时长 > 270 分钟 | 比赛时间长：4+ 小时的精神疲劳影响后半程决策 |
| SG_BALANCED | 所有 SG 类别绝对值 < 0.5 | SG 均衡：没有特别差或特别好的领域，全面稳定 |

### 6.4 球位判定逻辑风险分析

#### 当前判定规则

```javascript
if (idx === 0) lieBefore = 'tee';           // 第 1 杆 → 发球台
else if (isPutt) lieBefore = 'green';        // 推杆 → 果岭
else if (distBefore < 50) lieBefore = 'fairway'; // < 50 码 → 球道
else lieBefore = (idx === 1 && hs.fairway_hit) ? 'fairway' : 'rough';
```

#### 风险清单

| 风险 | 描述 | 影响 | 严重度 |
|------|------|------|--------|
| 短杆区域一律按球道 | 距离 < 50 码统一用 fairway 基线，不区分果岭边沙坑、长草 | 沙坑救球的 SG 被低估（实际难度更高） | 中 |
| 第 3 杆以后默认长草 | 除第 2 杆外，非推杆非短杆一律按 rough 处理 | 如果第 3 杆实际在球道上（如 par 5 第 3 杆），SG 会偏高 | 中 |
| lieAfter 简化过度 | 下一杆球位判定：非推杆一律按 fairway | 如果下一杆实际在长草，expAfter 被低估，当前杆 SG 被高估 | 中 |
| 无沙坑/水障碍球位 | 只有 tee/fairway/rough/green 四种球位 | 沙坑球（实际罚杆 0.5-1.0）被归入 rough（罚杆仅 0.15-0.25） | 高 |
| fairway_hit 依赖外部数据 | 第 2 杆球位取决于 fairway_hit 标志 | 如果数据源不提供此标志，所有第 2 杆默认 rough | 中 |
| Par 3 第 1 杆分类 | Par 3 的第 1 杆归入 approach（因为 par < 4），不归入 off_tee | 分类正确（par 3 开球本质是进攻果岭），但用户可能困惑 | 低 |

### 6.5 移植风险清单

#### 高风险

| 风险 | 描述 | 影响 | 缓解方案 |
|------|------|------|---------|
| 数据依赖：逐杆 GPS 坐标 | SG 计算需要每一杆的起点和终点 GPS 坐标 | 我们的 AppleOSDatasetCollectorApp 目前只录制视频，不采集逐杆 GPS | 需要扩展采集端：每次击球时记录 GPS 坐标，或从视频中推算距离 |
| 数据依赖：fairway_hit 标志 | 球位判定依赖 fairway_hit 布尔值 | 视频分析无法直接判断球是否在球道上 | 可用 GPS + 球场地图（Overpass API）自动判定球位 |
| 数据依赖：球杆类型 | 每一杆需要知道使用了什么球杆 | 视频分析可能无法准确识别球杆型号 | 用户手动输入，或通过挥杆特征（速度、角度）推断球杆类型 |
| NLG 中文本地化 | 原始模板只有英文和韩文，需要完整中文翻译 | 35 条规则 × 每条 2-4 个变体 = 约 100 条中文消息 | 工作量中等，但需要高尔夫领域专业术语准确翻译 |

#### 中风险

| 风险 | 描述 | 影响 | 缓解方案 |
|------|------|------|---------|
| 基线表适用性 | 单差点基线不适用于所有水平的球员 | 高差点球员的 SG 全面偏负，失去参考价值 | 提供多档基线，或根据用户历史数据动态调整 |
| NLG 阈值硬编码 | 所有触发条件的阈值（如 SG < -1.5）是固定的 | 不同水平球员的"严重"标准不同 | 阈值参数化，根据用户差点动态调整 |
| 心率/体力数据依赖 | 多条 NLG 规则依赖 Garmin 心率、Body Battery、压力数据 | iPhone 没有 Body Battery，Apple Watch 心率数据格式不同 | 移除 Garmin 特有规则，或用 HealthKit 数据替代 |
| 果岭距离单位混淆 | 代码中 `distYards * 3` 将码转英尺 | 如果 GPS 距离已经是米，需要先转码再转英尺 | 在数据入口统一单位，明确标注 |

#### 低风险

| 风险 | 描述 | 缓解方案 |
|------|------|---------|
| Haversine 精度 | 地球非完美球体，Haversine 有 ~0.3% 误差 | 高尔夫距离精度要求不高（±1 码可接受），无需修改 |
| NLG 随机变体 | 每次生成随机选择消息变体 | 可能导致同一问题每次描述不同，但增加自然感，无需修改 |
| 排序稳定性 | 同 tier 同 severity 的规则排序不确定 | 影响极小，可增加 code 字母序作为第三排序键 |

### 6.6 边界条件分析

| 场景 | 原始代码行为 | 是否需要处理 |
|------|------------|------------|
| 空 scorecard | `if (!sc?.hole_scores?.length) return null` | ✅ 已处理 |
| 某洞无击球数据 | `if (!shots.length) return` 跳过该洞 | ✅ 已处理 |
| 距离超出基线表范围 | 返回边界值（截断，不外推） | ⚠️ 极端距离可能不准确 |
| NLG 条件评估异常 | `try/catch` 静默跳过 | ✅ 已处理，但可能隐藏数据问题 |
| 正面洞察超过 2 条 | 截断为最多 2 条 positive | ✅ 已处理 |
| 总洞察超过 6 条 | 截断为最多 6 条 | ✅ 已处理 |
| 所有 SG 类别为 0 | 触发 SG_BALANCED 规则 | ✅ 合理 |
| 只打了 9 洞 | 前/后 9 洞对比规则可能不触发 | ⚠️ 需检查 frontNineScore/backNineScore 是否为 null |
| 无心率数据 | 心率相关规则条件中访问 null 会抛异常 → 被 catch 跳过 | ✅ 已处理（静默跳过） |
| 无球杆数据 | worstClub/bestClub 为 null → 条件检查 `d.worstClub != null` | ✅ 已处理 |
| 推杆距离为 0 | `distYards * 3 = 0` → 查表返回 1.00（1 英尺基线） | ⚠️ 0 英尺应该是进洞，不应查表 |
