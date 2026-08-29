#!/usr/bin/env bash
# Install a .desktop launcher and icon for QuickSnipp (per-user, no sudo).
set -e
cd "$(dirname "$0")"
APP_DIR="$(pwd)"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

# Install custom scalable SVG icon
if [ -f "packaging/io.github.marmarart.QuickSnipp.svg" ]; then
    cp "packaging/io.github.marmarart.QuickSnipp.svg" "$ICON_DIR/io.github.marmarart.QuickSnipp.svg"
    echo "Installed icon to $ICON_DIR/io.github.marmarart.QuickSnipp.svg"
fi

cat > "$DESKTOP_DIR/io.github.marmarart.QuickSnipp.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=QuickSnipp
Comment=Fast snipping tool — capture, annotate, copy
Exec=$APP_DIR/run.sh %U
Icon=io.github.marmarart.QuickSnipp
Terminal=false
Categories=Utility;Graphics;
Keywords=screenshot;snip;capture;snipping;annotate;
StartupNotify=true
EOF

chmod +x "$DESKTOP_DIR/io.github.marmarart.QuickSnipp.desktop"
echo "Installed $DESKTOP_DIR/io.github.marmarart.QuickSnipp.desktop"

# Refresh icon & desktop database if tools are present
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" || true

echo "QuickSnipp should now appear with its custom icon in your app grid."
