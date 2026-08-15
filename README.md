# QuickSnipp

A fast snipping tool for Ubuntu (Wayland and X11). Capture any part of the
screen, annotate it, and copy it to the clipboard — nothing is saved unless
you hit **Save**.

## Features

- **＋ New Snip** freezes the screen and lets you click-drag a selection —
  the drag can cross monitors freely.
- Edit before you share: **pen**, **arrow**, **line**, **rectangle**,
  **text**, **crop** (color + width apply to all drawing tools).
- **Undo/redo** for the last 15 edits (`Ctrl+Z` / `Ctrl+Shift+Z` or `Ctrl+Y`).
- **Ctrl+C** (or right-click → Copy) copies straight to the clipboard.
- **Ctrl+S** / Save button writes a PNG to `~/Pictures` — only when you ask.
- **Esc** cancels an in-progress drag, then discards the snip — nothing is
  saved unless you hit Save.
- Dark, minimal UI.

## Requirements

- Python 3.10+ with `venv`
- On Wayland: an XDG desktop portal with the Screenshot interface
  (preinstalled on Ubuntu GNOME and KDE). Optional fallbacks: `grim`
  (wlroots), `spectacle` (KDE), `gnome-screenshot`.

## Setup & run

```bash
./run.sh          # creates .venv and installs PyQt6 on first run
```

or manually:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python quicksnipp.py
```

## Usage

1. Click **＋ New Snip** (`Ctrl+N`). The screen freezes with a dim overlay.
2. Drag a rectangle around what you want; release to capture.
   - `Esc` or right-click cancels; `Enter` accepts the current selection.
3. Annotate in the editor: pen, arrow, line, rectangle, text (click where it
   should go). For **crop**, drag a rectangle, pull the handles or drag inside
   to adjust it, then click the floating **✓** button (or press `Enter`) to
   apply — **✕** / `Esc` cancels. Made a mistake? `Ctrl+Z` undoes,
   `Ctrl+Shift+Z` redoes.
4. `Ctrl+C` to copy, **Save** to keep a PNG, **Discard** to throw it away.

## Shortcuts

| Key            | Action                        |
|----------------|-------------------------------|
| `Ctrl+N`       | New snip                      |
| `Ctrl+Z`       | Undo                          |
| `Ctrl+Shift+Z` / `Ctrl+Y` | Redo               |
| `Ctrl+C`       | Copy                          |
| `Ctrl+S`       | Save PNG                      |
| `Esc`          | Cancel drag / discard         |

## Optional: app launcher

`install.sh` creates a `~/.local/share/applications/quicksnipp.desktop`
entry so QuickSnipp shows up in your app grid:

```bash
./install.sh
```

## Notes

- The first capture on GNOME Wayland may show a one-time system prompt or
  brief screen flash, depending on your GNOME version.
- **Flatpak on GNOME:** silent screenshots require a one-time permission
  grant. If the first snip fails, enable it in GNOME Settings → Apps →
  QuickSnipp → Screenshots, or run:
  `flatpak permission-set screenshot screenshot io.github.marmarart.QuickSnipp yes`
- Snips live only in memory until you press **Save**.
