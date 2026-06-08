"""The safety gate, factored so every frontend shares one authorization path.

Jarvis's whole safety posture is here, not in any UI. A frontend supplies only a
*prompter* - how it asks the operator and reads the answer - while the decision
logic that matters stays in this module:

  * pre_decision   classify + posture + saved-rule logic -> allow / deny / prompt
  * apply_choice   turn a y/n/b/e/g answer into an allow + (for b/e/g) a saved Rule
  * make_gate      the can_use_tool flow: local tools, ssh gating, denial logging

The terminal REPL and the web backend both build their gate from make_gate with
their own prompter, so a misjudged change can't make one frontend laxer than the
other. tests_smoke.py guards the read-only/write bias this depends on.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from . import classify
from .permissions import Rule
from .tools import AppContext

# Tools that never need approval; everything else but ssh_run is denied outright.
LOCAL_TOOLS = {
    "mcp__jarvis__list_servers",
    "mcp__jarvis__remember",
    "mcp__jarvis__recall",
}
SSH_TOOL = "mcp__jarvis__ssh_run"

# Canonical approval choices (what a prompter must return):
#   y run once   n deny   b always this binary   e always this exact command
#   g always this binary on ALL servers
CHOICES = ("y", "n", "b", "e", "g")


@dataclass
class PromptInfo:
    """Everything a frontend needs to render an approval request."""
    server: str
    posture: str
    command: str
    purpose: str
    reason: str          # why the classifier gated it
    binary: str          # first word of the command, path-stripped
    read_only: bool      # the classifier verdict (a strict server gates reads too)


@dataclass
class Decision:
    """Outcome of pre_decision. kind is allow | deny | prompt."""
    kind: str
    decision_key: str = ""        # allow: recorded in ctx.decisions for the journal
    message: str = ""             # deny: shown to the agent
    info: PromptInfo | None = None  # prompt: how to ask the operator


def binary_of(command: str) -> str:
    """The command's first word, path-stripped (e.g. '/usr/bin/apt' -> 'apt')."""
    try:
        return shlex.split(command)[0].rsplit("/", 1)[-1]
    except (ValueError, IndexError):
        return command.split()[0] if command else "?"


def normalize_choice(raw: str) -> str | None:
    """Map free-form operator input to a canonical choice, or None if unknown."""
    c = raw.strip().lower()
    if c in ("y", "yes"):
        return "y"
    if c in ("n", "no", ""):
        return "n"
    if c in ("b", "e", "g"):
        return c
    return None


def pre_decision(ctx: AppContext, server_name: str, command: str,
                 purpose: str = "") -> Decision:
    """Classify + apply the server's posture and saved rules. No side effects."""
    server = ctx.inventory.get(server_name)
    if server is None:
        return Decision("deny", message=f"Unknown server {server_name!r}.")

    verdict = classify.classify(command)

    # Posture: trusted auto-runs writes; strict gates everything (ignores rules).
    if server.posture != "strict":
        if verdict.read_only:
            return Decision("allow", decision_key="auto-readonly")
        if server.posture == "trusted":
            return Decision("allow", decision_key="auto-trusted")
        rule = ctx.permissions.authorizes(server_name, command)
        if rule is not None:
            return Decision("allow", decision_key=f"rule:{rule.describe()}")

    info = PromptInfo(
        server=server_name, posture=server.posture, command=command,
        purpose=purpose, reason=verdict.reason, binary=binary_of(command),
        read_only=verdict.read_only,
    )
    return Decision("prompt", info=info)


def apply_choice(ctx: AppContext, info: PromptInfo, choice: str) -> bool:
    """Apply a canonical choice. Saves a Rule for b/e/g. Returns whether approved.

    This is the single place a write gets authorized; both frontends call it so
    the saved-authority semantics cannot drift apart.
    """
    if choice == "y":
        return True
    if choice == "n":
        return False
    if choice == "b":
        ctx.permissions.add(Rule(server=info.server, match="binary",
                                 value=info.binary, note=info.purpose))
        return True
    if choice == "e":
        ctx.permissions.add(Rule(server=info.server, match="exact",
                                 value=info.command, note=info.purpose))
        return True
    if choice == "g":
        ctx.permissions.add(Rule(server="*", match="binary",
                                 value=info.binary, note=info.purpose))
        return True
    raise ValueError(f"unknown choice {choice!r}")


def make_gate(ctx: AppContext, prompter):
    """Build a can_use_tool callback.

    prompter: async (ctx, PromptInfo) -> bool. It renders the approval request,
    obtains the operator's answer, applies it via apply_choice, and returns
    whether the command was approved. Everything else - local-tool allowlist,
    the deny-everything-but-ssh rule, and journaling denials - lives here.
    """
    async def can_use_tool(tool_name, tool_input, context):
        if tool_name in LOCAL_TOOLS:
            return PermissionResultAllow()
        if tool_name != SSH_TOOL:
            return PermissionResultDeny(
                message="Jarvis only acts through its own SSH and memory tools."
            )

        server_name = tool_input.get("server", "")
        command = tool_input.get("command", "")
        purpose = tool_input.get("purpose", "")

        decision = pre_decision(ctx, server_name, command, purpose)
        key = f"{server_name}\x00{command}"

        if decision.kind == "deny":
            return PermissionResultDeny(message=decision.message)
        if decision.kind == "allow":
            ctx.decisions[key] = decision.decision_key
            return PermissionResultAllow()

        # decision.kind == "prompt": ask the operator through this frontend.
        approved = await prompter(ctx, decision.info)
        if approved:
            ctx.decisions[key] = "approved"
            return PermissionResultAllow()

        ctx.memory.log_task(server_name, command, read_only=decision.info.read_only,
                            decision="denied", exit_code=None, summary=purpose)
        return PermissionResultDeny(
            message="Operator declined this command. Do not retry it; ask what to do instead."
        )

    return can_use_tool
