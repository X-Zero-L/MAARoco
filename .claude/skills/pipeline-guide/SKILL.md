---
name: pipeline-guide
description: MaaFramework Pipeline JSON 编写指南。基于官方 Pipeline 协议文档，覆盖节点设计、识别算法、动作类型、流程控制、默认属性和调试方法。在编写、修改或审查 Pipeline JSON 时使用。
---

# MaaFramework Pipeline 编写指南

> 基于 MaaFramework v5.10+ Pipeline 协议官方文档

## 核心原则

1. **状态驱动**：遵循「识别 → 操作 → 识别」循环。每次操作必须基于识别结果，禁止假设操作后画面状态。
2. **高命中率**：`next` 列表必须覆盖操作后所有可能画面（含弹窗、加载、异常），力争一次截图命中。
3. **善用 `default_pipeline.json`**：通过默认属性文件统一设置全局参数，避免逐节点重复配置。
4. **少用硬延迟**：官方推荐用中间识别节点或 `pre_wait_freezes`/`post_wait_freezes` 替代 `pre_delay`/`post_delay`。
5. **720p 基准**：所有坐标、ROI、图片基于 **1280×720**。
6. **单一职责**：每个节点只做一件事。

## 基础格式

Pipeline 由若干节点（Node）构成，每个节点核心属性：

```jsonc
{
    "NodeA": {
        "recognition": "OCR",     // 识别算法，默认 DirectHit
        "action": "Click",        // 执行动作，默认 DoNothing
        "next": ["NodeB", "NodeC"] // 后续节点，按序识别首个命中
    }
}
```

## Pipeline v2 格式（推荐）

v2 将 recognition/action 相关字段放入二级字典，MaaFW v4.4.0+ 支持，兼容 v1：

```jsonc
{
    "NodeA": {
        "recognition": {
            "type": "TemplateMatch",
            "param": {
                "template": "A.png",
                "roi": [100, 100, 10, 10]
            }
        },
        "action": {
            "type": "Click",
            "param": {
                "target": true
            }
        },
        "next": ["NodeB"]
    }
}
```

## 默认属性（`default_pipeline.json`）

v5.3 起支持。放置在资源包根目录下（与 `pipeline` 文件夹同级），为所有节点设置默认参数：

```jsonc
{
    "Default": {
        // 通用字段默认值，适用于所有节点
        // 框架内置默认为 rate_limit: 1000, pre_delay: 200, post_delay: 200
        "rate_limit": 2000,
        "timeout": 20000,
        "pre_delay": 200
    },
    "TemplateMatch": {
        // TemplateMatch 算法的默认参数
        "recognition": "TemplateMatch",
        "threshold": 0.7
    },
    "Click": {
        // Click 动作的默认参数
        "action": "Click",
        "target": true
    }
}
```

**优先级**（高到低）：节点直接定义 > 算法/动作类型默认 > Default 默认 > 框架内置默认

**最佳实践**：若希望消除隐式延迟，可在 `default_pipeline.json` 的 `Default` 中将 `rate_limit`、`pre_delay`、`post_delay` 覆盖为 `0`，需要延迟的节点再单独设置非零值。注意这是**覆盖**框架默认值，不是框架本身的默认值。

## 执行逻辑

1. 通过 `tasker.post_task` 指定入口节点启动
2. 顺序检测 `next` 列表，依次尝试识别每个子节点
3. 首个命中的节点执行 action，然后进入该节点的 `next` 列表
4. 若动作失败，进入该节点的 `on_error` 列表
5. 若全部超时，进入当前节点的 `on_error` 列表

**终止条件**：next 为空 / next 超时 / 执行了 `StopTask`

## 节点通用字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `recognition` | string \| object | `"DirectHit"` | 识别算法 |
| `action` | string \| object | `"DoNothing"` | 执行动作 |
| `next` | string \| NodeAttr \| list | `[]` | 后续节点，按序识别首个命中 |
| `on_error` | string \| NodeAttr \| list | `[]` | 超时/动作失败后的节点 |
| `timeout` | int | `20000` | next 识别超时（ms），-1 永不超时 |
| `rate_limit` | uint | `1000` | 每轮识别最低耗时（ms） |
| `pre_delay` | uint | `200` | 动作前延迟（ms） |
| `post_delay` | uint | `200` | 动作后延迟（ms） |
| `pre_wait_freezes` | uint \| object | `0` | 动作前等待画面静止（ms） |
| `post_wait_freezes` | uint \| object | `0` | 动作后等待画面静止（ms） |
| `repeat` | uint | `1` | 动作重复次数 |
| `repeat_delay` | uint | `0` | 重复间延迟（ms） |
| `repeat_wait_freezes` | uint \| object | `0` | 重复间等待画面静止 |
| `inverse` | bool | `false` | 反转识别结果 |
| `enabled` | bool | `true` | 是否启用 |
| `max_hit` | uint | UINT_MAX | 最大命中次数，超过后跳过 |
| `anchor` | string \| list \| object | `""` | 锚点 |
| `focus` | object | `null` | 节点通知 |
| `attach` | object | `{}` | 附加配置（dict merge） |

**节点生命周期**：

```
pre_wait_freezes → pre_delay → action
  → [repeat_wait_freezes → repeat_delay → action] × (repeat-1)
  → post_wait_freezes → post_delay
  → 截图 → 识别 next
```

## 区分 roi / box / target

- **roi**：感兴趣区域，定义识别边界，仅在该区域内搜索
- **box**：识别命中后返回的匹配区域
- **target**：动作执行目标，默认 `true` 即使用 box

---

## 识别算法

### DirectHit

直接命中，不进行识别。不写 `recognition` 字段即为 DirectHit。

### TemplateMatch — 模板匹配（找图）

```jsonc
"recognition": {
    "type": "TemplateMatch",
    "param": {
        "template": "path/to/image.png",  // 相对 image/ 目录，必选
        "roi": [x, y, w, h],              // 识别区域，默认全屏
        "threshold": 0.7,                  // 匹配阈值，默认 0.7
        "method": 5,                       // TM_CCOEFF_NORMED（推荐），默认 5
        "green_mask": false,               // 绿色遮罩，默认 false
        "order_by": "Horizontal",          // 排序方式
        "index": 0                         // 取第几个结果
    }
}
```

**method 常用值**：5=TM_CCOEFF_NORMED（推荐，抗光照）、3=TM_CCORR_NORMED、10001=TM_SQDIFF_NORMED 反转版、1=TM_SQDIFF（少用）

**图片规范**：
- 从 720p 无损原图裁剪，template 支持文件夹路径（递归加载所有图片）
- `green_mask: true` 时，RGB(0,255,0) 区域不参与匹配，仅遮盖干扰区域

### FeatureMatch — 特征匹配

泛化能力更强的找图，抗透视、抗尺寸变化：

```jsonc
"recognition": {
    "type": "FeatureMatch",
    "param": {
        "template": "path/to/image.png",  // 必选，建议至少 64x64
        "roi": [x, y, w, h],
        "count": 4,                        // 最少匹配特征点数，默认 4
        "detector": "SIFT",                // 检测器，默认 SIFT（推荐）
        "ratio": 0.6                       // KNN 距离比值，默认 0.6
    }
}
```

**detector**：SIFT（最精确）> KAZE > AKAZE > BRISK > ORB（最快但无尺度不变性）

### ColorMatch — 颜色匹配（找色）

```jsonc
"recognition": {
    "type": "ColorMatch",
    "param": {
        "roi": [x, y, w, h],
        "method": 40,                      // 颜色空间，默认 4(RGB)
        "lower": [h_low, s_low, v_low],    // 颜色下限，必选
        "upper": [h_high, s_high, v_high], // 颜色上限，必选
        "count": 1,                        // 最少像素数，默认 1
        "connected": false                 // 是否要求连通，默认 false
    }
}
```

**method 常用值**：4=RGB（3 通道）、40=HSV（3 通道，推荐）、6=GRAY（1 通道）

### OCR — 文字识别

```jsonc
"recognition": {
    "type": "OCR",
    "param": {
        "roi": [x, y, w, h],
        "expected": ["完整文本"],   // 支持正则，默认匹配全部
        "threshold": 0.3,           // 模型置信度，默认 0.3
        "only_rec": false,          // 仅识别不检测，默认 false
        "model": "",                // 模型文件夹路径（相对 model/ocr），默认根目录
        "color_filter": "",         // ColorMatch 节点名，先二值化再识别
        "replace": [["壹", "1"]]   // OCR 结果替换
    }
}
```

### And — 组合识别（全部满足）

```jsonc
"recognition": {
    "type": "And",
    "param": {
        "all_of": [
            "NodeA",                 // 字符串：引用节点的识别参数（v5.7+）
            {                        // 对象：内联识别定义
                "recognition": "OCR",
                "expected": "OK"
            }
        ],
        "box_index": 0              // 使用第几个子识别的 box，默认 0
    }
}
```

支持 `sub_name` 字段，后续子识别可通过 `roi: sub_name` 引用前面的结果。

### Or — 组合识别（任一满足）

```jsonc
"recognition": {
    "type": "Or",
    "param": {
        "any_of": ["NodeA", "NodeB"]  // 命中第一个即成功
    }
}
```

### Custom — 自定义识别

```jsonc
"recognition": {
    "type": "Custom",
    "param": {
        "custom_recognition": "MyRecognizer",  // 必选
        "custom_recognition_param": {}         // 任意类型
    }
}
```

---

## 动作类型

### Click / LongPress

```jsonc
"action": { "type": "Click" }
// 或
"action": {
    "type": "Click",
    "param": {
        "target": true,             // true=识别结果 | 节点名 | [x,y] | [x,y,w,h]
        "target_offset": [0,0,0,0], // 偏移量
        "contact": 0                // 触点编号（Adb=手指, Win32=鼠标按键）
    }
}
```

LongPress 额外字段：`duration`（默认 1000ms）

### Swipe

```jsonc
"action": {
    "type": "Swipe",
    "param": {
        "begin": [640, 500, 1, 1],
        "end": [640, 200, 1, 1],     // 支持 list 做折线滑动
        "duration": 200,              // ms
        "end_hold": 0                 // 到终点后额外等待
    }
}
```

### StartApp / StopApp

```jsonc
"action": { "type": "StartApp", "param": { "package": "com.example.app" } }
"action": { "type": "StopApp", "param": { "package": "com.example.app" } }
```

### 其他动作

| 动作 | 用途 | 关键参数 |
|------|------|----------|
| `DoNothing` | 不执行（默认） | — |
| `Scroll` | 滚轮（Win32/macOS） | `target`, `dx`, `dy` |
| `ClickKey` | 按键 | `key`（虚拟键码） |
| `LongPressKey` | 长按键 | `key`, `duration` |
| `KeyDown` / `KeyUp` | 按下/松开键 | `key` |
| `InputText` | 输入文字 | `input_text` |
| `StopTask` | 终止当前任务链 | — |
| `Command` | 执行命令 | `exec`, `args`, `detach` |
| `Shell` | ADB shell 命令 | `cmd`, `shell_timeout`（默认 20000） |
| `Screencap` | 保存截图 | `filename`, `format`, `quality` |
| `MultiSwipe` | 多指滑动 | `swipes` 数组 |
| `Custom` | 自定义动作 | `custom_action`, `custom_action_param` |

---

## 流程控制

### [JumpBack] — 中断处理

命中后执行该节点链，完成后**自动返回父节点**重新从 next 起始位置识别。适合处理弹窗、加载等临时界面：

```jsonc
"next": [
    "BusinessNode",
    "[JumpBack]Handle_Popup",      // 弹窗处理后自动返回
    "[JumpBack]Handle_Loading"
]
```

等价对象形式：`{ "name": "Handle_Popup", "jump_back": true }`

### [Anchor] — 动态锚点

节点通过 `anchor` 字段设置锚点，`next` 中通过 `[Anchor]` 引用：

```jsonc
{
    "A": {
        "anchor": "X",              // 设置锚点 X = 当前节点
        "next": ["C"]
    },
    "C": {
        "next": ["[Anchor]X"]       // 运行时解析为最后设置 X 的节点
    }
}
```

支持对象形式指定目标或清除：`"anchor": {"X": "TargetNode", "Y": ""}`

### max_hit — 命中次数限制

```jsonc
"max_hit": 20    // 超过后该节点被跳过
```

### 等待画面静止

```jsonc
// 简写
"post_wait_freezes": 500

// 完整
"post_wait_freezes": {
    "time": 500,                   // 连续 500ms 无变化，默认 1
    "target": [0, 0, 1280, 720],  // 检测区域，默认 true
    "threshold": 0.95,             // 相似度阈值，默认 0.95
    "method": 5,                   // 匹配算法，默认 5
    "rate_limit": 1000,            // 检测速率，默认 1000
    "timeout": 20000               // 超时，默认 20000，-1 无限
}
```

---

## 常用模式

### 模式 1：弹窗防御

```jsonc
{
    "TaskEntry": {
        "next": [
            "TaskMainStep",
            "[JumpBack]Handle_Popup",
            "[JumpBack]Handle_Loading"
        ],
        "timeout": 15000
    }
}
```

### 模式 2：领取/签到类

```jsonc
{
    "Collect_Open": {
        "recognition": { "type": "TemplateMatch", "param": { "template": "panel.png" } },
        "action": { "type": "Click" },
        "post_wait_freezes": 500,
        "next": ["Collect_Claim", "Collect_Done"],
        "timeout": 10000
    },
    "Collect_Claim": {
        "recognition": { "type": "TemplateMatch", "param": { "template": "claim.png" } },
        "action": { "type": "Click" },
        "next": ["Collect_CloseReward"],
        "timeout": 5000
    },
    "Collect_CloseReward": {
        "recognition": { "type": "TemplateMatch", "param": { "template": "close.png" } },
        "action": { "type": "Click" },
        "post_wait_freezes": 300,
        "next": ["Collect_Claim", "Collect_Close"],
        "timeout": 5000
    }
}
```

### 模式 3：战斗循环

用 `max_hit` 控制循环次数，配合 `interface.json` 的 `pipeline_override` 让用户选择：

```jsonc
{
    "BattleLoop": {
        "max_hit": 20,
        "next": ["Battle_Start"],
        "on_error": ["BackToMain"]
    }
}
```

### 模式 4：确认后验证

避免重复点击（第二次可能作用于新界面其他元素）：

```jsonc
{
    "ClickConfirm": {
        "recognition": { "type": "TemplateMatch", "param": { "template": "confirm.png" } },
        "action": { "type": "Click" },
        "post_wait_freezes": { "time": 300, "target": [0, 0, 1280, 720] },
        "next": ["VerifyNextScreen", "[JumpBack]ClickConfirm"]
    }
}
```

---

## order_by 排序方式

| 值 | 说明 | 适用算法 |
|----|------|----------|
| `Horizontal` | 左→右，同列上→下（默认） | 全部 |
| `Vertical` | 上→下，同行左→右 | 全部 |
| `Score` | 分数降序 | TemplateMatch, FeatureMatch, ColorMatch, NNClassify, NNDetect |
| `Area` | 面积降序 | FeatureMatch, ColorMatch, OCR, NNDetect |
| `Length` | 文本长度降序 | OCR |
| `Random` | 随机 | 全部 |
| `Expected` | 按 expected 顺序 | OCR, NNClassify, NNDetect |

---

## 调试方法

```bash
# 截图
adb exec-out screencap -p > screenshot.png

# ROI 确定：在 720p 截图中找目标区域 [x, y, w, h]，上下左右留 10-20px 余量
```

用 MaaDebugger / MaaPiCli 逐节点测试识别命中和 threshold。

## 检查清单

- [ ] `next` 覆盖所有可能画面（含弹窗、加载、异常）
- [ ] 点击后有验证节点
- [ ] 坐标基于 1280×720
- [ ] OCR `expected` 写完整文本
- [ ] 使用 `default_pipeline.json` 管理通用默认值
- [ ] 场景切换用 `post_wait_freezes` 而非硬延迟
- [ ] 长流程有 `on_error` 回退
- [ ] 弹窗用 `[JumpBack]` 处理
- [ ] 图片从 720p 无损截图裁剪

## 参考

- 完整字段速查：[field-reference.md](field-reference.md)
- 官方 Pipeline 协议：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-任务流水线协议.md
- 快速开始：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.1-快速开始.md
