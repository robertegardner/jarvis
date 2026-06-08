"""JSON management API: inventory, permission rules, memory, and the task journal.

These endpoints read and write the on-disk state under $JARVIS_HOME directly (a
fresh load per request), reusing the same module APIs the agent uses. A running
agent session keeps the inventory/facts it loaded at start, so edits made here
take effect when the session is reloaded - the UI exposes a reload action.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..config import POSTURES, Inventory, Server, load_inventory, save_inventory
from ..memory import Memory
from ..permissions import PermissionStore, Rule
from .auth import token_from_header


def require_token(request: Request) -> None:
    expected = request.app.state.token
    import secrets
    provided = token_from_header(request.headers.get("authorization"))
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid token.")


def _paths(request: Request):
    return request.app.state.paths


router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


# --- models ---------------------------------------------------------------
class ServerModel(BaseModel):
    name: str
    host: str
    user: str = "root"
    port: int = 22
    identity_file: str | None = None
    posture: str = "normal"
    description: str = ""


class InventoryModel(BaseModel):
    servers: list[ServerModel]


class RuleModel(BaseModel):
    server: str = "*"
    match: str = "exact"
    value: str
    note: str = ""


class FactModel(BaseModel):
    note: str


# --- inventory ------------------------------------------------------------
@router.get("/postures")
def get_postures() -> list[str]:
    return list(POSTURES)


@router.get("/inventory")
def get_inventory(request: Request) -> InventoryModel:
    inv = load_inventory(_paths(request))
    return InventoryModel(servers=[
        ServerModel(name=n, host=s.host, user=s.user, port=s.port,
                    identity_file=s.identity_file, posture=s.posture,
                    description=s.description)
        for n, s in ((n, inv.servers[n]) for n in inv.names())
    ])


@router.put("/inventory")
def put_inventory(body: InventoryModel, request: Request) -> InventoryModel:
    seen: set[str] = set()
    servers: dict[str, Server] = {}
    for sm in body.servers:
        name = sm.name.strip()
        if not name:
            raise HTTPException(400, "Server name must not be empty.")
        if name in seen:
            raise HTTPException(400, f"Duplicate server name {name!r}.")
        if sm.posture not in POSTURES:
            raise HTTPException(400, f"Unknown posture {sm.posture!r}.")
        seen.add(name)
        servers[name] = Server(
            name=name, host=sm.host.strip() or name, user=sm.user or "root",
            port=int(sm.port), identity_file=sm.identity_file or None,
            posture=sm.posture, description=sm.description,
        )
    save_inventory(_paths(request), Inventory(servers=servers))
    return get_inventory(request)


# --- permission rules -----------------------------------------------------
@router.get("/permissions")
def get_permissions(request: Request) -> list[dict]:
    store = PermissionStore.load(_paths(request).permissions)
    return [
        {"index": i, "server": r.server, "match": r.match, "value": r.value,
         "note": r.note, "created": r.created}
        for i, r in enumerate(store.rules)
    ]


@router.post("/permissions")
def add_permission(body: RuleModel, request: Request) -> list[dict]:
    if body.match not in ("binary", "prefix", "exact"):
        raise HTTPException(400, f"Unknown match type {body.match!r}.")
    if not body.value.strip():
        raise HTTPException(400, "Rule value must not be empty.")
    store = PermissionStore.load(_paths(request).permissions)
    store.add(Rule(server=body.server or "*", match=body.match,
                   value=body.value, note=body.note))
    return get_permissions(request)


@router.delete("/permissions/{index}")
def delete_permission(index: int, request: Request) -> list[dict]:
    store = PermissionStore.load(_paths(request).permissions)
    if store.remove(index) is None:
        raise HTTPException(404, "No rule at that index.")
    return get_permissions(request)


# --- memory + journal -----------------------------------------------------
@router.get("/servers/{name}/memory")
def get_memory(name: str, request: Request) -> dict:
    mem = Memory(_paths(request))
    return {
        "server": name,
        "facts": mem.read_facts(name),
        "tasks": mem.recent_tasks(limit=20, server=name),
    }


@router.post("/servers/{name}/memory")
def add_fact(name: str, body: FactModel, request: Request) -> dict:
    if not body.note.strip():
        raise HTTPException(400, "Fact must not be empty.")
    mem = Memory(_paths(request))
    mem.append_fact(name, body.note)
    return get_memory(name, request)


@router.get("/tasks")
def get_tasks(request: Request, limit: int = 50, server: str | None = None) -> list[dict]:
    mem = Memory(_paths(request))
    return mem.recent_tasks(limit=limit, server=server)
