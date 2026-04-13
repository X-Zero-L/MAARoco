<!-- markdownlint-disable MD033 MD041 -->
<div align="center">

# MAARoco

**洛克王国：世界** 手游自动化助手

基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 开发

</div>

> [!NOTE]
> 本项目目前仅用于**小号自动化刷花**（循环执行表情动作），无意增加复杂的每日任务自动化功能。
> 建议仅在小号上使用，主号请谨慎操作，使用后果自负。

## 功能

- **循环产花** — 自动点击表情（鞠躬/大笑），每 8.5 秒执行一次，支持待机自动唤醒

## 快速开始

### 1. 环境准备

- ADB 工具（如 [scrcpy](https://github.com/Genymobile/scrcpy) 自带）
- [uv](https://docs.astral.sh/uv/)（可选，用于运行开发工具）

### 2. 下载 MaaFramework 运行时

```bash
uv run tools/setup.py
```

自动下载对应平台的 MaaFramework 到 `deps/` 目录。

### 3. 运行

```bash
# Windows
./run.sh
# 或手动
cp assets/interface.json deps/bin/ && ./deps/bin/MaaPiCli.exe
```

首次运行选择 ADB 设备连接，之后选择「循环产花」任务执行。

**使用前请先在游戏内手动进入表情面板**，脚本会在该界面循环点击表情按钮。

## 开发工具

### 截图裁剪工具（Cropper）

用于截取模板图片和标注 ROI，一键导出到 pipeline：

```bash
uv run tools/cropper.py
```

- 支持 ADB 截图 / 打开本地图片
- 画 ROI（搜索区域）和 Template（模板图片）
- 一键导出：保存模板图片 + 写入 Pipeline JSON
- 支持多模板追加

## 项目结构

```
assets/
├── interface.json          # MaaFW 任务接口定义
└── resource/
    ├── image/              # 模板图片
    │   ├── common/         # 通用（待机画面等）
    │   └── flower/         # 产花相关
    └── pipeline/           # Pipeline JSON
        ├── common.json     # 通用节点
        └── flower.json     # 产花流程
tools/
├── setup.py                # 一键下载 MaaFramework
└── cropper.py              # 截图裁剪工具
```

## 鸣谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！
