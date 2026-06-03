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
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from . import classify
from .config import Inventory, Paths
from .memory import Memory
from .permissions import PermissionStore, Rule
from .tools import AppContext, build_tools

# ---- terminal helpers ----------------------------------------------------
DIM = "\033[2m"; BOLD = "\033[1m"; CYAN = "\033[36m"; YELLOW = "\033[33m"
GREEN = "\033[32m"; RED = "\033[31m"; RESET = "\033[0m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if sys.stdout.isatty() else text


async def _ainput(prompt: str = "") -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


# ---- the permission gate -------------------------------------------------
LOCAL_TOOLS = {
    "mcp__jarvis__list_servers",
    "mcp__jarvis__remember",
    "mcp__jarvis__recall",
}
SSH_TOOL = "mcp__jarvis__ssh_run"


def make_gate(ctx: AppContext):
    async def can_use_tool(tool_name, tool_input, context):
        # Local, side-effect-free tools never need approval.
        if tool_name in LOCAL_TOOLS:
            return PermissionResultAllow()

        if tool_name != SSH_TOOL:
            return PermissionResultDeny(
                message="Jarvis only acts through its own SSH and memory tools."
            )

        server_name = tool_input.get("server", "")
        command = tool_input.get("command", "")
        purpose = tool_input.get("purpose", "")
        server = ctx.inventory.get(server_name)
        if server is None:
            return PermissionResultDeny(message=f"Unknown server {server_name!r}.")

        verdict = classify.classify(command)
        key = f"{server_name}\x00{command}"

        # Posture: trusted auto-runs writes; strict gates everything.
        if server.posture != "strict":
            if verdict.read_only:
                ctx.decisions[key] = "auto-readonly"
                return PermissionResultAllow()
            if server.posture == "trusted":
                ctx.decisions[key] = "auto-trusted"
                return PermissionResultAllow()
            rule = ctx.permissions.authorizes(server_name, command)
            if rule is not None:
                ctx.decisions[key] = f"rule:{rule.describe()}"
                return PermissionResultAllow()

        # Otherwise, ask the operator.
        approved = await _prompt_operator(ctx, server_name, server.posture, command,
                                          purpose, verdict)
        if approved:
            ctx.decisions[key] = "approved"
            return PermissionResultAllow()

        ctx.memory.log_task(server_name, command, read_only=verdict.read_only,
                            decision="denied", exit_code=None, summary=purpose)
        return PermissionResultDeny(
            message="Operator declined this command. Do not retry it; ask what to do instead."
        )

    return can_use_tool


async def _prompt_operator(ctx, server_name, posture, command, purpose, verdict) -> bool:
    import shlex
    try:
        binary = shlex.split(command)[0].rsplit("/", 1)[-1]
    except (ValueError, IndexError):
        binary = command.split()[0] if command else "?"

    print()
    print(_c("┌─ APPROVAL NEEDED", YELLOW)
          + _c(f"  server: {server_name} ({posture})", DIM))
    if purpose:
        print(_c(f"│ purpose: {purpose}", DIM))
    print(_c("│ reason:  ", DIM) + verdict.reason)
    print("│ " + _c("command: ", BOLD) + _c(command, CYAN))
    print(_c("└ [y] run once  [n] deny  "
             f"[b] always `{binary}` on {server_name}  "
             "[e] always this exact cmd  "
             "[g] always `" + binary + "` on ALL servers", DIM))

    while True:
        choice = (await _ainput(_c("  approve> ", YELLOW))).strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no", ""):
            return False
        if choice == "b":
            ctx.permissions.add(Rule(server=server_name, match="binary",
                                     value=binary, note=purpose))
            print(_c(f"  saved: always allow `{binary}` on {server_name}", GREEN))
            return True
        if choice == "e":
            ctx.permissions.add(Rule(server=server_name, match="exact",
                                     value=command, note=purpose))
            print(_c("  saved: always allow this exact command on "
                     f"{server_name}", GREEN))
            return True
        if choice == "g":
            ctx.permissions.add(Rule(server="*", match="binary",
                                     value=binary, note=purpose))
            print(_c(f"  saved: always allow `{binary}` on ALL servers", GREEN))
            return True
        print(_c("  please answer y / n / b / e / g", RED))


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
def build_options(ctx: AppContext) -> ClaudeAgentOptions:
    mcp_server, _tool_names = build_tools(ctx)
    return ClaudeAgentOptions(
        mcp_servers={"jarvis": mcp_server},
        system_prompt=build_system_prompt(ctx),
        permission_mode="default",
        can_use_tool=make_gate(ctx),
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
    paths.ensure()
    inventory = load(paths)
    ctx = AppContext(
        inventory=inventory,
        memory=Memory(paths),
        permissions=PermissionStore.load(paths.permissions),
    )
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


def load(paths: Paths) -> Inventory:
    from .config import load_inventory
    return load_inventory(paths)
