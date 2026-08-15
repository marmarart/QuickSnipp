"""QuickSnipp application entry point."""

import sys

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from .editor import EditorWindow

ACCENT = "#4da3ff"

QSS = f"""
QMainWindow, QDialog {{
    background: #1b1e23;
    color: #e6e6e6;
}}
QWidget {{
    font-size: 13px;
}}
QToolBar {{
    background: #22262c;
    border: none;
    border-bottom: 1px solid #111317;
    padding: 6px;
    spacing: 6px;
}}
QToolButton, QPushButton {{
    background: #2b3038;
    color: #e6e6e6;
    border: 1px solid #3a4048;
    border-radius: 6px;
    padding: 6px 12px;
}}
QToolButton:hover, QPushButton:hover {{
    background: #343a44;
    border-color: {ACCENT};
}}
QToolButton:pressed, QPushButton:pressed {{
    background: #262b32;
}}
QToolButton:checked {{
    background: {ACCENT};
    color: #101318;
    border-color: {ACCENT};
    font-weight: bold;
}}
QScrollArea {{
    background: #14161a;
    border: none;
}}
QStatusBar {{
    background: #22262c;
    color: #9aa4b0;
    border-top: 1px solid #111317;
}}
QMenu {{
    background: #22262c;
    color: #e6e6e6;
    border: 1px solid #3a4048;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {ACCENT};
    color: #101318;
}}
QSpinBox, QLineEdit {{
    background: #14161a;
    color: #e6e6e6;
    border: 1px solid #3a4048;
    border-radius: 4px;
    padding: 4px 8px;
}}
QToolTip {{
    background: #22262c;
    color: #e6e6e6;
    border: 1px solid #3a4048;
}}
"""


def apply_dark_palette(app: QApplication):
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#1b1e23"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#e6e6e6"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#14161a"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#e6e6e6"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#2b3038"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#e6e6e6"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#101318"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#5a6472"))
    app.setPalette(pal)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("QuickSnipp")
    app.setOrganizationName("QuickSnipp")
    app.setStyle("Fusion")
    apply_dark_palette(app)
    app.setStyleSheet(QSS)

    window = EditorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
