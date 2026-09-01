"""Render docs/screenshot.png entirely offscreen.

Runs the real EditorWindow with the offscreen platform, drives it with
synthetic mouse events (same code paths as real input), draws a few
annotations with different tools, leaves a pending crop selection visible
(handles + confirm button), then grabs the window once into
docs/screenshot.png.
"""

import sys

from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QApplication

from quicksnipp.editor import EditorWindow
from quicksnipp.main import QSS, apply_dark_palette

OUT = "docs/screenshot.png"


def mouse(canvas, t, x, y, buttons):
    pos = QPointF(x, y)
    ev = QMouseEvent(t, pos, canvas.mapToGlobal(pos.toPoint()).toPointF(),
                     Qt.MouseButton.LeftButton, buttons,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.postEvent(canvas, ev)


def drag(canvas, x1, y1, x2, y2):
    mouse(canvas, QEvent.Type.MouseButtonPress, x1, y1, Qt.MouseButton.LeftButton)
    steps = 10
    for i in range(1, steps + 1):
        x = x1 + (x2 - x1) * i // steps
        y = y1 + (y2 - y1) * i // steps
        mouse(canvas, QEvent.Type.MouseMove, x, y, Qt.MouseButton.LeftButton)
    mouse(canvas, QEvent.Type.MouseButtonRelease, x2, y2, Qt.MouseButton.NoButton)


def click(canvas, x, y):
    mouse(canvas, QEvent.Type.MouseButtonPress, x, y, Qt.MouseButton.LeftButton)
    mouse(canvas, QEvent.Type.MouseButtonRelease, x, y, Qt.MouseButton.NoButton)


def sample_image():
    img = QImage(1000, 560, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    for y in range(560):
        p.setPen(QColor(40 + y // 9, 90 + y // 7, 165))
        p.drawLine(0, y, 1000, y)
    p.setPen(QPen(QColor(255, 255, 255, 60), 2))
    for x in range(0, 1000, 125):
        p.drawLine(x, 0, x, 560)
    p.end()
    return img


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_dark_palette(app)
    app.setStyleSheet(QSS)

    win = EditorWindow()
    win.resize(1280, 800)
    win.canvas.set_image(sample_image())
    win.show()
    canvas = win.canvas

    def step(ms, fn):
        QTimer.singleShot(ms, fn)

    step(600, lambda: win._set_tool("pen"))
    step(900, lambda: drag(canvas, 140, 400, 340, 260))
    step(2200, lambda: win._set_tool("highlighter"))
    step(2500, lambda: drag(canvas, 420, 470, 700, 430))
    step(3800, lambda: win._set_tool("arrow"))
    step(4100, lambda: drag(canvas, 400, 330, 640, 190))
    step(5400, lambda: win._set_tool("rect"))
    step(5700, lambda: drag(canvas, 680, 150, 920, 340))
    step(7000, lambda: win._set_tool("ellipse"))
    step(7300, lambda: drag(canvas, 150, 120, 320, 250))
    step(8600, lambda: win._set_tool("step"))
    step(8900, lambda: click(canvas, 240, 180))
    step(10200, lambda: click(canvas, 760, 210))
    step(11500, lambda: win._set_tool("crop"))
    step(11800, lambda: drag(canvas, 90, 90, 950, 500))  # leave pending crop
    step(13000, lambda: win.grab().toImage().save(OUT, "PNG"))
    step(13400, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
