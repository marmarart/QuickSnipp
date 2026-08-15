#!/usr/bin/env bash
# Launch QuickSnipp using the project virtualenv.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "Virtualenv missing — creating it..."
    python3 -m venv .venv 2>/dev/null || python3 -m venv --without-pip .venv
    if [ ! -x .venv/bin/pip ]; then
        curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
    fi
    .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python quicksnipp.py "$@"
