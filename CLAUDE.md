# CLAUDE.md — Christopher AI

This file is the authoritative AI assistant guide for the `christopher-ai` repository.
Read this before making any changes.

## What This Repo Is

Christopher is a **fully offline, local voice AI assistant** that runs entirely on your
hardware with no cloud dependencies and no API keys. The pipeline:

```
Microphone → whisper.cpp (ASR) → transcript → llama.cpp (LLM) → reply → Piper TTS → Speakers
```

Built to run on WSL2 Ubuntu on a Windows machine. Primary target hardware:
`i5-7300HQ + GTX 1050 Ti 4GB`, hostname `t3610`.

This repo pairs with `mcp-consulting-kit` (MCP tool servers) and `fusional`
(governance gateway) for voice-controlled MCP operations.

---

## Stack

| Component | Engine | Default Model |
|-----------|--------|---------------|
| Speech recognition | whisper.cpp (compiled from source) | `ggml-base.en` |
| Language model | llama.cpp + CUDA (compiled from source) | Llama 3.2 3B Q4_K_M |
| Text to speech | Piper TTS | `en_US-libritts-high.onnx` |
| Orchestrator | `christopher.py` (Python 3) | — |

---

## Directory Structure

```
christopher-ai/
├── christopher.py                    # Main orchestrator — voice/chat/benchmark modes
├── christopher_requirements.txt      # Python deps (requests, dotenv, fastapi, uvicorn)
├── christopher_install.sh            # Lightweight installer (builds binaries + downloads model)
├── pilot_install.sh                  # Full pilot installer with prerequisite checks
├── preflight_voice.sh                # Pipeline health check before launch
├── voice_ai.sh                       # Minimal voice startup script
├── rotate_keys.py                    # API key rotation utility
├── christopher-macros.ahk            # Windows AutoHotKey macros for remote control
├── llama-server.service              # systemd service file for llama-server daemon
├── .env.example                      # All env vars with descriptions
├── .claude/
│   └── settings.local.json           # Claude Code local settings
├── docs/
│   ├── pilot-setup-guide.md          # Full install walkthrough + failure recovery
│   ├── offline-runbook.md            # Offline startup, fallbacks, air-gapped deploy
│   └── workflow-templates.md         # Workflow YAML schema + sample turns
├── workflows/
│   ├── dispatch.yaml                 # Route speech → Slack / GitHub / webhook
│   ├── notes.yaml                    # Transcribe + tag a spoken note
│   └── summaries.yaml               # Condense notes/transcripts into summaries
├── benchmarks/                       # Benchmark result files
├── recovery/                         # Recovery scripts for hardware/software failures
├── check-stack-status.ps1            # Full stack status check (Windows)
├── install-christopher-startup-shortcut.ps1
├── install-christopher-tunnel-task.ps1
├── install-pulseaudio.ps1            # PulseAudio setup for WSL2 audio
├── repair-pc-performance.ps1         # PC performance repair utility
├── start-christopher-remote.ps1      # Start Christopher via SSH on t3610
└── start-remote-tunnels.ps1          # SSH tunnels for remote access
```

---

## Installation

### Quick install (recommended)

```bash
bash pilot_install.sh
```

This script checks all prerequisites, then builds whisper.cpp and llama.cpp from source,
downloads the default model, and creates a `.env` with correct paths.

### Manual install

```bash
# whisper.cpp
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp && mkdir build && cd build
cmake .. && make -j4
bash models/download-ggml-model.sh base.en

# llama.cpp with CUDA
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp && mkdir build && cd build
cmake .. -DGGML_CUDA=ON && make -j4

# Piper TTS
pip install piper-tts

# Python deps
pip install -r christopher_requirements.txt

# System deps
sudo apt install alsa-utils ffmpeg
```

---

## Usage

```bash
# Health check first
bash preflight_voice.sh

# Voice mode
python3 christopher.py --voice

# Chat mode (text input/output)
python3 christopher.py --chat

# Benchmark mode (compare model latencies)
python3 christopher.py --benchmark --model-profile llama32-3b
python3 christopher.py --benchmark --model-profile qwen25-3b
python3 christopher.py --benchmark --model-profile mistral-7b --ngl 28 --ctx 512
```

Voice mode listens for `LISTEN_SECONDS` seconds (default 5) per turn.

---

## Model Profiles

Christopher uses named model profiles to switch between LLMs without editing config files.

| Profile | Model | VRAM | Best for |
|---------|-------|------|----------|
| `llama32-3b` | Llama 3.2 3B Q4_K_M | 4GB | Default; best fit for GTX 1050 Ti |
| `qwen25-3b` | Qwen2.5 3B Q4_K_M | 4GB | Alternative 3B with strong reasoning |
| `mistral-7b` | Mistral 7B Q4_K_M | 4GB (slow) / 8GB | Better quality, slower on 4GB |

Set default in `.env`:
```bash
MODEL_PROFILE=llama32-3b
```

Override per run:
```bash
python3 christopher.py --voice --model-profile qwen25-3b
python3 christopher.py --chat --model-profile mistral-7b --ngl 28 --ctx 512
```

### GPU Layer Tuning

| VRAM | Recommended flags |
|------|-------------------|
| 4GB (GTX 1050 Ti) | Profile defaults for `llama32-3b` / `qwen25-3b` |
| 4GB (Mistral 7B) | `--ngl 28 --ctx 512` |
| 8GB | `--ngl 40 --ctx 2048` |
| 16GB+ | `--ngl 99 --ctx 4096` |

---

## Environment Variables

All vars documented in `.env.example`. The install scripts generate `.env` with
correct paths. Key vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PROFILE` | `llama32-3b` | Default model profile |
| `LLAMA_SERVER_BIN` | `~/llama.cpp/build/bin/llama-server` | Path to llama-server binary |
| `LLAMA_MODEL` | (from profile) | GGUF model file path |
| `LLAMA_MODEL_LLAMA32_3B` | — | Path for llama32-3b profile |
| `LLAMA_MODEL_QWEN25_3B` | — | Path for qwen25-3b profile |
| `LLAMA_MODEL_MISTRAL_7B` | — | Path for mistral-7b profile |
| `LLAMA_SERVER_URL` | `http://localhost:8080` | llama-server URL |
| `LLAMA_NGL` | (from profile) | GPU layers to offload |
| `LLAMA_THREADS` | `4` | CPU threads for non-GPU layers |
| `LLAMA_CTX` | (from profile) | Context window size |
| `WHISPER_BIN` | `~/whisper.cpp/build/bin/whisper-cli` | Path to whisper binary |
| `WHISPER_MODEL` | `~/whisper.cpp/models/ggml-base.en.bin` | Path to whisper model |
| `PIPER_BIN` | (from PATH) | Path to piper binary |
| `PIPER_MODEL` | `~/piper_models/en_US-libritts-high.onnx` | TTS model |
| `PIPER_CONFIG` | `...high.onnx.json` | TTS model config |
| `LISTEN_SECONDS` | `5` | Recording duration per voice turn |
| `FUSIONAL_API_KEY` | `changeme` | Shared key for FusionAL MCP servers |
| `FUSIONAL_BI_URL` | `http://localhost:8101` | Business Intelligence MCP URL |
| `FUSIONAL_API_URL` | `http://localhost:8102` | API Integration Hub URL |
| `FUSIONAL_CONTENT_URL` | `http://localhost:8103` | Content Automation MCP URL |
| `PULSE_SERVER` | — | WSL2 PulseAudio server address |

---

## WSL2 Audio Setup

Voice capture in WSL2 requires PulseAudio running on the Windows host.

**Windows side:**
1. Install PulseAudio for Windows.
2. Run `C:\PulseAudio\start-pulseaudio.cmd`.

**WSL2 side:**
```bash
# Set PULSE_SERVER (WSL2 IP changes on reboot — get it dynamically)
export PULSE_SERVER=tcp:$(awk '/^nameserver / {print $2; exit}' /etc/resolv.conf):4713
```

Or set `PULSE_SERVER` in `.env` (note: hardcoded IP breaks on WSL2 reboot).

Use the Windows installer:
```powershell
.\install-pulseaudio.ps1
```

Audio capture priority: `parec` (PulseAudio) → `arecord` (ALSA) fallback.

---

## Voice Pipeline — Internal Flow

1. **Record**: `parec` or `arecord` captures `LISTEN_SECONDS` of audio → WAV file.
2. **Transcribe**: `whisper-cli` converts WAV → text transcript.
3. **Generate**: HTTP POST to `llama-server` at `LLAMA_SERVER_URL/v1/chat/completions`.
4. **Speak**: Response text piped to `piper` → audio output via `aplay`.

`christopher.py` orchestrates all four steps. It also manages llama-server lifecycle
(start/stop the subprocess), model profile selection, and `--benchmark` mode.

---

## MCP Integration

Christopher connects to the FusionAL MCP servers for voice-controlled tool use:

- Business Intelligence (`:8101`) — natural language SQL
- API Integration Hub (`:8102`) — Slack, GitHub, Stripe
- Content Automation (`:8103`) — web scraping, RSS

All calls authenticated with `FUSIONAL_API_KEY` header. When using SSH tunnels from
Windows, use tunnel ports (e.g., `18101`, `18102`, `18103`) instead.

---

## Workflow Templates

Three ready-to-use voice workflow templates in `workflows/`:

| Template | File | Description |
|----------|------|-------------|
| Dispatch | `workflows/dispatch.yaml` | Route speech → Slack / GitHub Issues / webhook |
| Note Capture | `workflows/notes.yaml` | Transcribe + tag spoken note → local file or remote store |
| Summary | `workflows/summaries.yaml` | Condense notes/transcript → bullet points, prose, TL;DR |

Full schema documentation: `docs/workflow-templates.md`.

---

## Key Scripts

| Script | Platform | Purpose |
|--------|----------|---------|
| `pilot_install.sh` | Linux/WSL | Full install with prerequisite checks |
| `christopher_install.sh` | Linux/WSL | Lightweight build + model download |
| `preflight_voice.sh` | Linux/WSL | Verify pipeline is ready before launch |
| `voice_ai.sh` | Linux/WSL | Minimal voice startup |
| `rotate_keys.py` | Any | API key rotation (overlap + revoke) |
| `check-stack-status.ps1` | Windows | Full stack status (local + remote) |
| `start-christopher-remote.ps1` | Windows | SSH into t3610, start Christopher |
| `start-remote-tunnels.ps1` | Windows | SSH tunnels for remote access |
| `install-christopher-startup-shortcut.ps1` | Windows | Windows startup shortcut |
| `install-christopher-tunnel-task.ps1` | Windows | Scheduled tunnel task |
| `install-pulseaudio.ps1` | Windows | PulseAudio setup |
| `repair-pc-performance.ps1` | Windows | System performance repair |
| `christopher-macros.ahk` | Windows | AutoHotKey voice macros |
| `llama-server.service` | Linux | systemd service for llama-server |

---

## Benchmarking

```bash
# Compare all three profiles on your hardware
python3 christopher.py --benchmark --model-profile llama32-3b
python3 christopher.py --benchmark --model-profile qwen25-3b
python3 christopher.py --benchmark --model-profile mistral-7b --ngl 28 --ctx 512
```

Benchmark mode runs several inference passes and prints per-run latency + average.
Results are written to `benchmarks/`. Use this before adopting a new model.

---

## Docs Index

| Doc | Purpose |
|-----|---------|
| `docs/pilot-setup-guide.md` | Full install walkthrough, supported hosts, failure recovery |
| `docs/offline-runbook.md` | Offline startup, fallback behaviors, air-gapped deployment |
| `docs/workflow-templates.md` | Workflow YAML schema, sample turns, domain adaptation |

---

## Python Dependencies (`christopher_requirements.txt`)

```
requests==2.33.1
python-dotenv==1.2.1
fastapi==0.136.0
uvicorn==0.34.0
```

Minimal by design — this is a local tool, not a service. No AI API clients needed
(all LLM inference happens via llama-server HTTP, not SDK).

---

## Cross-Repo Relationships

| Dependency | Direction | Details |
|-----------|-----------|--------|
| `mcp-consulting-kit` MCP servers (8101–8103) | christopher imports from | Via HTTP to `FUSIONAL_*_URL` |
| `fusional` gateway | christopher may route through | Optional gateway layer |
| t3610 deployment | All three repos sync here | Via `scripts/sync-all.*` in `mcp-consulting-kit` |

Local development assumes all repos are siblings:
```
~/Projects/
├── mcp-consulting-kit/
├── FusionAL/
└── Christopher-AI/
```

---

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Voice mode starts but no speech detected | PulseAudio not running on Windows | Start `C:\PulseAudio\start-pulseaudio.cmd`, then re-run |
| `llama-server` fails to start | Wrong binary path or model path | Check `LLAMA_SERVER_BIN` and `LLAMA_MODEL_*` in `.env` |
| CUDA out of memory | Too many GPU layers for VRAM | Reduce `LLAMA_NGL` (e.g., `--ngl 28` for Mistral 7B on 4GB) |
| Piper produces no audio | `PIPER_MODEL` path missing | Run `pilot_install.sh` or set `PIPER_MODEL` in `.env` |
| whisper-cli not found | Not built or wrong path | Check `WHISPER_BIN` in `.env`, rebuild if needed |

Full troubleshooting: `docs/pilot-setup-guide.md` and `docs/offline-runbook.md`.

---

## Key Conventions

- Python 3.11+ required.
- No cloud API keys for the core voice pipeline — it is intentionally offline-first.
- All secrets in `.env`, never committed. `.gitignore` covers `.env`.
- `FUSIONAL_API_KEY` must match the `API_KEY` set in `mcp-consulting-kit` server `.env` files.
- Model GGUF files are not committed — download via install scripts.
- Compiled binaries (whisper.cpp, llama.cpp) are not committed — build from source.
- The `christopher.py` orchestrator manages the llama-server subprocess lifecycle;
  do not run llama-server separately when using christopher.py.
