# Offline-Mode Operations Runbook — Christopher Voice AI

Christopher is designed to run **entirely offline** once the binaries and models
are in place. This runbook covers how to start Christopher without any internet
connection, what happens when optional external services are unavailable, and how
to verify that your installation is ready before going offline.

---

## Table of Contents

1. [Offline Readiness Checklist](#offline-readiness-checklist)
2. [Offline Startup — Step by Step](#offline-startup--step-by-step)
3. [Fallback Behaviors](#fallback-behaviors)
4. [Pre-Staging for Air-Gapped Machines](#pre-staging-for-air-gapped-machines)
5. [Troubleshooting Without Internet](#troubleshooting-without-internet)

---

## Offline Readiness Checklist

Run through this checklist on a **connected** machine first, then verify it again
on the target offline host.

### Required — Core Pipeline

- [ ] `whisper-cli` binary is compiled and present at `$WHISPER_BIN`
      (default: `~/whisper.cpp/build/bin/whisper-cli`)
- [ ] Whisper model file is downloaded and present at `$WHISPER_MODEL`
      (default: `~/whisper.cpp/models/ggml-base.en.bin`)
- [ ] `llama-cli` binary is compiled and present at `$LLAMA_BIN`
      (default: `~/llama.cpp/build/bin/llama-cli`)
- [ ] `llama-server` binary is compiled and present at `$LLAMA_SERVER_BIN`
      (default: `~/llama.cpp/build/bin/llama-server`)
- [ ] GGUF model file is downloaded for each profile you plan to use:
      - [ ] `llama32-3b` → `$LLAMA_MODEL_LLAMA32_3B`
      - [ ] `qwen25-3b`  → `$LLAMA_MODEL_QWEN25_3B` _(optional)_
      - [ ] `mistral-7b` → `$LLAMA_MODEL_MISTRAL_7B` _(optional)_
- [ ] `piper` is installed and in `$PATH`
- [ ] Piper voice model is present at `$PIPER_MODEL`
      (default: `~/piper_models/en_US-libritts-high.onnx`)
- [ ] Piper config is present at `$PIPER_CONFIG`
      (default: `~/piper_models/en_US-libritts-high.onnx.json`)
- [ ] Python dependencies are installed: `pip install -r christopher_requirements.txt`
- [ ] `.env` is configured with correct local paths (copy from `.env.example`)

### Required — System Utilities

- [ ] `ffmpeg` is installed (`sudo apt install ffmpeg`)
- [ ] `alsa-utils` is installed for ALSA audio (`sudo apt install alsa-utils`)

### Required for Voice Mode

- [ ] Microphone capture works — at least one of:
      - [ ] `parec` available and PulseAudio reachable (WSL2: see
            [WSL2 PulseAudio note](#wsl2-pulseaudio-note)), **or**
      - [ ] `arecord` available and ALSA microphone present

### Optional — Confirm Not Needed Offline

- [ ] MCP server URLs in `.env` (`FUSIONAL_BI_URL`, `FUSIONAL_API_URL`,
      `FUSIONAL_CONTENT_URL`) are not required for core voice/chat operation —
      only needed if you use Christopher MCP tool integrations
- [ ] No API keys or cloud services are used by the core pipeline

### Run the Automated Check

```bash
bash preflight_voice.sh
```

All items must show `[OK]` before operating offline. `[WARN]` items that relate
to optional features (e.g., MCP integrations) are acceptable for offline use.

---

## Offline Startup — Step by Step

### Step 1 — Confirm the environment file

```bash
cat .env
```

Verify that all paths resolve to **local files**, not remote URLs. Key variables:

| Variable | What to check |
|----------|---------------|
| `LLAMA_SERVER_BIN` | Absolute path to a compiled binary on this machine |
| `LLAMA_MODEL_*` | Absolute paths to `.gguf` files already downloaded |
| `WHISPER_BIN` | Absolute path to compiled `whisper-cli` |
| `WHISPER_MODEL` | Absolute path to `.bin` model file |
| `PIPER_MODEL` | Absolute path to `.onnx` voice model |
| `LLAMA_SERVER_URL` | Should be `http://localhost:8080` (local) |

### Step 2 — Run the preflight health check

```bash
bash preflight_voice.sh
```

Expected output when offline-ready:

```
== Binaries + Models ==
[OK]   whisper-cli found: /home/user/whisper.cpp/build/bin/whisper-cli
[OK]   Whisper model found: /home/user/whisper.cpp/models/ggml-base.en.bin
[OK]   llama-cli found at expected path
[OK]   piper found in PATH
[OK]   ffmpeg found

== Audio Input ==
[OK]   Mic capture works via PulseAudio (parec)    ← or ALSA (arecord)

== ASR Smoke Test ==
[OK]   Whisper ASR executed successfully

== Audio Output ==
[OK]   Playback path works via paplay              ← or ffplay

== Summary ==
Pass: 7 | Warn: 0 | Fail: 0
```

> If any `[FAIL]` items appear, resolve them before proceeding. See
> [Troubleshooting Without Internet](#troubleshooting-without-internet).

### Step 3 — Start llama-server (if not using systemd)

If you are **not** using the `llama-server.service` systemd unit:

```bash
# Load path variables from .env
export $(grep -v '^#' .env | xargs)

# Start the server with your chosen model profile
~/llama.cpp/build/bin/llama-server \
  --model "$LLAMA_MODEL_LLAMA32_3B" \
  --n-gpu-layers 99 \
  --ctx-size 2048 \
  --port 8080 &

# Wait for it to become ready
sleep 3 && curl -sf http://localhost:8080/health | grep -q ok && echo "Server ready" || echo "Server not yet ready"
```

If using systemd:

```bash
sudo systemctl start llama-server
sudo systemctl status llama-server
```

### Step 4 — Launch Christopher

**Voice mode** (full pipeline — microphone + ASR + LLM + TTS):

```bash
python3 christopher.py --voice
```

**Text / chat mode** (no microphone required — safe fallback for headless machines):

```bash
python3 christopher.py --chat
```

**Override the model profile for this run:**

```bash
python3 christopher.py --voice --model-profile qwen25-3b
```

---

## Fallback Behaviors

The following table describes what Christopher does when each external dependency
is unavailable. Every fallback listed here is observable and can be tested manually.

### Audio Input Fallbacks

| Scenario | What Christopher does | How to test |
|----------|----------------------|-------------|
| PulseAudio unreachable (WSL2) | Automatically falls back to ALSA `arecord` | Stop PulseAudio on Windows; run `bash preflight_voice.sh` and confirm `[OK] Mic capture works via ALSA` |
| `parec` not installed | Skips PulseAudio and uses `arecord` directly | `sudo apt remove pulseaudio-utils`; run preflight |
| Both `parec` and `arecord` unavailable | Reports `[FAIL] No working microphone capture backend found`; voice mode cannot proceed | Use `--chat` mode as the fallback |
| No microphone hardware | Voice mode fails at recording step | Use `python3 christopher.py --chat` instead |

### Audio Output Fallbacks

| Scenario | What Christopher does | How to test |
|----------|----------------------|-------------|
| `paplay` unavailable | Falls back to `ffplay` for audio output | `which paplay` returns nothing; run preflight |
| Both `paplay` and `ffplay` unavailable | Reports `[WARN] No playback tool found`; TTS audio cannot be played | Response text is still printed to terminal |

### LLM Server Fallbacks

| Scenario | What Christopher does | How to test |
|----------|----------------------|-------------|
| `llama-server` not running | `christopher.py` prints a connection error to `stderr` and exits | Stop the server; run `python3 christopher.py --chat` and observe the error |
| Wrong `LLAMA_SERVER_URL` in `.env` | Same connection error | Set URL to an unused port; observe error |
| Model file missing or wrong path | `llama-server` fails to start; Christopher reports a server error | Point `LLAMA_MODEL_*` to a non-existent path |

> **Recovery:** Ensure `llama-server` is started (Step 3 above) before launching
> Christopher. The server must be running for both `--voice` and `--chat` modes.

### MCP / FusionAL Integration Fallbacks

| Scenario | What Christopher does | How to test |
|----------|----------------------|-------------|
| FusionAL MCP servers unreachable | MCP tool calls fail with a connection error; core voice/chat pipeline is unaffected | Set `FUSIONAL_BI_URL` to a dead port; run a voice turn that does not invoke tools |
| `FUSIONAL_API_KEY` not set or wrong | MCP requests return 401/403; core pipeline is unaffected | Use a wrong key value; observe log output |

> The core pipeline (ASR → LLM → TTS) has **no dependency** on FusionAL MCP
> servers. You can operate fully offline without setting these values.

### `ffmpeg` Fallback (wav conversion)

| Scenario | What Christopher does | How to test |
|----------|----------------------|-------------|
| `ffmpeg` missing, `sox` present | Uses `sox` for raw-to-wav conversion | Remove ffmpeg; install sox; run preflight ASR smoke test |
| Both `ffmpeg` and `sox` missing | Skips wav conversion; Whisper may receive a raw PCM file instead of a wav | Remove both; run preflight and observe `[WARN]` |

---

## Pre-Staging for Air-Gapped Machines

If the target machine has **no internet access at all**, download all assets on a
connected machine first and transfer them.

### Assets to Collect

```
whisper.cpp/                        ← compiled source tree
  build/bin/whisper-cli
  models/ggml-base.en.bin

llama.cpp/                          ← compiled source tree
  build/bin/llama-cli
  build/bin/llama-server

models/                             ← GGUF model files
  Llama-3.2-3B-Instruct-Q4_K_M.gguf
  Qwen2.5-3B-Instruct-Q4_K_M.gguf   ← optional
  mistral-7b-instruct-v0.2.Q4_K_M.gguf  ← optional

piper_models/
  en_US-libritts-high.onnx
  en_US-libritts-high.onnx.json

Christopher-AI/                     ← this repo
  .env                              ← configured with local paths
  christopher_requirements.txt
  (+ all other repo files)

Python packages (offline wheel cache):
  pip download -r christopher_requirements.txt -d /tmp/pip-cache
  pip download piper-tts -d /tmp/pip-cache
```

### Transfer and Install

```bash
# On the air-gapped machine — install Python deps from local cache
pip install --no-index --find-links /path/to/pip-cache -r christopher_requirements.txt
pip install --no-index --find-links /path/to/pip-cache piper-tts

# Place binaries and models at the paths your .env references, then verify:
bash preflight_voice.sh
```

> **Note:** Compiled binaries must match the CPU architecture and OS of the target
> machine. Recompile from source on the target if the architectures differ.

### WSL2 PulseAudio Note

In WSL2, PulseAudio runs on the **Windows** host — it is not an internet service
and is fully available offline. The only requirement is that PulseAudio is started
on Windows before launching Christopher in WSL2:

1. Start PulseAudio on Windows: `C:\PulseAudio\start-pulseaudio.cmd`
2. In WSL2, export the server address (changes on each reboot):

```bash
export PULSE_SERVER=tcp:$(awk '/^nameserver / {print $2; exit}' /etc/resolv.conf):4713
```

---

## Troubleshooting Without Internet

### Binary or model missing

```
[FAIL] whisper-cli missing or not executable: /home/user/whisper.cpp/build/bin/whisper-cli
```

**Fix (online):** Run `bash pilot_install.sh` to rebuild and download.

**Fix (offline):** Transfer the compiled binary from another machine with the same
architecture, or rebuild from source using locally cached source tarballs.

### Piper not found

```
[WARN] piper not found in PATH
```

**Fix (online):** `pip install piper-tts`

**Fix (offline):** `pip install --no-index --find-links /path/to/pip-cache piper-tts`

Text/chat mode still works without piper. Voice mode will not produce speech output.

### llama-server fails to start

Check the server log directly:

```bash
~/llama.cpp/build/bin/llama-server \
  --model "$LLAMA_MODEL_LLAMA32_3B" \
  --n-gpu-layers 99 \
  --ctx-size 2048 \
  --port 8080
```

Common causes:

| Symptom | Fix |
|---------|-----|
| `model file not found` | Verify `LLAMA_MODEL_*` path in `.env` |
| `CUDA error: no kernel image available` | Recompile llama.cpp with matching CUDA version: `cmake .. -DGGML_CUDA=ON` |
| `out of memory` | Reduce `--n-gpu-layers` or `--ctx-size` |
| `address already in use` | Another process owns port 8080 — `lsof -i :8080` and stop it |

### No microphone capture

```
[FAIL] No working microphone capture backend found
```

**Immediate fallback:** Use text mode — no microphone required:

```bash
python3 christopher.py --chat
```

**WSL2 fix:** Start PulseAudio on Windows and export `PULSE_SERVER` (see above).

**Bare-metal / VM fix:** Confirm ALSA sees the microphone:

```bash
arecord -l          # list capture devices
arecord -d 3 /tmp/test.wav && aplay /tmp/test.wav
```

---

## Related Documentation

- [pilot-setup-guide.md](pilot-setup-guide.md) — full install walkthrough and host requirements
- [preflight_voice.sh](../preflight_voice.sh) — automated pipeline health check
- [.env.example](../.env.example) — all configuration variables with documentation
- [README.md](../README.md) — project overview, GPU tuning, model profiles
