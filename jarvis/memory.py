"""Jarvis's persistent memory.

Two kinds:
  * server facts  - one markdown file per server, freeform notes the agent
                    learns over time (quirks, service layout, fixes that worked).
  * task journal  - append-only JSONL, one line per command Jarvis actually ran.
                    This is the raw material for spotting repeatable routines
                    that could later be promoted to automation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Paths


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Memory:
    paths: Paths

    # --- server facts -----------------------------------------------------
    def _fact_file(self, server: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in server)
        return self.paths.server_facts / f"{safe}.md"

    def read_facts(self, server: str) -> str:
        f = self._fact_file(server)
        return f.read_text() if f.exists() else ""

    def append_fact(self, server: str, note: str) -> None:
        f = self._fact_file(server)
        self.paths.server_facts.mkdir(parents=True, exist_ok=True)
        if not f.exists():
            f.write_text(f"# {server}\n\n")
        with f.open("a") as fh:
            fh.write(f"- ({_now()}) {note.strip()}\n")

    def facts_overview(self, names: list[str]) -> str:
        """A short digest of what we know, injected into the system prompt."""
        chunks = []
        for name in names:
            text = self.read_facts(name).strip()
            if text:
                chunks.append(text)
        return "\n\n".join(chunks)

    # --- task journal -----------------------------------------------------
    def log_task(
        self,
        server: str,
        command: str,
        *,
        read_only: bool,
        decision: str,
        exit_code: int | None,
        summary: str = "",
    ) -> None:
        self.paths.memory.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _now(),
            "server": server,
            "command": command,
            "read_only": read_only,
            "decision": decision,   # auto-readonly | auto-trusted | rule:<...> | approved | denied
            "exit_code": exit_code,
            "summary": summary[:500],
        }
        with self.paths.task_log.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def recent_tasks(self, limit: int = 20, server: str | None = None) -> list[dict]:
        if not self.paths.task_log.exists():
            return []
        rows = []
        for line in self.paths.task_log.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if server and row.get("server") != server:
                continue
            rows.append(row)
        return rows[-limit:]
