#!/usr/bin/env python3
"""
christopher.py - Local Voice AI Orchestrator
Connects whisper.cpp ASR + llama-server LLM + Piper TTS + FusionAL MCP tools

Modes:
  --chat   : text input/output (no mic, no TTS)
  --voice  : full voice pipeline (default)

Usage:
  python3 christopher.py --chat
  python3 christopher.py --voice
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import threading
import requests
from pathlib import Path
from dotenv import dotenv_values

# ── Config ────────────────────────────────────────────────────────────────────

ENV = dotenv_values(Path(__file__).parent / ".env")

LLAMA_SERVER_BIN  = os.path.expanduser("~/llama.cpp/build/bin/llama-server")
LLAMA_MODEL       = os.path.expanduser(ENV.get("LLAMA_MODEL", "~/llama.cpp/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf"))
LLAMA_SERVER_URL  = ENV.get("LLAMA_SERVER_URL", "http://localhost:8080")
LLAMA_NGL         = int(ENV.get("LLAMA_NGL", "99"))
LLAMA_THREADS     = int(ENV.get("LLAMA_THREADS", "4"))
LLAMA_CTX         = int(ENV.get("LLAMA_CTX", "2048"))

WHISPER_BIN       = os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli")
WHISPER_MODEL     = os.path.expanduser("~/whisper.cpp/models/ggml-base.en.bin")

PIPER_BIN         = "piper"
PIPER_MODEL       = os.path.expanduser("~/piper_models/en_US-libritts-high.onnx")
PIPER_CONFIG      = os.path.expanduser("~/piper_models/en_US-libritts-high.onnx.json")

FUSIONAL_API_KEY  = ENV.get("FUSIONAL_API_KEY", "")
BI_URL            = ENV.get("FUSIONAL_BI_URL", "http://localhost:8101")
API_URL           = ENV.get("FUSIONAL_API_URL", "http://localhost:8102")
CONTENT_URL       = ENV.get("FUSIONAL_CONTENT_URL", "http://localhost:8103")

LISTEN_SECONDS    = int(ENV.get("LISTEN_SECONDS", "5"))

# PulseAudio — resolved dynamically so it survives WSL2 reboots where host IP changes
PULSE_SERVER = os.environ.get("PULSE_SERVER", "tcp:172.24.128.1:4713")
PULSE_ENV    = {**os.environ, "PULSE_SERVER": PULSE_SERVER}

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Christopher, a local AI assistant. Be brief and direct.

RULES:
- Maximum 2 sentences per response unless more is truly needed
- Never explain your capabilities unless asked
- Never show tool syntax to the user — use tools silently
- No bullet points, no markdown, no lists

TOOLS — use when the task requires it, output on its own line:
TOOL_CALL: {"tool": "tool_name", "params": {"key": "value"}}

nl_query       - query a database in plain english. params: query, schema_hint(optional)
scrape_article - extract article text from a URL. params: url
scrape_links   - extract links from a page. params: url
parse_rss      - parse an RSS feed. params: url, limit(optional, default 10)
slack_send     - send a slack message. params: channel, text
github_create_issue - create github issue. params: owner, repo, title, body(optional)
stripe_customer_lookup - look up stripe customer. params: customer_id

After a tool runs you will receive: Tool result: <data>
Summarize the result naturally in 1-2 sentences. Do not show raw data."""


# ── Tool Router ───────────────────────────────────────────────────────────────

def call_tool(tool_name: str, params: dict) -> str:
    headers = {"X-API-Key": FUSIONAL_API_KEY, "Content-Type": "application/json"}
    try:
        if tool_name == "nl_query":
            r = requests.post(f"{BI_URL}/nl-query", json=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            rows = data.get("rows", [])
            sql = data.get("sql", "")
            if not rows:
                return f"Query returned no results. SQL: {sql}"
            return f"Query: {sql}\nResults ({len(rows)} rows): {json.dumps(rows[:5], indent=2)}"

        elif tool_name == "scrape_article":
            r = requests.post(f"{CONTENT_URL}/scrape/article", json=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            text = data.get("text", data.get("content", str(data)))
            return text[:2000] + ("..." if len(text) > 2000 else "")

        elif tool_name == "scrape_links":
            r = requests.post(f"{CONTENT_URL}/scrape/links", json=params, headers=headers, timeout=30)
            r.raise_for_status()
            links = r.json().get("links", [])
            return f"Found {len(links)} links: " + ", ".join(links[:10])

        elif tool_name == "parse_rss":
            r = requests.post(f"{CONTENT_URL}/rss/parse", json=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            entries = data.get("entries", [])
            summary = f"Feed: {data.get('feed_title', 'Unknown')}\n"
            for e in entries[:5]:
                summary += f"- {e.get('title', 'No title')}: {e.get('link', '')}\n"
            return summary

        elif tool_name == "slack_send":
            r = requests.post(f"{API_URL}/slack/send", json=params, headers=headers, timeout=15)
            r.raise_for_status()
            return f"Slack message sent to {params.get('channel')}"

        elif tool_name == "github_create_issue":
            r = requests.post(f"{API_URL}/github/create-issue", json=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            return f"GitHub issue created: {data.get('html_url', 'created successfully')}"

        elif tool_name == "stripe_customer_lookup":
            r = requests.post(f"{API_URL}/stripe/customer", json=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            customer = data.get("customer", {})
            return f"Customer: {customer.get('email', 'unknown')} | Charges: {len(data.get('charges', []))} | Subs: {len(data.get('subscriptions', []))}"

        else:
            return f"Unknown tool: {tool_name}"

    except requests.exceptions.ConnectionError:
        return "Tool error: FusionAL server not reachable. Is docker compose running?"
    except Exception as e:
        return f"Tool error: {e}"


# ── LLM Interface ─────────────────────────────────────────────────────────────

def wait_for_server(timeout=60):
    print("⏳ Waiting for llama-server...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{LLAMA_SERVER_URL}/health", timeout=2)
            if r.status_code == 200:
                print(" ready.")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(2)
    print(" TIMEOUT")
    return False


def start_llama_server():
    cmd = [
        LLAMA_SERVER_BIN,
        "-m", LLAMA_MODEL,
        "-ngl", str(LLAMA_NGL),
        "-t", str(LLAMA_THREADS),
        "-c", str(LLAMA_CTX),
        "--host", "127.0.0.1",
        "--port", "8080",
        "--log-disable",
    ]
    print(f"🚀 Starting llama-server (ngl={LLAMA_NGL}, ctx={LLAMA_CTX})...")
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def chat_completion(messages: list, max_tokens=300) -> str:
    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "top_p": 0.9,
        "stop": ["</s>", "[INST]", "User:", "You:"],
    }
    try:
        r = requests.post(
            f"{LLAMA_SERVER_URL}/v1/chat/completions",
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"LLM error: {e}"


def parse_tool_call(text: str):
    match = re.search(r'TOOL_CALL:\s*(\{.*?\})', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get("tool"), data.get("params", {})
        except json.JSONDecodeError:
            pass
    return None, None


def run_turn(messages: list, user_input: str, voice_mode: bool) -> str:
    messages.append({"role": "user", "content": user_input})
    response = chat_completion(messages)
    tool_name, tool_params = parse_tool_call(response)

    if tool_name:
        print(f"🔧 Tool call: {tool_name}({json.dumps(tool_params)})")
        tool_result = call_tool(tool_name, tool_params)
        print(f"📦 Result: {tool_result[:200]}{'...' if len(tool_result) > 200 else ''}")
        messages.append({"role": "assistant", "content": response})
        messages.append({
            "role": "user",
            "content": f"Tool result: {tool_result}\n\nNow summarize this result naturally"
                       + (" in one or two spoken sentences" if voice_mode else "") + "."
        })
        final_response = chat_completion(messages, max_tokens=200)
        messages.append({"role": "assistant", "content": final_response})
        return final_response
    else:
        messages.append({"role": "assistant", "content": response})
        return response


# ── Voice I/O ─────────────────────────────────────────────────────────────────

def listen(tmpdir: str) -> str:
    """Record mic via parec (PulseAudio) and transcribe with whisper.cpp.
    Uses parec instead of arecord — WSL2 has no ALSA soundcard.
    PULSE_SERVER env var must point at Windows PulseAudio TCP server.
    """
    raw_file        = os.path.join(tmpdir, "input.raw")
    audio_file      = os.path.join(tmpdir, "input.wav")
    transcript_base = os.path.join(tmpdir, "transcript")

    print(f"🔴 Listening {LISTEN_SECONDS}s...", end="", flush=True)

    rec_proc = subprocess.Popen(
        ["parec", "--format=s16le", "--rate=16000", "--channels=1", raw_file],
        env=PULSE_ENV,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(LISTEN_SECONDS)
    rec_proc.terminate()
    rec_proc.wait()
    print(" done")

    # Convert raw PCM -> WAV for whisper.cpp — sox first, ffmpeg as fallback
    conv = subprocess.run(
        ["sox", "-t", "raw", "-r", "16000", "-e", "signed", "-b", "16",
         "-c", "1", raw_file, audio_file],
        capture_output=True
    )
    if conv.returncode != 0:
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
    """Synthesize text with Piper and play via paplay (PulseAudio).
    Falls back to ffplay if paplay not available.
    """
    try:
        piper_proc = subprocess.Popen(
            [PIPER_BIN, "-m", PIPER_MODEL, "-c", PIPER_CONFIG, "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        play_proc = subprocess.Popen(
            ["paplay", "--raw", "--format=s16le", "--rate=22050", "--channels=1"],
            stdin=piper_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=PULSE_ENV,
        )
        piper_proc.stdin.write(text.encode())
        piper_proc.stdin.close()
        play_proc.wait()
    except FileNotFoundError:
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
    except Exception as e:
        print(f"TTS error: {e}")


# ── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Christopher — Local Voice AI")
    parser.add_argument("--chat",      action="store_true", help="Text chat mode (no mic/TTS)")
    parser.add_argument("--voice",     action="store_true", help="Full voice mode (default)")
    parser.add_argument("--no-server", action="store_true", help="Skip llama-server launch (already running)")
    args = parser.parse_args()

    voice_mode = not args.chat

    print("=" * 55)
    print("  Christopher — Local AI")
    print(f"  Mode: {'VOICE' if voice_mode else 'TEXT CHAT'}")
    print(f"  Model: {os.path.basename(LLAMA_MODEL)} | GPU layers: {LLAMA_NGL}")
    print(f"  FusionAL: {BI_URL} / {API_URL} / {CONTENT_URL}")
    if voice_mode:
        print(f"  PulseAudio: {PULSE_SERVER}")
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
    tmpdir   = tempfile.mkdtemp(prefix="christopher-")

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
