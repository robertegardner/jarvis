"""The FastAPI application: REST API, the agent WebSocket, and the built SPA.

`create_app` wires a Paths + token into app.state and mounts everything; `serve`
runs it under uvicorn, printing the LAN URL and token so a phone can connect.
"""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import Paths
from .api import router
from .auth import load_or_create_token
from .session import AgentSession

# repo_root/frontend/dist  (jarvis/web/server.py -> parents[2] == repo root)
DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_PLACEHOLDER = """<!doctype html><meta charset=utf-8>
<title>Jarvis</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.5">
<h1>Jarvis backend is running</h1>
<p>The web UI has not been built yet. From the repo root:</p>
<pre>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>then reload. The API and WebSocket are already live under
<code>/api</code> and <code>/ws</code>.</p>
</body>"""


def create_app(paths: Paths, token: str) -> FastAPI:
    app = FastAPI(title="Jarvis")
    app.state.paths = paths
    app.state.token = token
    app.include_router(router)

    @app.websocket("/ws")
    async def agent_ws(ws: WebSocket) -> None:
        # Browsers can't set Authorization on a WS handshake; take it as a query param.
        if not secrets.compare_digest(ws.query_params.get("token", ""), token):
            await ws.close(code=1008)
            return
        await ws.accept()

        lock = asyncio.Lock()

        async def send(obj: dict) -> None:
            # The driver, the gate's prompter, and the reader can all send; the
            # transport is not safe for concurrent writes, so serialize them.
            async with lock:
                await ws.send_json(obj)

        session = AgentSession(paths, send)
        await session.start()
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")
                if kind == "directive":
                    await session.submit(str(msg.get("text", "")))
                elif kind == "approval_response":
                    session.resolve_approval(str(msg.get("id", "")),
                                             str(msg.get("choice", "n")))
                elif kind == "interrupt":
                    await session.interrupt()
                elif kind == "reload":
                    await session.reload()
        except WebSocketDisconnect:
            pass
        finally:
            await session.close()

    # Serve the built SPA at / if present; otherwise a build hint.
    if DIST_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="spa")
    else:
        @app.get("/")
        def placeholder() -> HTMLResponse:
            return HTMLResponse(_PLACEHOLDER)

    return app


def serve(host: str = "0.0.0.0", port: int = 8765) -> None:
    import uvicorn

    paths = Paths.resolve()
    paths.ensure()
    token = load_or_create_token(paths)
    app = create_app(paths, token)

    shown = "localhost" if host in ("0.0.0.0", "127.0.0.1", "") else host
    # flush so the banner appears before uvicorn takes over stdout (matters when
    # output is redirected and stdout is block-buffered rather than a tty).
    print(f"Jarvis web UI on http://{shown}:{port}", flush=True)
    print(f"  token: {token}", flush=True)
    if host == "0.0.0.0":
        print(f"  reachable from your LAN at http://<this-host-ip>:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")
