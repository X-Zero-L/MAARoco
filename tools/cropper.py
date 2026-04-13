#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "opencv-python>=4.8",
#     "numpy",
# ]
# ///
"""MaaFramework Pipeline 截图裁剪工具

双选区模式：
  红色框 = ROI（搜索区域，对应 pipeline 的 roi 字段）
  蓝色框 = Template（匹配目标，裁剪保存为模板图片）

快捷键：
  Tab        切换 ROI / Template 模式
  左键拖拽    框选当前模式的选区
  右键        清除当前模式选区
  Enter      导出（保存模板图片 + 输出 ROI 坐标）
  C          复制当前选区坐标到剪贴板
  G          切换 green_mask 涂色模式
  Space      重新 adb 截图
  ← →        浏览历史截图
  P          叠加显示 pipeline ROI
  R          重置所有选区
  Q / Esc    退出

用法：
  python tools/cropper.py --adb 127.0.0.1:5555
  python tools/cropper.py --image screenshot.png
"""

import argparse
import glob
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

TARGET_W, TARGET_H = 1280, 720
WINDOW_NAME = "MaaFW Cropper"

COLOR_ROI = (0, 0, 255)        # 红 (BGR)
COLOR_TEMPLATE = (255, 100, 0)  # 蓝
COLOR_GREEN = (0, 255, 0)       # green_mask
COLOR_PIPELINE = (0, 200, 200)  # 黄 pipeline 预览
COLOR_TEXT_BG = (30, 30, 30)
COLOR_TEXT = (220, 220, 220)

MODE_ROI = "ROI"
MODE_TEMPLATE = "Template"
MODE_GREEN_MASK = "GreenMask"


def clipboard_copy(text: str):
    """跨平台复制到剪贴板"""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        elif system == "Linux":
            try:
                subprocess.run(["xclip", "-selection", "clipboard"],
                               input=text.encode(), check=True)
            except FileNotFoundError:
                subprocess.run(["xsel", "--clipboard", "--input"],
                               input=text.encode(), check=True)
        elif system == "Windows":
            subprocess.run(["clip"], input=text.encode(), check=True)
    except Exception:
        pass


def adb_screencap(addr: str) -> np.ndarray | None:
    """通过 adb 截图，返回 numpy 数组"""
    try:
        cmd = ["adb"]
        if addr:
            cmd.extend(["-s", addr])
        cmd.extend(["exec-out", "screencap", "-p"])
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode != 0:
            print(f"[错误] adb 截图失败: {result.stderr.decode(errors='replace')}")
            return None
        arr = np.frombuffer(result.stdout, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            print("[错误] 无法解码截图数据")
            return None
        return img
    except subprocess.TimeoutExpired:
        print("[错误] adb 截图超时")
        return None
    except FileNotFoundError:
        print("[错误] 未找到 adb 命令")
        return None


def load_image(path: str) -> np.ndarray | None:
    """加载本地图片"""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        print(f"[错误] 无法加载图片: {path}")
    return img


def ensure_720p(img: np.ndarray) -> np.ndarray:
    """确保图片为 1280x720，非标准分辨率等比缩放"""
    h, w = img.shape[:2]
    if w == TARGET_W and h == TARGET_H:
        return img

    ratio = min(TARGET_W / w, TARGET_H / h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    if new_w == TARGET_W and new_h == TARGET_H:
        print(f"[提示] 已从 {w}x{h} 缩放到 720p")
        return resized

    canvas = np.zeros((TARGET_H, TARGET_W, 3), dtype=np.uint8)
    y_off = (TARGET_H - new_h) // 2
    x_off = (TARGET_W - new_w) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    print(f"[警告] 非标准比例 {w}x{h}，已缩放并居中到 720p")
    return canvas


def load_pipeline_rois(resource_dir: str) -> list[tuple[str, list[int]]]:
    """从 pipeline JSON 中加载所有 ROI 定义"""
    rois = []
    pipeline_dir = os.path.join(resource_dir, "pipeline")
    if not os.path.isdir(pipeline_dir):
        return rois

    for fpath in glob.glob(os.path.join(pipeline_dir, "*.json")):
        try:
            with open(fpath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue

        for node_name, node in data.items():
            if node_name.startswith("$") or not isinstance(node, dict):
                continue
            rec = node.get("recognition", {})
            if isinstance(rec, dict):
                param = rec.get("param", {})
                roi = param.get("roi")
            else:
                roi = node.get("roi")
            if isinstance(roi, list) and len(roi) == 4:
                rois.append((node_name, roi))
    return rois


class Cropper:
    def __init__(self, adb_addr: str = "", image_path: str = "",
                 resource_dir: str = ""):
        self.adb_addr = adb_addr
        self.resource_dir = resource_dir or self._find_resource_dir()
        self.image_dir = os.path.join(self.resource_dir, "image") if self.resource_dir else ""

        self.mode = MODE_TEMPLATE
        self.roi_rect = None          # (x1, y1, x2, y2)
        self.template_rect = None
        self.dragging = False
        self.drag_start = None

        self.green_mask_mode = False
        self.green_brush_size = 10
        self.green_mask_layer = None  # 与 base_img 同尺寸的 mask

        self.show_pipeline = False
        self.pipeline_rois = []

        self.screenshots: list[np.ndarray] = []
        self.screenshot_idx = -1
        self.base_img = None          # 当前原始截图（720p）
        self.status_msg = ""

        if image_path:
            img = load_image(image_path)
            if img is not None:
                self._push_screenshot(ensure_720p(img))
        elif adb_addr:
            self._take_screenshot()

    def _find_resource_dir(self) -> str:
        candidates = [
            "assets/resource",
            "../assets/resource",
        ]
        for c in candidates:
            if os.path.isdir(c):
                return os.path.abspath(c)
        return ""

    def _push_screenshot(self, img: np.ndarray):
        self.screenshots.append(img.copy())
        self.screenshot_idx = len(self.screenshots) - 1
        self.base_img = img.copy()
        self.green_mask_layer = np.zeros(img.shape[:2], dtype=np.uint8)
        self.status_msg = f"截图 {self.screenshot_idx + 1}/{len(self.screenshots)}"

    def _take_screenshot(self):
        self.status_msg = "正在截图..."
        self._render()
        img = adb_screencap(self.adb_addr)
        if img is not None:
            self._push_screenshot(ensure_720p(img))
            self.status_msg = f"截图成功 ({self.base_img.shape[1]}x{self.base_img.shape[0]})"
        else:
            self.status_msg = "截图失败"

    def _switch_screenshot(self, delta: int):
        if not self.screenshots:
            return
        self.screenshot_idx = max(0, min(len(self.screenshots) - 1,
                                         self.screenshot_idx + delta))
        self.base_img = self.screenshots[self.screenshot_idx].copy()
        self.green_mask_layer = np.zeros(self.base_img.shape[:2], dtype=np.uint8)
        self.status_msg = f"截图 {self.screenshot_idx + 1}/{len(self.screenshots)}"

    def _rect_to_xywh(self, rect: tuple[int, int, int, int]) -> list[int]:
        x1, y1, x2, y2 = rect
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        return [x, y, w, h]

    def _render(self):
        if self.base_img is None:
            canvas = np.zeros((TARGET_H, TARGET_W, 3), dtype=np.uint8)
            self._draw_status(canvas, "等待截图... 按 Space 截图 或提供 --image 参数")
            cv2.imshow(WINDOW_NAME, canvas)
            return

        canvas = self.base_img.copy()

        # 绘制 green_mask
        if self.green_mask_layer is not None:
            mask = self.green_mask_layer > 0
            canvas[mask] = COLOR_GREEN

        # 绘制 pipeline ROI 预览
        if self.show_pipeline:
            for name, roi in self.pipeline_rois:
                x, y, w, h = roi
                cv2.rectangle(canvas, (x, y), (x + w, y + h), COLOR_PIPELINE, 1)
                cv2.putText(canvas, name, (x, y - 4), cv2.FONT_HERSHEY_SIMPLEX,
                            0.35, COLOR_PIPELINE, 1)

        # 绘制 ROI 选区（红色）
        if self.roi_rect:
            x1, y1, x2, y2 = self.roi_rect
            cv2.rectangle(canvas, (x1, y1), (x2, y2), COLOR_ROI, 2)
            xywh = self._rect_to_xywh(self.roi_rect)
            cv2.putText(canvas, f"ROI {xywh}", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_ROI, 1)

        # 绘制 Template 选区（蓝色）
        if self.template_rect:
            x1, y1, x2, y2 = self.template_rect
            cv2.rectangle(canvas, (x1, y1), (x2, y2), COLOR_TEMPLATE, 2)
            xywh = self._rect_to_xywh(self.template_rect)
            cv2.putText(canvas, f"TPL {xywh}", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_TEMPLATE, 1)

        # 状态栏
        mode_str = self.mode
        if self.green_mask_mode:
            mode_str = f"GreenMask (笔刷={self.green_brush_size})"
        status = f"[{mode_str}] {self.status_msg}"
        self._draw_status(canvas, status)

        # 帮助提示
        help_text = "Tab:切换模式 Enter:导出 C:复制坐标 G:绿色涂色 Space:截图 P:Pipeline R:重置 Q:退出"
        cv2.putText(canvas, help_text, (5, TARGET_H - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.33, (150, 150, 150), 1)

        cv2.imshow(WINDOW_NAME, canvas)

    def _draw_status(self, canvas: np.ndarray, text: str):
        cv2.rectangle(canvas, (0, 0), (TARGET_W, 22), COLOR_TEXT_BG, -1)
        cv2.putText(canvas, text, (8, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, COLOR_TEXT, 1)

    def _mouse_callback(self, event, x, y, flags, param):
        x = max(0, min(x, TARGET_W - 1))
        y = max(0, min(y, TARGET_H - 1))

        if self.green_mask_mode and self.green_mask_layer is not None:
            if event == cv2.EVENT_LBUTTONDOWN or (
                event == cv2.EVENT_MOUSEMOVE and flags & cv2.EVENT_FLAG_LBUTTON
            ):
                cv2.circle(self.green_mask_layer, (x, y),
                           self.green_brush_size, 255, -1)
                self._render()
            elif event == cv2.EVENT_RBUTTONDOWN or (
                event == cv2.EVENT_MOUSEMOVE and flags & cv2.EVENT_FLAG_RBUTTON
            ):
                cv2.circle(self.green_mask_layer, (x, y),
                           self.green_brush_size, 0, -1)
                self._render()
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            self.dragging = True
            self.drag_start = (x, y)

        elif event == cv2.EVENT_MOUSEMOVE and self.dragging:
            rect = (self.drag_start[0], self.drag_start[1], x, y)
            if self.mode == MODE_ROI:
                self.roi_rect = rect
            else:
                self.template_rect = rect
            self.status_msg = f"选区: {self._rect_to_xywh(rect)}"
            self._render()

        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging = False
            if self.drag_start:
                rect = (self.drag_start[0], self.drag_start[1], x, y)
                xywh = self._rect_to_xywh(rect)
                if xywh[2] > 2 and xywh[3] > 2:
                    if self.mode == MODE_ROI:
                        self.roi_rect = rect
                    else:
                        self.template_rect = rect
                    self.status_msg = f"{self.mode}: {xywh}"
                self._render()

        elif event == cv2.EVENT_RBUTTONDOWN:
            if self.mode == MODE_ROI:
                self.roi_rect = None
                self.status_msg = "ROI 已清除"
            else:
                self.template_rect = None
                self.status_msg = "Template 已清除"
            self._render()

    def _export(self):
        if self.base_img is None:
            self.status_msg = "无截图，无法导出"
            return

        if self.template_rect is None:
            self.status_msg = "请先框选 Template 区域"
            return

        tpl_xywh = self._rect_to_xywh(self.template_rect)
        roi_xywh = self._rect_to_xywh(self.roi_rect) if self.roi_rect else None

        # 裁剪模板图片
        x, y, w, h = tpl_xywh
        crop = self.base_img[y:y + h, x:x + w].copy()

        # 应用 green_mask
        if self.green_mask_layer is not None:
            mask_crop = self.green_mask_layer[y:y + h, x:x + w]
            if np.any(mask_crop > 0):
                crop[mask_crop > 0] = COLOR_GREEN

        # 终端交互输入文件名
        print()
        if roi_xywh:
            print(f"  ROI:      {roi_xywh}")
        print(f"  Template: {tpl_xywh}")
        print()

        name = input("  保存路径 (相对 image/, 如 common/close_btn): ").strip()
        if not name:
            self.status_msg = "已取消导出"
            return

        if not name.endswith(".png"):
            name += ".png"

        if self.image_dir:
            save_path = os.path.join(self.image_dir, name)
        else:
            save_path = name

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        cv2.imwrite(save_path, crop, [cv2.IMWRITE_PNG_COMPRESSION, 9])

        # 输出结果
        print(f"\n  ✓ 已保存: {save_path}")
        print(f"  ✓ 尺寸: {w}x{h}")

        # 构建可粘贴的 pipeline 片段
        output_lines = []
        if roi_xywh:
            output_lines.append(f'"roi": {json.dumps(roi_xywh)}')
            clipboard_copy(json.dumps(roi_xywh))
            print(f"  ✓ ROI 已复制到剪贴板: {roi_xywh}")
        output_lines.append(f'"template": "{name}"')

        print(f"\n  Pipeline 片段:")
        for line in output_lines:
            print(f"    {line}")
        print()

        self.status_msg = f"已导出: {name}"

    def _copy_coords(self):
        rect = self.roi_rect if self.mode == MODE_ROI else self.template_rect
        if rect is None:
            self.status_msg = "无选区可复制"
            return
        xywh = self._rect_to_xywh(rect)
        text = json.dumps(xywh)
        clipboard_copy(text)
        self.status_msg = f"已复制: {text}"

    def run(self):
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WINDOW_NAME, self._mouse_callback)

        if self.resource_dir:
            self.pipeline_rois = load_pipeline_rois(self.resource_dir)

        if self.base_img is None:
            self.status_msg = "按 Space 截图，或用 --image 加载图片"

        self._render()

        while True:
            key = cv2.waitKey(50) & 0xFF

            if key == ord('q') or key == 27:  # Q / Esc
                break

            elif key == 9:  # Tab
                if self.green_mask_mode:
                    self.green_mask_mode = False
                self.mode = MODE_TEMPLATE if self.mode == MODE_ROI else MODE_ROI
                self.status_msg = f"切换到 {self.mode} 模式"
                self._render()

            elif key == 13:  # Enter
                self._export()
                self._render()

            elif key == ord('c'):
                self._copy_coords()
                self._render()

            elif key == ord('g'):
                self.green_mask_mode = not self.green_mask_mode
                if self.green_mask_mode:
                    self.status_msg = "GreenMask 涂色模式 (左键涂色/右键擦除, +/-调笔刷)"
                else:
                    self.status_msg = f"退出涂色模式，当前: {self.mode}"
                self._render()

            elif key == ord('+') or key == ord('='):
                self.green_brush_size = min(50, self.green_brush_size + 2)
                self.status_msg = f"笔刷大小: {self.green_brush_size}"
                self._render()

            elif key == ord('-'):
                self.green_brush_size = max(2, self.green_brush_size - 2)
                self.status_msg = f"笔刷大小: {self.green_brush_size}"
                self._render()

            elif key == 32:  # Space
                if self.adb_addr:
                    self._take_screenshot()
                    self._render()
                else:
                    self.status_msg = "未配置 adb，无法截图"
                    self._render()

            elif key == 81 or key == 2:  # ← 左
                self._switch_screenshot(-1)
                self._render()

            elif key == 83 or key == 3:  # → 右
                self._switch_screenshot(1)
                self._render()

            elif key == ord('p'):
                self.show_pipeline = not self.show_pipeline
                n = len(self.pipeline_rois)
                self.status_msg = f"Pipeline ROI {'显示' if self.show_pipeline else '隐藏'} ({n} 个)"
                self._render()

            elif key == ord('r'):
                self.roi_rect = None
                self.template_rect = None
                if self.green_mask_layer is not None:
                    self.green_mask_layer[:] = 0
                self.status_msg = "所有选区已重置"
                self._render()

        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        description="MaaFramework Pipeline 截图裁剪工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--adb", default="", help="adb 设备地址 (如 127.0.0.1:5555)")
    parser.add_argument("--image", default="", help="加载本地图片文件")
    parser.add_argument("--resource", default="", help="资源目录路径 (默认自动查找)")
    args = parser.parse_args()

    if not args.adb and not args.image:
        # 尝试检测已连接的 adb 设备
        try:
            result = subprocess.run(["adb", "devices"], capture_output=True,
                                    text=True, timeout=5)
            lines = result.stdout.strip().split("\n")[1:]
            devices = [l.split("\t")[0] for l in lines
                       if "\tdevice" in l]
            if devices:
                args.adb = devices[0]
                print(f"[自动检测] 使用 adb 设备: {args.adb}")
            else:
                print("[提示] 未检测到 adb 设备，可用 --adb 或 --image 指定输入源")
        except Exception:
            pass

    cropper = Cropper(
        adb_addr=args.adb,
        image_path=args.image,
        resource_dir=args.resource
    )
    cropper.run()


if __name__ == "__main__":
    main()
