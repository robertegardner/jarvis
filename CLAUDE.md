# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Jarvis** — a locally-run AI agent that manages the operator's homelab Linux
servers over SSH, at their direction (package updates, network-share changes,
troubleshooting). Built on the **Claude Agent SDK** (Python), so it reuses the
operator's Claude Code authentication rather than a separate API key.

Remote: `git@github.com:robertegardner/jarvis.git` (private), default branch `main`.

## Core design principle

Safety lives in one place: the gate in `jarvis/gate.py` (`pre_decision` decides
allow/deny/prompt; `apply_choice` turns a y/n/b/e/g answer into an allow + saved
rule; `make_gate` is the `can_use_tool` flow). Both frontends — the terminal REPL
(`agent.py`) and the web backend (`web/session.py`) — build their gate from
`make_gate` and supply only a *prompter* (how they ask the operator). Keep all
classify/posture/rule-saving logic in `gate.py` so the two frontends can't drift.

- **Read-only** commands auto-run.
- **State-changing** commands are gated (prompt the operator).
- **Per-server trust postures** (`strict` / `normal` / `trusted`) tune how
  writes are handled.
- The classifier (`jarvis/classify.py`) is **biased toward gating** — a misjudged
  read-only is one extra prompt, a misjudged write changes a server without
  consent. When editing the classifier, preserve this bias: if unsure, treat a
  command as state-changing. `tests_smoke.py` guards this direction.

## Architecture

```
jarvis/
  config.py      inventory + paths + trust postures (POSTURES tuple); save_inventory
  classify.py    read-only vs state-changing classifier (the safety filter)
  permissions.py saved-authority Rule matching (binary/prefix/exact, server-scoped)
  memory.py      per-server facts (markdown) + append-only task journal (jsonl)
  sshexec.py     runs commands via system `ssh` (BatchMode, key-only auth)
  tools.py       in-process MCP tools (list_servers, ssh_run, remember, recall); build_context
  gate.py        the shared safety gate: pre_decision / apply_choice / make_gate
  agent.py       system prompt, terminal prompter, REPL; build_options(ctx, prompter)
  web/           FastAPI backend (see below)
  __main__.py    entrypoint / argparse (repl | -c | servers | web)
frontend/        React + Vite SPA, built to frontend/dist and served by web/server.py
```

`jarvis/web/` (only imported when `jarvis web` runs, so the SDK/FastAPI deps stay
lazy):

```
  auth.py        shared-token load/generate (~/.jarvis/web_token) + bearer check
  approvals.py   ApprovalBroker: bridges the async gate to the browser via Futures
  session.py     AgentSession (one per WS): reader queue + driver loop + web prompter
  api.py         JSON management API (inventory, permissions, memory, tasks)
  server.py      FastAPI app: REST + /ws + serves the built SPA; serve() runs uvicorn
```

Data flow (both frontends): operator directive → SDK agent loop → agent calls
`ssh_run` → `make_gate`'s `can_use_tool` runs `pre_decision`; a prompt is routed
to the frontend's prompter (terminal `input()` or the web ApprovalBroker), which
applies the answer via `apply_choice` → on allow, `sshexec.run` executes → result
+ authorization decision logged to the task journal.

The web backend builds a fresh `AppContext` per connection, so inventory/fact
edits made through the API only affect a session after a reload (the UI exposes a
"reload session" action that tears down and rebuilds the `AgentSession`).

## Runtime state (NOT in the repo)

Lives under `$JARVIS_HOME` (default `~/.jarvis`), created on first run:
`inventory.yaml`, `permissions.yaml`, `memory/servers/*.md`, `memory/tasks.jsonl`.
The repo only ships `inventory.example.yaml`. Never commit anything from
`~/.jarvis` — it holds server addresses and saved authority.

## Running & testing

```bash
./run                 # interactive REPL (uses .venv)
./run -c "..."        # one-shot directive
./run servers         # list inventory and exit
./run web             # serve the web GUI (0.0.0.0:8765; prints an access token)
.venv/bin/python tests_smoke.py   # offline classifier/permission/gate checks

# web front-end (Node 18+): build once, then `./run web` serves frontend/dist
cd frontend && npm install && npm run build      # or `npm run dev` for hot reload
```

When changing `classify.py` or `permissions.py`, run `tests_smoke.py` and add
cases for any new command shape — especially new READ_ONLY entries, which must
not let a writing variant through.

## Environment quirks (this machine)

- System Python (`/usr/bin/python3`, 3.13) has **no `pip`/`ensurepip`**. The
  venv was bootstrapped with `get-pip.py`; don't assume `python3 -m pip` works
  outside `.venv`. To rebuild: `python3 -m venv --without-pip .venv` then
  fetch and run `get-pip.py`, then `pip install -r requirements.txt`.
- Claude Code CLI is installed and authenticated; the SDK spawns it. No
  `ANTHROPIC_API_KEY` is set (auth is via the operator's subscription).

## Conventions

- Match the existing style: module docstrings explain *why*, dataclasses for
  config/state, `async` throughout the agent/ssh path.
- The agent must only act through its own MCP tools — local tools (Bash, Read,
  Write, etc.) are in `disallowed_tools` and also denied by the gate. Keep it
  that way.
- Commit messages end with the `Co-Authored-By` trailer (see git log).

## Roadmap

The task journal (`tasks.jsonl`) is the seed for learned automation:
detect recurring command sequences → propose reviewable playbooks → optionally
schedule them with their own saved-authority scope.
