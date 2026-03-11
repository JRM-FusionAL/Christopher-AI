#!/usr/bin/env bash
# install.sh - Cross-platform setup for Christopher voice AI
# Works on Linux, macOS, and WSL2 on Windows
# Usage: bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS="$(uname -s)"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Christopher — Local Voice AI Setup  ║"
echo "╚══════════════════════════════════════╝"
echo "  OS: $OS"
echo ""

# ── Python deps ───────────────────────────────────────────────────────────────
echo "▶ Installing Python dependencies..."
pip3 install requests python-dotenv --quiet
echo "  ✅ requests, python-dotenv"

# ── whisper.cpp ───────────────────────────────────────────────────────────────
if [ ! -f "$HOME/whisper.cpp/build/bin/whisper-cli" ]; then
    echo ""
    echo "▶ Building whisper.cpp..."
    cd "$HOME"
    git clone https://github.com/ggerganov/whisper.cpp --depth 1 2>/dev/null || true
    cd whisper.cpp
    cmake -B build -DCMAKE_BUILD_TYPE=Release
    cmake --build build --config Release -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu)"
    bash models/download-ggml-model.sh base.en
    echo "  ✅ whisper.cpp built"
else
    echo "  ✅ whisper.cpp already built"
fi

# ── llama.cpp ─────────────────────────────────────────────────────────────────
if [ ! -f "$HOME/llama.cpp/build/bin/llama-server" ]; then
    echo ""
    echo "▶ Building llama.cpp..."
    cd "$HOME"
    git clone https://github.com/ggerganov/llama.cpp --depth 1 2>/dev/null || true
    cd llama.cpp
    # Build with CUDA if available, otherwise CPU
    if command -v nvcc &> /dev/null; then
        echo "  CUDA detected — building with GPU support"
        cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
    else
        echo "  No CUDA — building CPU only"
        cmake -B build -DCMAKE_BUILD_TYPE=Release
    fi
    cmake --build build --config Release -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu)"
    echo "  ✅ llama.cpp built"
else
    echo "  ✅ llama.cpp already built"
fi

# ── Download 3B model ─────────────────────────────────────────────────────────
MODEL="$HOME/llama.cpp/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
if [ ! -f "$MODEL" ]; then
    echo ""
    echo "▶ Downloading Llama 3.2 3B model (~2GB)..."
    mkdir -p "$HOME/llama.cpp/models"
    wget -q --show-progress \
        "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf" \
        -O "$MODEL"
    echo "  ✅ Model downloaded"
else
    echo "  ✅ Llama 3.2 3B model already present"
fi

# ── Piper TTS ─────────────────────────────────────────────────────────────────
if ! command -v piper &> /dev/null; then
    echo ""
    echo "▶ Installing Piper TTS..."
    pip3 install piper-tts --quiet
    # Download voice model
    mkdir -p "$HOME/piper_models"
    if [ ! -f "$HOME/piper_models/en_US-libritts-high.onnx" ]; then
        BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/libritts/high"
        wget -q --show-progress "$BASE/en_US-libritts-high.onnx" -P "$HOME/piper_models/"
        wget -q "$BASE/en_US-libritts-high.onnx.json" -P "$HOME/piper_models/"
    fi
    echo "  ✅ Piper TTS installed"
else
    echo "  ✅ Piper TTS already installed"
fi

# ── .env ─────────────────────────────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo ""
    echo "▶ Creating .env..."
    cat > "$SCRIPT_DIR/.env" << EOF
LLAMA_SERVER_BIN=$HOME/llama.cpp/build/bin/llama-server
LLAMA_MODEL=$HOME/llama.cpp/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
LLAMA_SERVER_URL=http://localhost:8080
LLAMA_NGL=99
LLAMA_THREADS=4
LLAMA_CTX=2048

WHISPER_BIN=$HOME/whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL=$HOME/whisper.cpp/models/ggml-base.en.bin

PIPER_MODEL=$HOME/piper_models/en_US-libritts-high.onnx
PIPER_CONFIG=$HOME/piper_models/en_US-libritts-high.onnx.json

FUSIONAL_API_KEY=changeme
FUSIONAL_BI_URL=http://localhost:8101
FUSIONAL_API_URL=http://localhost:8102
FUSIONAL_CONTENT_URL=http://localhost:8103

LISTEN_SECONDS=5
EOF
    echo "  ✅ .env created — edit FUSIONAL_API_KEY before running"
else
    echo "  ✅ .env already exists"
fi

# ── systemd service (Linux only) ──────────────────────────────────────────────
if [[ "$OS" == "Linux" ]] && command -v systemctl &>/dev/null; then
    SERVICE_SRC="$SCRIPT_DIR/llama-server.service"
    SERVICE_DST="/etc/systemd/system/llama-server.service"
    if [ -f "$SERVICE_SRC" ] && [ ! -f "$SERVICE_DST" ]; then
        echo ""
        echo "▶ Installing llama-server systemd service..."
        if sudo cp "$SERVICE_SRC" "$SERVICE_DST" && sudo systemctl daemon-reload && sudo systemctl enable llama-server; then
            echo "  ✅ llama-server.service installed and enabled"
            echo "  Start now: sudo systemctl start llama-server"
        else
            echo "  ⚠️  systemd install failed — run manually:"
            echo "      sudo cp llama-server.service /etc/systemd/system/"
            echo "      sudo systemctl daemon-reload && sudo systemctl enable llama-server"
        fi
    elif [ -f "$SERVICE_DST" ]; then
        echo "  ✅ llama-server.service already installed"
    fi
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Setup complete!                     ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "If llama-server.service was installed:"
echo "  sudo systemctl start llama-server     # start now"
echo "  sudo systemctl status llama-server    # check status"
echo ""
echo "Run Christopher (llama-server already running):"
echo "  python3 christopher.py --chat --no-server   # text mode"
echo "  python3 christopher.py --voice --no-server  # voice mode"
echo ""
echo "Or let Christopher manage llama-server itself:"
echo "  python3 christopher.py --chat               # starts llama-server automatically"
echo ""
