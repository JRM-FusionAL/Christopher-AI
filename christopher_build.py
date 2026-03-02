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
LLAMA_MODEL       = os.path.expanduser(ENV.get("LLAMA_MODEL", "~/llama.cpp/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf"))
LLAMA_SERVER_URL  = ENV.get("LLAMA_SERVER_URL", "http://localhost:8080")
LLAMA_NGL         = int(ENV.get("LLAMA_NGL", "28"))
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

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Christopher, a helpful local AI assistant with access to tools.
Keep responses concise and natural. No markdown formatting in voice mode.

You have access to these tools. To use a tool, output EXACTLY this format on its own line:
TOOL_CALL: {"tool": "tool_name", "params": {"param": "value"}}

Available tools:

TOOL: nl_query
DESC: Query a database using natural language
PARAMS: {"query": "plain english question", "schema_hint": "optional table info"}
EXAMPLE: TOOL_CALL: {"tool": "nl_query", "params": {"query": "how many users signed up last week"}}

TOOL: scrape_article
DESC: Extract article text from any URL
PARAMS: {"url": "https://..."}
EXAMPLE: TOOL_CALL: {"tool": "scrape_article", "params": {"url": "https://example.com/post"}}

TOOL: scrape_links
DESC: Extract all links from a webpage
PARAMS: {"url": "https://..."}

TOOL: parse_rss
DESC: Fetch and parse an RSS feed
PARAMS: {"url": "https://...", "limit": 10}
EXAMPLE: TOOL_CALL: {"tool": "parse_rss", "params": {"url": "https://news.ycombinator.com/rss", "limit": 5}}

TOOL: slack_send
DESC: Send a Slack message
PARAMS: {"channel": "#channel-name", "text": "message"}

TOOL: github_create_issue
DESC: Create a GitHub issue
PARAMS: {"owner": "username", "repo": "reponame", "title": "issue title", "body": "details"}

TOOL: stripe_customer_lookup
DESC: Look up a Stripe customer
PARAMS: {"customer_id": "cus_..."}

Only use a tool when the user explicitly asks for something that requires it.
After receiving a tool result, summarize it naturally for the user.
If no tool is needed, just respond directly."""


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
        return f"Tool error: FusionAL server not reachable. Is docker compose running?"
    except Exception as e:
        return f"Tool error: {e}"
