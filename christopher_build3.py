
# ── Voice I/O ─────────────────────────────────────────────────────────────────

def listen(tmpdir: str) -> str:
    """Record mic input via PulseAudio (parec) and transcribe with whisper.cpp.
    Uses parec instead of arecord — works in WSL2 where ALSA has no soundcard.
    Requires PULSE_SERVER env var pointing at Windows PulseAudio TCP server.
    """
    audio_file = os.path.join(tmpdir, "input.wav")
    transcript_base = os.path.join(tmpdir, "transcript")

    pulse_env = {
        **os.environ,
        "PULSE_SERVER": os.environ.get(
            "PULSE_SERVER",
            f"tcp:{os.environ.get('WINDOWS_HOST', '172.24.128.1')}:4713"
        )
    }

    print(f"🔴 Listening {LISTEN_SECONDS}s...", end="", flush=True)

    # parec records raw PCM to stdout; capture to file then convert to wav
    raw_file = os.path.join(tmpdir, "input.raw")
    rec_ok = False

    try:
        with open(raw_file, "wb") as raw_out:
            rec_proc = subprocess.Popen(
                ["parec", "--format=s16le", "--rate=16000", "--channels=1"],
                env=pulse_env,
                stdout=raw_out,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(LISTEN_SECONDS)
            rec_proc.terminate()
            rec_proc.wait(timeout=5)

        rec_ok = os.path.exists(raw_file) and os.path.getsize(raw_file) > 0
    except Exception:
        rec_ok = False

    if not rec_ok:
        try:
            subprocess.run(
                [
                    "arecord",
                    "-f", "S16_LE",
                    "-r", "16000",
                    "-c", "1",
                    "-d", str(LISTEN_SECONDS),
                    audio_file,
                ],
                check=True,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            print(" failed")
            return ""

    print(" done")

    if rec_ok:
        # Convert raw PCM to WAV so whisper.cpp can read it
        sox_result = subprocess.run(
            ["sox", "-t", "raw", "-r", "16000", "-e", "signed", "-b", "16",
             "-c", "1", raw_file, audio_file],
            capture_output=True
        )

        if sox_result.returncode != 0:
            # Fallback: use ffmpeg if sox not available
            subprocess.run(
                ["ffmpeg", "-y", "-f", "s16le", "-ar", "16000", "-ac", "1",
                 "-i", raw_file, audio_file],
                capture_output=True
            )

    if not os.path.exists(audio_file):
        return ""

    subprocess.run(
        [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", audio_file,
         "--output-txt", "--output-file", transcript_base,
         "--no-timestamps", "-t", "4"],
        capture_output=True
    )

    txt_file = transcript_base + ".txt"
    if os.path.exists(txt_file):
        return open(txt_file).read().strip()
    return ""


def speak(text: str):
    """Synthesize text with Piper and play via paplay (PulseAudio) or ffplay."""
    pulse_env = {
        **os.environ,
        "PULSE_SERVER": os.environ.get(
            "PULSE_SERVER",
            f"tcp:{os.environ.get('WINDOWS_HOST', '172.24.128.1')}:4713"
        )
    }
    try:
        piper_proc = subprocess.Popen(
            [PIPER_BIN, "-m", PIPER_MODEL, "-c", PIPER_CONFIG, "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        # Try paplay first (native PulseAudio, respects PULSE_SERVER)
        play_proc = subprocess.Popen(
            ["paplay", "--raw", "--format=s16le", "--rate=22050", "--channels=1"],
            stdin=piper_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=pulse_env,
        )
        piper_proc.stdin.write(text.encode())
        piper_proc.stdin.close()
        play_proc.wait()
    except FileNotFoundError:
        # paplay not available — fall back to ffplay
        try:
            piper_proc = subprocess.Popen(
                [PIPER_BIN, "-m", PIPER_MODEL, "-c", PIPER_CONFIG, "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            ffplay_proc = subprocess.Popen(
                ["ffplay", "-f", "s16le", "-ar", "22050", "-ac", "1",
                 "-nodisp", "-autoexit", "-"],
                stdin=piper_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            piper_proc.stdin.write(text.encode())
            piper_proc.stdin.close()
            ffplay_proc.wait()
        except Exception as e:
            print(f"TTS error: {e}")


# ── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Christopher — Local Voice AI")
    parser.add_argument("--chat", action="store_true", help="Text chat mode (no mic/TTS)")
    parser.add_argument("--voice", action="store_true", help="Full voice mode (default)")
    parser.add_argument("--no-server", action="store_true", help="Skip llama-server launch (already running)")
    args = parser.parse_args()

    voice_mode = not args.chat

    print("=" * 55)
    print("  Christopher — Local AI")
    print(f"  Mode: {'VOICE' if voice_mode else 'TEXT CHAT'}")
    print(f"  Model: {os.path.basename(LLAMA_MODEL)} | GPU layers: {LLAMA_NGL}")
    print(f"  FusionAL: {BI_URL} / {API_URL} / {CONTENT_URL}")
    if voice_mode:
        pulse = os.environ.get('PULSE_SERVER', 'not set')
        print(f"  PulseAudio: {pulse}")
    print("=" * 55)
    print()

    server_proc = None
    if not args.no_server:
        server_proc = start_llama_server()
        if not wait_for_server(timeout=90):
            print("❌ llama-server failed to start. Check your model path.")
            sys.exit(1)
    else:
        print("⚡ Using existing llama-server")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    tmpdir = tempfile.mkdtemp(prefix="christopher-")

    print("💬 Christopher is ready. Type 'quit' to exit.\n")

    try:
        while True:
            if voice_mode:
                user_input = listen(tmpdir)
                if not user_input:
                    print("⚠️  No speech detected")
                    continue
                print(f"👤 You: {user_input}")
            else:
                try:
                    user_input = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit", "bye"):
                    print("Christopher: Goodbye.")
                    break

            response = run_turn(messages, user_input, voice_mode)
            print(f"🤖 Christopher: {response}\n")

            if voice_mode:
                speak(response)

            if len(messages) > 20:
                messages = [messages[0]] + messages[-10:]

    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
        if server_proc:
            print("Stopping llama-server...")
            server_proc.terminate()
            server_proc.wait()


if __name__ == "__main__":
    main()
