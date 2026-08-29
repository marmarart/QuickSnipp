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


import argparse
from PyQt6.QtCore import QTimer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="quicksnipp",
        description="QuickSnipp — fast snipping tool for Linux (Wayland and X11)",
    )
    parser.add_argument(
        "-s", "--snip", action="store_true",
        help="Start interactive snip capture immediately",
    )
    parser.add_argument(
        "-f", "--fullscreen", action="store_true",
        help="Capture fullscreen immediately",
    )
    parser.add_argument(
        "-c", "--clipboard", action="store_true",
        help="Copy captured image directly to clipboard and exit",
    )
    parser.add_argument(
        "-d", "--delay", type=float, default=0.0,
        metavar="SECONDS", help="Delay in seconds before capturing",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        metavar="PATH", help="Save captured image directly to PATH",
    )
    parser.add_argument(
        "-v", "--version", action="version", version="QuickSnipp 1.0.0",
    )

    args = parser.parse_args(argv)

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    app.setApplicationName("QuickSnipp")
    app.setOrganizationName("QuickSnipp")
    app.setStyle("Fusion")
    apply_dark_palette(app)
    app.setStyleSheet(QSS)

    window = EditorWindow()

    delay_ms = max(0, int(args.delay * 1000))

    if args.fullscreen:
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, lambda: window.capture_fullscreen(
                copy_to_clipboard=args.clipboard, output_path=args.output))
        else:
            window.capture_fullscreen(
                copy_to_clipboard=args.clipboard, output_path=args.output)
    elif args.snip or args.clipboard or args.output:
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, lambda: window.start_snip(
                copy_to_clipboard=args.clipboard, output_path=args.output,
                exit_on_cancel=True))
        else:
            window.start_snip(
                copy_to_clipboard=args.clipboard, output_path=args.output,
                exit_on_cancel=True)
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
