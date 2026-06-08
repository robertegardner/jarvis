"""The in-process MCP tools Jarvis exposes to the model.

These run inside this Python process (no subprocess), so they share the
loaded inventory, memory, and permission store directly. Every tool call is
still routed through the can_use_tool gate in agent.py before it executes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import sshexec
from .config import Inventory, Paths, load_inventory
from .memory import Memory
from .permissions import PermissionStore


@dataclass
class AppContext:
    """Shared state threaded into tools and the permission gate."""
    inventory: Inventory
    memory: Memory
    permissions: PermissionStore
    # can_use_tool records how each command was authorized so the tool
    # handler can record an accurate decision in the task journal.
    decisions: dict[str, str] = field(default_factory=dict)


def build_context(paths: Paths) -> AppContext:
    """Load inventory, memory, and permissions from disk into a fresh context.

    A context is a snapshot: the agent's system prompt is built from it once per
    session, so inventory/fact edits take effect on the next session, not mid-run.
    """
    paths.ensure()
    return AppContext(
        inventory=load_inventory(paths),
        memory=Memory(paths),
        permissions=PermissionStore.load(paths.permissions),
    )


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


def build_tools(ctx: AppContext):
    @tool(
        "list_servers",
        "List the homelab servers Jarvis can manage, with their trust posture "
        "and description. Call this when you need to know what hosts exist.",
        {},
    )
    async def list_servers(args):
        if not ctx.inventory.servers:
            return _text("No servers configured yet. Edit the inventory file "
                         "(see `jarvis` startup message) to add some.")
        lines = []
        for name in ctx.inventory.names():
            s = ctx.inventory.servers[name]
            lines.append(f"- {name} ({s.ssh_target()}:{s.port}) "
                         f"[posture: {s.posture}] {s.description}".rstrip())
        return _text("\n".join(lines))

    @tool(
        "ssh_run",
        "Run a single shell command on a named server over SSH and return its "
        "output. Read-only commands run automatically; commands that change "
        "state require the operator's approval (handled outside this tool). "
        "Use one self-contained command per call.",
        {
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Server name from list_servers."},
                "command": {"type": "string", "description": "The shell command to run."},
                "purpose": {"type": "string", "description": "One short line on why you are running this."},
            },
            "required": ["server", "command"],
        },
    )
    async def ssh_run(args):
        server_name = args["server"]
        command = args["command"]
        server = ctx.inventory.get(server_name)
        if server is None:
            return _text(f"Unknown server {server_name!r}. Use list_servers to see options.")

        result = await sshexec.run(server, command)
        decision = ctx.decisions.pop(f"{server_name}\x00{command}", "executed")

        summary = result.combined()
        ctx.memory.log_task(
            server_name, command,
            read_only=False if decision in ("approved", "auto-trusted") else True,
            decision=decision,
            exit_code=result.exit_code,
            summary=summary,
        )
        header = f"$ {command}\n(exit {result.exit_code})\n"
        return _text(header + summary)

    @tool(
        "remember",
        "Save a durable fact about a server to long-term memory (e.g. a quirk, "
        "where a service lives, or a fix that worked). Use this so future "
        "sessions benefit from what you learned.",
        {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "note": {"type": "string", "description": "The fact to remember."},
            },
            "required": ["server", "note"],
        },
    )
    async def remember(args):
        ctx.memory.append_fact(args["server"], args["note"])
        return _text(f"Noted for {args['server']}.")

    @tool(
        "recall",
        "Read back what Jarvis knows about a server: saved facts plus the most "
        "recent actions taken on it. Call this before troubleshooting.",
        {
            "type": "object",
            "properties": {"server": {"type": "string"}},
            "required": ["server"],
        },
    )
    async def recall(args):
        server = args["server"]
        facts = ctx.memory.read_facts(server).strip() or "(no saved facts yet)"
        tasks = ctx.memory.recent_tasks(limit=10, server=server)
        hist = "\n".join(
            f"  {t['ts']} [{t['decision']}] (exit {t['exit_code']}) {t['command']}"
            for t in tasks
        ) or "  (no recorded actions yet)"
        return _text(f"# Facts\n{facts}\n\n# Recent actions\n{hist}")

    server = create_sdk_mcp_server(
        "jarvis", version="0.1.0",
        tools=[list_servers, ssh_run, remember, recall],
    )
    return server, ["list_servers", "ssh_run", "remember", "recall"]
