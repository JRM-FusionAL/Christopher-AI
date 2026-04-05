# Pilot Setup Guide — Christopher Voice AI

This guide walks through setting up a **local/private Christopher voice pilot**
using `pilot_install.sh` — a single-command bootstrap that validates all
dependencies before it touches your system.

---

## Quick Start

```bash
git clone https://github.com/JRM-FusionAL/Christopher-AI
cd Christopher-AI
bash pilot_install.sh
```

Run a health check after setup:

```bash
bash preflight_voice.sh
```

Then launch Christopher:

```bash
python3 christopher.py --voice      # voice mode
python3 christopher.py --chat       # text mode (no mic required)
```

---

## Installer Flow

```
pilot_install.sh
│
├── Step 1 — Prerequisite check
│     Fails fast with actionable error messages if anything is missing.
│
├── Step 2 — Python dependencies (requests, python-dotenv)
│
├── Step 3 — whisper.cpp
│     Clones from GitHub, compiles, downloads ggml-base.en model.
│     Skipped if ~/whisper.cpp/build/bin/whisper-cli already exists.
│
├── Step 4 — llama.cpp + Llama 3.2 3B model
│     Clones from GitHub, compiles with CUDA if nvcc is detected.
│     Downloads Llama-3.2-3B-Instruct-Q4_K_M.gguf (~2 GB) from HuggingFace.
│     Skipped if binary + model already present.
│
├── Step 5 — Piper TTS
│     pip-installs piper-tts.
│     Downloads en_US-libritts-high.onnx voice model from HuggingFace.
│     Skipped if piper command exists and model is present.
│
├── Step 6 — .env
│     Writes a starter .env with correct paths.
│     Skipped if .env already exists.
│
└── (Linux only) installs llama-server.service into systemd.
```

### Dry Run

Pass `--dry-run` to see what would happen without changing your system:

```bash
bash pilot_install.sh --dry-run
```

---

## Host Requirements

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| OS | Ubuntu 22.04, Debian 12, macOS 13, WSL2 | Other POSIX hosts may work |
| Shell | bash ≥ 4 | Installed by default on Linux; macOS ships bash 3 — install via brew |
| CMake | 3.18+ | `sudo apt install cmake` or `brew install cmake` |
| Python | 3.9+ | `sudo apt install python3 python3-pip` |
| git | any | `sudo apt install git` |
| make / gcc | build-essential | `sudo apt install build-essential` |
| wget **or** curl | either | `sudo apt install wget` |
| RAM | 8 GB | 4 GB usable for 3B-class models with swap |
| Disk | 10 GB free | whisper.cpp build + llama.cpp build + models |

### Optional (recommended)

| Tool | Purpose | Install |
|------|---------|---------|
| CUDA / nvcc | GPU inference — 5–10× faster | [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) |
| ffmpeg | Robust wav conversion | `sudo apt install ffmpeg` |
| PulseAudio | Microphone in WSL2 | [PulseAudio for Windows](https://www.freedesktop.org/wiki/Software/PulseAudio/Ports/Windows/) |
| paplay / aplay | Audio playback | `sudo apt install alsa-utils pulseaudio-utils` |

---

## Supported Host Configurations

### Ubuntu 22.04 / 24.04 (bare-metal or VM)

This is the primary supported configuration. GPU inference requires the NVIDIA
CUDA toolkit matching your driver version.

```bash
sudo apt update && sudo apt install -y \
  git cmake build-essential python3 python3-pip \
  wget ffmpeg alsa-utils pulseaudio-utils
bash pilot_install.sh
```

### WSL2 (Windows 11)

WSL2 supports GPU inference via CUDA if you have an NVIDIA GPU and the
[WSL2 CUDA driver](https://docs.nvidia.com/cuda/wsl-user-guide/index.html).

Microphone access requires a PulseAudio server running on the Windows host:

1. Download and start [PulseAudio for Windows](https://www.freedesktop.org/wiki/Software/PulseAudio/Ports/Windows/).
2. In WSL2, export the server address before running Christopher:

```bash
export PULSE_SERVER=tcp:$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf):4713
```

Or add this line to your `.env` (note: the WSL2 gateway IP changes on each reboot —
find the current value with `cat /etc/resolv.conf | grep nameserver`):

```bash
# PULSE_SERVER=tcp:172.24.128.1:4713
```

Run `bash preflight_voice.sh` to verify the microphone is reachable.

### macOS 13+ (Apple Silicon or x86_64)

```bash
brew install git cmake python3 wget ffmpeg
bash pilot_install.sh
```

> **Note:** Piper TTS does not officially support macOS. You may need to build
> piper from source or use an alternative TTS engine. Text mode
> (`python3 christopher.py --chat`) works without TTS.

### Debian 12

Same as Ubuntu. Ensure `python3-pip` and `cmake` versions from the Debian
bookworm repos are recent enough (cmake 3.25 ships by default — fine).

---

## Failure Recovery

If `pilot_install.sh` fails, it prints the missing tools and an install command.

**Example output when cmake is missing:**

```
  ✗  Prerequisites not met. Install the following before re-running:

    • cmake >= 3.18  (install: sudo apt install cmake  OR  brew install cmake)

  Quick-fix:
    sudo apt update && sudo apt install -y git cmake python3 python3-pip \
        wget ffmpeg alsa-utils pulseaudio-utils build-essential

  See docs/pilot-setup-guide.md → 'Host Requirements' for full details.
```

After fixing the error, simply re-run:

```bash
bash pilot_install.sh
```

The script is **idempotent** — already-completed steps are skipped.

---

## Post-Install Health Check

After installing, run the voice pipeline health check:

```bash
bash preflight_voice.sh
```

This checks:
- whisper-cli binary and model
- llama-cli binary
- piper in PATH
- ffmpeg
- Microphone capture (PulseAudio → ALSA fallback)
- ASR smoke test (records a short clip and runs Whisper)
- Audio playback

If health check reports failures, it prints targeted fix commands.

---

## Configuration

Edit `.env` to customise paths, GPU layers, and model selection:

```bash
$EDITOR .env
```

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PROFILE` | `llama32-3b` | Active model profile (`llama32-3b`, `qwen25-3b`, `mistral-7b`) |
| `LLAMA_NGL` | _(profile default)_ | GPU layers to offload — increase for more VRAM |
| `LISTEN_SECONDS` | `5` | Recording length per voice turn |
| `FUSIONAL_API_KEY` | `changeme` | Required for MCP tool integrations |

See `.env.example` for the full list with documentation.

---

## Running Christopher

```bash
# Voice mode (mic required + full pipeline)
python3 christopher.py --voice

# Text chat (no mic, good for testing on headless machines)
python3 christopher.py --chat

# Override model profile for this run
python3 christopher.py --voice --model-profile qwen25-3b

# Benchmark — compare model latency before committing
python3 christopher.py --benchmark --model-profile llama32-3b
python3 christopher.py --benchmark --model-profile qwen25-3b
```

---

## Uninstall

The installer only creates:

- `~/whisper.cpp/` — delete to remove whisper
- `~/llama.cpp/` — delete to remove llama
- `~/piper_models/` — delete to remove voice model
- `.env` in the repo directory

```bash
rm -rf ~/whisper.cpp ~/llama.cpp ~/piper_models
rm -f .env
# Optional: remove llama-server systemd service
sudo systemctl disable llama-server && sudo rm /etc/systemd/system/llama-server.service
```

---

## Further Help

- [README.md](../README.md) — project overview and GPU tuning guide
- [preflight_voice.sh](../preflight_voice.sh) — voice pipeline health check
- [.env.example](../.env.example) — all configuration variables with comments
