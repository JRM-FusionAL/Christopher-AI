#!/usr/bin/env bash
# voice_ai.sh - Backward-compatible wrapper for Christopher voice mode.
# Model selection now lives in christopher.py + .env so benchmarking and day-to-day
# runs use the same runtime path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/christopher.py" --voice "$@"
