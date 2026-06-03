"""Run a command on a server over the system `ssh` binary.

Using the system ssh (rather than a library like paramiko) means Jarvis
inherits your existing ~/.ssh config, keys, agent, and known_hosts exactly
as your shell would. We force key-based, non-interactive auth so the agent
can never get stuck on a password prompt.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .config import Server

DEFAULT_TIMEOUT = 120
MAX_OUTPUT = 16_000   # chars of combined output returned to the agent


@dataclass
class SSHResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def combined(self) -> str:
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append("[stderr]\n" + self.stderr.rstrip())
        text = "\n".join(parts) if parts else "(no output)"
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + f"\n...[truncated, {len(text)} chars total]"
        return text


def build_argv(server: Server, command: str, timeout: int) -> list[str]:
    argv = [
        "ssh",
        "-o", "BatchMode=yes",            # never prompt for a password
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={min(timeout, 30)}",
        "-p", str(server.port),
    ]
    if server.identity_file:
        argv += ["-i", str(Path(server.identity_file).expanduser())]
    argv += [server.ssh_target(), "--", command]
    return argv


async def run(server: Server, command: str, timeout: int = DEFAULT_TIMEOUT) -> SSHResult:
    argv = build_argv(server, command, timeout)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return SSHResult(None, "", "ssh binary not found on this machine")
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return SSHResult(None, "", f"command timed out after {timeout}s", timed_out=True)
    return SSHResult(
        exit_code=proc.returncode,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
    )
