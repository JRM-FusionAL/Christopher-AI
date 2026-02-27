#!/bin/bash
# voice_ai.sh - Local Voice AI Pipeline
# whisper.cpp ASR + llama.cpp CUDA LLM + Piper TTS
# GTX 1050 Ti: -ngl 35 offloads 35 layers to VRAM -> 15-25 tok/s

set -euo pipefail

WHISPER_BIN=~/whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL=~/whisper.cpp/models/ggml-base.en.bin
LLAMA_BIN=~/llama.cpp/build/bin/llama-cli
LLAMA_MODEL=~/llama.cpp/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf
PIPER_MODEL=~/piper_models/en_US-libritts-high.onnx
PIPER_CONFIG=~/piper_models/en_US-libritts-high.onnx.json

TMPDIR_AI=$(mktemp -d)
trap 'rm -rf $TMPDIR_AI' EXIT

SYSTEM="You are a helpful voice assistant. Keep responses under 3 sentences. No markdown. Speak naturally."

echo "Voice AI | Mistral 7B Q4_K_M | GTX 1050 Ti CUDA | Ctrl+C to exit"

while true; do
    echo "Listening 5s..."
    arecord -f S16_LE -r 16000 -c 1 -d 5 $TMPDIR_AI/input.wav 2>/dev/null

    $WHISPER_BIN -m $WHISPER_MODEL -f $TMPDIR_AI/input.wav \
        --output-txt --output-file $TMPDIR_AI/transcript \
        --no-timestamps -t 4 2>/dev/null

    TEXT=$(cat $TMPDIR_AI/transcript.txt 2>/dev/null | xargs)
    [ -z "$TEXT" ] && echo "No speech detected" && continue
    echo "You: $TEXT"

    $LLAMA_BIN -m $LLAMA_MODEL \
        -ngl 35 -t 4 -c 2048 -n 150 \
        --temp 0.7 --top-p 0.9 \
        --no-display-prompt --log-disable \
        -p "[INST] $SYSTEM

$TEXT [/INST]" 2>/dev/null > $TMPDIR_AI/reply.txt

    REPLY=$(cat $TMPDIR_AI/reply.txt | xargs)
    echo "AI: $REPLY"

    echo "$REPLY" \
        | piper -m $PIPER_MODEL -c $PIPER_CONFIG --output-raw \
        | ffplay -f s16le -ar 22050 -ac 1 -nodisp -autoexit - 2>/dev/null
    echo ""
done
