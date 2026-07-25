#!/usr/bin/env bash
# voice_ai.sh - Christopher voice mode.
# Activates the project venv, clears PYTHONPATH to avoid Hermes env bleed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate project virtualenv
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/venv/bin/activate"
fi

# Clear PYTHONPATH to avoid broken numpy from Hermes agent env
export PYTHONPATH=""

exec python3 "$SCRIPT_DIR/christopher.py" --voice "$@"
