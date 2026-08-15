"""Render the demo video entirely offscreen.

Runs the real EditorWindow with the offscreen platform, drives it with
synthetic mouse events (same code paths as real input) and grabs the window
every 200 ms into /tmp/qs-frames. No desktop content, no portal, fully
deterministic. Stitch with:

    ffmpeg -framerate 5 -i /tmp/qs-frames/f%04d.jpg \
        -c:v libx264 -pix_fmt yuv420p -movflags +faststart docs/demo.mp4
"""

import os
import shutil
import sys

from PyQt6.QtCore import QEvent, QPointF, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QApplication

from quicksnipp.editor import EditorWindow
from quicksnipp.main import QSS, apply_dark_palette

FRAMES_DIR = "/tmp/qs-frames"
GRAB_MS = 200


def mouse(canvas, t, x, y, buttons):
    pos = QPointF(x, y)
    ev = QMouseEvent(t, pos, canvas.mapToGlobal(pos.toPoint()).toPointF(),
                     Qt.MouseButton.LeftButton, buttons,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.postEvent(canvas, ev)


def drag(canvas, x1, y1, x2, y2):
    mouse(canvas, QEvent.Type.MouseButtonPress, x1, y1, Qt.MouseButton.LeftButton)
    steps = 8
    for i in range(1, steps + 1):
        x = x1 + (x2 - x1) * i // steps
        y = y1 + (y2 - y1) * i // steps
        mouse(canvas, QEvent.Type.MouseMove, x, y, Qt.MouseButton.LeftButton)
    mouse(canvas, QEvent.Type.MouseButtonRelease, x2, y2, Qt.MouseButton.NoButton)


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

    shutil.rmtree(FRAMES_DIR, ignore_errors=True)
    os.makedirs(FRAMES_DIR)

    win = EditorWindow()
    win.resize(1280, 800)
    win.canvas.set_image(sample_image())
    win.show()
    canvas = win.canvas

    frame = {"n": 0}

    def grab():
        frame["n"] += 1
        pm = win.grab()
        pm.toImage().save(
            os.path.join(FRAMES_DIR, f"f{frame['n']:04d}.jpg"), "JPG", 88)

    grabber = QTimer()
    grabber.timeout.connect(grab)
    grabber.start(GRAB_MS)

    def step(ms, fn):
        QTimer.singleShot(ms, fn)

    step(600, lambda: win._set_tool("pen"))
    step(900, lambda: drag(canvas, 140, 400, 340, 260))
    step(2400, lambda: win._set_tool("arrow"))
    step(2700, lambda: drag(canvas, 400, 330, 640, 190))
    step(4200, lambda: win._set_tool("rect"))
    step(4500, lambda: drag(canvas, 680, 150, 920, 340))
    step(6000, lambda: win._set_tool("crop"))
    step(6300, lambda: drag(canvas, 90, 90, 870, 480))
    step(7800, lambda: drag(canvas, 870, 480, 950, 540))  # pull br handle
    step(9200, canvas._apply_crop)
    step(10400, canvas.undo)
    step(11400, canvas.redo)
    step(12400, win.copy_to_clipboard)
    step(13200, grab)
    step(13400, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
