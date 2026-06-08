"""One agent session per WebSocket connection.

Two cooperating tasks share this object:

  * the connection's *reader* (in server.py) feeds directives onto a queue,
    resolves approvals through the broker, and forwards interrupts;
  * the *driver* (here) pulls one directive at a time, runs it through the SDK
    client, and streams each message block back to the browser as JSON.

Because the gate's prompter suspends on the broker (not on input()), the reader
keeps running and can deliver the approval answer while the driver is mid-turn.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from ..agent import build_options
from ..config import Paths
from ..gate import PromptInfo, apply_choice
from ..tools import AppContext, build_context
from .approvals import ApprovalBroker

Sender = Callable[[dict], Awaitable[None]]


def _result_text(content) -> str:
    """Flatten a ToolResultBlock's content (str or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return "" if content is None else str(content)


class AgentSession:
    def __init__(self, paths: Paths, send: Sender) -> None:
        self.paths = paths
        self.send = send
        self.broker = ApprovalBroker()
        self.ctx: AppContext | None = None
        self.client: ClaudeSDKClient | None = None
        self._directives: asyncio.Queue[str] = asyncio.Queue()
        self._driver: asyncio.Task | None = None

    # --- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        self.ctx = build_context(self.paths)
        options = build_options(self.ctx, self._prompter)
        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()
        self._driver = asyncio.create_task(self._drive())
        await self.send({
            "type": "ready",
            "servers": [self._server_dict(n) for n in self.ctx.inventory.names()],
        })

    async def reload(self) -> None:
        """Rebuild the session so inventory/fact edits take effect (new system prompt)."""
        await self._teardown()
        await self.start()

    async def close(self) -> None:
        self.broker.cancel_all()
        await self._teardown()

    async def _teardown(self) -> None:
        if self._driver is not None:
            self._driver.cancel()
            try:
                await self._driver
            except asyncio.CancelledError:
                pass
            self._driver = None
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    # --- inbound from the reader -----------------------------------------
    async def submit(self, text: str) -> None:
        await self._directives.put(text)

    def resolve_approval(self, rid: str, choice: str) -> bool:
        return self.broker.resolve(rid, choice)

    async def interrupt(self) -> None:
        if self.client is not None:
            try:
                await self.client.interrupt()
            except Exception:
                pass

    # --- the gate's web prompter -----------------------------------------
    async def _prompter(self, ctx: AppContext, info: PromptInfo) -> bool:
        choice = await self.broker.request(self.send, info)
        approved = apply_choice(ctx, info, choice)
        await self.send({
            "type": "approval_resolved",
            "command": info.command,
            "approved": approved,
            "choice": choice,
            "notice": _saved_notice(info, choice),
        })
        return approved

    # --- the driver loop --------------------------------------------------
    async def _drive(self) -> None:
        while True:
            text = await self._directives.get()
            try:
                await self.client.query(text)
                await self._stream_turn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let one bad turn kill the session
                await self.send({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            await self.send({"type": "turn_end"})

    async def _stream_turn(self) -> None:
        async for msg in self.client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        await self.send({"type": "assistant_text", "text": block.text})
                    elif isinstance(block, ToolUseBlock):
                        await self._send_tool_use(block)
            elif isinstance(msg, UserMessage):
                for block in getattr(msg, "content", []) or []:
                    if isinstance(block, ToolResultBlock):
                        await self.send({
                            "type": "tool_result",
                            "text": _result_text(block.content),
                            "is_error": bool(getattr(block, "is_error", False)),
                        })
            elif isinstance(msg, ResultMessage):
                if msg.is_error:
                    await self.send({
                        "type": "error",
                        "message": msg.result or str(msg.api_error_status),
                    })

    async def _send_tool_use(self, block: ToolUseBlock) -> None:
        name = block.name.rsplit("__", 1)[-1]
        payload = {"type": "tool_use", "tool": name}
        if name == "ssh_run":
            payload["server"] = block.input.get("server", "?")
            payload["command"] = block.input.get("command", "")
            payload["purpose"] = block.input.get("purpose", "")
        elif name == "remember":
            payload["server"] = block.input.get("server", "")
            payload["note"] = block.input.get("note", "")
        elif name == "recall":
            payload["server"] = block.input.get("server", "")
        await self.send(payload)

    def _server_dict(self, name: str) -> dict:
        s = self.ctx.inventory.servers[name]
        return {"name": name, "host": s.host, "posture": s.posture,
                "description": s.description}


def _saved_notice(info: PromptInfo, choice: str) -> str:
    if choice == "b":
        return f"Saved: always allow `{info.binary}` on {info.server}"
    if choice == "e":
        return f"Saved: always allow this exact command on {info.server}"
    if choice == "g":
        return f"Saved: always allow `{info.binary}` on ALL servers"
    return ""
