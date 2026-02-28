
# ── LLM Interface ─────────────────────────────────────────────────────────────

def wait_for_server(timeout=60):
    """Wait for llama-server to be ready."""
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
    """Launch llama-server as a background subprocess."""
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
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def chat_completion(messages: list, max_tokens=300) -> str:
    """Send messages to llama-server and return response text."""
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
    """Extract TOOL_CALL JSON from LLM output if present."""
    match = re.search(r'TOOL_CALL:\s*(\{.*?\})', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get("tool"), data.get("params", {})
        except json.JSONDecodeError:
            pass
    return None, None


def run_turn(messages: list, user_input: str, voice_mode: bool) -> str:
    """Run one conversation turn with optional tool calling."""
    messages.append({"role": "user", "content": user_input})

    response = chat_completion(messages)

    tool_name, tool_params = parse_tool_call(response)

    if tool_name:
        print(f"🔧 Tool call: {tool_name}({json.dumps(tool_params)})")
        tool_result = call_tool(tool_name, tool_params)
        print(f"📦 Result: {tool_result[:200]}{'...' if len(tool_result) > 200 else ''}")

        # Feed result back to LLM for natural language response
        messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": f"Tool result: {tool_result}\n\nNow summarize this result naturally" + (" in one or two spoken sentences" if voice_mode else "") + "."})
        final_response = chat_completion(messages, max_tokens=200)
        messages.append({"role": "assistant", "content": final_response})
        return final_response
    else:
        messages.append({"role": "assistant", "content": response})
        return response
