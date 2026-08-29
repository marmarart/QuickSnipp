"""Fullscreen selection overlay.

A SnipSession spans all screens: it owns one frameless fullscreen SnipOverlay
widget per screen, all showing the frozen desktop dimmed. The user click-drags
a rectangle anywhere (the drag can cross monitors); release accepts, Esc or
right-click cancels. The accepted rectangle is emitted in image pixel coords.
"""

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class SnipSession(QObject):
    accepted = pyqtSignal(QRect)  # QRect in image pixel coordinates
    canceled = pyqtSignal()

    MIN_SIZE = 4  # logical px; smaller drags are treated as stray clicks

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.image = image
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
            self.repaint_all()
            return
        self._accept(r)

    def confirm(self):
        r = self.selection_virtual()
        if r is not None:
            self._accept(r)

    def cancel_or_reset(self):
        if self.origin is not None:
            self.origin = None
            self.current = None
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

    def _close_overlays(self):
        for o in self._overlays:
            o.close()

    def repaint_all(self):
        for o in self._overlays:
            o.update()


from PyQt6.QtWidgets import QWidget


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

    # --- helpers ----------------------------------------------------------

    def _to_virtual(self, local: QPoint) -> QPoint:
        return self.screen.geometry().topLeft() + local

    # --- events -------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.session.begin(self._to_virtual(event.position().toPoint()))
        elif event.button() == Qt.MouseButton.RightButton:
            self.session.cancel_or_reset()

    def mouseMoveEvent(self, event):
        self.cursor_pos = event.position().toPoint()
        if self.session.origin is not None:
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
                and self.session.origin is not None):
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
        if self.cursor_pos is None:
            return
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.drawLine(0, self.cursor_pos.y(), self.width(), self.cursor_pos.y())
        p.drawLine(self.cursor_pos.x(), 0, self.cursor_pos.x(), self.height())

    def _draw_hint(self, p: QPainter):
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
        if y + 26 > self.height():
            y = target.top() - 34
        box = QRect(max(4, x), max(4, y), w, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 26, 230))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("#4da3ff"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
