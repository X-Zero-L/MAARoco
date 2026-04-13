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

- **产花·表情动作** — 自动点击表情（优先大笑，无则鞠躬），每 8.5 秒执行一次
- **产花·播放留影** — 循环点击观赏/播放留影按钮
- 待机画面自动唤醒

## 快速开始

### 方式一：使用 MWU Web GUI（推荐）

从 [Releases](../../releases) 下载对应平台的压缩包，解压后运行即可。内含 [MWU](https://github.com/ravizhan/MWU) Web GUI，打开浏览器访问即可操作。

> 服务器部署时建议配合 nginx 反向代理 + 身份认证，避免暴露在公网。

### 方式二：使用 MaaPiCli 命令行

#### 1. 下载 MaaFramework 运行时

```bash
uv run tools/setup.py
```

#### 2. 运行

```bash
./run.sh
# 或手动
cp assets/interface.json deps/bin/ && ./deps/bin/MaaPiCli.exe
```

首次运行选择 ADB 设备连接，之后选择需要执行的任务。

**表情动作任务需先在游戏内手动进入表情面板**，留影任务需保证留影按钮可见。

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
    │   ├── common/         # 通用（待机、加载等）
    │   ├── flower/         # 产花相关（laugh/bow/replay）
    │   └── login/          # 登录相关
    └── pipeline/           # Pipeline JSON
        ├── common.json     # 通用节点（待机、弹窗等）
        ├── flower.json     # 产花流程
        └── collect_mail.json
tools/
├── setup.py                # 一键下载 MaaFramework
└── cropper.py              # 截图裁剪工具（PySide6 GUI）
```

## 鸣谢

- **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** — 自动化框架
- **[MWU](https://github.com/ravizhan/MWU)** — Web GUI
