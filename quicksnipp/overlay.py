"""Fullscreen selection overlay.

A SnipSession spans all screens: it owns one frameless fullscreen SnipOverlay
widget per screen, all showing the frozen desktop dimmed. The user click-drags
a rectangle anywhere (the drag can cross monitors).

In snip mode, release accepts. In record mode, release keeps the selection
and shows Record / Cancel; recording starts only after Record (or Enter).
The accepted snip rectangle is emitted in image pixel coords; a confirmed
record region is emitted in virtual (logical) screen coords.
"""

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen
from PyQt6.QtWidgets import QPushButton, QWidget


class SnipSession(QObject):
    accepted = pyqtSignal(QRect)  # QRect in image pixel coordinates
    region_confirmed = pyqtSignal(QRect)  # QRect in virtual logical coords
    canceled = pyqtSignal()

    MIN_SIZE = 4  # logical px; smaller drags are treated as stray clicks

    def __init__(self, image: QImage, parent=None, *, confirm_record: bool = False):
        super().__init__(parent)
        self.image = image
        self.confirm_record = confirm_record
        screens = QGuiApplication.screens()
        self.virtual = screens[0].geometry()
        for s in screens[1:]:
            self.virtual = self.virtual.united(s.geometry())
        self.sx = image.width() / max(1, self.virtual.width())
        self.sy = image.height() / max(1, self.virtual.height())
        self.origin: QPoint | None = None      # virtual logical coords
        self.current: QPoint | None = None
        self._overlays = [_SnipOverlay(self, s) for s in screens]
        self._finished = False
        self._awaiting_confirm = False

    def start(self):
        for o in self._overlays:
            o.showFullScreen()
            o.raise_()

    # --- selection state ------------------------------------------------

    def selection_virtual(self) -> QRect | None:
        if self.origin is None or self.current is None:
            return None
        r = QRect(self.origin, self.current).normalized()
        if r.width() < self.MIN_SIZE or r.height() < self.MIN_SIZE:
            return None
        return r

    def begin(self, vpoint: QPoint):
        self._awaiting_confirm = False
        self._hide_confirm_buttons()
        self.origin = vpoint
        self.current = vpoint
        self.repaint_all()

    def update(self, vpoint: QPoint):
        self.current = vpoint
        self.repaint_all()

    def finish(self, vpoint: QPoint):
        self.current = vpoint
        r = self.selection_virtual()
        if r is None:  # stray click: reset, keep overlay open
            self.origin = self.current = None
            self._awaiting_confirm = False
            self._hide_confirm_buttons()
            self.repaint_all()
            return
        if self.confirm_record:
            self._awaiting_confirm = True
            self._place_confirm_buttons()
            self.repaint_all()
            return
        self._accept(r)

    def confirm(self):
        r = self.selection_virtual()
        if r is None:
            return
        if self.confirm_record:
            self._confirm_record(r)
        else:
            self._accept(r)

    def cancel_or_reset(self):
        if self.origin is not None:
            self.origin = None
            self.current = None
            self._awaiting_confirm = False
            self._hide_confirm_buttons()
            self.repaint_all()
        else:
            self.cancel()

    def cancel(self):
        if self._finished:
            return
        self._finished = True
        self._close_overlays()
        self.canceled.emit()

    # --- internals --------------------------------------------------------

    def _to_image_rect(self, r: QRect) -> QRect:
        tl = r.topLeft() - self.virtual.topLeft()
        return QRect(int(tl.x() * self.sx), int(tl.y() * self.sy),
                     int(r.width() * self.sx), int(r.height() * self.sy))

    def _accept(self, r: QRect):
        if self._finished:
            return
        self._finished = True
        img_rect = self._to_image_rect(r).intersected(self.image.rect())
        self._close_overlays()
        self.accepted.emit(img_rect)

    def _confirm_record(self, r: QRect):
        if self._finished:
            return
        self._finished = True
        virt = r.intersected(self.virtual)
        self._close_overlays()
        self.region_confirmed.emit(virt)

    def _overlay_for_point(self, vpoint: QPoint):
        for o in self._overlays:
            if o.screen.geometry().contains(vpoint):
                return o
        return self._overlays[0] if self._overlays else None

    def _place_confirm_buttons(self):
        sel = self.selection_virtual()
        if sel is None:
            return
        self._hide_confirm_buttons()
        # Prefer below the selection; fall back to above, then to the center.
        anchor = QPoint(sel.center().x(), sel.bottom() + 16)
        if not self.virtual.contains(anchor):
            anchor = QPoint(sel.center().x(), sel.top() - 16)
        overlay = self._overlay_for_point(anchor)
        if overlay is None:
            overlay = self._overlay_for_point(sel.center())
        if overlay is not None:
            overlay.place_confirm_buttons(sel)

    def _hide_confirm_buttons(self):
        for o in self._overlays:
            o.hide_confirm_buttons()

    def _close_overlays(self):
        for o in self._overlays:
            o.close()

    def repaint_all(self):
        for o in self._overlays:
            o.update()


class _SnipOverlay(QWidget):
    """One frameless fullscreen widget per screen."""

    def __init__(self, session: SnipSession, screen):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.session = session
        self.screen = screen
        self.cursor_pos: QPoint | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(screen.geometry())
        self.winId()  # make sure the window handle exists before setScreen
        if self.windowHandle() is not None:
            self.windowHandle().setScreen(screen)

        self._btn_record = QPushButton("●  Record", self)
        self._btn_record.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_record.setFixedHeight(36)
        self._btn_record.setStyleSheet(
            "QPushButton { background: #c62828; color: #ffffff; border: none; "
            "border-radius: 8px; padding: 6px 18px; font-weight: bold; font-size: 14px; }"
            "QPushButton:hover { background: #e53935; }"
        )
        self._btn_record.clicked.connect(self.session.confirm)
        self._btn_record.hide()

        self._btn_cancel = QPushButton("Cancel", self)
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.setFixedHeight(36)
        self._btn_cancel.setStyleSheet(
            "QPushButton { background: #2b3038; color: #e6e6e6; "
            "border: 1px solid #3a4048; border-radius: 8px; padding: 6px 16px; "
            "font-size: 14px; }"
            "QPushButton:hover { background: #343a44; border-color: #4da3ff; }"
        )
        self._btn_cancel.clicked.connect(self.session.cancel)
        self._btn_cancel.hide()

    # --- helpers ----------------------------------------------------------

    def _to_virtual(self, local: QPoint) -> QPoint:
        return self.screen.geometry().topLeft() + local

    def place_confirm_buttons(self, sel: QRect):
        geo = self.screen.geometry()
        visible = sel.intersected(geo)
        if visible.isEmpty():
            return
        local = visible.translated(-geo.topLeft())
        self._btn_record.adjustSize()
        self._btn_cancel.adjustSize()
        rec_w = max(110, self._btn_record.sizeHint().width())
        can_w = max(84, self._btn_cancel.sizeHint().width())
        self._btn_record.setFixedWidth(rec_w)
        self._btn_cancel.setFixedWidth(can_w)
        gap = 8
        total = rec_w + gap + can_w
        x = local.center().x() - total // 2
        y = local.bottom() + 10
        if y + 36 > self.height() - 8:
            y = local.top() - 46
        x = min(max(8, x), self.width() - total - 8)
        y = min(max(8, y), self.height() - 44)
        self._btn_record.move(x, y)
        self._btn_cancel.move(x + rec_w + gap, y)
        self._btn_record.show()
        self._btn_cancel.show()
        self._btn_record.raise_()
        self._btn_cancel.raise_()

    def hide_confirm_buttons(self):
        self._btn_record.hide()
        self._btn_cancel.hide()

    # --- events -------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.session.begin(self._to_virtual(event.position().toPoint()))
        elif event.button() == Qt.MouseButton.RightButton:
            self.session.cancel_or_reset()

    def mouseMoveEvent(self, event):
        self.cursor_pos = event.position().toPoint()
        if self.session.origin is not None and not self.session._awaiting_confirm:
            # While dragging, this widget keeps receiving moves (implicit
            # grab) even when the cursor crosses onto another monitor.
            self.session.update(self._to_virtual(self.cursor_pos))
        else:
            self.update()

    def leaveEvent(self, event):
        self.cursor_pos = None
        self.update()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.session.origin is not None
                and not self.session._awaiting_confirm):
            self.session.finish(self._to_virtual(event.position().toPoint()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.session.cancel_or_reset()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.session.confirm()

    # --- painting -----------------------------------------------------------

    def _image_rect_for(self, virtual_rect: QRect) -> QRect:
        s = self.session
        tl = virtual_rect.topLeft() - s.virtual.topLeft()
        return QRect(int(tl.x() * s.sx), int(tl.y() * s.sy),
                     int(virtual_rect.width() * s.sx),
                     int(virtual_rect.height() * s.sy))

    def paintEvent(self, event):
        s = self.session
        geo = self.screen.geometry()
        p = QPainter(self)

        # Frozen desktop for this screen, dimmed.
        p.drawImage(self.rect(), s.image, self._image_rect_for(geo))
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))

        sel = s.selection_virtual()
        if sel is not None:
            visible = sel.intersected(geo)
            if not visible.isEmpty():
                target = visible.translated(-geo.topLeft())
                # Un-dim the selection by redrawing its image slice.
                p.drawImage(target, s.image, self._image_rect_for(visible))
                p.setPen(QPen(QColor("#4da3ff"), 2))
                p.drawRect(target)
                self._draw_badge(p, target, sel)

        self._draw_crosshair(p)
        if sel is None:
            self._draw_hint(p)
        p.end()

    def _draw_crosshair(self, p: QPainter):
        if self.cursor_pos is None or self.session._awaiting_confirm:
            return
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.drawLine(0, self.cursor_pos.y(), self.width(), self.cursor_pos.y())
        p.drawLine(self.cursor_pos.x(), 0, self.cursor_pos.x(), self.height())

    def _draw_hint(self, p: QPainter):
        if self.session.confirm_record:
            text = "Drag to select the area to record   ·   Esc / right-click to cancel"
        else:
            text = "Drag to select a region   ·   Esc / right-click to cancel"
        p.setFont(QFont("Sans", 11))
        rect = self.rect()
        metrics = p.fontMetrics()
        w = metrics.horizontalAdvance(text) + 32
        box = QRect((rect.width() - w) // 2, 24, w, 34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 26, 220))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QColor("#e6e6e6"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_badge(self, p: QPainter, target: QRect, sel: QRect):
        s = self.session
        text = f"{int(sel.width() * s.sx)} × {int(sel.height() * s.sy)}"
        p.setFont(QFont("Sans", 10))
        metrics = p.fontMetrics()
        w = metrics.horizontalAdvance(text) + 16
        x = min(target.right() - w + 2, self.width() - w - 4)
        y = target.bottom() + 8
        if s._awaiting_confirm:
            # Keep the size badge inside the selection so it doesn't cover Record.
            x = min(target.left() + 6, self.width() - w - 4)
            y = target.top() + 6
        elif y + 26 > self.height():
            y = target.top() - 34
        box = QRect(max(4, x), max(4, y), w, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 26, 230))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("#4da3ff"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
