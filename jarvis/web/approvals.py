"""Bridges the async gate to the browser.

When the gate needs the operator's approval it calls the broker's `request`,
which emits an `approval_request` over the WebSocket and suspends on a Future.
The connection's reader task calls `resolve` when the browser answers, waking the
gate. On disconnect, `cancel_all` fails every pending request as a deny so a closed
socket can never leave the agent waiting forever.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from ..gate import PromptInfo

Sender = Callable[[dict], Awaitable[None]]


class ApprovalBroker:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"appr-{self._counter}"

    async def request(self, send: Sender, info: PromptInfo) -> str:
        """Emit an approval request and await the operator's canonical choice char."""
        rid = self._next_id()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        await send({
            "type": "approval_request",
            "id": rid,
            "server": info.server,
            "posture": info.posture,
            "command": info.command,
            "purpose": info.purpose,
            "reason": info.reason,
            "binary": info.binary,
        })
        try:
            return await fut
        finally:
            self._pending.pop(rid, None)

    def resolve(self, rid: str, choice: str) -> bool:
        """Wake the matching pending request. Returns False if id is unknown/stale."""
        fut = self._pending.get(rid)
        if fut is not None and not fut.done():
            fut.set_result(choice)
            return True
        return False

    def cancel_all(self) -> None:
        """Fail all pending approvals as denials (the socket is going away)."""
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result("n")
        self._pending.clear()
