# Christopher — Local Voice AI Assistant

**Fully local. Privacy-first. Real-time. Built from source.**

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
| Language Model | llama.cpp + CUDA | Mistral 7B Instruct Q4_K_M |
| Text to Speech | Piper | en_US-libritts-high |

**Hardware:** i5-7300HQ + GTX 1050 Ti 4GB + WSL2 Ubuntu

---

## How It Works
```
Microphone → whisper.cpp → transcript → llama.cpp → reply → Piper TTS → speakers
```

One bash script. Three binaries. Zero cloud dependencies.

---

## Requirements
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
# Download Mistral 7B Q4_K_M from HuggingFace into models/

# Piper TTS
pip install piper-tts

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

`-ngl 35` offloads 35 transformer layers to VRAM.

| VRAM | Recommended flags |
|------|-------------------|
| 4GB (GTX 1050 Ti) | `-ngl 28 -c 512` |
| 8GB | `-ngl 40 -c 2048` |
| 16GB+ | `-ngl 99 -c 4096` |

---

## Roadmap

- [ ] Wake word detection
- [ ] MCP tool integration (voice control over FusionAL — database, Slack, GitHub)
- [ ] Llama 3.2 3B for faster response on 4GB VRAM
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

**JRM** — Self-taught developer. Privacy-first AI engineering.
Building [FusionAL](https://github.com/TangMan69/FusionAL), mcp-consulting-kit, and Christopher from scratch.
