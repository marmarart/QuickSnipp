"""Editor window: toolbar, canvas, drawing tools, clipboard/save actions."""

import math
import os
import time

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QGuiApplication, QIcon,
                         QImage, QKeySequence, QPainter, QPainterPath, QPen,
                         QPixmap)
from PyQt6.QtWidgets import (QApplication, QColorDialog, QFileDialog, QFrame,
                             QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QMainWindow, QMenu, QMessageBox,
                             QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                             QToolBar, QToolButton, QVBoxLayout, QWidget)

from .capture import CaptureError, capture_full_desktop
from .overlay import SnipSession

PEN_WIDTHS = (2, 4, 6, 10)
DEFAULT_COLOR = "#ff4d4d"

PRESET_COLORS = [
    ("#ff4d4d", "Red"),
    ("#ff9933", "Orange"),
    ("#ffea00", "Yellow"),
    ("#4cd964", "Green"),
    ("#4da3ff", "Blue"),
    ("#b366ff", "Purple"),
    ("#ffffff", "White"),
    ("#1b1e23", "Dark"),
]


class HorizontalScrollArea(QScrollArea):
    """Horizontal scroll area that translates vertical mouse wheel events to horizontal scrolling."""

    def wheelEvent(self, event):
        if event.angleDelta().y() != 0:
            delta = event.angleDelta().y()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta
            )
            event.accept()
        else:
            super().wheelEvent(event)


class ColorPaletteWidget(QWidget):
    color_selected = pyqtSignal(QColor)

    def __init__(self, current_color: QColor, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        self._buttons = []
        self._current_hex = current_color.name().lower()

        for hex_col, name in PRESET_COLORS:
            btn = QPushButton()
            btn.setToolTip(f"{name} ({hex_col})")
            btn.setFixedSize(26, 26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, c=hex_col: self._on_color_clicked(c))
            layout.addWidget(btn)
            self._buttons.append((hex_col.lower(), btn))

        self.custom_btn = QPushButton("🎨")
        self.custom_btn.setToolTip("Custom Color...")
        self.custom_btn.setFixedSize(30, 26)
        self.custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.custom_btn.setStyleSheet(
            "QPushButton { background: #232730; color: #fff; border: 1px solid #444c5c; border-radius: 6px; font-size: 14px; } "
            "QPushButton:hover { background: #2f3542; border-color: #66b3ff; }"
        )
        self.custom_btn.clicked.connect(self._pick_custom)
        layout.addWidget(self.custom_btn)

        self._refresh_styles()

    def _refresh_styles(self):
        for hex_col, btn in self._buttons:
            is_active = (hex_col == self._current_hex)
            border = "2.5px solid #ffffff" if is_active else "1px solid rgba(255,255,255,0.4)"
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {hex_col}; border-radius: 13px; border: {border}; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; }} "
                f"QPushButton:hover {{ border: 2px solid #66b3ff; }}"
            )

    def set_color(self, color: QColor):
        self._current_hex = color.name().lower()
        self._refresh_styles()

    def _on_color_clicked(self, hex_col: str):
        self._current_hex = hex_col.lower()
        self._refresh_styles()
        self.color_selected.emit(QColor(hex_col))

    def _pick_custom(self):
        col = QColorDialog.getColor(QColor(self._current_hex), self, "Select Color")
        if col.isValid():
            self.set_color(col)
            self.color_selected.emit(col)


def _snap_point(start: QPoint, pos: QPoint, tool: str, shift_held: bool) -> QPoint:
    if not shift_held or start is None or pos is None:
        return pos
    dx = pos.x() - start.x()
    dy = pos.y() - start.y()
    if tool in ("line", "arrow"):
        dist = math.hypot(dx, dy)
        angle = math.atan2(dy, dx)
        step = math.pi / 4  # 45 degrees
        snapped = round(angle / step) * step
        return QPoint(int(start.x() + dist * math.cos(snapped)),
                      int(start.y() + dist * math.sin(snapped)))
    elif tool in ("rect", "ellipse", "blur"):
        side = max(abs(dx), abs(dy))
        sx = 1 if dx >= 0 else -1
        sy = 1 if dy >= 0 else -1
        return QPoint(start.x() + sx * side, start.y() + sy * side)
    return pos


class Canvas(QWidget):
    """1:1 image canvas with pen / line / arrow / rect / text / crop tools."""

    MAX_HISTORY = 15

    image_changed = pyqtSignal()
    zoom_changed = pyqtSignal(float)
    modified = pyqtSignal()
    copy_requested = pyqtSignal()
    paste_requested = pyqtSignal()
    save_requested = pyqtSignal()
    discard_requested = pyqtSignal()

    FREEHAND_TOOLS = ("pen", "highlighter")
    SHAPE_TOOLS = ("line", "arrow", "rect", "ellipse", "blur")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: QImage | None = None
        self.tool = "pen"
        self.color = QColor(DEFAULT_COLOR)
        self.pen_width = 4
        self.step_counter = 1
        self.zoom_factor: float = 1.0
        self._stroke: list[QPoint] | None = None
        self._shape_start: QPoint | None = None
        self._shape_end: QPoint | None = None
        self._text_editor: QLineEdit | None = None
        self._text_pos: QPoint | None = None
        # crop state: _crop_rect persists after the drag so it can be
        # adjusted; _crop_mode is None (idle) / "draw" / "move" / a handle id
        self._crop_rect: QRect | None = None
        self._crop_mode: str | None = None
        self._crop_anchor: QPoint | None = None
        self._crop_orig: QRect | None = None
        self._move_offset: QPoint | None = None
        self._undo: list[QImage] = []
        self._redo: list[QImage] = []
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._crop_ok = QToolButton(self)
        self._crop_ok.setText("✓")
        self._crop_ok.setToolTip("Apply crop (Enter)")
        self._crop_ok.clicked.connect(self._apply_crop)
        self._crop_cancel = QToolButton(self)
        self._crop_cancel.setText("✕")
        self._crop_cancel.setToolTip("Cancel crop (Esc)")
        self._crop_cancel.clicked.connect(self._clear_crop)
        for btn in (self._crop_ok, self._crop_cancel):
            btn.setFixedSize(30, 30)
            btn.hide()

        self._refresh_size()

    # --- image state ----------------------------------------------------

    def has_image(self) -> bool:
        return self._image is not None

    def image(self) -> QImage | None:
        return self._image

    def set_image(self, img: QImage | None, clear_history: bool = True):
        self._image = img.convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied) if img is not None else None
        self._stroke = None
        self._shape_start = None
        self._shape_end = None
        self._clear_crop()
        if getattr(self, "_text_editor", None) is not None:
            self._text_editor.deleteLater()
            self._text_editor = None
        if clear_history:
            self._undo.clear()
            self._redo.clear()
            self.step_counter = 1
            self.zoom_factor = 1.0
            self.zoom_changed.emit(self.zoom_factor)
        self._refresh_size()
        self.update()
        self.image_changed.emit()

    def set_zoom(self, factor: float):
        factor = max(0.2, min(5.0, factor))
        if abs(factor - self.zoom_factor) < 0.005:
            return
        self.zoom_factor = factor
        self._refresh_size()
        if self._crop_rect is not None:
            self._show_crop_buttons()
        self.update()
        self.zoom_changed.emit(self.zoom_factor)

    def _to_image_point(self, pt: QPoint) -> QPoint:
        if abs(self.zoom_factor - 1.0) < 0.001:
            return pt
        return QPoint(int(pt.x() / self.zoom_factor), int(pt.y() / self.zoom_factor))

    def _refresh_size(self):
        if self._image is None:
            self.setFixedSize(720, 420)
        else:
            w = max(1, int(self._image.width() * self.zoom_factor))
            h = max(1, int(self._image.height() * self.zoom_factor))
            self.setFixedSize(w, h)

    # --- undo / redo ----------------------------------------------------

    def _push_undo(self):
        if self._image is None:
            return
        self._undo.append(self._image.copy())
        if len(self._undo) > self.MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self):
        if not self._undo or self._image is None:
            return
        self._redo.append(self._image.copy())
        self._image = self._undo.pop()
        self._refresh_size()
        self.update()
        self.image_changed.emit()

    def redo(self):
        if not self._redo or self._image is None:
            return
        self._undo.append(self._image.copy())
        self._image = self._redo.pop()
        self._refresh_size()
        self.update()
        self.image_changed.emit()

    # --- painting -----------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1b1e23"))
        if self._image is None:
            p.setPen(QColor("#5a6472"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "No snip yet — click  ＋ New Snip  to capture a region")
            p.end()
            return

        p.save()
        if abs(self.zoom_factor - 1.0) > 0.001:
            p.scale(self.zoom_factor, self.zoom_factor)

        p.drawImage(0, 0, self._image)

        if self._stroke and len(self._stroke) > 1:
            p.setPen(self._pen())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath(QPointF(self._stroke[0]))
            for pt in self._stroke[1:]:
                path.lineTo(QPointF(pt))
            p.drawPath(path)

        if self._shape_start is not None and self._shape_end is not None:
            p.setPen(self._pen())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_shape(p, self.tool, self._shape_start, self._shape_end)

        if self._crop_rect is not None:
            bounds = self._image.rect()
            r = self._crop_rect.intersected(bounds)
            # dim everything outside the crop rect
            shade = QColor(0, 0, 0, 130)
            p.fillRect(QRect(0, 0, bounds.width(), r.top()), shade)
            p.fillRect(QRect(0, r.bottom() + 1, bounds.width(),
                             bounds.height() - r.bottom() - 1), shade)
            p.fillRect(QRect(0, r.top(), r.left(), r.height() + 1), shade)
            p.fillRect(QRect(r.right() + 1, r.top(),
                             bounds.width() - r.right() - 1, r.height() + 1), shade)
            pen = QPen(QColor("#4da3ff"), 1.0 / self.zoom_factor, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(r)
            p.setPen(QColor("#4da3ff"))
            p.drawText(r.left(), max(14, r.top() - 6),
                       f"{r.width()} × {r.height()}")
            # resize handles (only when not mid-drag)
            if self._crop_mode is None:
                p.setPen(QPen(QColor("#4da3ff"), 1.0 / self.zoom_factor))
                p.setBrush(QColor("#ffffff"))
                h_size = max(6, int(8 / self.zoom_factor))
                h_half = h_size // 2
                for c in self._handle_points(r).values():
                    p.drawRect(QRect(c.x() - h_half, c.y() - h_half, h_size, h_size))

        p.restore()
        p.end()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.set_zoom(self.zoom_factor * 1.15)
            elif delta < 0:
                self.set_zoom(self.zoom_factor / 1.15)
            event.accept()
        else:
            super().wheelEvent(event)

    def _pen(self) -> QPen:
        if self.tool == "highlighter":
            c = QColor(self.color)
            c.setAlpha(110)
            return QPen(c, max(14, self.pen_width * 3), Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        pen = QPen(self.color, self.pen_width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        return pen

    @staticmethod
    def _draw_shape(p: QPainter, tool: str, start: QPoint, end: QPoint):
        if tool == "rect":
            p.drawRect(QRect(start, end).normalized())
            return
        if tool == "ellipse":
            p.drawEllipse(QRect(start, end).normalized())
            return
        if tool == "blur":
            r = QRect(start, end).normalized()
            p.setPen(QPen(QColor("#4da3ff"), 1, Qt.PenStyle.DashLine))
            p.drawRect(r)
            p.fillRect(r, QColor(0, 0, 0, 80))
            return
        p.drawLine(start, end)
        if tool == "arrow":
            angle = math.atan2(end.y() - start.y(), end.x() - start.x())
            head = 10 + p.pen().width() * 3
            for offset in (math.radians(155), math.radians(-155)):
                tip = QPointF(end)
                wing = QPointF(end.x() + head * math.cos(angle + offset),
                               end.y() + head * math.sin(angle + offset))
                p.drawLine(tip, wing)

    def _apply_blur(self, rect: QRect):
        if self._image is None:
            return
        r = rect.intersected(self._image.rect())
        if r.width() < 4 or r.height() < 4:
            return
        self._push_undo()
        sub = self._image.copy(r)
        block_size = max(6, self.pen_width * 2)
        small_w = max(1, r.width() // block_size)
        small_h = max(1, r.height() // block_size)
        pixelated = sub.scaled(small_w, small_h,
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.FastTransformation)
        pixelated = pixelated.scaled(r.width(), r.height(),
                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.FastTransformation)
        p = QPainter(self._image)
        p.drawImage(r.topLeft(), pixelated)
        p.end()
        self.modified.emit()

    def _place_step_badge(self, pos: QPoint):
        if self._image is None:
            return
        self._push_undo()
        p = QPainter(self._image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = max(13, 10 + self.pen_width)
        circle_rect = QRect(pos.x() - radius, pos.y() - radius, radius * 2, radius * 2)

        # Draw circle badge with border
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        p.setBrush(self.color)
        p.drawEllipse(circle_rect)

        # Text color based on luminance
        lum = 0.299 * self.color.red() + 0.587 * self.color.green() + 0.114 * self.color.blue()
        text_color = QColor("#101318") if lum > 150 else QColor("#ffffff")
        p.setPen(text_color)
        font = p.font()
        font.setPixelSize(max(10, int(radius * 1.1)))
        font.setBold(True)
        p.setFont(font)
        p.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, str(self.step_counter))
        p.end()

        self.step_counter += 1
        self.modified.emit()
        self.update()

    # --- mouse handling -------------------------------------------------------

    def mousePressEvent(self, event):
        if self._image is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if getattr(self, "_text_editor", None) is not None:
            self._commit_text()
        pos = self._to_image_point(event.position().toPoint())
        if self.tool in self.FREEHAND_TOOLS:
            self._stroke = [pos]
            self.update()
        elif self.tool in self.SHAPE_TOOLS:
            self._shape_start = pos
            self._shape_end = pos
            self.update()
        elif self.tool == "step":
            self._place_step_badge(pos)
        elif self.tool == "crop":
            self._crop_press(pos)
        elif self.tool == "text":
            self._place_text(pos)

    def mouseMoveEvent(self, event):
        pos = self._to_image_point(event.position().toPoint())
        if self._stroke is not None:
            self._stroke.append(pos)
            self.update()
        elif self._shape_start is not None:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._shape_end = _snap_point(self._shape_start, pos, self.tool, shift)
            self.update()
        elif self._crop_mode is not None:
            self._crop_drag(pos)
        elif self.tool == "crop" and self._crop_rect is not None:
            self._update_crop_cursor(pos)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = self._to_image_point(event.position().toPoint())
        if self._stroke is not None:
            self._stroke.append(pos)
            if len(self._stroke) > 1:
                self._push_undo()
                p = QPainter(self._image)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(self._pen())
                path = QPainterPath(QPointF(self._stroke[0]))
                for pt in self._stroke[1:]:
                    path.lineTo(QPointF(pt))
                p.drawPath(path)
                p.end()
                self.modified.emit()
            self._stroke = None
            self.update()
        elif self._shape_start is not None:
            start = self._shape_start
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            end_pos = _snap_point(start, pos, self.tool, shift)
            self._shape_start = None
            self._shape_end = None
            if start is not None and start != end_pos:
                if self.tool == "blur":
                    self._apply_blur(QRect(start, end_pos).normalized())
                else:
                    self._push_undo()
                    p = QPainter(self._image)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    p.setPen(self._pen())
                    self._draw_shape(p, self.tool, start, end_pos)
                    p.end()
                    self.modified.emit()
            self.update()
        elif self._crop_mode is not None:
            self._crop_release(pos)

    # --- crop tool --------------------------------------------------------------

    MIN_CROP = 4
    HANDLE_HIT = 10

    def _crop_press(self, pos: QPoint):
        if self._crop_rect is not None:
            handle = self._hit_handle(pos)
            if handle is not None:
                self._crop_mode = handle
                self._crop_orig = QRect(self._crop_rect)
                return
            if self._crop_rect.contains(pos):
                self._crop_mode = "move"
                self._crop_orig = QRect(self._crop_rect)
                self._move_offset = pos - self._crop_rect.topLeft()
                return
        # start a new rectangle
        self._crop_mode = "draw"
        self._crop_anchor = pos
        self._crop_rect = QRect(pos, pos)
        self._hide_crop_buttons()
        self.update()

    def _crop_drag(self, pos: QPoint):
        bounds = self._image.rect() if self._image else self.rect()
        if self._crop_mode == "draw":
            r = QRect(self._crop_anchor, pos).normalized()
        elif self._crop_mode == "move":
            top_left = pos - self._move_offset
            r = QRect(top_left, self._crop_orig.size())
            # keep the rect fully inside the image
            x = min(max(r.left(), 0), max(0, bounds.right() - r.width() + 1))
            y = min(max(r.top(), 0), max(0, bounds.bottom() - r.height() + 1))
            r.moveTo(x, y)
        else:  # a resize handle
            o = self._crop_orig
            left, top, right, bottom = o.left(), o.top(), o.right(), o.bottom()
            if "l" in self._crop_mode:
                left = pos.x()
            if "r" in self._crop_mode:
                right = pos.x()
            if "t" in self._crop_mode:
                top = pos.y()
            if "b" in self._crop_mode:
                bottom = pos.y()
            r = QRect(QPoint(left, top), QPoint(right, bottom)).normalized()
        self._crop_rect = r.intersected(bounds)
        self.update()

    def _crop_release(self, pos: QPoint):
        mode = self._crop_mode
        self._crop_mode = None
        if mode == "draw":
            self._crop_rect = QRect(self._crop_anchor, pos).normalized()
        if (self._crop_rect is None or self._crop_rect.width() < self.MIN_CROP
                or self._crop_rect.height() < self.MIN_CROP):
            self._clear_crop()
            return
        self._show_crop_buttons()
        self.update()

    def _handle_points(self, r: QRect) -> dict:
        cx, cy = r.center().x(), r.center().y()
        return {
            "tl": r.topLeft(), "t": QPoint(cx, r.top()), "tr": r.topRight(),
            "l": QPoint(r.left(), cy), "r": QPoint(r.right(), cy),
            "bl": r.bottomLeft(), "b": QPoint(cx, r.bottom()),
            "br": r.bottomRight(),
        }

    def _hit_handle(self, pos: QPoint) -> str | None:
        if self._crop_rect is None:
            return None
        hit_dist = max(self.HANDLE_HIT, int(self.HANDLE_HIT / self.zoom_factor))
        for name, center in self._handle_points(self._crop_rect).items():
            if abs(pos.x() - center.x()) <= hit_dist \
                    and abs(pos.y() - center.y()) <= hit_dist:
                return name
        return None

    def _update_crop_cursor(self, pos: QPoint):
        handle = self._hit_handle(pos)
        cursors = {
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
            "t": Qt.CursorShape.SizeVerCursor,
            "b": Qt.CursorShape.SizeVerCursor,
            "l": Qt.CursorShape.SizeHorCursor,
            "r": Qt.CursorShape.SizeHorCursor,
        }
        if handle is not None:
            self.setCursor(cursors[handle])
        elif self._crop_rect.contains(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _apply_crop(self):
        r = self._crop_rect
        if (r is None or self._image is None or r.width() < self.MIN_CROP
                or r.height() < self.MIN_CROP):
            self._clear_crop()
            return
        self._push_undo()
        self.set_image(self._image.copy(r.intersected(self._image.rect())),
                       clear_history=False)
        self.modified.emit()

    def _clear_crop(self):
        had = self._crop_rect is not None or self._crop_mode is not None
        self._crop_rect = None
        self._crop_mode = None
        self._crop_anchor = None
        self._crop_orig = None
        self._move_offset = None
        self._hide_crop_buttons()
        if had:
            self.update()

    def _show_crop_buttons(self):
        if self._crop_rect is None or self._image is None:
            return
        r = self._crop_rect
        img_w = self._image.width()
        img_h = self._image.height()
        y = r.bottom() + 8
        if y + 34 > img_h:
            y = r.top() - 38
        y = max(4, y)
        x = min(r.right() - 64, img_w - 68)
        x = max(4, x)
        self._crop_cancel.move(int(x * self.zoom_factor), int(y * self.zoom_factor))
        self._crop_ok.move(int((x + 34) * self.zoom_factor), int(y * self.zoom_factor))
        self._crop_cancel.show()
        self._crop_ok.show()
        self._crop_ok.raise_()
        self._crop_cancel.raise_()

    def _hide_crop_buttons(self):
        self._crop_ok.hide()
        self._crop_cancel.hide()

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and self._crop_rect is not None):
            self._apply_crop()
            return
        super().keyPressEvent(event)

    def _place_text(self, pos: QPoint):
        self._commit_text()
        editor = QLineEdit(self)
        editor.setStyleSheet(
            f"background: #14161a; color: {self.color.name()}; "
            f"border: 1px dashed #4da3ff; border-radius: 3px; padding: 2px 4px;"
        )
        font = editor.font()
        font_pixel = max(14, int((16 + self.pen_width * 2) * self.zoom_factor))
        font.setPixelSize(font_pixel)
        font.setBold(True)
        editor.setFont(font)
        editor.setMinimumWidth(120)

        screen_pos = QPoint(int(pos.x() * self.zoom_factor), int(pos.y() * self.zoom_factor))
        editor.move(screen_pos)
        editor.show()
        editor.setFocus()

        self._text_pos = pos
        self._text_editor = editor
        editor.returnPressed.connect(self._commit_text)

    def _commit_text(self):
        if getattr(self, "_text_editor", None) is None or self._image is None:
            return
        editor = self._text_editor
        text = editor.text().strip()
        pos = getattr(self, "_text_pos", None)
        self._text_editor = None
        editor.deleteLater()
        if not text or pos is None:
            self.update()
            return
        self._push_undo()
        p = QPainter(self._image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = p.font()
        font.setPixelSize(16 + self.pen_width * 2)
        font.setBold(True)
        p.setFont(font)
        p.setPen(self.color)
        metrics = p.fontMetrics()
        p.drawText(pos.x(), pos.y() + metrics.ascent(), text)
        p.end()
        self.modified.emit()
        self.update()

    def cancel_pending(self) -> bool:
        """Abort any in-progress drag, pending crop, or active text editing. True if one existed."""
        had = False
        if getattr(self, "_text_editor", None) is not None:
            self._text_editor.deleteLater()
            self._text_editor = None
            had = True
        if (self._stroke is not None or self._shape_start is not None
                or self._crop_rect is not None or self._crop_mode is not None):
            self._stroke = None
            self._shape_start = None
            self._shape_end = None
            self._clear_crop()
            had = True
        if had:
            self.update()
            return True
        return False

    def has_pending_crop(self) -> bool:
        return self._crop_rect is not None or self._crop_mode is not None

    # --- context menu ---------------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self._image is not None:
            menu.addAction("Copy", QKeySequence("Ctrl+C"), self.copy_requested.emit)
            menu.addAction("Save…", QKeySequence("Ctrl+S"), self.save_requested.emit)
            menu.addSeparator()
        menu.addAction("Paste", QKeySequence("Ctrl+V"), self.paste_requested.emit)
        if self._image is not None:
            menu.addSeparator()
            menu.addAction("Discard", self.discard_requested.emit)
        menu.exec(event.globalPos())


class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QuickSnipp")
        self.resize(960, 680)

        self.canvas = Canvas()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Top horizontally scrollable bar containing all tools, colors & undo/redo
        top_bar = self._build_top_bar()

        # Bottom Action Bar: Copy/Save on Left, Status in Center, Zoom on Right
        bottom_bar = QWidget()
        bottom_bar.setFixedHeight(44)
        bottom_bar.setStyleSheet("""
            QWidget#bottom_bar {
                background: #14161b;
                border-top: 1px solid #232730;
            }
            QPushButton {
                background: #20242c;
                color: #e1e4ea;
                border: 1px solid #333842;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #2b313c;
                border-color: #4da3ff;
            }
            QPushButton#copy_btn {
                background: #0066cc;
                color: #ffffff;
                border: 1px solid #1a75ff;
                font-weight: bold;
            }
            QPushButton#copy_btn:hover {
                background: #0073e6;
            }
        """)
        bottom_bar.setObjectName("bottom_bar")
        self._build_bottom_bar(bottom_bar)

        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(top_bar)
        main_layout.addWidget(self.scroll, stretch=1)
        main_layout.addWidget(bottom_bar)
        self.setCentralWidget(main_container)

        self._build_menu_bar()
        self.setAcceptDrops(True)
        self._session: SnipSession | None = None
        self._wire_canvas()
        self._set_status_text("Ctrl+N new snip · Ctrl+V paste · Ctrl+Z undo · Ctrl+C copy · Ctrl+S save · Esc discard")

    # --- UI construction ------------------------------------------------------

    def _build_menu_bar(self):
        mb = self.menuBar()
        mb.setStyleSheet("""
            QMenuBar { font-size: 13px; font-weight: 500; padding: 2px 4px; }
            QMenu { font-size: 13px; padding: 4px; }
            QMenu::item { padding: 4px 20px; }
        """)

        def _add_action(menu, text, slot, shortcut=None):
            act = QAction(text, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(slot)
            menu.addAction(act)
            return act

        # File Menu
        menu_file = mb.addMenu("&File")
        _add_action(menu_file, "＋ New Snip", self.start_snip, "Ctrl+N")
        _add_action(menu_file, "📋 Paste Image", self.paste_from_clipboard, "Ctrl+V")
        _add_action(menu_file, "💾 Save...", self.save_to_file, "Ctrl+S")
        menu_file.addSeparator()
        _add_action(menu_file, "✕ Discard", self.discard, "Esc")
        menu_file.addSeparator()
        _add_action(menu_file, "Quit", QApplication.quit, "Ctrl+Q")

        # Edit Menu
        menu_edit = mb.addMenu("&Edit")
        _add_action(menu_edit, "↶ Undo", self.canvas.undo, "Ctrl+Z")
        _add_action(menu_edit, "↷ Redo", self.canvas.redo, "Ctrl+Shift+Z")
        menu_edit.addSeparator()
        _add_action(menu_edit, "⧉ Copy", self.copy_to_clipboard, "Ctrl+C")

        # Tools Menu
        menu_tools = mb.addMenu("&Tools")
        for k, lbl in (("pen", "✏ Pen"), ("highlighter", "🖍 Highlighter"),
                       ("arrow", "➶ Arrow"), ("line", "╱ Line"),
                       ("rect", "▭ Rectangle"), ("ellipse", "⬭ Circle"),
                       ("step", "① Step Badge"), ("text", "🅣 Text"),
                       ("blur", "░ Blur / Pixelate"), ("crop", "⬚ Crop")):
            _add_action(menu_tools, lbl, lambda checked=False, t=k: self._set_tool_and_check(t))

        # View Menu
        menu_view = mb.addMenu("&View")
        _add_action(menu_view, "Zoom In", self._zoom_in, "Ctrl++")
        _add_action(menu_view, "Zoom Out", self._zoom_out, "Ctrl+-")
        _add_action(menu_view, "Fit to Window", self._zoom_fit, "Ctrl+0")
        _add_action(menu_view, "Actual Size (100%)", self._zoom_100, "Ctrl+1")

    def _build_top_bar(self) -> QWidget:
        # Top toolbar inside a horizontal scroll area (translates vertical mouse wheel to horizontal scroll)
        self.top_scroll = HorizontalScrollArea()
        self.top_scroll.setFixedHeight(56)
        self.top_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.top_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.top_scroll.setWidgetResizable(True)
        self.top_scroll.setStyleSheet("""
            QScrollArea {
                background: #14161b;
                border-bottom: 1px solid #232730;
            }
            QScrollBar:horizontal {
                height: 4px;
                background: #14161b;
            }
            QScrollBar::handle:horizontal {
                background: #3d4454;
                border-radius: 2px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #4da3ff;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

        container = QWidget()
        container.setStyleSheet("""
            QToolButton, QPushButton {
                background: #1c1f26;
                color: #e1e4ea;
                border: 1px solid #2d3340;
                border-radius: 6px;
                padding: 5px 11px;
                font-size: 13px;
                font-weight: 500;
            }
            QToolButton:hover, QPushButton:hover {
                background: #272c37;
                border-color: #4da3ff;
            }
            QToolButton:checked {
                background: #0066cc;
                color: #ffffff;
                border-color: #3385ff;
                font-weight: bold;
            }
            QToolButton#snip_btn {
                background: #1a4473;
                color: #ffffff;
                border: 1px solid #2b619e;
                font-size: 13px;
                font-weight: bold;
                padding: 5px 14px;
            }
            QToolButton#snip_btn:hover {
                background: #205691;
                border-color: #4da3ff;
            }
        """)
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(10, 8, 10, 8)
        c_layout.setSpacing(6)

        # ＋ New Snip
        btn_snip = QToolButton()
        btn_snip.setObjectName("snip_btn")
        btn_snip.setText("＋ New Snip")
        btn_snip.setShortcut(QKeySequence("Ctrl+N"))
        btn_snip.setFixedHeight(34)
        btn_snip.clicked.connect(self.start_snip)
        c_layout.addWidget(btn_snip)

        # Separator line
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #232730;")
        c_layout.addWidget(sep1)

        # 10 Tool buttons in a horizontal row
        self.tool_actions = {}
        self.tool_buttons = {}

        for key, label in (("pen", "✏ Pen"), ("highlighter", "🖍 Highlight"),
                           ("arrow", "➶ Arrow"), ("line", "╱ Line"),
                           ("rect", "▭ Rect"), ("ellipse", "⬭ Circle"),
                           ("step", "① Step"), ("text", "🅣 Text"),
                           ("blur", "░ Blur"), ("crop", "⬚ Crop")):
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda checked=False, k=key: self._set_tool(k))
            c_layout.addWidget(btn)
            self.tool_buttons[key] = btn

            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, k=key: self._set_tool(k))
            self.tool_actions[key] = act

        self.tool_buttons["pen"].setChecked(True)
        self.tool_actions["pen"].setChecked(True)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #232730;")
        c_layout.addWidget(sep2)

        # Colors & Width
        self.color_palette = ColorPaletteWidget(self.canvas.color)
        self.color_palette.color_selected.connect(self._on_palette_color_selected)
        c_layout.addWidget(self.color_palette)

        c_layout.addWidget(self._make_width_spin())

        # Separator
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setStyleSheet("color: #232730;")
        c_layout.addWidget(sep3)

        # Undo / Redo
        btn_undo = QPushButton("↶ Undo")
        btn_undo.setToolTip("Undo (Ctrl+Z)")
        btn_undo.setFixedHeight(34)
        btn_undo.clicked.connect(self.canvas.undo)
        c_layout.addWidget(btn_undo)

        btn_redo = QPushButton("↷ Redo")
        btn_redo.setToolTip("Redo (Ctrl+Shift+Z)")
        btn_redo.setFixedHeight(34)
        btn_redo.clicked.connect(self.canvas.redo)
        c_layout.addWidget(btn_redo)

        c_layout.addStretch(1)

        self.top_scroll.setWidget(container)
        return self.top_scroll

    def _build_bottom_bar(self, bottom_bar: QWidget):
        b_layout = QHBoxLayout(bottom_bar)
        b_layout.setContentsMargins(12, 6, 12, 6)
        b_layout.setSpacing(8)

        # Bottom Left: Primary Action Buttons
        self.btn_copy = QPushButton("⧉ Copy (Ctrl+C)")
        self.btn_copy.setObjectName("copy_btn")
        self.btn_copy.setFixedHeight(36)
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        b_layout.addWidget(self.btn_copy)

        self.btn_save = QPushButton("💾 Save (Ctrl+S)")
        self.btn_save.setFixedHeight(36)
        self.btn_save.clicked.connect(self.save_to_file)
        b_layout.addWidget(self.btn_save)

        self.btn_paste = QPushButton("📋 Paste (Ctrl+V)")
        self.btn_paste.setFixedHeight(36)
        self.btn_paste.clicked.connect(self.paste_from_clipboard)
        b_layout.addWidget(self.btn_paste)

        self.btn_discard = QPushButton("✕ Discard (Esc)")
        self.btn_discard.setFixedHeight(36)
        self.btn_discard.clicked.connect(self.discard)
        b_layout.addWidget(self.btn_discard)

        b_layout.addSpacing(12)

        # Center: Status & Helpful Hints
        self._status_label = QLabel("Ctrl+N new snip · Draw, then copy or save")
        self._status_label.setStyleSheet("color: #8e98a8; font-size: 13px;")
        b_layout.addWidget(self._status_label, stretch=1)

        # Bottom Right: Zoom Controls
        btn_zoom_out = QPushButton("－")
        btn_zoom_out.setToolTip("Zoom Out (Ctrl+-)")
        btn_zoom_out.setFixedSize(30, 30)
        btn_zoom_out.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0;")
        btn_zoom_out.clicked.connect(self._zoom_out)
        b_layout.addWidget(btn_zoom_out)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("color: #9aa4b0; font-weight: bold; font-size: 14px; padding: 0 6px;")
        b_layout.addWidget(self._zoom_label)

        btn_zoom_in = QPushButton("＋")
        btn_zoom_in.setToolTip("Zoom In (Ctrl++)")
        btn_zoom_in.setFixedSize(30, 30)
        btn_zoom_in.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0;")
        btn_zoom_in.clicked.connect(self._zoom_in)
        b_layout.addWidget(btn_zoom_in)

        btn_zoom_fit = QPushButton("Fit")
        btn_zoom_fit.setToolTip("Fit to Window (Ctrl+0)")
        btn_zoom_fit.setFixedHeight(30)
        btn_zoom_fit.setStyleSheet("font-size: 12px; font-weight: bold;")
        btn_zoom_fit.clicked.connect(self._zoom_fit)
        b_layout.addWidget(btn_zoom_fit)

        btn_zoom_100 = QPushButton("1:1")
        btn_zoom_100.setToolTip("Actual Size 100% (Ctrl+1)")
        btn_zoom_100.setFixedHeight(30)
        btn_zoom_100.setStyleSheet("font-size: 12px; font-weight: bold;")
        btn_zoom_100.clicked.connect(self._zoom_100)
        b_layout.addWidget(btn_zoom_100)

    def _make_width_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 20)
        spin.setValue(4)
        spin.setPrefix("Width ")
        spin.setFixedHeight(34)
        spin.setStyleSheet("""
            QSpinBox {
                background: #1c1f26;
                color: #e1e4ea;
                border: 1px solid #2d3340;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 13px;
                font-weight: 500;
            }
            QSpinBox:hover {
                border-color: #4da3ff;
            }
        """)
        spin.valueChanged.connect(lambda v: setattr(self.canvas, "pen_width", v))
        return spin

    def _wire_canvas(self):
        self.canvas.copy_requested.connect(self.copy_to_clipboard)
        self.canvas.paste_requested.connect(self.paste_from_clipboard)
        self.canvas.save_requested.connect(self.save_to_file)
        self.canvas.discard_requested.connect(self.discard)
        self.canvas.image_changed.connect(self._on_image_changed)
        self.canvas.zoom_changed.connect(
            lambda z: self._zoom_label.setText(f"{int(round(z * 100))}%"))

    def _zoom_in(self):
        self.canvas.set_zoom(self.canvas.zoom_factor * 1.25)

    def _zoom_out(self):
        self.canvas.set_zoom(self.canvas.zoom_factor / 1.25)

    def _zoom_100(self):
        self.canvas.set_zoom(1.0)

    def _zoom_fit(self):
        img = self.canvas.image()
        if img is None:
            return
        vp = self.scroll.viewport().size()
        vw = max(10, vp.width() - 20)
        vh = max(10, vp.height() - 20)
        scale = min(vw / img.width(), vh / img.height(), 1.0)
        self.canvas.set_zoom(scale)

    def _set_status_text(self, msg: str):
        if hasattr(self, "_status_label"):
            self._status_label.setText(msg)
        self.statusBar().showMessage(msg)

    def _on_image_changed(self):
        has = self.canvas.has_image()
        self._set_status_text(
            "Snip loaded — draw, add text or crop, then click Copy or Ctrl+C"
            if has else
            "Ctrl+N new snip · Ctrl+V paste · Ctrl+Z undo · Ctrl+C copy · Ctrl+S save · Esc discard")

    def _set_tool_and_check(self, tool: str):
        self._set_tool(tool)

    def _set_tool(self, tool: str):
        if tool != "crop" and self.canvas.has_pending_crop():
            self.canvas.cancel_pending()
        self.canvas.tool = tool
        for k, btn in getattr(self, "tool_buttons", {}).items():
            btn.setChecked(k == tool)
        for k, act in getattr(self, "tool_actions", {}).items():
            act.setChecked(k == tool)
        cursors = {"pen": Qt.CursorShape.CrossCursor,
                   "highlighter": Qt.CursorShape.CrossCursor,
                   "arrow": Qt.CursorShape.CrossCursor,
                   "line": Qt.CursorShape.CrossCursor,
                   "rect": Qt.CursorShape.CrossCursor,
                   "ellipse": Qt.CursorShape.CrossCursor,
                   "step": Qt.CursorShape.PointingHandCursor,
                   "blur": Qt.CursorShape.CrossCursor,
                   "text": Qt.CursorShape.IBeamCursor,
                   "crop": Qt.CursorShape.CrossCursor}
        self.canvas.setCursor(cursors.get(tool, Qt.CursorShape.ArrowCursor))
        if tool == "crop":
            self._set_status_text(
                "Drag a crop area, pull the handles to adjust, then ✓ or Enter to apply")
        elif tool == "blur":
            self._set_status_text(
                "Drag a rectangle over sensitive text or details to pixelate")
        elif tool == "highlighter":
            self._set_status_text(
                "Draw over text to highlight with semi-transparent color")
        elif tool == "step":
            self._set_status_text(
                "Click anywhere on the snip to place numbered step badges (①, ②, ③...)")

    def _on_palette_color_selected(self, color: QColor):
        self.canvas.color = color

    def _set_preset_color(self, hex_color: str):
        self.canvas.color = QColor(hex_color)
        if hasattr(self, "color_palette"):
            self.color_palette.set_color(self.canvas.color)

    def _pick_color(self):
        if hasattr(self, "color_palette"):
            self.color_palette._pick_custom()

    # --- snip flow ------------------------------------------------------------

    def start_snip(self, copy_to_clipboard: bool = False,
                   output_path: str | None = None,
                   exit_on_cancel: bool = False):
        self._silent_clipboard = copy_to_clipboard
        self._output_path = output_path
        self._exit_on_cancel = exit_on_cancel
        self.hide()
        # Give the compositor a moment to actually remove our window.
        QTimer.singleShot(350, self._do_capture)

    def capture_fullscreen(self, copy_to_clipboard: bool = False,
                           output_path: str | None = None):
        try:
            image = capture_full_desktop()
        except CaptureError as exc:
            QMessageBox.critical(None, "QuickSnipp", str(exc))
            QApplication.quit()
            return
        if copy_to_clipboard:
            QGuiApplication.clipboard().setImage(image)
        if output_path:
            path = output_path if output_path.lower().endswith(".png") else output_path + ".png"
            image.save(path, "PNG")
        if copy_to_clipboard or output_path:
            QApplication.quit()
        else:
            self.canvas.set_image(image)
            self._restore_window()

    def _do_capture(self):
        try:
            image = capture_full_desktop()
        except CaptureError as exc:
            self.show()
            self.raise_()
            QMessageBox.critical(self, "QuickSnipp", str(exc))
            return
        session = SnipSession(image, parent=self)
        self._session = session
        session.accepted.connect(
            lambda rect: self._on_snip_accepted(image, rect))
        session.canceled.connect(self._on_snip_canceled)
        session.start()

    def _on_snip_accepted(self, image: QImage, rect: QRect):
        self._session = None
        cropped = image.copy(rect)
        if getattr(self, "_silent_clipboard", False):
            QGuiApplication.clipboard().setImage(cropped)
        if getattr(self, "_output_path", None):
            out = self._output_path
            path = out if out.lower().endswith(".png") else out + ".png"
            cropped.save(path, "PNG")
        if getattr(self, "_silent_clipboard", False) or getattr(self, "_output_path", None):
            QApplication.quit()
        else:
            self.canvas.set_image(cropped)
            self._restore_window()

    def _on_snip_canceled(self):
        self._session = None
        if (getattr(self, "_exit_on_cancel", False)
                or getattr(self, "_silent_clipboard", False)
                or getattr(self, "_output_path", None)):
            QApplication.quit()
        else:
            self._restore_window()

    def _restore_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    # --- actions ----------------------------------------------------------------

    def copy_to_clipboard(self):
        img = self.canvas.image()
        if img is None:
            return
        QGuiApplication.clipboard().setImage(img)
        self.statusBar().showMessage("Copied to clipboard", 3000)

    def paste_from_clipboard(self):
        cb = QGuiApplication.clipboard()
        img = cb.image()
        if img is not None and not img.isNull():
            self.canvas.set_image(img)
            self.statusBar().showMessage("Pasted image from clipboard", 3000)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasImage():
            img = QImage(event.mimeData().imageData())
            if not img.isNull():
                self.canvas.set_image(img)
                self.statusBar().showMessage("Loaded dropped image", 3000)
                event.acceptProposedAction()
                return
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                img = QImage(path)
                if not img.isNull():
                    self.canvas.set_image(img)
                    self.statusBar().showMessage(f"Loaded {os.path.basename(path)}", 3000)
                    event.acceptProposedAction()
                    return

    def save_to_file(self):
        img = self.canvas.image()
        if img is None:
            return
        pictures = os.path.expanduser("~/Pictures")
        os.makedirs(pictures, exist_ok=True)
        default = os.path.join(
            pictures, time.strftime("snipp-%Y%m%d-%H%M%S.png"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save snip", default, "PNG image (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if img.save(path, "PNG"):
            self.statusBar().showMessage(f"Saved to {path}", 5000)
        else:
            QMessageBox.warning(self, "QuickSnipp",
                                f"Could not save to {path}")

    def discard(self):
        if self.canvas.cancel_pending():
            return
        self.canvas.set_image(None)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.discard()
            return
        super().keyPressEvent(event)
