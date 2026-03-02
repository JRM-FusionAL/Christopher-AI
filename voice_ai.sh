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

detect_windows_host() {
    if [ -n "${WINDOWS_HOST:-}" ]; then
        echo "$WINDOWS_HOST"
        return
    fi

    if [ -f /etc/resolv.conf ]; then
        awk '/^nameserver / { print $2; exit }' /etc/resolv.conf
        return
    fi

    echo "127.0.0.1"
}

can_reach_pulse() {
    local host="$1"
    timeout 1 bash -c "cat < /dev/null > /dev/tcp/${host}/4713" >/dev/null 2>&1
}

choose_pulse_server() {
    local candidates=()
    local env_host=""

    if [ -n "${PULSE_SERVER:-}" ]; then
        env_host="${PULSE_SERVER#tcp:}"
        env_host="${env_host%%:*}"
        [ -n "$env_host" ] && candidates+=("$env_host")
    fi

    candidates+=("$(detect_windows_host)")

    if command -v ip >/dev/null 2>&1; then
        local gw
        gw="$(ip route 2>/dev/null | awk '/^default/ {print $3; exit}')"
        [ -n "$gw" ] && candidates+=("$gw")
    fi

    candidates+=("host.docker.internal" "127.0.0.1" "localhost")

    local seen=""
    local host
    for host in "${candidates[@]}"; do
        [ -z "$host" ] && continue
        case " $seen " in
            *" $host "*) continue ;;
        esac
        seen="$seen $host"

        if can_reach_pulse "$host"; then
            echo "tcp:${host}:4713"
            return
        fi
    done

    echo "tcp:$(detect_windows_host):4713"
}

WINDOWS_HOST=$(detect_windows_host)
export PULSE_SERVER="$(choose_pulse_server)"

record_audio() {
    local out_wav="$1"
    local raw_file="$TMPDIR_AI/input.raw"

    rm -f "$raw_file" "$out_wav"

    if command -v parec >/dev/null 2>&1 && command -v ffmpeg >/dev/null 2>&1; then
        if timeout "${LISTEN_SECONDS:-5}" parec --format=s16le --rate=16000 --channels=1 > "$raw_file" 2>/dev/null; then
            ffmpeg -y -f s16le -ar 16000 -ac 1 -i "$raw_file" "$out_wav" >/dev/null 2>&1 || true
            if [ -s "$out_wav" ]; then
                return 0
            fi
        fi
    fi

    if command -v arecord >/dev/null 2>&1; then
        if arecord -f S16_LE -r 16000 -c 1 -d "${LISTEN_SECONDS:-5}" "$out_wav" 2>/dev/null; then
            [ -s "$out_wav" ] && return 0
        fi
    fi

    return 1
}

echo "Voice AI | Mistral 7B Q4_K_M | GTX 1050 Ti CUDA | Ctrl+C to exit"

while true; do
    echo "Listening 5s..."
    if ! record_audio "$TMPDIR_AI/input.wav"; then
        echo "Audio capture failed (PulseAudio/ALSA unavailable)."
        echo "Tip: start Windows PulseAudio and ensure PULSE_SERVER is reachable."
        continue
    fi

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
