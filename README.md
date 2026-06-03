# Jarvis — homelab operations agent

A locally-run AI agent that manages your homelab servers over SSH, at your
direction. It keeps packages updated, makes share/config changes, and
troubleshoots issues — asking permission before it changes anything, and
remembering what it learns so routines can later be automated.

Built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python),
so it reuses your existing Claude Code authentication (no separate API key).

## How it thinks about safety

Every action goes through one gate (`can_use_tool` in `jarvis/agent.py`):

| Command kind | What happens |
|---|---|
| **Read-only** (`uptime`, `df`, `systemctl status`, `apt list`, `docker ps`, …) | Runs automatically. |
| **State-changing** (`apt upgrade`, `systemctl restart`, edits, redirects, `sudo`, chaining) | Pauses and asks you. |
| **Anything not an ssh/memory tool** (local Bash, file writes) | Denied — Jarvis only acts through its own tools. |

The classifier (`jarvis/classify.py`) is deliberately biased toward *gating*:
a misjudged read-only command just costs an extra prompt, but a misjudged
write would change a server without consent, so anything ambiguous is gated.

### Trust postures (per server)

Set in the inventory, controls how **writes** are handled:

- `strict`  — everything is gated, saved rules are ignored, always re-ask. *(Use for the NAS.)*
- `normal`  — read-only auto-runs; writes are gated, but you can save standing approvals.
- `trusted` — read-only auto-runs; writes auto-run with no prompt. *(Use for throwaway lab boxes.)*

### Saving authority

When a write is gated, you choose:

```
└ [y] run once  [n] deny  [b] always `apt` on nas  [e] always this exact cmd  [g] always `apt` on ALL servers
```

`b`/`e`/`g` write a rule to `~/.jarvis/permissions.yaml`, so next time that
command is pre-authorized (except on `strict` servers, which always re-ask).

## Memory

Lives under `$JARVIS_HOME` (default `~/.jarvis`):

- `memory/servers/<name>.md` — facts the agent learns (call `remember`).
- `memory/tasks.jsonl` — append-only journal of every command run, with how it
  was authorized and the result. **This is the raw material for learning which
  routines to automate.**

## Setup

```bash
# one-time: create the venv and install deps
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # see note below if pip is missing

# first run creates ~/.jarvis/inventory.yaml from a template
./run servers          # edit ~/.jarvis/inventory.yaml, then:
./run servers          # list configured servers
```

> **Note (Debian/this machine):** the system Python has no `pip`/`ensurepip`.
> The venv was bootstrapped with `get-pip.py`
> (`.venv/bin/python <(curl -s https://bootstrap.pypa.io/get-pip.py)`), or
> install the `python3-venv` apt package to get the normal flow.

Add your servers to `~/.jarvis/inventory.yaml` (template in
`inventory.example.yaml`). Jarvis connects with your existing `~/.ssh` keys —
make sure you can `ssh user@host` non-interactively first.

## Usage

```bash
./run                              # interactive REPL
./run -c "update packages on dockerhost and tell me what changed"
./run servers                      # list inventory and exit
```

In the REPL, just talk to it:

```
you> dockerhost is out of disk, figure out what's eating it
you> check for package updates on all servers, summarize, don't install anything yet
you> restart the nginx container on dockerhost
```

## Layout

```
jarvis/
  config.py      inventory + paths + trust postures
  classify.py    read-only vs state-changing classifier
  permissions.py saved-authority rules + matching
  memory.py      server facts + task journal
  sshexec.py     runs commands via system ssh
  tools.py       the MCP tools the agent calls (list_servers, ssh_run, remember, recall)
  agent.py       permission gate, system prompt, REPL
  __main__.py    entrypoint
tests_smoke.py   offline classifier/permission checks
```

## Roadmap (toward learned automation)

The task journal is the seed. Natural next steps:

1. A `routines` command that scans `tasks.jsonl` for recurring command
   sequences and proposes them as named, reviewable playbooks.
2. Promote an approved playbook to a scheduled run (cron) with its own
   saved-authority scope.
3. Parallel fan-out across servers for fleet-wide read-only checks.
