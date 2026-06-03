"""Classify a shell command as read-only (safe to auto-run) or state-changing.

This is the gatekeeper's first filter. It is deliberately *conservative*:
the cost of misclassifying a read-only command as a write is one extra
approval prompt; the cost of misclassifying a write as read-only is an
un-approved change on a server. So when in doubt, we call it a write.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

# Base commands considered read-only with ANY arguments.
_ALWAYS_READ = {
    "uptime", "w", "who", "whoami", "id", "hostname", "hostnamectl", "uname",
    "date", "cal", "arch", "df", "du", "free", "lsblk", "lscpu", "lsusb",
    "lspci", "lsmod", "cat", "less", "more", "head", "tail", "ls", "dir",
    "stat", "file", "readlink", "realpath", "basename", "dirname", "pwd",
    "grep", "egrep", "fgrep", "rg", "wc", "sort", "uniq", "cut", "tr",
    "column", "ps", "pgrep", "pstree", "top", "htop", "vmstat", "iostat",
    "mpstat", "ss", "netstat", "ip", "ifconfig", "ping", "ping6",
    "traceroute", "tracepath", "dig", "nslookup", "host", "getent",
    "findmnt", "mountpoint", "lsof", "env", "printenv", "echo", "uptime",
    "sensors", "free", "nproc", "getconf", "locale", "tty", "groups",
    "last", "lastlog", "logname", "ipcs", "ulimit", "blkid", "fdisk_l",
}

# Commands that are read-only ONLY with a specific safe subcommand/flag.
# Map: base command -> set of allowed first arguments (subcommands).
_SUBCOMMAND_READ = {
    "systemctl": {"status", "show", "list-units", "list-unit-files",
                  "is-active", "is-enabled", "is-failed", "cat", "get-default"},
    "journalctl": {"*"},          # journalctl is read-only; flags only print
    "apt": {"list", "show", "policy"},
    "apt-get": {"-s"},
    "apt-cache": {"*"},
    "dpkg": {"-l", "-L", "-s", "-S", "--list", "--status"},
    "snap": {"list", "info", "find", "version", "connections"},
    "docker": {"ps", "images", "logs", "inspect", "stats", "top", "port",
               "version", "info", "df", "history"},
    "podman": {"ps", "images", "logs", "inspect", "stats", "top", "version", "info"},
    "kubectl": {"get", "describe", "logs", "top", "version", "explain", "api-resources"},
    "zfs": {"list", "get"},
    "zpool": {"list", "status", "iostat", "history", "get"},
    "smartctl": {"-a", "-i", "-H", "-x", "--all", "--info", "--health"},
    "btrfs": {"filesystem", "subvolume", "device"},   # used with show/list flavors
    "git": {"status", "log", "diff", "show", "branch", "remote", "config"},
    "mount": {"*"},               # bare `mount` lists; `mount /x` is a write -> handled below
}

# Tokens that mean the command can write/redirect/execute-something-else.
# Their presence anywhere forces a "write" classification.
_DANGER = re.compile(r"(>>|>|<\(|\$\(|`|\bsudo\b|\bsu\b|;|&&|\|\||&)")

# `mount` with an argument is a write; bare `mount` is read-only.
_BARE_OK = {"mount", "btrfs"}


@dataclass
class Verdict:
    read_only: bool
    reason: str


def classify(command: str) -> Verdict:
    cmd = command.strip()
    if not cmd:
        return Verdict(False, "empty command")

    # Any redirection, command substitution, privilege escalation, or chaining
    # means we cannot reason about it segment-by-segment safely -> gate it.
    if _DANGER.search(cmd):
        return Verdict(False, "contains redirection, sudo, or command chaining")

    # Split a simple pipeline (`a | b | c`). Every stage must be read-only.
    stages = [s.strip() for s in cmd.split("|")]
    for stage in stages:
        v = _classify_stage(stage)
        if not v.read_only:
            return v
    return Verdict(True, "all pipeline stages are read-only")


def _classify_stage(stage: str) -> Verdict:
    try:
        tokens = shlex.split(stage)
    except ValueError:
        return Verdict(False, "unparseable command")
    if not tokens:
        return Verdict(False, "empty stage")

    base = tokens[0].rsplit("/", 1)[-1]   # strip any path prefix

    if base in _ALWAYS_READ:
        return Verdict(True, f"{base} is read-only")

    if base in _SUBCOMMAND_READ:
        allowed = _SUBCOMMAND_READ[base]
        # find first non-flag-ish argument as the subcommand
        sub = next((t for t in tokens[1:] if not t.startswith("-")), None)
        if "*" in allowed:
            # whole command is read-only regardless of subcommand (e.g. journalctl)
            if base in _BARE_OK and sub is not None:
                return Verdict(False, f"{base} with an argument may modify state")
            return Verdict(True, f"{base} is read-only")
        if base in _BARE_OK and sub is None:
            return Verdict(True, f"bare {base} just lists state")
        # match either the subcommand or any matching flag in the token list
        if sub in allowed or any(t in allowed for t in tokens[1:]):
            return Verdict(True, f"{base} {sub or ''}".strip() + " is read-only")
        return Verdict(False, f"{base} '{sub}' is not a known read-only subcommand")

    return Verdict(False, f"'{base}' is not on the read-only allowlist")
