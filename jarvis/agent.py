"""Agent wiring: the permission gate, the system prompt, and the REPL.

The permission gate (can_use_tool) is where Jarvis's safety posture lives:
  * local/read tools (list_servers, remember, recall) -> always allowed
  * ssh_run             -> classified, then gated per the server's posture
  * anything else       -> denied (Jarvis only acts through its own tools)
"""
from __future__ import annotations

import asyncio
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from .config import Paths
from .gate import PromptInfo, apply_choice, make_gate, normalize_choice
from .tools import AppContext, build_context, build_tools

# ---- terminal helpers ----------------------------------------------------
DIM = "\033[2m"; BOLD = "\033[1m"; CYAN = "\033[36m"; YELLOW = "\033[33m"
GREEN = "\033[32m"; RED = "\033[31m"; RESET = "\033[0m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if sys.stdout.isatty() else text


async def _ainput(prompt: str = "") -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


# ---- the permission gate -------------------------------------------------
# The gate logic itself lives in jarvis/gate.py so the web frontend shares it.
# Here we supply only the terminal prompter: how the REPL asks the operator.


async def _terminal_prompter(ctx: AppContext, info: PromptInfo) -> bool:
    """Render an approval request to the terminal and read the operator's answer.

    Returns whether the command is approved, having applied the choice (and saved
    any b/e/g rule) through the shared apply_choice in gate.py.
    """
    print()
    print(_c("┌─ APPROVAL NEEDED", YELLOW)
          + _c(f"  server: {info.server} ({info.posture})", DIM))
    if info.purpose:
        print(_c(f"│ purpose: {info.purpose}", DIM))
    print(_c("│ reason:  ", DIM) + info.reason)
    print("│ " + _c("command: ", BOLD) + _c(info.command, CYAN))
    print(_c("└ [y] run once  [n] deny  "
             f"[b] always `{info.binary}` on {info.server}  "
             "[e] always this exact cmd  "
             "[g] always `" + info.binary + "` on ALL servers", DIM))

    while True:
        choice = normalize_choice(await _ainput(_c("  approve> ", YELLOW)))
        if choice is None:
            print(_c("  please answer y / n / b / e / g", RED))
            continue
        approved = apply_choice(ctx, info, choice)
        if choice == "b":
            print(_c(f"  saved: always allow `{info.binary}` on {info.server}", GREEN))
        elif choice == "e":
            print(_c(f"  saved: always allow this exact command on {info.server}", GREEN))
        elif choice == "g":
            print(_c(f"  saved: always allow `{info.binary}` on ALL servers", GREEN))
        return approved


# ---- system prompt -------------------------------------------------------
def build_system_prompt(ctx: AppContext) -> str:
    inv_lines = []
    for name in ctx.inventory.names():
        s = ctx.inventory.servers[name]
        inv_lines.append(f"- {name}: {s.ssh_target()}:{s.port} "
                         f"(posture {s.posture}) {s.description}".rstrip())
    inventory_block = "\n".join(inv_lines) or "(no servers configured yet)"

    facts = ctx.memory.facts_overview(ctx.inventory.names())
    facts_block = f"\n\nWHAT YOU ALREADY KNOW:\n{facts}" if facts.strip() else ""

    return f"""You are Jarvis, an operations agent for a personal homelab. You manage \
a small set of Linux servers over SSH at the operator's direction: keeping \
packages updated, adjusting network shares, and troubleshooting issues.

YOUR SERVERS:
{inventory_block}{facts_block}

HOW YOU WORK:
- Act only through your tools: list_servers, ssh_run, remember, recall.
- Before troubleshooting a server, call recall to load what you already know.
- Run ONE self-contained command per ssh_run call, and pass a short `purpose`.
- Read-only commands run automatically. Commands that change state may pause \
for the operator's approval; if a command is denied, do not retry it - ask the \
operator how to proceed.
- Diagnose before you change anything. Gather evidence with read-only commands, \
explain what you found, then propose the specific change before running it.
- Prefer the least invasive action. Avoid destructive operations (rm -rf, \
mkfs, disk writes) unless explicitly instructed and confirmed.
- When you learn something durable about a server (a quirk, a service location, \
a fix that worked), call remember so future sessions benefit.
- Be concise. Report what you ran, what it returned, and what it means."""


# ---- the REPL ------------------------------------------------------------
def build_options(ctx: AppContext, prompter=_terminal_prompter) -> ClaudeAgentOptions:
    """Assemble SDK options. The prompter decides how approvals are requested;
    the terminal REPL uses _terminal_prompter, the web backend its own."""
    mcp_server, _tool_names = build_tools(ctx)
    return ClaudeAgentOptions(
        mcp_servers={"jarvis": mcp_server},
        system_prompt=build_system_prompt(ctx),
        permission_mode="default",
        can_use_tool=make_gate(ctx, prompter),
        # Jarvis must not touch the local machine; only its own tools are allowed.
        disallowed_tools=["Bash", "Read", "Write", "Edit", "NotebookEdit",
                          "WebFetch", "WebSearch", "Glob", "Grep", "Task"],
        setting_sources=None,
    )


async def _print_turn(client: ClaudeSDKClient) -> None:
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    if block.name.endswith("ssh_run"):
                        srv = block.input.get("server", "?")
                        cmd = block.input.get("command", "")
                        print(_c(f"  → {srv}: {cmd}", DIM))
                    elif block.name.endswith("__remember"):
                        print(_c(f"  → remembering: {block.input.get('note','')}", DIM))
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                print(_c(f"  [error: {msg.result or msg.api_error_status}]", RED))


async def run_repl(once: str | None = None) -> None:
    paths = Paths.resolve()
    ctx = build_context(paths)
    inventory = ctx.inventory
    options = build_options(ctx)

    async with ClaudeSDKClient(options=options) as client:
        if once:
            await client.query(once)
            await _print_turn(client)
            return

        print(_c("Jarvis online.", BOLD)
              + _c(f"  {len(inventory.servers)} server(s) loaded. "
                   "Type a directive, or 'exit'.", DIM))
        while True:
            try:
                line = (await _ainput(_c("\nyou> ", GREEN))).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.lower() in ("exit", "quit", ":q"):
                break
            await client.query(line)
            await _print_turn(client)
