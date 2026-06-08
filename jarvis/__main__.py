"""Entrypoint: `python -m jarvis`.

  python -m jarvis              interactive REPL
  python -m jarvis -c "..."     run a single directive and exit
  python -m jarvis servers      list configured servers and exit
  python -m jarvis web          serve the web GUI (default 0.0.0.0:8765)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from .config import Paths, bootstrap_inventory, load_inventory


def main() -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Homelab ops agent.")
    parser.add_argument("-c", "--command", help="Run one directive non-interactively, then exit.")
    parser.add_argument("command_word", nargs="?", help="Optional subcommand: 'servers' or 'web'.")
    parser.add_argument("--host", default=os.environ.get("JARVIS_WEB_HOST", "0.0.0.0"),
                        help="Web bind host (default 0.0.0.0, LAN-reachable).")
    parser.add_argument("--port", type=int, default=int(os.environ.get("JARVIS_WEB_PORT", "8765")),
                        help="Web bind port (default 8765).")
    args = parser.parse_args()

    paths = Paths.resolve()
    if bootstrap_inventory(paths):
        print(f"Created a starter inventory at {paths.inventory}\n"
              f"Edit it to point at your real servers, then run jarvis again.")
        return

    if args.command_word == "web":
        # Defer heavy imports (SDK + FastAPI) until the web command is used.
        from .web.server import serve
        try:
            serve(host=args.host, port=args.port)
        except KeyboardInterrupt:
            sys.exit(130)
        return

    if args.command_word == "servers":
        inv = load_inventory(paths)
        if not inv.servers:
            print("No servers configured. Edit", paths.inventory)
            return
        for name in inv.names():
            s = inv.servers[name]
            print(f"{name:<16} {s.ssh_target()}:{s.port:<5} [{s.posture}] {s.description}")
        return

    # Defer heavy import (SDK) until we actually need the agent.
    from .agent import run_repl
    try:
        asyncio.run(run_repl(once=args.command))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
