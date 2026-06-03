"""Saved-authority rules: persistent 'you may always do X' grants.

A rule authorizes future write commands without prompting. Scope is chosen
by the user at approval time:

  binary  - any command whose first word matches (e.g. allow `apt` on nas)
  prefix  - any command that starts with the saved string
  exact   - only this exact command string

Rules are scoped to a server name, or "*" for all servers. Servers with
posture 'strict' ignore saved rules entirely and always re-ask.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml


@dataclass
class Rule:
    server: str          # server name or "*"
    match: str           # "binary" | "prefix" | "exact"
    value: str
    note: str = ""
    created: str = ""

    def matches(self, server: str, command: str) -> bool:
        if self.server != "*" and self.server != server:
            return False
        command = command.strip()
        if self.match == "exact":
            return command == self.value
        if self.match == "prefix":
            return command.startswith(self.value)
        if self.match == "binary":
            try:
                first = shlex.split(command)[0].rsplit("/", 1)[-1]
            except (ValueError, IndexError):
                return False
            return first == self.value
        return False

    def describe(self) -> str:
        scope = "all servers" if self.server == "*" else self.server
        return f"[{self.match}] {self.value!r} on {scope}"


@dataclass
class PermissionStore:
    path: Path
    rules: list[Rule] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "PermissionStore":
        rules: list[Rule] = []
        if path.exists():
            raw = yaml.safe_load(path.read_text()) or {}
            for r in raw.get("rules", []) or []:
                rules.append(Rule(
                    server=r.get("server", "*"),
                    match=r.get("match", "exact"),
                    value=r.get("value", ""),
                    note=r.get("note", ""),
                    created=r.get("created", ""),
                ))
        return cls(path=path, rules=rules)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"rules": [
            {"server": r.server, "match": r.match, "value": r.value,
             "note": r.note, "created": r.created}
            for r in self.rules
        ]}
        self.path.write_text(yaml.safe_dump(data, sort_keys=False))

    def authorizes(self, server: str, command: str) -> Rule | None:
        for r in self.rules:
            if r.matches(server, command):
                return r
        return None

    def add(self, rule: Rule) -> None:
        rule.created = rule.created or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.rules.append(rule)
        self.save()
