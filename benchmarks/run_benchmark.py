#!/usr/bin/env python3
"""
benchmarks/run_benchmark.py — Christopher-AI baseline benchmark runner

Connects to a running llama-server, runs every scenario from scenarios.yaml
across the model currently loaded, and writes a Markdown results matrix.

Prerequisites
─────────────
1. Start Christopher (which auto-starts llama-server):
     python3 christopher.py --chat --no-kb
   Wait for "Christopher is ready."

2. In a separate terminal (or after Ctrl-C if using --no-server externally):
     python3 benchmarks/run_benchmark.py --profile llama32-3b

For a full three-profile comparison run each profile in sequence:
     python3 benchmarks/run_benchmark.py --profile llama32-3b \\
         --output benchmarks/results/baseline_$(date +%Y-%m-%d).md
   # restart christopher with qwen25-3b, then:
     python3 benchmarks/run_benchmark.py --profile qwen25-3b \\
         --output benchmarks/results/baseline_$(date +%Y-%m-%d).md --append
   # restart christopher with mistral-7b, then:
     python3 benchmarks/run_benchmark.py --profile mistral-7b \\
         --output benchmarks/results/baseline_$(date +%Y-%m-%d).md --append

See benchmarks/scenarios.yaml to add or modify scenarios.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed.  Run: pip install requests")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed.  Run: pip install pyyaml")
    sys.exit(1)

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_FILE = Path(__file__).resolve().parent / "scenarios.yaml"
SYSTEM_PROMPT = "You are Christopher. Be brief and direct."


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_scenarios(path: Path, ids: list[str] | None = None) -> list[dict]:
    with open(path) as fh:
        data = yaml.safe_load(fh)
    scenarios = data["scenarios"]
    if ids:
        scenarios = [s for s in scenarios if s["id"] in ids]
    return scenarios


def server_reachable(base_url: str, timeout: int = 5) -> bool:
    for path in ("/health", "/v1/models"):
        try:
            r = requests.get(f"{base_url}{path}", timeout=timeout)
            if r.status_code < 500:
                return True
        except Exception:
            pass
    return False


def chat_completion(base_url: str, prompt: str, max_tokens: int) -> tuple[str, int]:
    """Returns (response_text, completion_token_count)."""
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "top_p": 0.9,
    }
    r = requests.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"].strip()
    tokens = data.get("usage", {}).get("completion_tokens", 0)
    return text, tokens


def sample_vram_mb() -> int | None:
    """Read GPU VRAM in use via nvidia-smi (best-effort)."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return int(out.decode().strip().split("\n")[0])
    except Exception:
        return None


def sample_llama_rss_mb() -> int | None:
    """RSS of the llama-server process (best-effort, requires psutil)."""
    if not _HAS_PSUTIL:
        return None
    try:
        for proc in psutil.process_iter(["name", "memory_info"]):
            name = (proc.info.get("name") or "").lower()
            if "llama" in name or "llama-server" in name:
                return proc.info["memory_info"].rss // (1024 * 1024)
    except Exception:
        pass
    return None


def get_gpu_label() -> str:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return out.decode().strip().split("\n")[0]
    except Exception:
        return "N/A"


def get_env_ngl_ctx() -> tuple[str, str]:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return "default", "default"
    try:
        from dotenv import dotenv_values
        env = dotenv_values(env_file)
        return env.get("LLAMA_NGL", "default"), env.get("LLAMA_CTX", "default")
    except Exception:
        return "default", "default"


# ── Core benchmark ────────────────────────────────────────────────────────────

def run_scenario(base_url: str, scenario: dict, runs: int) -> dict:
    latencies: list[float] = []
    token_counts: list[int] = []
    responses: list[str] = []
    vram_readings: list[int] = []

    for _ in range(runs):
        t0 = time.perf_counter()
        text, tokens = chat_completion(base_url, scenario["prompt"], scenario["max_tokens"])
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)
        token_counts.append(tokens)
        responses.append(text)
        v = sample_vram_mb()
        if v is not None:
            vram_readings.append(v)

    avg_lat = sum(latencies) / len(latencies)
    avg_tok = sum(token_counts) / len(token_counts) if token_counts else 0
    tps = avg_tok / avg_lat if avg_lat > 0 and avg_tok > 0 else 0.0

    return {
        "avg_latency": avg_lat,
        "min_latency": min(latencies),
        "max_latency": max(latencies),
        "avg_tokens": avg_tok,
        "tok_per_sec": tps,
        "vram_mb": max(vram_readings) if vram_readings else None,
        "rss_mb": sample_llama_rss_mb(),
        "sample_response": responses[-1][:140],
    }


# ── Markdown output ───────────────────────────────────────────────────────────

def _fmt(value: float | None, fmt: str = ".2f") -> str:
    return f"{value:{fmt}}" if value is not None else "—"


def _fmt_int(value: float | None) -> str:
    return f"{int(value)}" if value is not None else "—"


def render_markdown(
    profile: str,
    results: dict[str, dict],
    scenarios: list[dict],
    runs: int,
    base_url: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ngl, ctx = get_env_ngl_ctx()
    gpu = get_gpu_label()
    lines: list[str] = []

    lines += [
        f"# Christopher-AI Benchmark — {profile}",
        "",
        f"**Generated:** {now}  ",
        f"**Platform:** {platform.platform()}  ",
        f"**GPU:** {gpu}  ",
        f"**Profile:** {profile} | GPU layers (ngl): {ngl} | Context (ctx): {ctx}  ",
        f"**Runs per scenario:** {runs}  ",
        f"**Temperature:** 0.1 (fixed for reproducibility)  ",
        f"**Server:** {base_url}  ",
        "",
        "---",
        "",
        "## Results",
        "",
        "| Scenario | Avg (s) | Min (s) | Max (s) | Tokens | Tok/s | VRAM (MB) | RSS (MB) |",
        "|----------|--------|---------|---------|--------|-------|-----------|----------|",
    ]

    for s in scenarios:
        cell = results.get(s["id"])
        if cell is None:
            lines.append(f"| {s['label']} | FAILED | — | — | — | — | — | — |")
        else:
            vram = _fmt_int(cell["vram_mb"])
            rss = _fmt_int(cell["rss_mb"])
            lines.append(
                f"| {s['label']}"
                f" | {_fmt(cell['avg_latency'])}"
                f" | {_fmt(cell['min_latency'])}"
                f" | {_fmt(cell['max_latency'])}"
                f" | {_fmt_int(cell['avg_tokens'])}"
                f" | {_fmt(cell['tok_per_sec'], '.1f')}"
                f" | {vram}"
                f" | {rss} |"
            )

    lines += [
        "",
        "## Sample Responses (last run)",
        "",
    ]
    for s in scenarios:
        cell = results.get(s["id"])
        if cell:
            lines.append(f"**{s['label']}** — _{s['quality_rubric']}_")
            lines.append(f"> {cell['sample_response']}")
            lines.append("")

    lines += [
        "---",
        "",
        "## Reproduction",
        "",
        "```bash",
        "# Start Christopher (launches llama-server automatically)",
        f"python3 christopher.py --chat --no-kb --model-profile {profile}",
        "",
        "# In a separate terminal, run the benchmark",
        f"python3 benchmarks/run_benchmark.py --profile {profile} \\",
        f"    --server-url {base_url} --runs {runs} \\",
        f"    --output benchmarks/results/baseline_{profile}_$(date +%Y-%m-%d).md",
        "```",
        "",
        "Scenarios are defined in `benchmarks/scenarios.yaml` and can be extended.",
    ]

    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Christopher-AI baseline benchmark runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--profile", default="llama32-3b",
        help="Label for the currently loaded model profile (default: llama32-3b)",
    )
    parser.add_argument(
        "--server-url", default="http://127.0.0.1:8080",
        help="llama-server base URL (default: http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="Inference runs per scenario (default: 3)",
    )
    parser.add_argument(
        "--scenarios", nargs="+", default=None,
        help="Scenario IDs to run (default: all). e.g. --scenarios short-factual complex-list",
    )
    parser.add_argument(
        "--scenarios-file", default=str(SCENARIOS_FILE),
        help="Path to scenarios.yaml",
    )
    parser.add_argument(
        "--output", default=None,
        help="Write Markdown results to this file (default: print to stdout)",
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Append to --output instead of overwriting",
    )
    args = parser.parse_args()

    scenarios = load_scenarios(Path(args.scenarios_file), ids=args.scenarios)
    if not scenarios:
        print("ERROR: no scenarios matched. Check --scenarios or scenarios.yaml")
        sys.exit(1)

    if not server_reachable(args.server_url):
        print(f"ERROR: llama-server not reachable at {args.server_url}")
        print("Start Christopher first:  python3 christopher.py --chat --no-kb")
        sys.exit(1)

    print(f"Profile : {args.profile}")
    print(f"Server  : {args.server_url}")
    print(f"Runs    : {args.runs} per scenario")
    print(f"Scenarios: {[s['id'] for s in scenarios]}")
    print()

    results: dict[str, dict | None] = {}
    for s in scenarios:
        print(f"  [{s['id']}] ...", end=" ", flush=True)
        try:
            cell = run_scenario(args.server_url, s, args.runs)
            results[s["id"]] = cell
            print(
                f"avg={cell['avg_latency']:.2f}s  "
                f"tok/s={cell['tok_per_sec']:.1f}  "
                f"tokens={cell['avg_tokens']:.0f}"
            )
        except Exception as exc:
            results[s["id"]] = None
            print(f"FAILED: {exc}")

    print()
    md = render_markdown(args.profile, results, scenarios, args.runs, args.server_url)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.append else "w"
        with open(out_path, mode) as fh:
            if args.append:
                fh.write("\n\n---\n\n")
            fh.write(md)
        print(f"Results written to {out_path}")
    else:
        print(md)


if __name__ == "__main__":
    main()
