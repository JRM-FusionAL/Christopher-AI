#!/usr/bin/env python3
"""
rotate_keys.py - Cross-platform API key rotation for FusionAL + mcp-consulting-kit
Works on Windows, Linux, and macOS

Usage:
  python3 rotate_keys.py              # rotate and update all envs
  python3 rotate_keys.py --dry-run    # show what would change
  python3 rotate_keys.py --restart    # rotate and restart servers
"""

import argparse
import os
import platform
import re
import secrets
import subprocess
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

# ── Find repo roots dynamically ──────────────────────────────────────────────

def find_repo(name: str) -> Path | None:
    candidates = [
        Path(__file__).resolve().parent / name,
        Path(__file__).resolve().parents[1] / name,
        Path.home() / "Projects" / name,
        Path.home() / "projects" / name,
        Path.home() / name,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


MCP_KIT = find_repo("mcp-consulting-kit")
FUSIONAL = find_repo("FusionAL")

ENV_FILES = []
if MCP_KIT:
    ENV_FILES += [
        MCP_KIT / "showcase-servers" / "business-intelligence-mcp" / ".env",
        MCP_KIT / "showcase-servers" / "api-integration-hub" / ".env",
        MCP_KIT / "showcase-servers" / "content-automation-mcp" / ".env",
    ]
if FUSIONAL:
    ENV_FILES.append(FUSIONAL / "core" / ".env")

# Christopher .env — resolved relative to this script's own location
CHRISTOPHER_ENV = Path(__file__).resolve().parent / ".env"


def generate_key() -> str:
    return secrets.token_hex(16)


def read_current_key(env_path: Path) -> str:
    if not env_path.exists():
        return "unknown"
    for line in env_path.read_text().splitlines():
        if re.match(r"^(?:FUSIONAL_)?API_KEY=", line):
            return line.split("=", 1)[1].strip()
    return "unknown"


def update_env_file(env_path: Path, new_key: str, dry_run: bool) -> bool:
    if not env_path.exists():
        print(f"  ⚠️  Not found: {env_path}")
        return False

    content = env_path.read_text(encoding="utf-8")
    new_content = re.sub(
        r"^((?:FUSIONAL_)?API_KEY=).*$",
        lambda m: m.group(1) + new_key,
        content,
        flags=re.MULTILINE,
    )

    if new_content == content:
        print(f"  ⚠️  No API_KEY line in: {env_path.name}")
        return False

    if dry_run:
        print(f"  [DRY RUN] Would update: {env_path}")
        return True

    env_path.write_text(new_content, encoding="utf-8")
    print(f"  ✅ Updated: {env_path}")
    return True


def restart_servers():
    print("  🔄 Restarting servers...")
    if IS_WINDOWS:
        bat = MCP_KIT / "launch-all-servers.bat" if MCP_KIT else None
        subprocess.run(
            ["powershell", "-Command",
             "Get-Process python3,python,uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force"],
            capture_output=True,
        )
        if bat and bat.exists():
            subprocess.Popen(["cmd", "/c", str(bat)])
    else:
        subprocess.run(["pkill", "-f", "uvicorn"], capture_output=True)
        launch = MCP_KIT / "launch.sh" if MCP_KIT else None
        if launch and launch.exists():
            subprocess.Popen(["bash", str(launch), "start"])
    print("  ✅ Servers relaunching")


def main():
    parser = argparse.ArgumentParser(description="Rotate FusionAL API keys")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--key", type=str, help="Use a specific key instead of generating")
    args = parser.parse_args()

    new_key = args.key or generate_key()
    old_key = read_current_key(ENV_FILES[0]) if ENV_FILES else "unknown"

    print("=" * 55)
    print("  API Key Rotation")
    print(f"  Platform: {platform.system()}")
    print("=" * 55)
    print(f"  Old: {old_key[:8]}...{old_key[-4:]}")
    print(f"  New: {new_key[:8]}...{new_key[-4:]}")
    if args.dry_run:
        print("  Mode: DRY RUN")
    print()

    print("Updating server .env files:")
    for f in ENV_FILES:
        update_env_file(f, new_key, args.dry_run)

    print("\nUpdating Christopher .env:")
    update_env_file(CHRISTOPHER_ENV, new_key, args.dry_run)

    if not args.dry_run:
        print(f"\n✅ New key: {new_key}")
        if args.restart:
            print()
            restart_servers()
        else:
            print("\n⚠️  Restart servers to apply the new key.")
            print("   python3 rotate_keys.py --restart")

    print("\nDone.")


if __name__ == "__main__":
    main()
