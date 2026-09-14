#!/usr/bin/env bash
# Same QuickSnipp tree as on an Intel/AMD PC — Raspberry Pi 5 is just ARM64.
# Installs distro PyQt6 + grim + wf-recorder so we do not compile Qt on the Pi.
set -e
cd "$(dirname "$0")/.."

if [ "$(uname -m)" != "aarch64" ] && [ "$(uname -m)" != "arm64" ]; then
    echo "This helper is for 64-bit Raspberry Pi OS / Ubuntu on Pi 5 (aarch64)."
    echo "On an Intel/AMD PC use ./run.sh and ./install.sh only."
    exit 1
fi

echo "Installing packages (needs sudo)…"
sudo apt-get update
sudo apt-get install -y \
    python3 python3-venv python3-pip python3-pyqt6 python3-pyqt6.qtsvg \
    qt6-wayland \
    grim \
    gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-pipewire \
    ffmpeg

if apt-cache show wf-recorder >/dev/null 2>&1; then
    sudo apt-get install -y wf-recorder
else
    echo "Note: wf-recorder is not in this repo. Video needs it:"
    echo "  sudo apt install wf-recorder"
    echo "  or build https://github.com/ammen99/wf-recorder"
fi

echo
echo "Starting QuickSnipp (same commands as on your PC)…"
./run.sh "$@"
