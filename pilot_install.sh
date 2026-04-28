#!/usr/bin/env bash
# pilot_install.sh — Single-command bootstrap for Christopher pilot voice environments.
#
# Usage:  bash pilot_install.sh [--dry-run]
#
# What this script does:
#   1. Checks all required host dependencies and exits with actionable errors.
#   2. Builds whisper.cpp and llama.cpp from source (skip if already present).
#   3. Downloads the default Llama 3.2 3B GGUF model.
#   4. Installs Piper TTS and downloads the libritts-high voice model.
#   5. Writes a starter .env if one does not exist.
#   6. Installs the llama-server systemd service on Linux hosts.
#
# Supported host configurations:
#   - Ubuntu 22.04 / 24.04 (bare-metal or WSL2)
#   - Debian 12
#   - macOS 13+ (Apple Silicon or x86_64)
#   - Any POSIX host with bash ≥ 4, cmake ≥ 3.18, python3 ≥ 3.9
#
# See docs/pilot-setup-guide.md for full walkthrough and troubleshooting.

set -euo pipefail

# ── Script globals ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS="$(uname -s)"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

# ── Helpers ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YEL='\033[0;33m'
GRN='\033[0;32m'
NC='\033[0m'   # no colour

info()  { echo -e "  ${GRN}✓${NC}  $*"; }
warn()  { echo -e "  ${YEL}⚠${NC}  $*"; }
error() { echo -e "  ${RED}✗${NC}  $*" >&2; }
header(){ echo; echo "── $* ──"; }

# Accumulate failures so we can report them all at once.
MISSING_TOOLS=()

require_cmd() {
  local cmd="$1"
  local hint="${2:-}"
  if ! command -v "$cmd" &>/dev/null; then
    MISSING_TOOLS+=("$cmd${hint:+  ($hint)}")
  fi
}

require_python_version() {
  if command -v python3 &>/dev/null; then
    if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
      MISSING_TOOLS+=("python3 >= 3.9  (found $(python3 --version 2>&1))")
    fi
  fi
}

require_cmake_version() {
  if command -v cmake &>/dev/null; then
    if ! cmake --version 2>/dev/null | awk 'NR==1 {
      split($3, v, "."); if (v[1]+0 < 3 || (v[1]+0 == 3 && v[2]+0 < 18)) exit 1
    }'; then
      MISSING_TOOLS+=("cmake >= 3.18  (found $(cmake --version | head -1))")
    fi
  fi
}

abort_if_missing() {
  if [[ ${#MISSING_TOOLS[@]} -gt 0 ]]; then
    echo >&2
    error "Prerequisites not met. Install the following before re-running:"
    echo >&2
    for item in "${MISSING_TOOLS[@]}"; do
      echo -e "    ${RED}•${NC} $item" >&2
    done
    echo >&2
    echo "  Quick-fix:" >&2
    if [[ "$OS" == "Linux" ]]; then
      echo "    sudo apt update && sudo apt install -y git cmake python3 python3-pip \\" >&2
      echo "        wget ffmpeg alsa-utils pulseaudio-utils build-essential" >&2
    elif [[ "$OS" == "Darwin" ]]; then
      echo "    brew install git cmake python3 wget ffmpeg" >&2
    fi
    echo >&2
    echo "  See docs/pilot-setup-guide.md → 'Host Requirements' for full details." >&2
    echo >&2
    exit 1
  fi
}

run() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# ── Banner ─────────────────────────────────────────────────────────────────────
echo
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Christopher — Pilot Voice Environment Installer   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo "  OS  : $OS"
echo "  DIR : $SCRIPT_DIR"
[[ "$DRY_RUN" == "true" ]] && echo "  MODE: DRY RUN — nothing will be installed"
echo

# ── 1. Prerequisite check ──────────────────────────────────────────────────────
header "Step 1 of 6: Checking prerequisites"

require_cmd git     "install: sudo apt install git  OR  brew install git"
require_cmd cmake   "install: sudo apt install cmake  OR  brew install cmake"
require_cmd python3 "install: sudo apt install python3  OR  brew install python3"
require_cmd pip3    "install: sudo apt install python3-pip"
require_cmd make    "install: sudo apt install build-essential"

# At least one download tool
if ! command -v wget &>/dev/null && ! command -v curl &>/dev/null; then
  MISSING_TOOLS+=("wget or curl  (install: sudo apt install wget)")
fi

require_cmake_version
require_python_version

abort_if_missing

info "git      $(git --version | head -1)"
info "cmake    $(cmake --version | head -1)"
info "python3  $(python3 --version)"
info "pip3     $(pip3 --version | cut -d' ' -f1-2)"
info "make     $(make --version | head -1)"

# Optional but recommended
if command -v ffmpeg &>/dev/null; then
  info "ffmpeg   $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
else
  warn "ffmpeg not found — wav conversion may be limited (sudo apt install ffmpeg)"
fi
if command -v nvcc &>/dev/null; then
  info "nvcc     $(nvcc --version | tail -1)  ← CUDA GPU build will be enabled"
else
  warn "nvcc not found — llama.cpp will be built CPU-only"
fi

# ── 2. Python dependencies ─────────────────────────────────────────────────────
header "Step 2 of 6: Python dependencies"
echo "  Installing requests and python-dotenv..."
run pip3 install requests python-dotenv --quiet --break-system-packages
info "requests, python-dotenv"

# ── 3. whisper.cpp ─────────────────────────────────────────────────────────────
header "Step 3 of 6: whisper.cpp"

WHISPER_CLI="$HOME/whisper.cpp/build/bin/whisper-cli"
if [[ -x "$WHISPER_CLI" ]]; then
  info "whisper.cpp already built at $WHISPER_CLI"
else
  echo "  Cloning and building whisper.cpp..."
  run git -C "$HOME" clone https://github.com/ggerganov/whisper.cpp --depth 1 2>/dev/null || true
  if [[ "$DRY_RUN" == "false" ]]; then
    cd "$HOME/whisper.cpp"
    cmake -B build -DCMAKE_BUILD_TYPE=Release -Wno-dev
    cmake --build build --config Release -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu)"
    bash models/download-ggml-model.sh base.en
    cd "$SCRIPT_DIR"
  fi
  info "whisper.cpp built"
fi

# ── 4. llama.cpp ──────────────────────────────────────────────────────────────
header "Step 4 of 6: llama.cpp"

LLAMA_SERVER="$HOME/llama.cpp/build/bin/llama-server"
if [[ -x "$LLAMA_SERVER" ]]; then
  info "llama.cpp already built at $LLAMA_SERVER"
else
  echo "  Cloning and building llama.cpp (this takes a few minutes)..."
  run git -C "$HOME" clone https://github.com/ggerganov/llama.cpp --depth 1 2>/dev/null || true
  if [[ "$DRY_RUN" == "false" ]]; then
    cd "$HOME/llama.cpp"
    if command -v nvcc &>/dev/null; then
      echo "  CUDA detected — enabling GPU layers"
      cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release -Wno-dev
    else
      cmake -B build -DCMAKE_BUILD_TYPE=Release -Wno-dev
    fi
    cmake --build build --config Release -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu)"
    cd "$SCRIPT_DIR"
  fi
  info "llama.cpp built"
fi

# Download Llama 3.2 3B model
MODEL_PATH="$HOME/llama.cpp/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
if [[ -f "$MODEL_PATH" ]]; then
  info "Llama 3.2 3B model already present"
else
  echo "  Downloading Llama 3.2 3B Q4_K_M model (~2 GB)..."
  run mkdir -p "$HOME/llama.cpp/models"
  LLAMA_URL="https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
  if [[ "$DRY_RUN" == "false" ]]; then
    if command -v wget &>/dev/null; then
      wget -q --show-progress "$LLAMA_URL" -O "$MODEL_PATH"
    else
      curl -L --progress-bar "$LLAMA_URL" -o "$MODEL_PATH"
    fi
  fi
  info "Llama 3.2 3B model downloaded"
fi

# ── 5. Piper TTS ───────────────────────────────────────────────────────────────
header "Step 5 of 6: Piper TTS"

PIPER_MODEL_DIR="$HOME/piper_models"
PIPER_ONNX="$PIPER_MODEL_DIR/en_US-libritts-high.onnx"

if command -v piper &>/dev/null && [[ -f "$PIPER_ONNX" ]]; then
  info "Piper TTS already installed with voice model"
else
  echo "  Installing Piper TTS..."
  run pip3 install piper-tts --quiet --break-system-packages
  run mkdir -p "$PIPER_MODEL_DIR"
  if [[ ! -f "$PIPER_ONNX" ]]; then
    echo "  Downloading Piper libritts-high voice model..."
    PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/libritts/high"
    if [[ "$DRY_RUN" == "false" ]]; then
      if command -v wget &>/dev/null; then
        wget -q --show-progress "${PIPER_BASE}/en_US-libritts-high.onnx"      -P "$PIPER_MODEL_DIR/"
        wget -q --show-progress "${PIPER_BASE}/en_US-libritts-high.onnx.json" -P "$PIPER_MODEL_DIR/"
      else
        curl -L --progress-bar "${PIPER_BASE}/en_US-libritts-high.onnx"     -o "$PIPER_ONNX"
        curl -sL "${PIPER_BASE}/en_US-libritts-high.onnx.json" -o "${PIPER_ONNX}.json"
      fi
    fi
  fi
  info "Piper TTS installed"
fi

# ── 6. .env ────────────────────────────────────────────────────────────────────
header "Step 6 of 6: Environment configuration (.env)"

ENV_FILE="$SCRIPT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  info ".env already exists — skipping (no changes made)"
else
  if [[ "$DRY_RUN" == "false" ]]; then
    cat > "$ENV_FILE" << EOF
# Christopher — auto-generated by pilot_install.sh
# Edit FUSIONAL_API_KEY before running Christopher.

MODEL_PROFILE=llama32-3b

LLAMA_SERVER_BIN=$HOME/llama.cpp/build/bin/llama-server
# Leave blank to use MODEL_PROFILE path below; or set an explicit gguf path here.
LLAMA_MODEL=
LLAMA_MODEL_LLAMA32_3B=$HOME/llama.cpp/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
# Fill in if you download additional models:
LLAMA_MODEL_QWEN25_3B=
LLAMA_MODEL_MISTRAL_7B=

LLAMA_SERVER_URL=http://localhost:8080
# GPU layers to offload. Leave empty to use profile defaults (99 for 3B, 28 for 7B).
LLAMA_NGL=
LLAMA_THREADS=4
# Context window in tokens. Leave empty to use profile defaults.
LLAMA_CTX=

WHISPER_BIN=$HOME/whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL=$HOME/whisper.cpp/models/ggml-base.en.bin

PIPER_MODEL=$PIPER_MODEL_DIR/en_US-libritts-high.onnx
PIPER_CONFIG=$PIPER_MODEL_DIR/en_US-libritts-high.onnx.json

FUSIONAL_API_KEY=changeme
FUSIONAL_BI_URL=http://localhost:8101
FUSIONAL_API_URL=http://localhost:8102
FUSIONAL_CONTENT_URL=http://localhost:8103

LISTEN_SECONDS=5
EOF
  fi
  info ".env created — edit FUSIONAL_API_KEY before running Christopher"
fi

# ── systemd service (Linux only) ──────────────────────────────────────────────
if [[ "$OS" == "Linux" ]] && command -v systemctl &>/dev/null; then
  SERVICE_SRC="$SCRIPT_DIR/llama-server.service"
  SERVICE_DST="/etc/systemd/system/llama-server.service"
  if [[ -f "$SERVICE_SRC" && ! -f "$SERVICE_DST" ]]; then
    echo
    echo "  Installing llama-server systemd service..."
    if [[ "$DRY_RUN" == "false" ]]; then
      if sudo cp "$SERVICE_SRC" "$SERVICE_DST" \
          && sudo systemctl daemon-reload \
          && sudo systemctl enable llama-server 2>/dev/null; then
        info "llama-server.service installed and enabled"
      else
        warn "systemd install failed — run manually:"
        warn "  sudo cp llama-server.service /etc/systemd/system/"
        warn "  sudo systemctl daemon-reload && sudo systemctl enable llama-server"
      fi
    else
      info "[dry-run] llama-server.service would be installed"
    fi
  elif [[ -f "$SERVICE_DST" ]]; then
    info "llama-server.service already installed"
  fi
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Pilot install complete!                           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo
echo "Next steps:"
echo
echo "  1. Run the voice health check:"
echo "       bash preflight_voice.sh"
echo
echo "  2. Start Christopher in text mode (quick test):"
echo "       python3 christopher.py --chat"
echo
echo "  3. Start Christopher in voice mode:"
echo "       python3 christopher.py --voice"
echo
echo "  4. Optional — set FUSIONAL_API_KEY in .env if using MCP tools:"
echo "       \$EDITOR .env"
echo
echo "  See docs/pilot-setup-guide.md for full configuration options."
echo
