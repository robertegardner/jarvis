"""Shared-token auth for the web backend.

The GUI is LAN-reachable (bound to 0.0.0.0), so it cannot be wide open. A single
bearer token - generated on first run and stored under $JARVIS_HOME, never in the
repo - gates every REST call and the WebSocket handshake. This is adequate for a
trusted home network; TLS / an SSH tunnel is the recommended next step (README).
"""
from __future__ import annotations

import secrets

from ..config import Paths


def token_file(paths: Paths):
    return paths.home / "web_token"


def load_or_create_token(paths: Paths) -> str:
    """Return the web token, generating and persisting one on first call."""
    p = token_file(paths)
    if p.exists():
        existing = p.read_text().strip()
        if existing:
            return existing
    paths.ensure()
    token = secrets.token_urlsafe(32)
    p.write_text(token + "\n")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return token


def token_from_header(authorization: str | None) -> str | None:
    """Extract a bearer token from an Authorization header value, if present."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None
