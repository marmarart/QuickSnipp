#!/usr/bin/env bash
# Launch QuickSnipp using the project virtualenv.
set -e
cd "$(dirname "$0")"

# When started from the app grid there is no terminal — keep a log.
LOGDIR="${XDG_CACHE_HOME:-$HOME/.cache}/quicksnipp"
mkdir -p "$LOGDIR"
if [[ ! -t 2 ]]; then
    exec 2>>"$LOGDIR/last-launch.log"
    echo "=== $(date -Iseconds) pid=$$ display=${DISPLAY-} wayland=${WAYLAND_DISPLAY-} ===" >&2
fi

if [ ! -x .venv/bin/python ]; then
    echo "Virtualenv missing — creating it..." >&2
    python3 -m venv .venv 2>/dev/null || python3 -m venv --without-pip .venv
    if [ ! -x .venv/bin/pip ]; then
        curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
    fi
    .venv/bin/pip install -r requirements.txt
fi

# Desktop Exec %U can leave empty tokens; argparse would then abort silently.
args=()
for a in "$@"; do
    case "$a" in
        ""|"%U"|"%u"|"%F"|"%f") ;;
        *) args+=("$a") ;;
    esac
done

# Do not use `exec -a`: Python then misses the venv and fails with
# "No module named 'PyQt6'" when launched from the app grid.
exec "$(pwd)/.venv/bin/python" quicksnipp.py "${args[@]}"
