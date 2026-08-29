"""Unit and GUI tests for QuickSnipp."""

import os
import unittest

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

# Ensure offscreen Qt platform for testing in headless/CI environments
os.environ["QT_QPA_PLATFORM"] = "offscreen"

app = QApplication.instance() or QApplication([])

from quicksnipp.editor import Canvas, EditorWindow, _snap_point
from quicksnipp.main import main


class TestQuickSnipp(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        # Create a 200x200 solid test image
        img = QImage(200, 200, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("#ffffff"))
        self.canvas.set_image(img)

    def test_initial_state(self):
        self.assertTrue(self.canvas.has_image())
        self.assertEqual(self.canvas.tool, "pen")
        self.assertEqual(self.canvas.pen_width, 4)
        self.assertEqual(self.canvas.step_counter, 1)
        self.assertEqual(self.canvas.zoom_factor, 1.0)

    def test_zoom_functionality(self):
        self.canvas.set_zoom(2.0)
        self.assertEqual(self.canvas.zoom_factor, 2.0)
        self.assertEqual(self.canvas.width(), 400)
        self.assertEqual(self.canvas.height(), 400)

        # Coordinate conversion under zoom
        screen_pt = QPoint(100, 100)
        img_pt = self.canvas._to_image_point(screen_pt)
        self.assertEqual(img_pt, QPoint(50, 50))

        # Reset zoom
        self.canvas.set_zoom(1.0)
        self.assertEqual(self.canvas.zoom_factor, 1.0)
        self.assertEqual(self.canvas.width(), 200)

    def test_step_badge_tool(self):
        self.assertEqual(self.canvas.step_counter, 1)
        self.canvas.tool = "step"
        self.canvas._place_step_badge(QPoint(50, 50))
        self.assertEqual(self.canvas.step_counter, 2)
        self.canvas._place_step_badge(QPoint(80, 80))
        self.assertEqual(self.canvas.step_counter, 3)

        # Test Undo
        self.canvas.undo()
        self.assertEqual(len(self.canvas._undo), 1)

    def test_blur_pixelate_tool(self):
        # Draw a black square at center
        img = self.canvas.image()
        for x in range(80, 120):
            for y in range(80, 120):
                img.setPixelColor(x, y, QColor("#000000"))

        # Apply blur on the area
        self.canvas._apply_blur(QRect(70, 70, 60, 60))
        self.assertTrue(self.canvas.has_image())
        self.assertEqual(len(self.canvas._undo), 1)

    def test_snap_point_helper(self):
        start = QPoint(100, 100)

        # Line snapping to 45 deg
        pos = QPoint(150, 148)  # close to 45 deg
        snapped = _snap_point(start, pos, "line", shift_held=True)
        self.assertAlmostEqual(snapped.x() - 100, snapped.y() - 100, delta=2)

        # Rect snapping to 1:1 square
        rect_pos = QPoint(180, 130)
        snapped_rect = _snap_point(start, rect_pos, "rect", shift_held=True)
        dx = abs(snapped_rect.x() - 100)
        dy = abs(snapped_rect.y() - 100)
        self.assertEqual(dx, dy)

    def test_crop_tool(self):
        self.canvas._crop_rect = QRect(20, 20, 100, 100)
        self.canvas._apply_crop()
        self.assertEqual(self.canvas.image().width(), 100)
        self.assertEqual(self.canvas.image().height(), 100)

        # Test undo restores original size
        self.canvas.undo()
        self.assertEqual(self.canvas.image().width(), 200)
        self.assertEqual(self.canvas.image().height(), 200)

    def test_editor_window_tools(self):
        win = EditorWindow()
        win.canvas.set_image(self.canvas.image())
        self.assertIn("pen", win.tool_actions)
        self.assertIn("highlighter", win.tool_actions)
        self.assertIn("blur", win.tool_actions)
        self.assertIn("step", win.tool_actions)
        self.assertIn("ellipse", win.tool_actions)

        # Test color change
        win._set_preset_color("#ffea00")
        self.assertEqual(win.canvas.color.name(), "#ffea00")

        # Test tool switch
        win._set_tool("highlighter")
        self.assertEqual(win.canvas.tool, "highlighter")


if __name__ == "__main__":
    unittest.main()
