# Christopher — Local Voice AI Assistant

**Fully local. Privacy-first. Real-time. Built from source.**

> 🌐 [**fusional.dev**](https://fusional.dev) — Production MCP deployments by the team behind Christopher

Christopher is a fully offline voice AI pipeline running entirely on your hardware.
No cloud. No API keys. No data leaving your machine.
You speak — it listens, thinks, and talks back.

Built on three compiled-from-source inference engines:
- **whisper.cpp** — speech recognition
- **llama.cpp** — LLM inference with CUDA GPU acceleration  
- **Piper TTS** — neural text-to-speech

---

## Stack

| Component | Engine | Model |
|-----------|--------|-------|
| Speech Recognition | whisper.cpp | ggml-base.en |
| Language Model | llama.cpp + CUDA | Model profile: Llama 3.2 3B / Qwen2.5 3B / Mistral 7B |
| Text to Speech | Piper | en_US-libritts-high |

**Hardware:** i5-7300HQ + GTX 1050 Ti 4GB + WSL2 Ubuntu

---

## How It Works
```
Microphone → whisper.cpp → transcript → llama.cpp → reply → Piper TTS → speakers
```

One bash script. Three binaries. Zero cloud dependencies.

---

## Quick Start (Pilot Installer)

Single command — checks all prerequisites first, then builds and downloads everything:

```bash
bash pilot_install.sh
```

After install, run the health check and launch Christopher:

```bash
bash preflight_voice.sh       # verify the pipeline is ready
python3 christopher.py --voice  # start voice mode
```

> See **[docs/pilot-setup-guide.md](docs/pilot-setup-guide.md)** for supported host
> configurations, failure recovery, and full walkthrough.
> See **[docs/offline-runbook.md](docs/offline-runbook.md)** for offline startup,
> fallback behaviors, and air-gapped deployment.

---

## Manual Requirements
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
# Default install downloads Llama 3.2 3B Q4_K_M into models/

# Piper TTS
pip install piper-tts

# Christopher orchestrator deps
pip install -r christopher_requirements.txt

# System
sudo apt install alsa-utils ffmpeg
```

---

## Usage
```bash
chmod +x voice_ai.sh
chmod +x preflight_voice.sh
./preflight_voice.sh
./voice_ai.sh
```

Speak after the prompt. Christopher listens for 5 seconds, generates a response, speaks it back.

### WSL2 Microphone Troubleshooting

If voice mode starts but never detects speech:

1. Start PulseAudio on Windows (`C:\PulseAudio\start-pulseaudio.cmd`).
2. In WSL, set `PULSE_SERVER` if needed:

```bash
export PULSE_SERVER=tcp:$(awk '/^nameserver / {print $2; exit}' /etc/resolv.conf):4713
```

3. Re-run `./voice_ai.sh`.

The script now tries PulseAudio capture first (`parec`) and falls back to ALSA (`arecord`) automatically.

---

## GPU Tuning

Christopher now uses a model-profile system so you can switch models without editing multiple files.

| VRAM | Recommended flags |
|------|-------------------|
| 4GB (GTX 1050 Ti) | `llama32-3b` or `qwen25-3b` with profile defaults |
| 4GB (GTX 1050 Ti, slower) | `mistral-7b` with `-ngl 28 -c 512` |
| 8GB | `-ngl 40 -c 2048` |
| 16GB+ | `-ngl 99 -c 4096` |

## Model Profiles

Christopher can now run three named local model profiles:

- `llama32-3b` — default; best fit for 4GB VRAM
- `qwen25-3b` — best candidate if you want a smarter small model on the same hardware
- `mistral-7b` — usable, but slower on 4GB VRAM

Set the default in `.env`:

```bash
MODEL_PROFILE=llama32-3b
```

Or switch per run:

```bash
python3 christopher.py --chat --model-profile qwen25-3b
python3 christopher.py --voice --model-profile llama32-3b
python3 christopher.py --chat --model-profile mistral-7b --ngl 28 --ctx 512
```

## Benchmarking Models

Use the built-in benchmark mode to compare latency before adopting a model:

```bash
python3 christopher.py --benchmark --model-profile llama32-3b
python3 christopher.py --benchmark --model-profile qwen25-3b
python3 christopher.py --benchmark --model-profile mistral-7b --ngl 28 --ctx 512
```

This prints per-run latency and the average so you can compare on your actual hardware.

---

## Workflow Templates

Christopher ships three ready-to-use voice workflow templates in the
[`workflows/`](workflows/) directory.

| Template | File | Description |
|----------|------|-------------|
| Dispatch | [`workflows/dispatch.yaml`](workflows/dispatch.yaml) | Route a spoken message to Slack, GitHub Issues, or a webhook |
| Note Capture | [`workflows/notes.yaml`](workflows/notes.yaml) | Transcribe and tag a spoken note; write it to a local file or remote store |
| Summary Generation | [`workflows/summaries.yaml`](workflows/summaries.yaml) | Condense notes or a transcript into bullet points, prose, or a TL;DR |

See **[docs/workflow-templates.md](docs/workflow-templates.md)** for full schemas,
sample turns, and domain adaptation guidance.

---

## Roadmap

- [ ] Wake word detection
- [ ] MCP tool integration (voice control over FusionAL — database, Slack, GitHub)
- [x] Centralized model profiles + benchmark mode
- [ ] Test Qwen2.5 3B against Llama 3.2 3B on GTX 1050 Ti
- [ ] RAG module for local document search
- [ ] WebSocket streaming
- [ ] GUI dashboard

---

## Origin

This was my first ever systems-level build.

I built Christopher in a hospital over 4-5 days — compiling whisper.cpp and llama.cpp
from source, getting CUDA running on a GTX 1050 Ti, wiring the full pipeline in bash.
No prior C++ experience. No prior CUDA experience.
Just time, necessity, and refusal to stop.

The name Christopher belongs to my brother and his son.
His son saved me. This project is dedicated to them.

---

## Author

**Jonathan Melton** — Self-taught developer. Privacy-first AI engineering.

**Projects**:
- [FusionAL](https://gitlab.com/JRM-FusionAL/FusionAL) — Self-hosted MCP governance gateway
- [mcp-consulting-kit](https://gitlab.com/JRM-FusionAL/FusionAL-mcp-consulting-kit) — Production MCP servers
- [Christopher-AI](https://gitlab.com/JRM-FusionAL/Christopher-AI) — This project

**Consulting**: [fusional.dev](https://fusional.dev) — Done-for-you MCP governance deployments ($3.5k-9k)  
**Contact**: [jonathanmelton.fusional@gmail.com](mailto:jonathanmelton.fusional@gmail.com) • [Book Call](https://calendly.com/jonathanmelton004/30min)

