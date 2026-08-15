#!/usr/bin/env bash
# Install a .desktop launcher for QuickSnipp (per-user, no sudo).
set -e
cd "$(dirname "$0")"
APP_DIR="$(pwd)"
DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_DIR/quicksnipp.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=QuickSnipp
Comment=Fast snipping tool — capture, annotate, copy
Exec=$APP_DIR/run.sh
Icon=applets-screenshooter
Terminal=false
Categories=Utility;Graphics;
Keywords=screenshot;snip;capture;snipping;
StartupNotify=true
EOF

chmod +x "$DESKTOP_DIR/quicksnipp.desktop"
echo "Installed $DESKTOP_DIR/quicksnipp.desktop"
echo "QuickSnipp should now appear in your app grid (log out/in if it doesn't)."
