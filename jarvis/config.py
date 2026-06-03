"""Configuration, paths, and inventory loading for Jarvis.

Runtime state lives under JARVIS_HOME (default ~/.jarvis) so it persists
across runs and is kept out of the source tree. The repo only ships an
inventory.example.yaml; the real inventory is created on first run.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Trust postures control how writes are gated for a given server.
#   strict  - everything is gated, saved-authority rules are ignored (always re-ask)
#   normal  - read-only auto-runs; writes are gated but saved rules can pre-authorize
#   trusted - read-only auto-runs; writes auto-run with no prompt (use sparingly)
POSTURES = ("strict", "normal", "trusted")


def jarvis_home() -> Path:
    return Path(os.environ.get("JARVIS_HOME", str(Path.home() / ".jarvis"))).expanduser()


@dataclass
class Server:
    name: str
    host: str
    user: str = "root"
    port: int = 22
    identity_file: str | None = None
    posture: str = "normal"
    description: str = ""

    def ssh_target(self) -> str:
        return f"{self.user}@{self.host}"


@dataclass
class Paths:
    home: Path
    inventory: Path
    permissions: Path
    memory: Path
    server_facts: Path
    task_log: Path

    @classmethod
    def resolve(cls) -> "Paths":
        home = jarvis_home()
        memory = home / "memory"
        return cls(
            home=home,
            inventory=home / "inventory.yaml",
            permissions=home / "permissions.yaml",
            memory=memory,
            server_facts=memory / "servers",
            task_log=memory / "tasks.jsonl",
        )

    def ensure(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.memory.mkdir(parents=True, exist_ok=True)
        self.server_facts.mkdir(parents=True, exist_ok=True)


@dataclass
class Inventory:
    servers: dict[str, Server] = field(default_factory=dict)

    def get(self, name: str) -> Server | None:
        return self.servers.get(name)

    def names(self) -> list[str]:
        return sorted(self.servers)


def load_inventory(paths: Paths) -> Inventory:
    if not paths.inventory.exists():
        return Inventory()
    raw = yaml.safe_load(paths.inventory.read_text()) or {}
    servers: dict[str, Server] = {}
    for name, spec in (raw.get("servers") or {}).items():
        spec = spec or {}
        posture = spec.get("posture", "normal")
        if posture not in POSTURES:
            posture = "normal"
        servers[name] = Server(
            name=name,
            host=spec.get("host", name),
            user=spec.get("user", "root"),
            port=int(spec.get("port", 22)),
            identity_file=spec.get("identity_file"),
            posture=posture,
            description=spec.get("description", ""),
        )
    return Inventory(servers=servers)


EXAMPLE_INVENTORY = """\
# Jarvis server inventory.
# Each server is reachable over SSH using your existing keys (~/.ssh).
# posture: strict | normal | trusted   (see README for what each means)
servers:
  nas:
    host: 192.168.1.10
    user: admin
    port: 22
    identity_file: ~/.ssh/id_ed25519
    posture: strict
    description: "Synology NAS - media library and nightly backups. Be careful."

  dockerhost:
    host: 192.168.1.20
    user: rgardner
    posture: normal
    description: "Ubuntu box running the Docker compose stack."

  pi-lab:
    host: 192.168.1.30
    user: pi
    posture: trusted
    description: "Throwaway Raspberry Pi for experiments - looser gating is fine."
"""


def bootstrap_inventory(paths: Paths) -> bool:
    """Create a starter inventory.yaml if none exists. Returns True if created."""
    if paths.inventory.exists():
        return False
    paths.ensure()
    paths.inventory.write_text(EXAMPLE_INVENTORY)
    return True
