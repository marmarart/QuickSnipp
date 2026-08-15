"""Editor window: toolbar, canvas, drawing tools, clipboard/save actions."""

import math
import os
import time

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QGuiApplication, QIcon,
                         QImage, QKeySequence, QPainter, QPainterPath, QPen,
                         QPixmap)
from PyQt6.QtWidgets import (QColorDialog, QFileDialog, QInputDialog,
                             QMainWindow, QMenu, QMessageBox, QScrollArea,
                             QSpinBox, QToolBar, QToolButton, QWidget)

from .capture import CaptureError, capture_full_desktop
from .overlay import SnipSession

PEN_WIDTHS = (2, 4, 6, 10)
DEFAULT_COLOR = "#ff4d4d"


class Canvas(QWidget):
    """1:1 image canvas with pen / line / arrow / rect / text / crop tools."""

    MAX_HISTORY = 15

    image_changed = pyqtSignal()
    modified = pyqtSignal()
    copy_requested = pyqtSignal()
    save_requested = pyqtSignal()
    discard_requested = pyqtSignal()

    SHAPE_TOOLS = ("line", "arrow", "rect")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: QImage | None = None
        self.tool = "pen"
        self.color = QColor(DEFAULT_COLOR)
        self.pen_width = 4
        self._stroke: list[QPoint] | None = None
        self._shape_start: QPoint | None = None
        self._shape_end: QPoint | None = None
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
        if clear_history:
            self._undo.clear()
            self._redo.clear()
        self._refresh_size()
        self.update()
        self.image_changed.emit()

    def _refresh_size(self):
        if self._image is None:
            self.setFixedSize(720, 420)
        else:
            self.setFixedSize(self._image.size())

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
            r = self._crop_rect.intersected(self.rect())
            # dim everything outside the crop rect
            shade = QColor(0, 0, 0, 130)
            p.fillRect(QRect(0, 0, self.width(), r.top()), shade)
            p.fillRect(QRect(0, r.bottom() + 1, self.width(),
                             self.height() - r.bottom() - 1), shade)
            p.fillRect(QRect(0, r.top(), r.left(), r.height() + 1), shade)
            p.fillRect(QRect(r.right() + 1, r.top(),
                             self.width() - r.right() - 1, r.height() + 1), shade)
            pen = QPen(QColor("#4da3ff"), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(r)
            p.setPen(QColor("#4da3ff"))
            p.drawText(r.left(), max(14, r.top() - 6),
                       f"{r.width()} × {r.height()}")
            # resize handles (only when not mid-drag)
            if self._crop_mode is None:
                p.setPen(QPen(QColor("#4da3ff"), 1))
                p.setBrush(QColor("#ffffff"))
                for c in self._handle_points(r).values():
                    p.drawRect(QRect(c.x() - 4, c.y() - 4, 8, 8))
        p.end()

    def _pen(self) -> QPen:
        pen = QPen(self.color, self.pen_width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        return pen

    @staticmethod
    def _draw_shape(p: QPainter, tool: str, start: QPoint, end: QPoint):
        if tool == "rect":
            p.drawRect(QRect(start, end).normalized())
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

    # --- mouse handling -------------------------------------------------------

    def mousePressEvent(self, event):
        if self._image is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self.tool == "pen":
            self._stroke = [pos]
            self.update()
        elif self.tool in self.SHAPE_TOOLS:
            self._shape_start = pos
            self._shape_end = pos
            self.update()
        elif self.tool == "crop":
            self._crop_press(pos)
        elif self.tool == "text":
            self._place_text(pos)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._stroke is not None:
            self._stroke.append(pos)
            self.update()
        elif self._shape_start is not None:
            self._shape_end = pos
            self.update()
        elif self._crop_mode is not None:
            self._crop_drag(pos)
        elif self.tool == "crop" and self._crop_rect is not None:
            self._update_crop_cursor(pos)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
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
            self._shape_start = None
            self._shape_end = None
            if start is not None and start != pos:
                self._push_undo()
                p = QPainter(self._image)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(self._pen())
                self._draw_shape(p, self.tool, start, pos)
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
        bounds = self.rect()
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
        for name, center in self._handle_points(self._crop_rect).items():
            if abs(pos.x() - center.x()) <= self.HANDLE_HIT \
                    and abs(pos.y() - center.y()) <= self.HANDLE_HIT:
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
        if self._crop_rect is None:
            return
        r = self._crop_rect
        y = r.bottom() + 8
        if y + 34 > self.height():
            y = r.top() - 38
        y = max(4, y)
        x = min(r.right() - 64, self.width() - 68)
        x = max(4, x)
        self._crop_cancel.move(x, y)
        self._crop_ok.move(x + 34, y)
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
        text, ok = QInputDialog.getText(self, "Add text", "Text:")
        if not ok or not text:
            return
        self._push_undo()
        p = QPainter(self._image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = p.font()
        font.setPixelSize(20 + self.pen_width)
        font.setBold(True)
        p.setFont(font)
        p.setPen(self.color)
        p.drawText(pos, text)
        p.end()
        self.modified.emit()
        self.update()

    def cancel_pending(self) -> bool:
        """Abort any in-progress drag or pending crop. True if one existed."""
        if (self._stroke is not None or self._shape_start is not None
                or self._crop_rect is not None or self._crop_mode is not None):
            self._stroke = None
            self._shape_start = None
            self._shape_end = None
            self._clear_crop()
            self.update()
            return True
        return False

    def has_pending_crop(self) -> bool:
        return self._crop_rect is not None or self._crop_mode is not None

    # --- context menu ---------------------------------------------------------

    def contextMenuEvent(self, event):
        if self._image is None:
            return
        menu = QMenu(self)
        menu.addAction("Copy", QKeySequence("Ctrl+C"), self.copy_requested.emit)
        menu.addAction("Save…", QKeySequence("Ctrl+S"), self.save_requested.emit)
        menu.addSeparator()
        menu.addAction("Discard", self.discard_requested.emit)
        menu.exec(event.globalPos())


class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QuickSnipp")
        self.resize(1024, 700)

        self.canvas = Canvas()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(self.scroll)

        self._session: SnipSession | None = None
        self._build_toolbar()
        self._wire_canvas()
        self.statusBar().showMessage(
            "Ctrl+N new snip · Ctrl+Z undo · Ctrl+C copy · Ctrl+S save · Esc discard")

    # --- UI construction ------------------------------------------------------

    def _build_toolbar(self):
        tb = QToolBar("Tools")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        act_new = QAction("＋ New Snip", self)
        act_new.setShortcut(QKeySequence("Ctrl+N"))
        act_new.triggered.connect(self.start_snip)
        tb.addAction(act_new)
        tb.addSeparator()

        group = QActionGroup(self)
        group.setExclusive(True)
        self.tool_actions = {}
        for key, label in (("pen", "✏ Pen"), ("arrow", "➶ Arrow"),
                           ("line", "╱ Line"), ("rect", "▭ Rect"),
                           ("text", "🅣 Text"), ("crop", "⬚ Crop")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, k=key: self._set_tool(k))
            group.addAction(act)
            tb.addAction(act)
            self.tool_actions[key] = act
        self.tool_actions["pen"].setChecked(True)

        self.color_button = QToolButton()
        self.color_button.setText("Color")
        self.color_button.clicked.connect(self._pick_color)
        tb.addWidget(self.color_button)
        self._update_color_button()

        tb.addWidget(self._make_width_spin())
        tb.addSeparator()

        act_undo = QAction("↶ Undo", self)
        act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        act_undo.triggered.connect(self.canvas.undo)
        tb.addAction(act_undo)

        act_redo = QAction("↷ Redo", self)
        act_redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"),
                               QKeySequence("Ctrl+Y")])
        act_redo.triggered.connect(self.canvas.redo)
        tb.addAction(act_redo)
        tb.addSeparator()

        act_copy = QAction("⧉ Copy", self)
        act_copy.setShortcut(QKeySequence("Ctrl+C"))
        act_copy.triggered.connect(self.copy_to_clipboard)
        tb.addAction(act_copy)

        act_save = QAction("💾 Save", self)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self.save_to_file)
        tb.addAction(act_save)

        act_discard = QAction("✕ Discard", self)
        act_discard.setShortcut(QKeySequence("Esc"))
        act_discard.triggered.connect(self.discard)
        tb.addAction(act_discard)

    def _make_width_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 20)
        spin.setValue(4)
        spin.setPrefix("Width ")
        spin.valueChanged.connect(lambda v: setattr(self.canvas, "pen_width", v))
        return spin

    def _wire_canvas(self):
        self.canvas.copy_requested.connect(self.copy_to_clipboard)
        self.canvas.save_requested.connect(self.save_to_file)
        self.canvas.discard_requested.connect(self.discard)
        self.canvas.image_changed.connect(self._on_image_changed)

    def _on_image_changed(self):
        has = self.canvas.has_image()
        self.statusBar().showMessage(
            "Snip loaded — draw, add text or crop, then Ctrl+C to copy"
            if has else
            "Ctrl+N new snip · Ctrl+Z undo · Ctrl+C copy · Ctrl+S save · Esc discard")

    # --- tools ----------------------------------------------------------------

    def _set_tool(self, tool: str):
        if tool != "crop" and self.canvas.has_pending_crop():
            self.canvas.cancel_pending()
        self.canvas.tool = tool
        cursors = {"pen": Qt.CursorShape.CrossCursor,
                   "arrow": Qt.CursorShape.CrossCursor,
                   "line": Qt.CursorShape.CrossCursor,
                   "rect": Qt.CursorShape.CrossCursor,
                   "text": Qt.CursorShape.IBeamCursor,
                   "crop": Qt.CursorShape.CrossCursor}
        self.canvas.setCursor(cursors.get(tool, Qt.CursorShape.ArrowCursor))
        if tool == "crop":
            self.statusBar().showMessage(
                "Drag a crop area, pull the handles to adjust, then ✓ or Enter to apply")

    def _pick_color(self):
        color = QColorDialog.getColor(self.canvas.color, self, "Pen color")
        if color.isValid():
            self.canvas.color = color
            self._update_color_button()

    def _update_color_button(self):
        pm = QPixmap(16, 16)
        pm.fill(self.canvas.color)
        self.color_button.setIcon(QIcon(pm))

    # --- snip flow ------------------------------------------------------------

    def start_snip(self):
        self.hide()
        # Give the compositor a moment to actually remove our window.
        QTimer.singleShot(350, self._do_capture)

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
        self.canvas.set_image(image.copy(rect))
        self._restore_window()

    def _on_snip_canceled(self):
        self._session = None
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
