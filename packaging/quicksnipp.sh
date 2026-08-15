#!/bin/sh
# QuickSnipp launcher inside the Flatpak sandbox.
export PYTHONPATH="/app/share/quicksnipp${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m quicksnipp.main "$@"
