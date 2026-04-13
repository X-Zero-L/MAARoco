#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "PySide6-Fluent-Widgets",
#     "opencv-python>=4.8",
#     "numpy",
# ]
# ///
"""MaaFramework Pipeline 截图裁剪工具

用法：
  uv run tools/cropper.py --adb 127.0.0.1:5555
  uv run tools/cropper.py --image screenshot.png
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PillPushButton,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    SingleDirectionScrollArea,
    StrongBodyLabel,
    SwitchButton,
    Theme,
    TreeWidget,
    setTheme,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_W, TARGET_H = 1280, 720

COLOR_ROI = QColor(255, 75, 75, 210)
COLOR_ROI_FILL = QColor(255, 75, 75, 25)
COLOR_TEMPLATE = QColor(56, 152, 255, 220)
COLOR_TEMPLATE_FILL = QColor(56, 152, 255, 25)
COLOR_TEMPLATE_SEL = QColor(255, 196, 0, 230)
COLOR_TEMPLATE_SEL_FILL = QColor(255, 196, 0, 35)
COLOR_GREEN = QColor(0, 220, 80, 180)
COLOR_PIPELINE = QColor(0, 200, 200, 140)

MODE_ROI = "ROI"
MODE_TEMPLATE = "Template"
MODE_GREEN_MASK = "GreenMask"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TemplateEntry:
    rect: tuple[int, int, int, int]  # (x1, y1, x2, y2) image coords
    name: str


@dataclass
class AppState:
    base_img: np.ndarray | None = None
    roi_rect: tuple[int, int, int, int] | None = None
    templates: list[TemplateEntry] = field(default_factory=list)
    screenshots: list[np.ndarray] = field(default_factory=list)
    screenshot_idx: int = -1
    mode: str = MODE_TEMPLATE
    green_brush_size: int = 10
    green_mask_layer: np.ndarray | None = None
    show_pipeline: bool = False
    pipeline_rois: list[tuple[str, list[int]]] = field(default_factory=list)
    zoom_factor: float = 1.0
    pan_offset: QPointF = field(default_factory=lambda: QPointF(0, 0))
    selected_template_idx: int = -1


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def adb_screencap(addr: str) -> np.ndarray | None:
    try:
        cmd = ["adb"]
        if addr:
            cmd.extend(["-s", addr])
        cmd.extend(["exec-out", "screencap", "-p"])
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode != 0:
            return None
        arr = np.frombuffer(result.stdout, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def ensure_720p(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if w == TARGET_W and h == TARGET_H:
        return img
    ratio = min(TARGET_W / w, TARGET_H / h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    if new_w == TARGET_W and new_h == TARGET_H:
        return resized
    canvas = np.zeros((TARGET_H, TARGET_W, 3), dtype=np.uint8)
    y_off = (TARGET_H - new_h) // 2
    x_off = (TARGET_W - new_w) // 2
    canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
    return canvas


def load_pipeline_rois(resource_dir: str) -> list[tuple[str, list[int]]]:
    rois: list[tuple[str, list[int]]] = []
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
                roi = rec.get("param", {}).get("roi")
            else:
                roi = node.get("roi")
            if isinstance(roi, list) and len(roi) == 4:
                rois.append((node_name, roi))
    return rois


def qimage_from_numpy(img: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()


def rect_to_xywh(rect: tuple[int, int, int, int]) -> list[int]:
    x1, y1, x2, y2 = rect
    x, y = min(x1, x2), min(y1, y2)
    return [x, y, abs(x2 - x1), abs(y2 - y1)]


def normalize_rect(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = rect
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def imwrite_safe(path: str, img: np.ndarray) -> bool:
    """cv2.imwrite that handles non-ASCII (中文) paths on Windows."""
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if ok:
        Path(path).write_bytes(buf.tobytes())
    return ok


# ---------------------------------------------------------------------------
# ExportDialog
# ---------------------------------------------------------------------------


class ExportDialog(QDialog):
    """Adaptive export dialog — works for template+ROI, template-only, or ROI-only."""

    def __init__(
        self,
        parent: QWidget | None,
        image_dir: str,
        pipeline_dir: str,
        template_count: int,
        roi_xywh: list[int] | None,
        existing_nodes: list[str] | None = None,
    ):
        super().__init__(parent)
        self.setMinimumWidth(460)
        self._image_dir = image_dir
        self._pipeline_dir = pipeline_dir
        self._template_count = template_count
        self._multi = template_count > 1
        self._roi_xywh = roi_xywh
        self._has_templates = template_count > 0
        self._roi_only = not self._has_templates and roi_xywh is not None
        self._existing_nodes = existing_nodes or []

        self.setWindowTitle("写入 ROI" if self._roi_only else "导出")

        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 18, 20, 16)
        lo.setSpacing(10)

        # ── Template image path (hidden when ROI-only) ──
        self._tpl_label = StrongBodyLabel("模板路径")
        lo.addWidget(self._tpl_label)
        self.tpl_path_edit = LineEdit(self)
        self.tpl_path_edit.setPlaceholderText("相对 image/，如 pet/wild_enemy")
        self.tpl_path_edit.setClearButtonEnabled(True)
        self.tpl_path_edit.textChanged.connect(self._on_tpl_path_changed)
        lo.addWidget(self.tpl_path_edit)
        if self._roi_only:
            self._tpl_label.hide()
            self.tpl_path_edit.hide()

        # ── Node name (auto-derived, editable) ──
        lo.addWidget(StrongBodyLabel("节点名称"))
        self.node_name_edit = LineEdit(self)
        if self._roi_only and self._existing_nodes:
            self.node_name_edit.setPlaceholderText("输入或从已有节点选择")
        else:
            self.node_name_edit.setPlaceholderText("Pipeline 节点 key，如 Pet_FindEnemy")
        self.node_name_edit.textChanged.connect(self._update_preview)
        lo.addWidget(self.node_name_edit)

        # ── Existing node picker (ROI-only mode) ──
        if self._roi_only and self._existing_nodes:
            self.node_combo = ComboBox(self)
            self.node_combo.addItem("— 新建节点 —")
            for n in self._existing_nodes:
                self.node_combo.addItem(n)
            self.node_combo.currentTextChanged.connect(self._on_node_combo_changed)
            lo.addWidget(self.node_combo)
        else:
            self.node_combo = None

        # ── Pipeline file selector ──
        lo.addWidget(StrongBodyLabel("写入 Pipeline"))
        self.pipeline_combo = ComboBox(self)
        self._populate_pipeline_files()
        self.pipeline_combo.currentTextChanged.connect(self._on_pipeline_file_changed)
        lo.addWidget(self.pipeline_combo)

        # ── Live preview ──
        self.preview = CaptionLabel("")
        self.preview.setWordWrap(True)
        lo.addWidget(self.preview)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        ok_text = "写入 ROI" if self._roi_only else "导出"
        self.ok_btn = PrimaryPushButton(ok_text, self, icon=FIF.SAVE)
        self.ok_btn.clicked.connect(self.accept)
        self.ok_btn.setEnabled(False)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.ok_btn)
        lo.addLayout(btn_row)

        if self._roi_only:
            self.node_name_edit.setFocus()
        else:
            self.tpl_path_edit.setFocus()
        self._update_preview()

    def _populate_pipeline_files(self):
        self.pipeline_combo.clear()
        if self._pipeline_dir and os.path.isdir(self._pipeline_dir):
            for f in sorted(Path(self._pipeline_dir).glob("*.json")):
                if f.name != "default_pipeline.json":
                    self.pipeline_combo.addItem(f.name)
        self.pipeline_combo.addItem("新建文件...")

    def _on_pipeline_file_changed(self):
        """When pipeline file changes in ROI-only mode, refresh node list."""
        if self.node_combo and self._pipeline_dir:
            pipe_file = self.pipeline_combo.currentText()
            if pipe_file and pipe_file != "新建文件...":
                pipe_path = os.path.join(self._pipeline_dir, pipe_file)
                if os.path.isfile(pipe_path):
                    try:
                        with open(pipe_path, "r", encoding="utf-8-sig") as f:
                            data = json.load(f)
                        nodes = [k for k in data if not k.startswith("$") and isinstance(data[k], dict)]
                        self.node_combo.blockSignals(True)
                        self.node_combo.clear()
                        self.node_combo.addItem("— 新建节点 —")
                        for n in nodes:
                            self.node_combo.addItem(n)
                        self.node_combo.blockSignals(False)
                    except Exception:
                        pass
        self._update_preview()

    def _on_node_combo_changed(self, text: str):
        if text and text != "— 新建节点 —":
            self.node_name_edit.setText(text)

    def _on_tpl_path_changed(self):
        path = self.tpl_path_edit.text().strip().replace("\\", "/")
        if path and not self.node_name_edit.isModified():
            leaf = path.rstrip("/").split("/")[-1]
            self.node_name_edit.setText(leaf)
        self._update_preview()

    def _update_preview(self):
        tpl = self.tpl_path_edit.text().strip().replace("\\", "/")
        node = self.node_name_edit.text().strip()
        pipe = self.pipeline_combo.currentText()

        if self._roi_only:
            self.ok_btn.setEnabled(bool(node and pipe))
        else:
            self.ok_btn.setEnabled(bool(tpl and node and pipe))

        if not node:
            self.preview.setText("")
            return

        lines: list[str] = []

        # Image info
        if self._has_templates and tpl:
            if self._multi:
                lines.append(f"图片  → image/{tpl}/0.png, 1.png ...")
                tpl_field = tpl
            else:
                lines.append(f"图片  → image/{tpl}.png")
                tpl_field = f"{tpl}.png"
        else:
            tpl_field = None

        # Node preview
        lines.append(f"节点  → pipeline/{pipe}")

        param_parts: list[str] = []
        if tpl_field:
            param_parts.append(f'"template": "{tpl_field}"')
        if self._roi_xywh:
            param_parts.append(f'"roi": {self._roi_xywh}')
        param_str = ", ".join(param_parts)

        if self._roi_only:
            is_existing = self.node_combo and self.node_combo.currentText() != "— 新建节点 —"
            if is_existing:
                lines.append(f'  更新 "{node}".roi = {self._roi_xywh}')
            else:
                lines.append(f'  "{node}": {{recognition: {{{param_str}}}, action: Click}}')
        else:
            lines.append(f'  "{node}": {{recognition: {{TemplateMatch, {param_str}}}, action: Click}}')

        self.preview.setText("\n".join(lines))

    def template_path(self) -> str:
        return self.tpl_path_edit.text().strip().replace("\\", "/")

    def node_name(self) -> str:
        return self.node_name_edit.text().strip()

    def pipeline_file(self) -> str:
        return self.pipeline_combo.currentText()

    def is_roi_only(self) -> bool:
        return self._roi_only

    def is_updating_existing(self) -> bool:
        return bool(
            self.node_combo
            and self.node_combo.currentText() != "— 新建节点 —"
        )


# ---------------------------------------------------------------------------
# CanvasWidget
# ---------------------------------------------------------------------------


class CanvasWidget(QWidget):
    """Custom painting widget for image display and annotation."""

    status_message = Signal(str)
    templates_changed = Signal()
    roi_changed = Signal()

    MIN_ZOOM = 0.25
    MAX_ZOOM = 4.0

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._cached_qimage: QImage | None = None
        self._dragging = False
        self._drag_start_img: tuple[int, int] | None = None
        self._drag_current_img: tuple[int, int] | None = None
        self._panning = False
        self._pan_start: QPointF | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)

    def invalidate_cache(self):
        self._cached_qimage = None
        self.update()

    def fit_to_window(self):
        if self.state.base_img is None:
            return
        h, w = self.state.base_img.shape[:2]
        zx = self.width() / w
        zy = self.height() / h
        self.state.zoom_factor = min(zx, zy, 1.0)
        scaled_w = w * self.state.zoom_factor
        scaled_h = h * self.state.zoom_factor
        self.state.pan_offset = QPointF(
            (self.width() - scaled_w) / 2,
            (self.height() - scaled_h) / 2,
        )
        self.update()

    def image_to_widget(self, ix: float, iy: float) -> QPointF:
        z = self.state.zoom_factor
        return QPointF(
            ix * z + self.state.pan_offset.x(),
            iy * z + self.state.pan_offset.y(),
        )

    def widget_to_image(self, wx: float, wy: float) -> tuple[int, int]:
        z = self.state.zoom_factor
        ix = int((wx - self.state.pan_offset.x()) / z)
        iy = int((wy - self.state.pan_offset.y()) / z)
        return max(0, min(ix, TARGET_W - 1)), max(0, min(iy, TARGET_H - 1))

    # ── paint ──

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(32, 32, 32))

        if self.state.base_img is None:
            self._paint_empty(p)
            p.end()
            return

        if self._cached_qimage is None:
            display = self.state.base_img.copy()
            if self.state.green_mask_layer is not None:
                mask = self.state.green_mask_layer > 0
                display[mask] = (0, 220, 80)
            self._cached_qimage = qimage_from_numpy(display)

        z = self.state.zoom_factor
        ox, oy = self.state.pan_offset.x(), self.state.pan_offset.y()
        target = QRectF(ox, oy, TARGET_W * z, TARGET_H * z)

        # Image shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(target.adjusted(3, 3, 3, 3), 2, 2)
        p.drawImage(target, self._cached_qimage)

        # Pipeline ROI overlay
        if self.state.show_pipeline:
            p.setFont(QFont("Consolas", 8))
            for name, roi in self.state.pipeline_rois:
                x, y, w, h = roi
                tl = self.image_to_widget(x, y)
                r = QRectF(tl.x(), tl.y(), w * z, h * z)
                p.setPen(QPen(COLOR_PIPELINE, 1, Qt.PenStyle.DashLine))
                p.setBrush(QColor(0, 200, 200, 10))
                p.drawRect(r)
                p.setPen(COLOR_PIPELINE)
                p.drawText(tl.x() + 3, tl.y() - 3, name)

        # ROI
        if self.state.roi_rect:
            self._draw_rect(p, self.state.roi_rect, COLOR_ROI, COLOR_ROI_FILL, "ROI")

        # Templates
        for i, tpl in enumerate(self.state.templates):
            sel = i == self.state.selected_template_idx
            c = COLOR_TEMPLATE_SEL if sel else COLOR_TEMPLATE
            f = COLOR_TEMPLATE_SEL_FILL if sel else COLOR_TEMPLATE_FILL
            self._draw_rect(p, tpl.rect, c, f, tpl.name or f"T{i}")

        # Drag preview
        if self._dragging and self._drag_start_img and self._drag_current_img:
            sx, sy = self._drag_start_img
            cx, cy = self._drag_current_img
            if self.state.mode == MODE_ROI:
                self._draw_rect(p, (sx, sy, cx, cy), COLOR_ROI, COLOR_ROI_FILL, "ROI")
            elif self.state.mode == MODE_TEMPLATE:
                self._draw_rect(
                    p, (sx, sy, cx, cy), COLOR_TEMPLATE, COLOR_TEMPLATE_FILL, ""
                )

        # Green mask brush cursor
        if self.state.mode == MODE_GREEN_MASK and self.underMouse():
            pos = self.mapFromGlobal(QCursor.pos())
            r = self.state.green_brush_size * z
            p.setPen(QPen(COLOR_GREEN, 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(pos.x(), pos.y()), r, r)

        p.end()

    def _paint_empty(self, p: QPainter):
        """Minimal prompt when no image is loaded."""
        cw, ch = self.width(), self.height()
        p.setPen(QColor(100, 100, 120))
        p.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        p.drawText(
            QRectF(0, ch / 2 - 50, cw, 40),
            Qt.AlignmentFlag.AlignCenter,
            "载入截图以开始",
        )
        p.setFont(QFont("Segoe UI", 11))
        p.setPen(QColor(80, 80, 100))
        p.drawText(
            QRectF(0, ch / 2 - 10, cw, 30),
            Qt.AlignmentFlag.AlignCenter,
            "Space  ADB 截图    Ctrl+O  打开文件    左侧双击浏览资源图片",
        )
        p.setFont(QFont("Segoe UI", 10))
        p.setPen(QColor(70, 70, 90))
        p.drawText(
            QRectF(0, ch / 2 + 20, cw, 30),
            Qt.AlignmentFlag.AlignCenter,
            "画 ROI / Template → Ctrl+E 导出模板图片 + 写入 Pipeline JSON",
        )

    def _draw_rect(
        self,
        p: QPainter,
        rect: tuple[int, int, int, int],
        color: QColor,
        fill: QColor,
        label: str,
    ):
        x1, y1, x2, y2 = rect
        tl = self.image_to_widget(min(x1, x2), min(y1, y2))
        br = self.image_to_widget(max(x1, x2), max(y1, y2))
        r = QRectF(tl, br)
        p.setPen(QPen(color, 2))
        p.setBrush(QBrush(fill))
        p.drawRect(r)
        if label:
            xywh = rect_to_xywh(rect)
            p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            text = f"{label}  {xywh}"
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(text) + 10
            th = fm.height() + 4
            lx, ly = tl.x(), tl.y() - th - 2
            pill = QRectF(lx, ly, tw, th)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(pill, 4, 4)
            p.setPen(color)
            p.drawText(int(lx + 5), int(ly + th - 4), text)

    # ── mouse ──

    def mousePressEvent(self, event):
        if self.state.base_img is None:
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        pos = event.position()
        ix, iy = self.widget_to_image(pos.x(), pos.y())
        if self.state.mode == MODE_GREEN_MASK:
            if event.button() in (
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.RightButton,
            ):
                self._paint_green(
                    ix, iy, erase=event.button() == Qt.MouseButton.RightButton
                )
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_img = (ix, iy)
            self._drag_current_img = (ix, iy)
        elif event.button() == Qt.MouseButton.RightButton and self.state.mode == MODE_ROI:
            self.state.roi_rect = None
            self.roi_changed.emit()
            self.status_message.emit("ROI 已清除")
            self.update()

    def mouseMoveEvent(self, event):
        if self.state.base_img is None:
            return
        if self._panning and self._pan_start is not None:
            delta = event.position() - self._pan_start
            self.state.pan_offset += QPointF(delta.x(), delta.y())
            self._pan_start = event.position()
            self.update()
            return
        pos = event.position()
        ix, iy = self.widget_to_image(pos.x(), pos.y())
        if self.state.mode == MODE_GREEN_MASK:
            btns = event.buttons()
            if btns & Qt.MouseButton.LeftButton:
                self._paint_green(ix, iy, erase=False)
            elif btns & Qt.MouseButton.RightButton:
                self._paint_green(ix, iy, erase=True)
            else:
                self.update()
            self.status_message.emit(
                f"({ix}, {iy})  笔刷={self.state.green_brush_size}"
            )
            return
        if self._dragging:
            self._drag_current_img = (ix, iy)
            self.status_message.emit(
                f"选区: {rect_to_xywh((*self._drag_start_img, ix, iy))}"
            )
            self.update()
        else:
            self.status_message.emit(f"({ix}, {iy})")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if not self._dragging:
            return
        self._dragging = False
        if not self._drag_start_img or not self._drag_current_img:
            return
        sx, sy = self._drag_start_img
        ex, ey = self.widget_to_image(event.position().x(), event.position().y())
        xywh = rect_to_xywh((sx, sy, ex, ey))
        if xywh[2] < 3 or xywh[3] < 3:
            self._drag_start_img = self._drag_current_img = None
            self.update()
            return
        rect = normalize_rect((sx, sy, ex, ey))
        if self.state.mode == MODE_ROI:
            self.state.roi_rect = rect
            self.roi_changed.emit()
            self.status_message.emit(f"ROI: {rect_to_xywh(rect)}")
        elif self.state.mode == MODE_TEMPLATE:
            idx = len(self.state.templates)
            entry = TemplateEntry(rect=rect, name=f"T{idx}")
            self.state.templates.append(entry)
            self.state.selected_template_idx = idx
            self.templates_changed.emit()
            self.status_message.emit(f"Template {entry.name}: {rect_to_xywh(rect)}")
        self._drag_start_img = self._drag_current_img = None
        self.update()

    def wheelEvent(self, event):
        if self.state.base_img is None:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        old_z = self.state.zoom_factor
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_z = max(self.MIN_ZOOM, min(self.MAX_ZOOM, old_z * factor))
        pos = event.position()
        self.state.pan_offset = QPointF(
            pos.x() - (pos.x() - self.state.pan_offset.x()) * new_z / old_z,
            pos.y() - (pos.y() - self.state.pan_offset.y()) * new_z / old_z,
        )
        self.state.zoom_factor = new_z
        self.status_message.emit(f"缩放: {new_z:.0%}")
        self.update()

    def _paint_green(self, ix: int, iy: int, erase: bool):
        if self.state.green_mask_layer is None:
            return
        cv2.circle(
            self.state.green_mask_layer,
            (ix, iy),
            self.state.green_brush_size,
            0 if erase else 255,
            -1,
        )
        self._cached_qimage = None
        self.update()


# ---------------------------------------------------------------------------
# SidebarWidget
# ---------------------------------------------------------------------------


class SidebarWidget(QFrame):
    """Scrollable sidebar with fluent cards."""

    screenshot_requested = Signal()
    screenshot_selected = Signal(int)
    image_file_selected = Signal(str)
    template_delete_requested = Signal(int)
    templates_clear_requested = Signal()
    template_selection_changed = Signal(int)
    mode_changed = Signal(str)
    pipeline_toggled = Signal()
    export_requested = Signal()
    open_image_requested = Signal()

    def __init__(self, state: AppState, image_dir: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.image_dir = image_dir
        self.setFixedWidth(288)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = SingleDirectionScrollArea(orient=Qt.Orientation.Vertical, parent=self)
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── 1. Guide card ──
        layout.addWidget(self._build_guide_card())

        # ── 2. Screenshot card ──
        layout.addWidget(self._build_screenshot_card())

        # ── 3. Mode card ──
        layout.addWidget(self._build_mode_card())

        # ── 4. History card ──
        layout.addWidget(self._build_history_card())

        # ── 5. Image browser card ──
        layout.addWidget(self._build_browser_card())

        # ── 6. Template card ──
        layout.addWidget(self._build_template_card())

        # ── Export button (standalone, always visible) ──
        self.export_btn = PrimaryPushButton("导出  Ctrl+E", self, icon=FIF.SAVE)
        self.export_btn.clicked.connect(self.export_requested.emit)
        layout.addWidget(self.export_btn)

        layout.addStretch()

        scroll.setWidget(container)
        root.addWidget(scroll)

    # ── Card builders ──

    def _build_guide_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget(self)
        card.setBorderRadius(8)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(6)

        lo.addWidget(StrongBodyLabel("使用说明"))

        steps = [
            ("①", "载入截图", "Space ADB截图 / Ctrl+O 打开 / 双击浏览"),
            ("②", "画 ROI (可选)", "Tab 切到 ROI，拖拽画红色搜索区域"),
            ("③", "画 Template (可选)", "Tab 切到 Template，拖拽追加蓝色模板框"),
            ("④", "导出", "Ctrl+E，保存模板图片 + 写入 Pipeline"),
        ]
        for num, title, desc in steps:
            row = QHBoxLayout()
            row.setSpacing(8)
            num_lbl = BodyLabel(num)
            num_lbl.setFixedWidth(18)
            num_lbl.setStyleSheet("color: #8b5cf6; font-weight: bold;")
            title_lbl = BodyLabel(title)
            title_lbl.setStyleSheet("font-weight: 600;")
            row.addWidget(num_lbl)
            row.addWidget(title_lbl)
            row.addStretch()
            lo.addLayout(row)
            desc_lbl = CaptionLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setContentsMargins(26, 0, 0, 4)
            lo.addWidget(desc_lbl)

        # Workflow tip
        lo.addSpacing(2)
        tip = CaptionLabel("ROI 和 Template 均可独立导出，也可组合使用")
        tip.setStyleSheet("color: #8b5cf6;")
        tip.setWordWrap(True)
        lo.addWidget(tip)

        # Shortcut reference
        lo.addSpacing(4)
        shortcuts_text = (
            "G 涂色   C 复制坐标   R 重置   Del 删除模板\n"
            "+/- 笔刷   P Pipeline叠加   Ctrl+0 适应窗口\n"
            "滚轮缩放   中键平移   ←/→ 切换截图"
        )
        sc_lbl = CaptionLabel(shortcuts_text)
        sc_lbl.setWordWrap(True)
        lo.addWidget(sc_lbl)

        return card

    def _build_screenshot_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget(self)
        card.setBorderRadius(8)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(8)

        lo.addWidget(StrongBodyLabel("截图"))

        self.adb_addr_edit = LineEdit(self)
        self.adb_addr_edit.setPlaceholderText("ADB 地址  例 127.0.0.1:5555")
        lo.addWidget(self.adb_addr_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.screencap_btn = PrimaryPushButton("ADB 截图", self, icon=FIF.CAMERA)
        self.screencap_btn.clicked.connect(self.screenshot_requested.emit)
        self.open_btn = PushButton("打开图片", self, icon=FIF.FOLDER)
        self.open_btn.clicked.connect(self.open_image_requested.emit)
        btn_row.addWidget(self.screencap_btn)
        btn_row.addWidget(self.open_btn)
        lo.addLayout(btn_row)

        return card

    def _build_mode_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget(self)
        card.setBorderRadius(8)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(8)

        lo.addWidget(StrongBodyLabel("模式"))

        pill_row = QHBoxLayout()
        pill_row.setSpacing(6)
        self.btn_roi = PillPushButton("ROI", self)
        self.btn_tpl = PillPushButton("Template", self)
        self.btn_green = PillPushButton("GreenMask", self)
        for btn in (self.btn_roi, self.btn_tpl, self.btn_green):
            btn.setCheckable(True)
            pill_row.addWidget(btn)
        self.btn_tpl.setChecked(True)

        self.btn_roi.clicked.connect(lambda: self.mode_changed.emit(MODE_ROI))
        self.btn_tpl.clicked.connect(lambda: self.mode_changed.emit(MODE_TEMPLATE))
        self.btn_green.clicked.connect(lambda: self.mode_changed.emit(MODE_GREEN_MASK))
        lo.addLayout(pill_row)

        # ROI indicator
        self.roi_label = CaptionLabel("")
        self.roi_label.setStyleSheet("color: #ff4b4b;")
        lo.addWidget(self.roi_label)

        # Pipeline toggle
        pipe_row = QHBoxLayout()
        pipe_row.addWidget(BodyLabel("Pipeline 叠加"))
        pipe_row.addStretch()
        self.pipeline_switch = SwitchButton(self)
        self.pipeline_switch.checkedChanged.connect(lambda _: self.pipeline_toggled.emit())
        pipe_row.addWidget(self.pipeline_switch)
        lo.addLayout(pipe_row)

        return card

    def _build_history_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget(self)
        card.setBorderRadius(8)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(8)

        lo.addWidget(StrongBodyLabel("截图历史"))

        self.history_list = ListWidget(self)
        self.history_list.setIconSize(QSize(100, 56))
        self.history_list.setMinimumHeight(60)
        self.history_list.setMaximumHeight(140)
        self.history_list.currentRowChanged.connect(self.screenshot_selected.emit)
        lo.addWidget(self.history_list)

        return card

    def _build_browser_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget(self)
        card.setBorderRadius(8)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(8)

        lo.addWidget(StrongBodyLabel("资源图片"))

        self.image_tree = TreeWidget(self)
        self.image_tree.setHeaderHidden(True)
        self.image_tree.setMinimumHeight(80)
        self.image_tree.setMaximumHeight(200)
        self.image_tree.itemDoubleClicked.connect(self._on_image_item_double_clicked)
        lo.addWidget(self.image_tree)

        self._populate_image_tree()
        return card

    def _build_template_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget(self)
        card.setBorderRadius(8)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(8)

        lo.addWidget(StrongBodyLabel("模板列表"))

        self.template_list = ListWidget(self)
        self.template_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.template_list.setMinimumHeight(60)
        self.template_list.setMaximumHeight(160)
        self.template_list.currentRowChanged.connect(
            self.template_selection_changed.emit
        )
        lo.addWidget(self.template_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        del_btn = PushButton("删除选中", self, icon=FIF.DELETE)
        del_btn.clicked.connect(self._on_delete_template)
        clear_btn = PushButton("清空全部", self, icon=FIF.BROOM)
        clear_btn.clicked.connect(self.templates_clear_requested.emit)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(clear_btn)
        lo.addLayout(btn_row)

        return card

    # ── Public helpers ──

    def set_adb_addr(self, addr: str):
        self.adb_addr_edit.setText(addr)

    def get_adb_addr(self) -> str:
        return self.adb_addr_edit.text().strip()

    def refresh_history(self):
        self.history_list.blockSignals(True)
        self.history_list.clear()
        for i, img in enumerate(self.state.screenshots):
            thumb = cv2.resize(img, (100, 56), interpolation=cv2.INTER_AREA)
            qimg = qimage_from_numpy(thumb)
            pix = QPixmap.fromImage(qimg)
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(pix, f"截图 {i + 1}")
            self.history_list.addItem(item)
        if self.state.screenshot_idx >= 0:
            self.history_list.setCurrentRow(self.state.screenshot_idx)
        self.history_list.blockSignals(False)

    def refresh_templates(self):
        self.template_list.blockSignals(True)
        self.template_list.clear()
        for i, tpl in enumerate(self.state.templates):
            xywh = rect_to_xywh(tpl.rect)
            self.template_list.addItem(f"{tpl.name}  {xywh}")
        if 0 <= self.state.selected_template_idx < len(self.state.templates):
            self.template_list.setCurrentRow(self.state.selected_template_idx)
        self.template_list.blockSignals(False)

    def update_mode_buttons(self, mode: str):
        for btn, m in [
            (self.btn_roi, MODE_ROI),
            (self.btn_tpl, MODE_TEMPLATE),
            (self.btn_green, MODE_GREEN_MASK),
        ]:
            btn.setChecked(mode == m)

    def update_roi_label(self):
        if self.state.roi_rect:
            xywh = rect_to_xywh(self.state.roi_rect)
            self.roi_label.setText(f"ROI: {xywh}  (右键清除)")
        else:
            self.roi_label.setText("")

    # ── Private ──

    def _populate_image_tree(self):
        self.image_tree.clear()
        if not self.image_dir or not os.path.isdir(self.image_dir):
            return
        self._add_tree_items(self.image_tree.invisibleRootItem(), Path(self.image_dir))

    def _add_tree_items(self, parent_item, path: Path):
        try:
            entries = sorted(
                path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except PermissionError:
            return
        for entry in entries:
            if entry.is_dir():
                d = QTreeWidgetItem(parent_item, [entry.name])
                self._add_tree_items(d, entry)
            elif entry.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
                f = QTreeWidgetItem(parent_item, [entry.name])
                f.setData(0, Qt.ItemDataRole.UserRole, str(entry))

    def _on_image_item_double_clicked(self, item: QTreeWidgetItem, _col: int):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.image_file_selected.emit(path)

    def _on_delete_template(self):
        row = self.template_list.currentRow()
        if row >= 0:
            self.template_delete_requested.emit(row)


# ---------------------------------------------------------------------------
# CropperWindow
# ---------------------------------------------------------------------------


class CropperWindow(QMainWindow):
    def __init__(
        self, adb_addr: str = "", image_path: str = "", resource_dir: str = ""
    ):
        super().__init__()
        self.setWindowTitle("MaaFW Cropper")
        self.resize(1360, 820)

        self.resource_dir = resource_dir or self._find_resource_dir()
        self.image_dir = (
            os.path.join(self.resource_dir, "image") if self.resource_dir else ""
        )

        self.state = AppState()
        if self.resource_dir:
            self.state.pipeline_rois = load_pipeline_rois(self.resource_dir)

        # ── Layout ──
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        self.sidebar = SidebarWidget(self.state, self.image_dir)
        self.canvas = CanvasWidget(self.state)

        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        # Status bar row
        status = QFrame()
        status.setFixedHeight(32)
        status.setStyleSheet(
            "QFrame{background:rgba(40,40,40,200); border-top:1px solid #3a3a3a;}"
        )
        slo = QHBoxLayout(status)
        slo.setContentsMargins(14, 0, 14, 0)
        slo.setSpacing(16)
        self.mode_label = CaptionLabel("Template")
        self.mode_label.setStyleSheet("font-weight:600;")
        self.coord_label = CaptionLabel("")
        self.zoom_label = CaptionLabel("100%")
        self.msg_label = CaptionLabel("")
        slo.addWidget(self.mode_label)
        slo.addWidget(self.coord_label)
        slo.addStretch()
        slo.addWidget(self.msg_label)
        slo.addWidget(self.zoom_label)
        outer.addWidget(status)

        # ── Signals ──
        self.canvas.status_message.connect(self._on_canvas_status)
        self.canvas.templates_changed.connect(self._on_templates_changed)
        self.canvas.roi_changed.connect(self._on_roi_changed)

        self.sidebar.screenshot_requested.connect(self._take_screenshot)
        self.sidebar.screenshot_selected.connect(self._switch_screenshot)
        self.sidebar.image_file_selected.connect(self._load_image_file)
        self.sidebar.template_delete_requested.connect(self._delete_template)
        self.sidebar.templates_clear_requested.connect(self._clear_templates)
        self.sidebar.template_selection_changed.connect(self._on_sidebar_template_select)
        self.sidebar.mode_changed.connect(self._set_mode)
        self.sidebar.pipeline_toggled.connect(self._toggle_pipeline)
        self.sidebar.export_requested.connect(self._export)
        self.sidebar.open_image_requested.connect(self._open_image_dialog)

        self._setup_shortcuts()

        # ── Init ──
        if adb_addr:
            self.sidebar.set_adb_addr(adb_addr)
        if image_path:
            self._load_image_file(image_path)
        elif adb_addr:
            self._take_screenshot()

        self._update_status()

    @staticmethod
    def _find_resource_dir() -> str:
        for c in ("assets/resource", "../assets/resource"):
            if os.path.isdir(c):
                return os.path.abspath(c)
        return ""

    def _setup_shortcuts(self):
        def sc(key, fn):
            QShortcut(QKeySequence(key), self, fn)

        sc(Qt.Key.Key_Tab, self._cycle_mode)
        sc(Qt.Key.Key_G, lambda: self._set_mode(MODE_GREEN_MASK))
        sc(Qt.Key.Key_Plus, self._brush_inc)
        sc(Qt.Key.Key_Equal, self._brush_inc)
        sc(Qt.Key.Key_Minus, self._brush_dec)
        sc("Ctrl+E", self._export)
        sc(Qt.Key.Key_Return, self._export)
        sc(Qt.Key.Key_Enter, self._export)
        sc(Qt.Key.Key_C, self._copy_coords)
        sc(Qt.Key.Key_P, self._toggle_pipeline)
        sc(Qt.Key.Key_Space, self._take_screenshot)
        sc(Qt.Key.Key_Left, lambda: self._nav_screenshot(-1))
        sc(Qt.Key.Key_Right, lambda: self._nav_screenshot(1))
        sc(Qt.Key.Key_R, self._reset_all)
        sc(Qt.Key.Key_Delete, self._delete_selected_template)
        sc("Ctrl+O", self._open_image_dialog)
        sc("Ctrl+0", self.canvas.fit_to_window)
        sc(Qt.Key.Key_Q, self.close)
        sc(Qt.Key.Key_Escape, self.close)

    # ── helpers ──

    def _info(self, msg: str):
        InfoBar.success("", msg, duration=2000, position=InfoBarPosition.BOTTOM, parent=self)
        self.msg_label.setText(msg)

    def _warn(self, msg: str):
        InfoBar.warning("", msg, duration=3000, position=InfoBarPosition.BOTTOM, parent=self)
        self.msg_label.setText(msg)

    # ── mode ──

    def _set_mode(self, mode: str):
        self.state.mode = mode
        self.sidebar.update_mode_buttons(mode)
        self._update_status()
        self.canvas.update()

    def _cycle_mode(self):
        nxt = {MODE_ROI: MODE_TEMPLATE, MODE_TEMPLATE: MODE_ROI, MODE_GREEN_MASK: MODE_ROI}
        self._set_mode(nxt.get(self.state.mode, MODE_ROI))

    # ── brush ──

    def _brush_inc(self):
        self.state.green_brush_size = min(50, self.state.green_brush_size + 2)
        self.msg_label.setText(f"笔刷: {self.state.green_brush_size}")

    def _brush_dec(self):
        self.state.green_brush_size = max(2, self.state.green_brush_size - 2)
        self.msg_label.setText(f"笔刷: {self.state.green_brush_size}")

    # ── screenshot ──

    def _take_screenshot(self):
        addr = self.sidebar.get_adb_addr()
        if not addr:
            self._warn("请输入 ADB 地址")
            return
        self.msg_label.setText("正在截图...")
        QApplication.processEvents()
        img = adb_screencap(addr)
        if img is not None:
            self._push_screenshot(ensure_720p(img))
            self._info("截图成功")
        else:
            self._warn("截图失败，请检查 ADB 连接")

    def _push_screenshot(self, img: np.ndarray):
        self.state.screenshots.append(img.copy())
        self.state.screenshot_idx = len(self.state.screenshots) - 1
        self.state.base_img = img.copy()
        self.state.green_mask_layer = np.zeros(img.shape[:2], dtype=np.uint8)
        self.canvas.invalidate_cache()
        self.canvas.fit_to_window()
        self.sidebar.refresh_history()
        self._update_status()

    def _switch_screenshot(self, idx: int):
        if idx < 0 or idx >= len(self.state.screenshots):
            return
        self.state.screenshot_idx = idx
        self.state.base_img = self.state.screenshots[idx].copy()
        self.state.green_mask_layer = np.zeros(
            self.state.base_img.shape[:2], dtype=np.uint8
        )
        self.canvas.invalidate_cache()
        self._update_status()

    def _nav_screenshot(self, delta: int):
        if not self.state.screenshots:
            return
        new_idx = max(
            0, min(len(self.state.screenshots) - 1, self.state.screenshot_idx + delta)
        )
        if new_idx != self.state.screenshot_idx:
            self._switch_screenshot(new_idx)
            self.sidebar.refresh_history()

    # ── image loading ──

    def _open_image_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开图片",
            self.image_dir or "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All (*)",
        )
        if path:
            self._load_image_file(path)

    def _load_image_file(self, path: str):
        # cv2.imread can't handle non-ASCII paths on Windows
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            self._warn(f"无法加载: {path}")
            return
        self._push_screenshot(ensure_720p(img))
        self._info(f"已加载: {os.path.basename(path)}")

    # ── templates ──

    def _on_roi_changed(self):
        self.sidebar.update_roi_label()
        self._update_status()

    def _on_templates_changed(self):
        self.sidebar.refresh_templates()
        self._update_status()

    def _on_sidebar_template_select(self, idx: int):
        self.state.selected_template_idx = idx
        self.canvas.update()

    def _delete_template(self, idx: int):
        if 0 <= idx < len(self.state.templates):
            self.state.templates.pop(idx)
            self.state.selected_template_idx = min(
                self.state.selected_template_idx, len(self.state.templates) - 1
            )
            self.sidebar.refresh_templates()
            self.canvas.update()
            self._update_status()

    def _delete_selected_template(self):
        if self.state.selected_template_idx >= 0:
            self._delete_template(self.state.selected_template_idx)

    def _clear_templates(self):
        self.state.templates.clear()
        self.state.selected_template_idx = -1
        self.sidebar.refresh_templates()
        self.canvas.update()
        self._update_status()

    # ── pipeline ──

    def _toggle_pipeline(self):
        self.state.show_pipeline = self.sidebar.pipeline_switch.isChecked()
        n = len(self.state.pipeline_rois)
        self.msg_label.setText(
            f"Pipeline ROI {'显示' if self.state.show_pipeline else '隐藏'} ({n} 个)"
        )
        self.canvas.update()

    # ── copy ──

    def _copy_coords(self):
        if self.state.mode == MODE_ROI and self.state.roi_rect:
            xywh = rect_to_xywh(self.state.roi_rect)
        elif 0 <= self.state.selected_template_idx < len(self.state.templates):
            xywh = rect_to_xywh(
                self.state.templates[self.state.selected_template_idx].rect
            )
        else:
            self._warn("无选区可复制")
            return
        text = json.dumps(xywh)
        QApplication.clipboard().setText(text)
        self._info(f"已复制: {text}")

    # ── reset ──

    def _reset_all(self):
        self.state.roi_rect = None
        self.state.templates.clear()
        self.state.selected_template_idx = -1
        if self.state.green_mask_layer is not None:
            self.state.green_mask_layer[:] = 0
        self.sidebar.refresh_templates()
        self.sidebar.update_roi_label()
        self.canvas.invalidate_cache()
        self._info("所有选区已重置")
        self._update_status()

    # ── export ──

    def _export(self):
        if self.state.base_img is None:
            self._warn("无截图，无法导出")
            return
        if not self.state.templates and not self.state.roi_rect:
            self._warn("请先画 ROI 或 Template")
            return

        roi_xywh = rect_to_xywh(self.state.roi_rect) if self.state.roi_rect else None
        pipeline_dir = os.path.join(self.resource_dir, "pipeline") if self.resource_dir else ""

        # Collect existing node names for ROI-only picker
        existing_nodes: list[str] = []
        if not self.state.templates and pipeline_dir and os.path.isdir(pipeline_dir):
            for fpath in sorted(Path(pipeline_dir).glob("*.json")):
                try:
                    with open(fpath, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                    for k in data:
                        if not k.startswith("$") and isinstance(data[k], dict):
                            existing_nodes.append(k)
                except Exception:
                    pass

        dlg = ExportDialog(
            self, self.image_dir, pipeline_dir,
            len(self.state.templates), roi_xywh,
            existing_nodes=existing_nodes,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        tpl_path = dlg.template_path()
        node_name = dlg.node_name()
        pipeline_file = dlg.pipeline_file()
        if not node_name:
            self._warn("节点名不能为空")
            return

        # ── 1. Save template images (if any) ──
        tpl_field: str | None = None
        start_idx = 0
        if self.state.templates and tpl_path:
            save_base = self.image_dir or os.getcwd()
            folder = os.path.join(save_base, tpl_path)
            single_file = os.path.join(save_base, f"{tpl_path}.png")

            # Determine starting index: check existing folder or single file
            start_idx = 0
            if os.path.isdir(folder):
                # Folder exists — find next available index to append
                existing = [
                    int(p.stem) for p in Path(folder).glob("*.png")
                    if p.stem.isdigit()
                ]
                start_idx = max(existing) + 1 if existing else 0
            elif os.path.isfile(single_file):
                # Single .png exists — upgrade to folder, move old file to 0.png
                old_img = single_file
                os.makedirs(folder, exist_ok=True)
                shutil.move(old_img, os.path.join(folder, "0.png"))
                start_idx = 1

            if start_idx > 0 or len(self.state.templates) > 1:
                # Save as folder (multi-template)
                os.makedirs(folder, exist_ok=True)
                for i, tpl in enumerate(self.state.templates):
                    imwrite_safe(
                        os.path.join(folder, f"{start_idx + i}.png"),
                        self._crop_template(tpl.rect),
                    )
                tpl_field = tpl_path  # MaaFW folder match
            else:
                # First time, single template → single file
                os.makedirs(os.path.dirname(single_file) or save_base, exist_ok=True)
                imwrite_safe(single_file, self._crop_template(self.state.templates[0].rect))
                tpl_field = f"{tpl_path}.png"

            # Save source screenshots for later re-editing
            source_dir = os.path.join(save_base, ".source", tpl_path)
            os.makedirs(source_dir, exist_ok=True)
            for i, tpl in enumerate(self.state.templates):
                imwrite_safe(
                    os.path.join(source_dir, f"{start_idx + i}.png"),
                    self.state.base_img,
                )

        # ── 2. Write into pipeline JSON ──
        wrote_pipeline = False
        if pipeline_dir:
            if pipeline_file == "新建文件...":
                stem = tpl_path.split("/")[0] if (tpl_path and "/" in tpl_path) else (tpl_path or node_name)
                pipeline_file = f"{stem}.json"

            pipe_path = os.path.join(pipeline_dir, pipeline_file)
            os.makedirs(pipeline_dir, exist_ok=True)

            if os.path.isfile(pipe_path):
                with open(pipe_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            else:
                data = {"$schema": "../../../deps/tools/pipeline.schema.json"}

            if dlg.is_roi_only() and dlg.is_updating_existing() and node_name in data:
                # Update existing node's ROI only
                node_data = data[node_name]
                rec = node_data.get("recognition", {})
                if isinstance(rec, dict):
                    param = rec.setdefault("param", {})
                    param["roi"] = roi_xywh
                else:
                    node_data.setdefault("roi", roi_xywh)
            elif node_name in data and tpl_field:
                # Node exists — update template path (e.g. single→folder upgrade)
                node_data = data[node_name]
                rec = node_data.get("recognition", {})
                if isinstance(rec, dict):
                    param = rec.get("param", {})
                    param["template"] = tpl_field
                    if roi_xywh:
                        param["roi"] = roi_xywh
                    rec["param"] = param
            else:
                # Build new pipeline node
                rec_param: dict = {}
                if tpl_field:
                    rec_param["template"] = tpl_field
                if roi_xywh:
                    rec_param["roi"] = roi_xywh

                node = {
                    "doc": "",
                    "recognition": {"type": "TemplateMatch", "param": rec_param},
                    "action": {"type": "Click"},
                }
                data[node_name] = node

            with open(pipe_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write("\n")
            wrote_pipeline = True

            # Refresh pipeline ROI cache
            self.state.pipeline_rois = load_pipeline_rois(self.resource_dir)

        # ── 3. Copy snippet to clipboard ──
        if dlg.is_roi_only():
            QApplication.clipboard().setText(json.dumps(roi_xywh))
        else:
            rec_param_clip: dict = {}
            if tpl_field:
                rec_param_clip["template"] = tpl_field
            if roi_xywh:
                rec_param_clip["roi"] = roi_xywh
            snippet = {node_name: {
                "recognition": {"type": "TemplateMatch", "param": rec_param_clip},
                "action": {"type": "Click"},
            }}
            QApplication.clipboard().setText(json.dumps(snippet, indent=4, ensure_ascii=False))

        # ── 4. Feedback ──
        parts: list[str] = []
        if tpl_field:
            n = len(self.state.templates)
            if start_idx > 0:
                parts.append(f"追加 {n} 张 → image/{tpl_path}/ (#{start_idx}-{start_idx+n-1})")
            else:
                parts.append(f"{n} 个模板 → image/{tpl_field}")
        if wrote_pipeline:
            if dlg.is_roi_only() and dlg.is_updating_existing():
                parts.append(f"ROI 已更新 → {node_name}")
            else:
                parts.append(f"节点 {node_name} → pipeline/{pipeline_file}")
        self._info("已保存: " + "，".join(parts) if parts else "已导出")

    def _crop_template(self, rect: tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = normalize_rect(rect)
        crop = self.state.base_img[y1:y2, x1:x2].copy()
        if self.state.green_mask_layer is not None:
            mask_crop = self.state.green_mask_layer[y1:y2, x1:x2]
            if np.any(mask_crop > 0):
                crop[mask_crop > 0] = (0, 220, 80)
        return crop

    # ── status ──

    def _on_canvas_status(self, msg: str):
        self.coord_label.setText(msg)
        self.zoom_label.setText(f"{self.state.zoom_factor:.0%}")

    def _update_status(self):
        mode = self.state.mode
        text = mode
        if mode == MODE_GREEN_MASK:
            text += f"  笔刷={self.state.green_brush_size}"
        self.mode_label.setText(text)
        self.zoom_label.setText(f"{self.state.zoom_factor:.0%}")

        # Show annotation summary in msg_label
        parts: list[str] = []
        if self.state.roi_rect:
            parts.append(f"ROI: {rect_to_xywh(self.state.roi_rect)}")
        if self.state.templates:
            parts.append(f"模板×{len(self.state.templates)}")
        self.msg_label.setText("  ".join(parts))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="MaaFramework Pipeline 截图裁剪工具")
    parser.add_argument("--adb", default="", help="ADB 设备地址")
    parser.add_argument("--image", default="", help="加载本地图片")
    parser.add_argument("--resource", default="", help="资源目录路径")
    args = parser.parse_args()

    if not args.adb and not args.image:
        try:
            result = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")[1:]
            devices = [l.split("\t")[0] for l in lines if "\tdevice" in l]
            if devices:
                args.adb = devices[0]
                print(f"[自动检测] ADB: {args.adb}")
        except Exception:
            pass

    app = QApplication(sys.argv)
    setTheme(Theme.DARK)

    window = CropperWindow(
        adb_addr=args.adb, image_path=args.image, resource_dir=args.resource
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
