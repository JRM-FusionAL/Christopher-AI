#!/usr/bin/env bash
# preflight_voice.sh
# Quick health check for Christopher voice pipeline on Linux/WSL

set -u

WHISPER_BIN="${WHISPER_BIN:-$HOME/whisper.cpp/build/bin/whisper-cli}"
WHISPER_MODEL="${WHISPER_MODEL:-$HOME/whisper.cpp/models/ggml-base.en.bin}"
LLAMA_BIN="${LLAMA_BIN:-$HOME/llama.cpp/build/bin/llama-cli}"
PIPER_BIN="${PIPER_BIN:-piper}"
LISTEN_SECONDS="${LISTEN_SECONDS:-2}"
# If PAREC_DEVICE is set (e.g. from .env), pass it to parec to avoid monitor source
PAREC_DEVICE="${PAREC_DEVICE:-}"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

pass() { echo "[OK]   $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
warn() { echo "[WARN] $1"; WARN_COUNT=$((WARN_COUNT + 1)); }
fail() { echo "[FAIL] $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

section() { echo; echo "== $1 =="; }

is_wsl() {
  grep -qi microsoft /proc/version 2>/dev/null
}

detect_windows_host() {
  if [[ -n "${WINDOWS_HOST:-}" ]]; then
    echo "$WINDOWS_HOST"; return
  fi
  awk '/^nameserver / { print $2; exit }' /etc/resolv.conf 2>/dev/null || echo "127.0.0.1"
}

can_reach_pulse_tcp() {
  local host="$1"
  timeout 1 bash -c "cat < /dev/null > /dev/tcp/${host}/4713" >/dev/null 2>&1
}

choose_pulse_server() {
  # Honour explicit override
  if [[ -n "${PULSE_SERVER:-}" ]]; then
    echo "$PULSE_SERVER"; return
  fi

  # Native Linux: check for local user socket first
  local sock="/run/user/$(id -u)/pulse/native"
  if [[ -S "$sock" ]]; then
    echo "unix:$sock"; return
  fi

  # WSL2: try Windows host over TCP
  if is_wsl; then
    local candidates=()
    candidates+=("$(detect_windows_host)")
    if command -v ip >/dev/null 2>&1; then
      local gw
      gw="$(ip route 2>/dev/null | awk '/^default/ {print $3; exit}')"
      [[ -n "$gw" ]] && candidates+=("$gw")
    fi
    candidates+=("host.docker.internal" "127.0.0.1" "localhost")
    local host
    for host in "${candidates[@]}"; do
      [[ -z "$host" ]] && continue
      if can_reach_pulse_tcp "$host"; then
        echo "tcp:${host}:4713"; return
      fi
    done
    echo "tcp:$(detect_windows_host):4713"
    return
  fi

  # Native Linux fallback: localhost TCP (in case daemon is on TCP)
  echo ""
}

cleanup() {
  [[ -n "${TMPDIR_AI:-}" && -d "$TMPDIR_AI" ]] && rm -rf "$TMPDIR_AI"
}
trap cleanup EXIT

TMPDIR_AI="$(mktemp -d)"
RAW_FILE="$TMPDIR_AI/input.raw"
WAV_FILE="$TMPDIR_AI/input.wav"
TRANSCRIPT_BASE="$TMPDIR_AI/transcript"

section "Environment"
if is_wsl; then
  WINDOWS_HOST="$(detect_windows_host)"
  echo "Environment: WSL2 (Windows host: $WINDOWS_HOST)"
else
  echo "Environment: native Linux"
fi
RESOLVED_PULSE="$(choose_pulse_server)"
if [[ -n "$RESOLVED_PULSE" ]]; then
  export PULSE_SERVER="$RESOLVED_PULSE"
fi
echo "PULSE_SERVER=${PULSE_SERVER:-<using daemon default>}"

section "Binaries + Models"
[[ -x "$WHISPER_BIN" ]] && pass "whisper-cli found: $WHISPER_BIN" || fail "whisper-cli missing or not executable: $WHISPER_BIN"
[[ -f "$WHISPER_MODEL" ]] && pass "Whisper model found: $WHISPER_MODEL" || fail "Whisper model missing: $WHISPER_MODEL"
[[ -x "$LLAMA_BIN" ]] && pass "llama-cli found: $LLAMA_BIN" || warn "llama-cli not found at expected path: $LLAMA_BIN"
command -v "$PIPER_BIN" >/dev/null 2>&1 && pass "piper found in PATH" || warn "piper not found in PATH"
command -v ffmpeg >/dev/null 2>&1 && pass "ffmpeg found" || warn "ffmpeg missing (needed for robust wav conversion)"

section "Audio Input"
CAPTURE_BACKEND="none"

if command -v parec >/dev/null 2>&1; then
  # Mirror christopher.py: background + sleep + SIGTERM (timeout can swallow the exit flush)
  # Use explicit PAREC_DEVICE if set to avoid defaulting to the monitor (loopback) source
  PAREC_CMD=(parec --format=s16le --rate=16000 --channels=1)
  [[ -n "$PAREC_DEVICE" ]] && PAREC_CMD+=(--device "$PAREC_DEVICE")
  PAREC_CMD+=("$RAW_FILE")
  "${PAREC_CMD[@]}" 2>/dev/null &
  PAREC_PID=$!
  sleep "$LISTEN_SECONDS"
  kill -TERM "$PAREC_PID" 2>/dev/null
  wait "$PAREC_PID" 2>/dev/null
  if [[ -s "$RAW_FILE" ]]; then
    CAPTURE_BACKEND="parec"
    pass "Mic capture works via PulseAudio (parec${PAREC_DEVICE:+ device=$PAREC_DEVICE})"
  else
    warn "parec captured empty audio (PulseAudio may not be reachable or no mic connected)"
  fi
else
  warn "parec not installed"
fi

if [[ "$CAPTURE_BACKEND" == "none" ]] && command -v arecord >/dev/null 2>&1; then
  if arecord -f S16_LE -r 16000 -c 1 -d "$LISTEN_SECONDS" "$WAV_FILE" >/dev/null 2>&1; then
    if [[ -s "$WAV_FILE" ]]; then
      CAPTURE_BACKEND="arecord"
      pass "Mic capture works via ALSA (arecord)"
    else
      warn "arecord returned but captured empty audio"
    fi
  else
    warn "arecord capture failed"
  fi
fi

[[ "$CAPTURE_BACKEND" == "none" ]] && fail "No working microphone capture backend found"

section "ASR Smoke Test"
if [[ "$CAPTURE_BACKEND" == "parec" ]]; then
  if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -f s16le -ar 16000 -ac 1 -i "$RAW_FILE" "$WAV_FILE" >/dev/null 2>&1 || true
  elif command -v sox >/dev/null 2>&1; then
    sox -t raw -r 16000 -e signed -b 16 -c 1 "$RAW_FILE" "$WAV_FILE" >/dev/null 2>&1 || true
  fi
fi

if [[ -s "$WAV_FILE" && -x "$WHISPER_BIN" && -f "$WHISPER_MODEL" ]]; then
  if "$WHISPER_BIN" -m "$WHISPER_MODEL" -f "$WAV_FILE" --output-txt --output-file "$TRANSCRIPT_BASE" --no-timestamps -t 4 ${WHISPER_NO_GPU:+-ng} >/dev/null 2>&1; then
    if [[ -f "${TRANSCRIPT_BASE}.txt" ]]; then
      pass "Whisper ASR executed successfully"
    else
      warn "Whisper ran but transcript file was not produced"
    fi
  else
    fail "Whisper ASR execution failed"
  fi
else
  warn "Skipping ASR smoke test (no wav captured or missing Whisper assets)"
fi

section "Audio Output"
if command -v paplay >/dev/null 2>&1; then
  if head -c 22050 /dev/zero | paplay --raw --format=s16le --rate=22050 --channels=1 >/dev/null 2>&1; then
    pass "Playback path works via paplay"
  else
    warn "paplay exists but playback test failed"
  fi
elif command -v ffplay >/dev/null 2>&1; then
  if ffplay -f lavfi -i anullsrc=r=22050:cl=mono -t 0.3 -nodisp -autoexit >/dev/null 2>&1; then
    pass "Playback path works via ffplay"
  else
    warn "ffplay exists but playback test failed"
  fi
else
  warn "No playback tool found (paplay or ffplay)"
fi

section "Summary"
echo "Pass: $PASS_COUNT | Warn: $WARN_COUNT | Fail: $FAIL_COUNT"

if [[ $FAIL_COUNT -gt 0 ]]; then
  echo
  echo "Fixes to try:"
  if is_wsl; then
    echo "1) Start Windows PulseAudio: C:\\PulseAudio\\start-pulseaudio.cmd"
    echo "2) Export PULSE_SERVER in WSL:"
    echo "   export PULSE_SERVER=tcp:\$(awk '/^nameserver / {print \$2; exit}' /etc/resolv.conf):4713"
  else
    echo "1) Install PulseAudio:  sudo apt install pulseaudio"
    echo "2) Start the daemon:    pulseaudio --start"
    echo "   (or install as user service: systemctl --user enable --now pulseaudio)"
    echo "3) For SSH audio forwarding from your client machine:"
    echo "   - Client: pactl load-module module-native-protocol-tcp auth-anonymous=1"
    echo "   - SSH:     ssh -R 4713:localhost:4713 user@thishost"
    echo "   - Server:  export PULSE_SERVER=tcp:localhost:4713"
  fi
  echo
  echo "Re-run: ./preflight_voice.sh"
  exit 1
fi

echo "Voice preflight passed. You can now run ./voice_ai.sh"
exit 0
