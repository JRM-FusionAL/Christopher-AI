#!/usr/bin/env python3
"""
christopher.py - Local Voice AI Orchestrator
Connects whisper.cpp ASR + llama-server LLM + Piper TTS + FusionAL MCP tools

Modes:
  --chat   : text input/output (no mic, no TTS)
  --voice  : full voice pipeline (default)
  --server : OpenAI-compatible HTTP server for OpenClaw/Telegram integration

Usage:
  python3 christopher.py --chat
  python3 christopher.py --voice
  python3 christopher.py --server --server-port 8090
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import requests
import scipy.io.wavfile as wavfile
from pathlib import Path
from dotenv import dotenv_values
if sys.platform != "win32":
    import fcntl

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    import uvicorn
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

# ── Config ────────────────────────────────────────────────────────────────────

ENV = dotenv_values(Path(__file__).parent / ".env")

MODEL_PROFILES = {
    "llama32-3b": {
        "label": "Llama 3.2 3B Instruct Q4_K_M",
        "default_ngl": 99,
        "default_ctx": 2048,
        "candidates": [
            ENV.get("LLAMA_MODEL_LLAMA32_3B", ""),
            "~/llama.cpp/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "/home/oledad/llama.cpp/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "/data/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        ],
    },
    "qwen25-3b": {
        "label": "Qwen2.5 3B Instruct Q4_K_M",
        "default_ngl": 99,
        "default_ctx": 2048,
        "candidates": [
            ENV.get("LLAMA_MODEL_QWEN25_3B", ""),
            "~/llama.cpp/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
            "/home/oledad/llama.cpp/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
            "/data/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        ],
    },
    "mistral-7b": {
        "label": "Mistral 7B Instruct v0.2 Q4_K_M",
        "default_ngl": 28,
        "default_ctx": 512,
        "candidates": [
            ENV.get("LLAMA_MODEL_MISTRAL_7B", ""),
            "~/llama.cpp/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
            "/home/oledad/llama.cpp/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
            "/data/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        ],
    },
}

DEFAULT_MODEL_PROFILE = ENV.get("MODEL_PROFILE", "llama32-3b")


def _expand(path: str) -> str:
    return os.path.expanduser(os.path.expandvars(path))


def _first_existing_path(candidates: list[str]) -> str:
    first_non_empty = ""
    for raw in candidates:
        if not raw:
            continue
        candidate = _expand(raw)
        if not first_non_empty:
            first_non_empty = candidate
        if Path(candidate).exists():
            return candidate
    return first_non_empty


def _which_any(candidates: list[str], fallback: str = "") -> str:
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    return fallback


def _resolve_model_path(profile: str, explicit_path: str = "") -> str:
    profile_data = MODEL_PROFILES.get(profile, MODEL_PROFILES[DEFAULT_MODEL_PROFILE])
    return _first_existing_path([explicit_path, *profile_data["candidates"]])


def _profile_default(profile: str, key: str) -> int:
    profile_data = MODEL_PROFILES.get(profile, MODEL_PROFILES[DEFAULT_MODEL_PROFILE])
    return int(profile_data[key])

LLAMA_SERVER_BIN  = _first_existing_path([
    ENV.get("LLAMA_SERVER_BIN", ""),
    "~/llama.cpp/build/bin/llama-server",
    "~/llama.cpp/build/bin/llama-server.exe",
    "/home/oledad/llama.cpp/build/bin/llama-server",
])
CURRENT_MODEL_PROFILE = DEFAULT_MODEL_PROFILE
LLAMA_MODEL       = _resolve_model_path(CURRENT_MODEL_PROFILE, ENV.get("LLAMA_MODEL", ""))
LLAMA_SERVER_URL  = ENV.get("LLAMA_SERVER_URL", "http://localhost:8080")
LLAMA_NGL         = int(ENV.get("LLAMA_NGL", str(_profile_default(CURRENT_MODEL_PROFILE, "default_ngl"))))
LLAMA_THREADS     = int(ENV.get("LLAMA_THREADS", "4"))
LLAMA_CTX         = int(ENV.get("LLAMA_CTX", str(_profile_default(CURRENT_MODEL_PROFILE, "default_ctx"))))

WHISPER_BIN       = _first_existing_path([
    ENV.get("WHISPER_BIN", ""),
    "~/whisper.cpp/build/bin/whisper-cli",
    "~/whisper.cpp/build/bin/whisper-cli.exe",
    "/home/oledad/whisper.cpp/build/bin/whisper-cli",
])
WHISPER_MODEL     = _first_existing_path([
    ENV.get("WHISPER_MODEL", ""),
    "~/whisper.cpp/models/ggml-base.en.bin",
    "/home/oledad/whisper.cpp/models/ggml-base.en.bin",
])

PIPER_BIN         = _which_any([ENV.get("PIPER_BIN", ""), "piper", "piper.exe"], fallback="piper")
PIPER_MODEL       = _first_existing_path([
    ENV.get("PIPER_MODEL", ""),
    "~/piper_models/en_US-libritts-high.onnx",
    "/home/oledad/piper_models/en_US-libritts-high.onnx",
])
PIPER_CONFIG      = _first_existing_path([
    ENV.get("PIPER_CONFIG", ""),
    "~/piper_models/en_US-libritts-high.onnx.json",
    "/home/oledad/piper_models/en_US-libritts-high.onnx.json",
])

FUSIONAL_API_KEY  = ENV.get("FUSIONAL_API_KEY", "")
BI_URL            = ENV.get("FUSIONAL_BI_URL", "http://localhost:8101")
API_URL           = ENV.get("FUSIONAL_API_URL", "http://localhost:8102")
CONTENT_URL       = ENV.get("FUSIONAL_CONTENT_URL", "http://localhost:8103")
KNOWLEDGE_BASE_ROOT = ENV.get("KNOWLEDGE_BASE_ROOT", "C:/Users/puddi/Projects/fusional-knowledge-base")
KB_MAX_TOTAL_CHARS = int(ENV.get("KB_MAX_TOTAL_CHARS", "2800"))
KB_MAX_FILE_CHARS = int(ENV.get("KB_MAX_FILE_CHARS", "1400"))

LISTEN_SECONDS    = int(ENV.get("LISTEN_SECONDS", "5"))

# PulseAudio — resolved dynamically so it survives WSL2 reboots where host IP changes
PULSE_SERVER = os.environ.get("PULSE_SERVER", "tcp:172.24.128.1:4713")
PULSE_ENV    = {**os.environ, "PULSE_SERVER": PULSE_SERVER}

# ── Logging ───────────────────────────────────────────────────────────────────

_LOG_FILE = Path(__file__).parent / "christopher.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Christopher, a local AI assistant. Be brief and direct.

RULES:
- Maximum 2 sentences per response unless more is truly needed
- Never explain your capabilities unless asked
- Never repeat TOOL_CALL lines in your final response to the user
- No bullet points, no markdown, no lists
- Output ONLY the TOOL_CALL line, then STOP. Never write "Tool result:" yourself.

TOOLS — use when the task requires it, output on its own line, then stop:
TOOL_CALL: {"tool": "tool_name", "params": {"key": "value"}}

nl_query            - query a SQL database only. params: query, schema_hint(optional)
                      Use ONLY for business data, metrics, revenue. NOT for web content.
scrape_article      - extract article text from a URL. params: url
scrape_links        - extract all links from a page. params: url
parse_rss           - fetch headlines from any RSS feed. params: url, limit(optional)
                      Hacker News: https://news.ycombinator.com/rss
                      Reddit: https://www.reddit.com/r/SUBREDDIT/.rss
slack_send          - send a slack message. params: channel, text
github_create_issue - create github issue. params: owner, repo, title, body(optional)
stripe_customer_lookup - look up stripe customer. params: customer_id

After a tool runs you will receive: Tool result: <data>
Summarize the result naturally in 1-2 sentences. Do not show raw data."""


def load_knowledge_context(kb_root_override: str = "") -> tuple[str, list[str]]:
    """Load and compact FusionAL status/priorities within char limits.

    Returns: (context_text, loaded_files_list)
    """
    _kb_cache = {}
    _kb_cache_time = getattr(load_knowledge_context, '_cache_time', 0)

    if time.time() - _kb_cache_time > 300:  # 5 min cache
        kb_root_raw = kb_root_override or str(KNOWLEDGE_BASE_ROOT or "")

        if not kb_root_raw:
            logger.warning("Knowledge base root not configured")
            return "", []

        kb_root = Path(_expand(kb_root_raw))
        files = [
            kb_root / "00-CURRENT-STATUS" / "STATUS.md",
            kb_root / "00-CURRENT-STATUS" / "PRIORITIES.md",
        ]

        loaded_files = []
        sections = []
        current_total = 0

        for file_path in files:
            if not file_path.exists():
                logger.debug(f"KB file not found: {file_path}")
                continue

            try:
                # Acquire file lock for reading (Unix-like systems only; Windows uses OS-level locking)
                with open(file_path, 'r', encoding="utf-8") as fh:
                    try:
                        if sys.platform != "win32":  # Unix-like systems
                            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)  # Shared lock
                        status_content = fh.read().strip()
                        if sys.platform != "win32":
                            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                    except (IOError, OSError) as lock_e:
                        logger.warning(f"Could not lock KB file {file_path}: {lock_e}")
                        status_content = fh.read().strip()

                if not status_content:
                    continue

                section = f"# {file_path.name}\n{status_content}"
                projected_total = current_total + len(section) + 2

                if projected_total > KB_MAX_TOTAL_CHARS:
                    remaining = max(0, KB_MAX_TOTAL_CHARS - current_total - 2)
                    if remaining <= 0:
                        break
                    section = section[:remaining]
                    sections.append(section)
                    loaded_files.append(str(file_path))
                    logger.info(f"KB truncated at {file_path.name}")
                    break

                loaded_files.append(str(file_path))
                sections.append(section)
                current_total += len(section) + 2

            except UnicodeDecodeError as e:
                logger.warning(f"KB file {file_path} has invalid encoding: {e}")
            except Exception as e:
                logger.error(f"Failed to load KB file {file_path}: {e}")

        if sections:
            _kb_cache['context'] = "\n\n".join(sections)
            _kb_cache['files'] = loaded_files
        else:
            _kb_cache['context'] = ""
            _kb_cache['files'] = loaded_files

        load_knowledge_context._cache_time = time.time()
        load_knowledge_context._cache = _kb_cache

    cache = getattr(load_knowledge_context, '_cache', _kb_cache)
    return cache.get('context', ''), cache.get('files', [])


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
            if "limit" in params:
                params["limit"] = int(params["limit"])
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
        logger.error(f"tool={tool_name} connection_error FusionAL server not reachable")
        return "Tool error: FusionAL server not reachable. Is docker compose running?"
    except Exception as e:
        logger.error(f"tool={tool_name} error={e}")
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


def is_server_reachable(timeout=3) -> bool:
    try:
        r = requests.get(f"{LLAMA_SERVER_URL}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def start_llama_server():
    from urllib.parse import urlparse
    parsed = urlparse(LLAMA_SERVER_URL)
    server_host = parsed.hostname or "127.0.0.1"
    server_port = str(parsed.port or 8080)
    cmd = [
        LLAMA_SERVER_BIN,
        "-m", LLAMA_MODEL,
        "-ngl", str(LLAMA_NGL),
        "-t", str(LLAMA_THREADS),
        "-c", str(LLAMA_CTX),
        "--host", server_host,
        "--port", server_port,
        "--log-disable",
    ]
    print(f"🚀 Starting llama-server (ngl={LLAMA_NGL}, ctx={LLAMA_CTX})...")
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def configure_model_runtime(profile: str, model_path: str = "", ngl: int | None = None, ctx: int | None = None):
    global CURRENT_MODEL_PROFILE, LLAMA_MODEL, LLAMA_NGL, LLAMA_CTX

    if profile not in MODEL_PROFILES:
        raise ValueError(f"Unknown model profile: {profile}")

    CURRENT_MODEL_PROFILE = profile
    LLAMA_MODEL = _resolve_model_path(profile, model_path or ENV.get("LLAMA_MODEL", ""))
    LLAMA_NGL = int(ngl if ngl is not None else ENV.get("LLAMA_NGL", str(_profile_default(profile, "default_ngl"))))
    LLAMA_CTX = int(ctx if ctx is not None else ENV.get("LLAMA_CTX", str(_profile_default(profile, "default_ctx"))))


def run_benchmark(prompt: str, runs: int):
    latencies = []
    print(f"🧪 Benchmarking profile={CURRENT_MODEL_PROFILE} model={os.path.basename(LLAMA_MODEL)}")
    print(f"   prompt={prompt!r}")

    for index in range(1, runs + 1):
        messages = [
            {"role": "system", "content": "You are Christopher. Be brief and direct."},
            {"role": "user", "content": prompt},
        ]
        started = time.perf_counter()
        response = chat_completion(messages, max_tokens=120)
        elapsed = time.perf_counter() - started
        latencies.append(elapsed)
        print(f"Run {index}: {elapsed:.2f}s | {response[:120]}")

    average = sum(latencies) / len(latencies)
    fastest = min(latencies)
    slowest = max(latencies)
    print()
    print(f"Average: {average:.2f}s | Fastest: {fastest:.2f}s | Slowest: {slowest:.2f}s")


def validate_runtime(voice_mode: bool, skip_server_start: bool) -> list[str]:
    problems = []

    if not skip_server_start:
        if not Path(LLAMA_SERVER_BIN).exists():
            problems.append(f"LLAMA_SERVER_BIN not found: {LLAMA_SERVER_BIN}")
        if not Path(LLAMA_MODEL).exists():
            problems.append(f"LLAMA_MODEL not found: {LLAMA_MODEL}")

    if voice_mode:
        if not Path(WHISPER_BIN).exists():
            problems.append(f"WHISPER_BIN not found: {WHISPER_BIN}")
        if not Path(WHISPER_MODEL).exists():
            problems.append(f"WHISPER_MODEL not found: {WHISPER_MODEL}")
        if not Path(PIPER_MODEL).exists():
            problems.append(f"PIPER_MODEL not found: {PIPER_MODEL}")
        if not Path(PIPER_CONFIG).exists():
            problems.append(f"PIPER_CONFIG not found: {PIPER_CONFIG}")

    return problems


def chat_completion(messages: list, max_tokens: int = 300) -> str:
    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "top_p": 0.9,
        "stop": ["</s>", "[INST]", "User:", "You:", "Tool result:", "TOOL_RESULT:"],
    }
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.post(
            f"{LLAMA_SERVER_URL}/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=120,
        )
        r.raise_for_status()
        logger.debug(f"chat_completion tokens={r.json().get('usage', {}).get('completion_tokens', 'unknown')}")
        return r.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.Timeout:
        logger.error("LLM timeout after 120s")
        return "LLM error: Request timed out"
    except requests.exceptions.ConnectionError:
        logger.error(f"LLM connection failed to {LLAMA_SERVER_URL}")
        return f"LLM error: Cannot reach {LLAMA_SERVER_URL}"
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return f"LLM error: {e}"


def parse_tool_call(text: str):
    match = re.search(r'TOOL_CALL:\s*(\{.*\})', text, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get("tool"), data.get("params", {})
        except json.JSONDecodeError:
            pass
    return None, None


def run_turn(messages: list, user_input: str, voice_mode: bool) -> str:
    """Execute one conversation turn: send message, handle tool calling."""
    messages.append({"role": "user", "content": user_input})
    response = chat_completion(messages)
    tool_name, tool_params = parse_tool_call(response)

    if tool_name:
        print(f"🔧 Tool call: {tool_name}({json.dumps(tool_params)})")
        logger.info(f"tool_call tool={tool_name} params={json.dumps(tool_params)}")
        tool_result = call_tool(tool_name, tool_params)
        logger.info(f"tool_result tool={tool_name} result_len={len(tool_result)}")
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

    try:
        rec_proc = subprocess.Popen(
            ["parec", "--format=s16le", "--rate=16000", "--channels=1", raw_file],
            env=PULSE_ENV,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(LISTEN_SECONDS)
        rec_proc.terminate()
        try:
            rec_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            logger.warning("parec did not terminate gracefully, killing")
            rec_proc.kill()
            rec_proc.wait()
        print(" done")
    except FileNotFoundError:
        logger.error("parec binary not found - PulseAudio not installed or not in PATH")
        return ""
    except Exception as e:
        logger.error(f"Audio recording failed: {e}")
        return ""

    if not os.path.exists(raw_file):
        logger.error("Recording produced no audio file")
        return ""

    # Convert raw PCM -> WAV for whisper.cpp — sox first, ffmpeg as fallback
    try:
        conv = subprocess.run(
            ["sox", "-t", "raw", "-r", "16000", "-e", "signed", "-b", "16",
             "-c", "1", raw_file, audio_file],
            capture_output=True,
            timeout=10
        )
        if conv.returncode != 0:
            logger.debug(f"sox failed ({conv.returncode}), trying ffmpeg")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "s16le", "-ar", "16000", "-ac", "1",
                     "-i", raw_file, audio_file],
                    capture_output=True,
                    timeout=10
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                logger.error(f"ffmpeg failed: {e}, cannot convert audio")
                return ""
    except subprocess.TimeoutExpired:
        logger.error("Audio conversion timeout")
        return ""

    if not os.path.exists(audio_file):
        logger.error("Audio conversion produced no output file")
        return ""

    try:
        proc = subprocess.run(
            [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", audio_file,
             "--output-txt", "--output-file", transcript_base,
             "--no-timestamps", "-t", "4"],
            capture_output=True,
            timeout=30
        )
        if proc.returncode != 0:
            logger.warning(f"whisper.cpp exited with code {proc.returncode}")
            logger.debug(f"whisper stderr: {proc.stderr.decode('utf-8', errors='ignore')[:200]}")
    except FileNotFoundError:
        logger.error("whisper-cli binary not found")
        return ""
    except subprocess.TimeoutExpired:
        logger.error("Whisper transcription timed out")
        return ""
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return ""

    txt_file = transcript_base + ".txt"
    if os.path.exists(txt_file):
        try:
            with open(txt_file, encoding="utf-8") as fh:
                text = fh.read().strip()
                logger.debug(f"transcribed {len(text)} chars")
                return text
        except Exception as e:
            logger.error(f"Failed to read transcript: {e}")
            return ""
    else:
        logger.warning("Whisper produced no output")
        return ""


def speak(text: str) -> None:
    """Synthesize text with Piper and play via paplay (PulseAudio).
    Falls back to ffplay if paplay not available.
    """
    if not text:
        logger.warning("speak() called with empty text")
        return

    try:
        # Check if Piper binary exists before launching
        if not Path(PIPER_BIN).exists():
            logger.error(f"Piper binary not found: {PIPER_BIN}")
            return

        piper_proc = subprocess.Popen(
            [PIPER_BIN, "-m", PIPER_MODEL, "-q"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        play_proc = subprocess.Popen(
            ["paplay", "--raw", "--format=s16le", "--rate=22050", "--channels=1"],
            stdin=piper_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=PULSE_ENV,
        )

        # Write text to Piper and close stdin
        piper_proc.stdin.write(text.encode("utf-8"))
        piper_proc.stdin.close()

        # Wait for playback to complete with timeout
        try:
            play_proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            logger.warning("Audio playback timeout, terminating")
            play_proc.terminate()
            try:
                play_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                play_proc.kill()

        # Check Piper exit status
        piper_proc.wait()
        if piper_proc.returncode != 0:
            stderr = piper_proc.stderr.read().decode("utf-8", errors="ignore")[:200] if piper_proc.stderr else "unknown error"
            logger.warning(f"Piper exited with code {piper_proc.returncode}: {stderr}")

    except FileNotFoundError as e:
        logger.error(f"Audio binary not found: {e.filename}")
        # Try fallback to ffplay if paplay missing
        if "paplay" in str(e):
            logger.info("Attempting ffplay fallback")
            try:
                piper_fb = subprocess.Popen(
                    [PIPER_BIN, "-m", PIPER_MODEL, "-q", "--output-raw"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                ffplay_fb = subprocess.Popen(
                    ["ffplay", "-autoexit", "-nodisp", "-f", "s16le", "-ar", "22050", "-ac", "1", "-i", "pipe:0"],
                    stdin=piper_fb.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                piper_fb.stdin.write(text.encode("utf-8"))
                piper_fb.stdin.close()
                ffplay_fb.wait(timeout=30)
            except Exception as fallback_e:
                logger.error(f"ffplay fallback also failed: {fallback_e}")

    except BrokenPipeError:
        logger.warning("Broken pipe during audio playback - Piper or paplay terminated unexpectedly")
    except Exception as e:
        logger.error(f"Audio synthesis failed: {e}")


# ── Server Mode ───────────────────────────────────────────────────────────────

def _server_turn(messages: list) -> str:
    """Stateless single-turn handler for server mode.
    Expects the user message to already be the last entry in messages.
    Handles tool calling internally and returns the final assistant response.
    """
    response = chat_completion(messages)
    tool_name, tool_params = parse_tool_call(response)

    if tool_name:
        logger.info(f"server tool_call tool={tool_name} params={json.dumps(tool_params)}")
        tool_result = call_tool(tool_name, tool_params)
        logger.info(f"server tool_result tool={tool_name} result_len={len(tool_result)}")
        follow_up = messages + [
            {"role": "assistant", "content": response},
            {"role": "user", "content": f"Tool result: {tool_result}\n\nNow summarize this result naturally."},
        ]
        return chat_completion(follow_up, max_tokens=200)

    return response


def build_server_app(kb_context: str) -> "FastAPI":
    app = FastAPI(title="Christopher", version="1.0")

    base_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if kb_context:
        base_messages.append({
            "role": "system",
            "content": (
                "Use this project knowledge-base context as high-priority background facts. "
                "If user asks about current priorities/status, prefer this context over stale assumptions.\n\n"
                f"{kb_context}"
            ),
        })

    @app.get("/health")
    async def health():
        reachable = is_server_reachable()
        return JSONResponse({"status": "ok" if reachable else "degraded", "llm": reachable})

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        incoming = body.get("messages", [])

        # Strip any system messages from the client — we own the system prompt
        user_turns = [m for m in incoming if m.get("role") != "system"]
        # Cap history to last 6 turns so base_messages + history stays within LLAMA_CTX
        user_turns = user_turns[-6:]
        messages = base_messages + user_turns

        response_text = _server_turn(messages)
        logger.info(f"server response len={len(response_text)}")

        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": os.path.basename(LLAMA_MODEL),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return app


# ── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Christopher — Local Voice AI")
    parser.add_argument("--chat",      action="store_true", help="Text chat mode (no mic/TTS)")
    parser.add_argument("--voice",     action="store_true", help="Full voice mode (default)")
    parser.add_argument("--no-server", action="store_true", help="Skip llama-server launch (already running)")
    parser.add_argument("--model-profile", choices=sorted(MODEL_PROFILES.keys()), default=DEFAULT_MODEL_PROFILE,
                        help="Select a predefined local model profile")
    parser.add_argument("--model-path", help="Override GGUF model path for this run")
    parser.add_argument("--ngl", type=int, help="Override GPU layers for this run")
    parser.add_argument("--ctx", type=int, help="Override context window for this run")
    parser.add_argument("--benchmark", action="store_true", help="Run latency benchmark instead of interactive chat")
    parser.add_argument("--benchmark-runs", type=int, default=3, help="Number of benchmark runs")
    parser.add_argument("--benchmark-prompt", default="In one sentence, summarize why local-first AI can be useful.",
                        help="Prompt to use during benchmark mode")
    parser.add_argument("--no-kb", action="store_true", help="Disable fusional-knowledge-base bootstrap context")
    parser.add_argument("--kb-root", default="", help="Override knowledge-base root path for this run")
    parser.add_argument("--server", action="store_true", help="Run as OpenAI-compatible HTTP server (for OpenClaw/Telegram)")
    parser.add_argument("--server-port", type=int, default=8090, help="Port for server mode (default: 8090)")
    args = parser.parse_args()

    configure_model_runtime(
        profile=args.model_profile,
        model_path=args.model_path or "",
        ngl=args.ngl,
        ctx=args.ctx,
    )

    voice_mode = not args.chat and not args.benchmark and not args.server

    print("=" * 55)
    print("  Christopher — Local AI")
    mode_label = "BENCHMARK" if args.benchmark else ("SERVER" if args.server else ("VOICE" if voice_mode else "TEXT CHAT"))
    print(f"  Mode: {mode_label}")
    print(f"  Profile: {CURRENT_MODEL_PROFILE} ({MODEL_PROFILES[CURRENT_MODEL_PROFILE]['label']})")
    print(f"  Model: {os.path.basename(LLAMA_MODEL)} | GPU layers: {LLAMA_NGL} | ctx: {LLAMA_CTX}")
    print(f"  FusionAL: {BI_URL} / {API_URL} / {CONTENT_URL}")
    kb_context = ""
    kb_files_loaded = []
    if not args.no_kb:
        kb_context, kb_files_loaded = load_knowledge_context(kb_root_override=args.kb_root)
    print(f"  KB context: {'loaded' if kb_context else 'not loaded'}")
    if voice_mode:
        print(f"  PulseAudio: {PULSE_SERVER}")
    if args.server:
        print(f"  Server: http://0.0.0.0:{args.server_port}/v1")
    print("=" * 55)
    print()

    if (not args.no_server) and is_server_reachable(timeout=2):
        if not Path(LLAMA_SERVER_BIN).exists() or not Path(LLAMA_MODEL).exists():
            print(f"⚡ Detected reachable llama-server at {LLAMA_SERVER_URL}; using existing server mode.")
            args.no_server = True

    preflight_issues = validate_runtime(voice_mode=voice_mode, skip_server_start=args.no_server)
    if preflight_issues:
        print("⚠️  Runtime preflight found missing dependencies:")
        for issue in preflight_issues:
            print(f"   - {issue}")
        print("\nSet absolute paths in Christopher-AI/.env to override defaults.")
        if voice_mode or not args.no_server:
            print("Cannot continue in this mode until required binaries/models are available.")
            sys.exit(1)

    server_proc = None
    if not args.no_server:
        server_proc = start_llama_server()
        if not wait_for_server(timeout=90):
            print("❌ llama-server failed to start. Check your model path.")
            sys.exit(1)
    else:
        print("⚡ Using existing llama-server")

    if args.benchmark:
        run_benchmark(args.benchmark_prompt, args.benchmark_runs)
        if server_proc:
            print("Stopping llama-server...")
            server_proc.terminate()
            server_proc.wait()
        return

    if args.server:
        if not _FASTAPI_AVAILABLE:
            print("❌ fastapi/uvicorn not installed. Run: pip install fastapi uvicorn")
            sys.exit(1)
        logger.info(f"kb_context_loaded files={';'.join(kb_files_loaded)}" if kb_context else "kb_context_loaded files=none")
        app = build_server_app(kb_context)
        print(f"🦞 Christopher server ready — OpenClaw baseUrl: http://<host>:{args.server_port}/v1")
        try:
            uvicorn.run(app, host="0.0.0.0", port=args.server_port, log_level="warning")
        finally:
            if server_proc:
                print("Stopping llama-server...")
                server_proc.terminate()
                server_proc.wait()
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if kb_context:
        kb_system_message = (
            "Use this project knowledge-base context as high-priority background facts. "
            "If user asks about current priorities/status, prefer this context over stale assumptions.\n\n"
            f"{kb_context}"
        )
        messages.append({"role": "system", "content": kb_system_message})
        logger.info(f"kb_context_loaded files={';'.join(kb_files_loaded)}")
    else:
        logger.info("kb_context_loaded files=none")
    tmpdir   = tempfile.mkdtemp(prefix="christopher-")

    logger.info(f"startup mode={'voice' if voice_mode else 'chat'} model={os.path.basename(LLAMA_MODEL)} ngl={LLAMA_NGL}")
    print("💬 Christopher is ready. Type 'quit' to exit.\n")

    try:
        while True:
            if voice_mode:
                user_input = listen(tmpdir)
                if not user_input:
                    print("⚠️  No speech detected")
                    continue
                logger.info(f"speech transcript={user_input!r}")
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
            logger.info(f"response len={len(response)}")
            print(f"🤖 Christopher: {response}\n")

            if voice_mode:
                speak(response)

            if len(messages) > 20:
                # Keep system prompt + optional KB context (first 2) + last 10 turns
                head = messages[:2] if len(messages) > 1 and messages[1].get("role") == "system" else messages[:1]
                messages = head + messages[-10:]

    except KeyboardInterrupt:
        logger.info("shutdown keyboard_interrupt")
        print("\n\nShutting down...")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        if server_proc:
            print("Stopping llama-server...")
            server_proc.terminate()
            server_proc.wait()


if __name__ == "__main__":
    main()
