# QuickSnipp

A fast snipping tool for Ubuntu (Wayland and X11). Capture any part of the
screen, annotate it, and copy it to the clipboard — nothing is saved unless
you hit **Save**.

## Features

- **＋ New Snip** freezes the screen and lets you click-drag a selection —
  the drag can cross monitors freely.
- Edit before you share:
  - **✏ Pen** & **🖍 Highlighter** (semi-transparent marker).
  - **➶ Arrow**, **╱ Line**, **▭ Rect**, **⬭ Circle**.
  - **① Step** numbers (auto-incrementing ①, ②, ③... badges for tutorials & bug reports).
  - **🅣 Text** (click to type directly on the canvas).
  - **░ Blur / Pixelate** (obfuscate passwords, emails, tokens, and sensitive details).
  - **⬚ Crop** with drag handles and floating confirmation buttons.
- **Angle & shape snapping**: Hold `Shift` while drawing lines/arrows for 45° snapping, or rectangles/circles for 1:1 squares and circles.
- **Quick color palette**: 8 preset swatches + custom color picker and line width selector.
- **Zoom & Pan**: `Ctrl + Scroll` or toolbar buttons to zoom in/out, **Fit to Window** (`Ctrl+0`), and **100% Actual Size** (`Ctrl+1`).
- **Drag & drop and paste**: Paste images from clipboard (`Ctrl+V`) or drop image files onto the editor.
- **Undo/redo** for edits (`Ctrl+Z` / `Ctrl+Shift+Z` or `Ctrl+Y`).
- **Ctrl+C** (or right-click → Copy) copies straight to the clipboard.
- **Ctrl+S** / Save button writes a PNG to `~/Pictures` — only when you ask.
- **Esc** cancels an in-progress drag, resets selection, or discards the snip.
- Dark, minimal UI.

## Requirements

- Python 3.10+ with `venv`
- On Wayland: an XDG desktop portal with the Screenshot interface
  (preinstalled on Ubuntu GNOME and KDE). Optional fallbacks: `grim`
  (wlroots), `spectacle` (KDE), `gnome-screenshot`.

## 🚀 Quick Start (How to Run)

**You do NOT need to uninstall anything!** If you already have it installed or cloned, it will use your updated code immediately.

### Option 1: Run directly from the terminal
Open your terminal in the QuickSnipp folder and run:
```bash
./run.sh
```
*(On first run, this automatically creates the Python environment and installs all requirements).*

---

### Option 2: Add to your Linux App Menu (Recommended)
Run this once:
```bash
./install.sh
```
Now **QuickSnipp** will appear in your application launcher / app grid just like any other Linux app!

---

## ⌨️ How to Set up Global Shortcut (PrintScreen or Super+Shift+S)

You can trigger a snip anytime using your keyboard without opening a terminal or looking for the app.

### On Ubuntu / GNOME:
1. Open **Settings** → **Keyboard** → **View and Customize Shortcuts** (or **Custom Shortcuts**).
2. Scroll to the bottom and click **Custom Shortcuts** → **＋ (Add Shortcut)**.
3. Fill in:
   - **Name:** `QuickSnipp`
   - **Command:** `/absolute/path/to/QuickSnipp/run.sh -s` *(replace with your actual folder path)*
   - **Shortcut:** Press `PrintScreen` (or `Super + Shift + S`)
4. Click **Add**. Now pressing your hotkey instantly starts snipping!

> **Tip (Silent instant clipboard copy):** Change the command to `/path/to/run.sh -c` to take a snip and copy it straight to your clipboard without even opening the editor!

### On KDE Plasma:
1. Open **System Settings** → **Shortcuts** → **Custom Shortcuts**.
2. Click **Edit** → **New** → **Global Shortcut** → **Command/URL**.
3. Set the trigger key (e.g. `PrintScreen`) and the action command to `/path/to/QuickSnipp/run.sh -s`.

---

## 📖 Beginner's Tutorial: How to Use QuickSnipp

### 1. Capture a Snip
- Click **＋ New Snip** (or press `Ctrl+N` or your custom hotkey).
- The screen dims. **Click and drag** a box over whatever you want to capture.
  - *Made a mistake?* Press `Esc` or right-click to cancel the drag and try again.
  - *Want 1:1 square?* Hold `Shift` while dragging.
- Release the mouse — your snip opens in the editor!

### 2. Annotate & Edit
- **✏ Pen & 🖍 Highlighter:** Draw freehand or highlight text with translucent color.
- **➶ Arrow & ╱ Line:** Point to things (hold `Shift` for straight 45° angles).
- **▭ Rect & ⬭ Circle:** Draw boxes or circles around items.
- **① Step Badges:** Click anywhere to drop auto-incrementing numbered pins (①, ②, ③...).
- **░ Blur / Pixelate:** Drag a box over passwords, emails, or sensitive info to hide them.
- **🅣 Text:** Click on the image and type directly. Press `Enter` to place.
- **⬚ Crop:** Drag to adjust the crop box and click **✓** (or press `Enter`) to apply.
- **Colors & Width:** Click any of the quick color swatches or change the line width.
- **Zoom:** Use `Ctrl + MouseWheel`, **＋ / －**, **Fit** (`Ctrl+0`), or **1:1** (`Ctrl+1`).

### 3. Share or Save
- **Ctrl+C** (or click **⧉ Copy**): Copies directly to your clipboard so you can paste (`Ctrl+V`) into Discord, Slack, Telegram, WhatsApp, Email, or Docs.
- **Ctrl+S** (or click **💾 Save**): Saves a PNG image file to your `~/Pictures` folder.
- **Paste existing images:** Press `Ctrl+V` or drag-and-drop any image file into QuickSnipp to annotate it.
- **Esc** (or **✕ Discard**): Throws the current snip away. Nothing is ever saved to disk unless you hit Save!

---

## 🛠️ Command-Line Options

| Command | What it does |
|---|---|
| `./run.sh` | Launch the editor window |
| `./run.sh -s` | Start snip selection overlay immediately |
| `./run.sh -f` | Capture fullscreen immediately |
| `./run.sh -c` | Capture snip & copy directly to clipboard (silent mode) |
| `./run.sh -d 3 -s` | Wait 3 seconds before capturing (great for tooltips & menus) |
| `./run.sh -o shot.png` | Capture and save directly to `shot.png` |

---

## ⌨️ Full Shortcut Cheat Sheet

| Shortcut | Action |
|---|---|
| `Ctrl+N` | New snip |
| `Ctrl+V` | Paste image from clipboard |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` / `Ctrl+Y` | Redo |
| `Ctrl+C` | Copy to clipboard |
| `Ctrl+S` | Save as PNG |
| `Ctrl + Scroll` | Zoom in / Zoom out |
| `Ctrl++` / `Ctrl+=` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Ctrl+0` | Fit to window |
| `Ctrl+1` | Actual size (100%) |
| `Shift` (hold) | Snap angles to 45° / constrain 1:1 squares & circles |
| `Esc` | Cancel current action / discard |

---

## 🗑️ How to Uninstall (If you ever want to)

Since QuickSnipp is lightweight and clean, uninstalling is as simple as removing the desktop launcher:
```bash
rm -f ~/.local/share/applications/io.github.marmarart.QuickSnipp.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/io.github.marmarart.QuickSnipp.svg
```
And then delete the project folder. No hidden background services or system bloat are left behind.

---

## Running Tests

```bash
.venv/bin/python -m unittest discover -s tests
```

---

## 💡 Notes

- The first capture on GNOME Wayland may show a brief one-time system prompt or screen flash depending on your GNOME version.
- **Flatpak on GNOME:** Silent screenshots require a one-time permission grant. If the first snip fails, enable it in GNOME Settings → Apps → QuickSnipp → Screenshots, or run:
  ```bash
  flatpak permission-set screenshot screenshot io.github.marmarart.QuickSnipp yes
  ```
- Snips live only in memory until you press **Save**.
