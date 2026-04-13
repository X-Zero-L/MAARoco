# Pipeline 字段速查表

基于 MaaFramework v5.10+ 官方 Pipeline 协议文档。

## 通用字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `recognition` | string \| object | `"DirectHit"` | 识别算法（v2 用 `{type, param}`） |
| `action` | string \| object | `"DoNothing"` | 动作类型（v2 用 `{type, param}`） |
| `next` | string \| NodeAttr \| list | `[]` | 后续节点，按序识别首个命中 |
| `on_error` | string \| NodeAttr \| list | `[]` | 超时/动作失败后执行 |
| `timeout` | int | `20000` | next 识别超时（ms），-1 无限 |
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
| `max_hit` | uint | UINT_MAX | 最大命中次数 |
| `anchor` | string \| list \| object | `""` | 锚点名 |
| `focus` | object | `null` | 节点通知回调 |
| `attach` | object | `{}` | 附加配置（dict merge） |

## 节点生命周期

```
pre_wait_freezes → pre_delay → action
  → [repeat_wait_freezes → repeat_delay → action] × (repeat-1)
  → post_wait_freezes → post_delay
  → 截图 → 识别 next
```

## roi / box / target 区分

- **roi** + roi_offset → 识别搜索范围
- **box** → 识别命中返回的匹配区域
- **target** + target_offset → 动作执行位置（默认 true，即用 box）

---

## 识别算法字段

### DirectHit

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `roi` | array\<int,4\> \| string | `[0,0,0,0]`（全屏） | 识别区域。string 填节点名或 `[Anchor]锚点名` |
| `roi_offset` | array\<int,4\> | `[0,0,0,0]` | roi 偏移量，四值相加 |

roi 支持负数（v5.6+）：x/y 负数从右/下计算；w/h 为 0 延伸至边缘。

### TemplateMatch

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `template` | string \| list\<string\> | **必填** | 相对 image/ 的路径，支持文件夹（递归加载） |
| `roi` / `roi_offset` | 同 DirectHit | | |
| `threshold` | double \| list\<double\> | `0.7` | 匹配阈值 |
| `method` | int | `5` | cv::TemplateMatchModes |
| `order_by` | string | `"Horizontal"` | 排序方式 |
| `index` | int | `0` | 取第几个结果（支持负数） |
| `green_mask` | bool | `false` | RGB(0,255,0) 区域不参与匹配 |

method：5=TM_CCOEFF_NORMED（推荐），3=TM_CCORR_NORMED，10001=TM_SQDIFF_NORMED 反转，1=TM_SQDIFF（少用）

### FeatureMatch

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `template` | string \| list\<string\> | **必填** | 建议至少 64x64，含足够纹理 |
| `roi` / `roi_offset` | 同 DirectHit | | |
| `count` | uint | `4` | 最少匹配特征点数 |
| `detector` | string | `"SIFT"` | 特征检测器 |
| `ratio` | double | `0.6` | KNN 距离比值 [0-1.0] |
| `order_by` | string | `"Horizontal"` | 排序。额外支持 `Area` |
| `index` | int | `0` | |
| `green_mask` | bool | `false` | |

detector：SIFT（最精确）> KAZE > AKAZE > BRISK > ORB（最快，无尺度不变性）

### ColorMatch

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `roi` / `roi_offset` | 同 DirectHit | | |
| `method` | int | `4`（RGB） | cv::ColorConversionCodes |
| `lower` | list\<int\> \| list\<list\<int\>\> | **必填** | 颜色下限 |
| `upper` | list\<int\> \| list\<list\<int\>\> | **必填** | 颜色上限 |
| `count` | uint | `1` | 最少匹配像素数 |
| `connected` | bool | `false` | 是否要求像素全部相连 |
| `order_by` | string | `"Horizontal"` | 额外支持 `Area` |
| `index` | int | `0` | |

method 常用值：4=RGB（3通道），40=HSV（3通道，推荐），6=GRAY（1通道）

### OCR

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `roi` / `roi_offset` | 同 DirectHit | | |
| `expected` | string \| list\<string\> | 匹配全部 | 期望文本，支持正则 |
| `threshold` | double | `0.3` | 模型置信度阈值 |
| `replace` | array\<string,2\> \| list | — | 结果文本替换 |
| `only_rec` | bool | `false` | 仅识别不检测（需精确 roi） |
| `model` | string | `""` | 模型文件夹（相对 model/ocr） |
| `color_filter` | string | `""` | ColorMatch 节点名，先二值化再 OCR |
| `order_by` | string | `"Horizontal"` | 额外支持 `Area`, `Length`, `Expected` |
| `index` | int | `0` | |

### NeuralNetworkClassify

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `roi` / `roi_offset` | 同 DirectHit | | |
| `model` | string | **必填** | 相对 model/classify 的 ONNX 模型路径 |
| `labels` | list\<string\> | `[]`（未填写时显示 "Unknown"） | 分类标注名（仅调试用） |
| `expected` | int \| list\<int\> | 匹配全部 | 期望的分类下标 |
| `order_by` | string | `"Horizontal"` | 额外支持 `Score`, `Expected` |
| `index` | int | `0` | |

### NeuralNetworkDetect

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `roi` / `roi_offset` | 同 DirectHit | | |
| `model` | string | **必填** | 相对 model/detect 的 ONNX 模型（YOLOv8/v11） |
| `labels` | list\<string\> | 自动读取 metadata | 分类标注名 |
| `expected` | int \| list\<int\> | 匹配全部 | 期望的分类下标 |
| `threshold` | double \| list\<double\> | `0.3` | 置信度阈值 |
| `order_by` | string | `"Horizontal"` | 额外支持 `Score`, `Area`, `Expected` |
| `index` | int | `0` | |

### And

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `all_of` | list\<string \| object\> | **必填** | 全部满足才命中。string=节点名引用 |
| `box_index` | int | `0` | 输出哪个子识别的 box |
| `sub_name` | string | — | 子识别别名，后续可通过 `roi: sub_name` 引用 |

### Or

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `any_of` | list\<string \| object\> | **必填** | 首个命中即成功 |

### Custom

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `custom_recognition` | string | **必填** | 已注册的识别器名 |
| `custom_recognition_param` | any | `null` | 传递给识别器的参数 |
| `roi` / `roi_offset` | 同 DirectHit | | |

---

## 动作字段

### Click

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `target` | true \| string \| array\<int,2\> \| array\<int,4\> | `true` | true=识别结果，string=节点名/锚点 |
| `target_offset` | array\<int,4\> | `[0,0,0,0]` | 偏移量 |
| `contact` | uint | `0` | 触点（Adb=手指号，Win32=鼠标按键） |
| `pressure` | int | `1` | 触点力度 |

### LongPress

同 Click，额外字段：

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `duration` | uint | `1000` |

### Swipe

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `begin` / `begin_offset` | 同 Click target | `true` / `[0,0,0,0]` | 起点 |
| `end` / `end_offset` | 同上，支持 list | `true` / `[0,0,0,0]` | 终点，list 做折线滑动 |
| `duration` | uint \| list\<uint\> | `200` | 滑动时长 |
| `end_hold` | uint \| list\<uint\> | `0` | 到终点后等待时间 |
| `only_hover` | bool | `false` | 仅悬停移动，无按下/抬起 |
| `contact` | uint | `0` | 触点编号 |
| `pressure` | int | `1` | 触点力度 |

### MultiSwipe

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `swipes` | list\<object\> | **必填** | 多个滑动配置 |

每个 swipe 对象含 Swipe 全部字段，额外：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `starting` | uint | `0` | 该滑动在 action 中的起始时间（ms） |
| `contact` | uint | 数组索引 | 默认用数组下标作为手指号 |

### Scroll（Win32/macOS/自定义控制器）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `target` / `target_offset` | 同 Click | `true` / `[0,0,0,0]` | 鼠标位置 |
| `dx` | int | `0` | 水平滚动（正=右） |
| `dy` | int | `0` | 垂直滚动（正=上） |

Windows 标准每格 120（WHEEL_DELTA），建议用 120 的倍数。

### TouchDown / TouchMove / TouchUp

底层触控操作，可实现自定义触控时序。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `contact` | uint | `0` | 触点编号 |
| `target` / `target_offset` | 同 Click | `true` / `[0,0,0,0]` | 触控位置（TouchUp 无此字段） |
| `pressure` | int | `0` | 触控压力 |

### ClickKey

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `key` | int \| list\<int\> | **必填** | 虚拟键码 |

### LongPressKey

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `key` | int \| list\<int\> | **必填** |
| `duration` | uint | `1000` |

### KeyDown / KeyUp

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `key` | int | **必填** |

### InputText

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `input_text` | string | **必填** |

### StartApp / StopApp

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `package` | string | **必填** | StartApp 支持 activity 格式 |

### StopTask

无参数。终止当前任务链。

### Command

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `exec` | string | **必填** | 程序路径 |
| `args` | list\<string\> | `[]` | 参数，支持 `{ENTRY}` `{NODE}` `{IMAGE}` `{BOX}` `{RESOURCE_DIR}` `{LIBRARY_DIR}` |
| `detach` | bool | `false` | 分离子进程，不等待完成 |

### Shell（仅 Adb）

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `cmd` | string | **必填** |
| `shell_timeout` | int | `20000` |

### Screencap

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `filename` | string | 时间戳_节点名 | 文件名（不含扩展名） |
| `format` | string | `"png"` | `"png"` \| `"jpg"` \| `"jpeg"` |
| `quality` | int | `100` | 仅 jpg 有效（0-100） |

### Custom Action

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `custom_action` | string | **必填** |
| `custom_action_param` | any | `null` |
| `target` / `target_offset` | 同 Click | `true` / `[0,0,0,0]` |

---

## order_by 排序方式

| 值 | 说明 | 适用算法 |
|----|------|----------|
| `Horizontal` | 左→右，同列上→下 | 全部 |
| `Vertical` | 上→下，同行左→右 | 全部 |
| `Score` | 分数降序 | TemplateMatch, FeatureMatch, ColorMatch, NNClassify, NNDetect |
| `Area` | 面积降序 | FeatureMatch, ColorMatch, OCR, NNDetect |
| `Length` | 文本长度降序 | OCR |
| `Random` | 随机 | 全部 |
| `Expected` | 按 expected 顺序 | OCR, NNClassify, NNDetect |

---

## wait_freezes object

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `time` | uint | `1` | 连续多久无变化（ms） |
| `target` / `target_offset` | 同 Click | `true` / `[0,0,0,0]` | 检测区域 |
| `threshold` | double | `0.95` | 相似度阈值 |
| `method` | int | `5` | 匹配算法 |
| `rate_limit` | uint | `1000` | 检测速率 |
| `timeout` | int | `20000` | 超时，-1 无限 |

---

## 节点属性

在 `next` / `on_error` 中使用，两种等价语法：

| 前缀形式 | 对象形式 | 说明 |
|----------|----------|------|
| `"[JumpBack]NodeName"` | `{ "name": "NodeName", "jump_back": true }` | 执行后返回父节点继续 next |
| `"[Anchor]AnchorName"` | `{ "name": "AnchorName", "anchor": true }` | 运行时解析为最后设置该锚点的节点 |

---

## default_pipeline.json

放在资源包根目录（与 pipeline/ 同级），为所有节点设置默认参数：

```jsonc
{
    "Default": { "rate_limit": 0, "pre_delay": 0, "post_delay": 0 },
    "TemplateMatch": { "recognition": "TemplateMatch", "threshold": 0.7 },
    "Click": { "action": "Click", "target": true }
}
```

优先级：节点定义 > 算法/动作类型默认 > Default > 框架内置

多 Bundle 加载时，default 按序 merge，已加载节点不受后续 default 影响。

---

## 版本变更摘要

| 版本 | 新增 |
|------|------|
| v5.0 | `attach`, TouchDown/Move/Up, contact, pressure, target `[x,y]` |
| v5.1 | anchor, max_hit, Scroll, [JumpBack]/[Anchor] 节点属性, `Expected` 排序 |
| v5.3 | repeat/repeat_delay/repeat_wait_freezes, And/Or, Shell, default_pipeline.json |
| v5.5 | timeout=-1, Scroll target/target_offset |
| v5.6 | roi/target 负数坐标 |
| v5.7 | anchor 对象形式, And/Or 节点名引用 |
| v5.8 | OCR color_filter, Shell shell_timeout, Screencap |
| v5.9 | roi/target `[Anchor]` 引用, on_error 路径不触发 JumpBack |
