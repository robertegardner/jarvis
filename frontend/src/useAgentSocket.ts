import { useCallback, useEffect, useRef, useState } from "react";
import type { ApprovalRequest, Choice, FeedItem, ServerInfo } from "./types";

export type ConnStatus = "connecting" | "open" | "closed" | "unauthorized";

// Manages the agent WebSocket: streams the conversation feed, surfaces pending
// approval requests, and exposes the actions the UI can send back. The gate on
// the backend suspends on our approval answer, so responding here unblocks the
// in-flight command.
export function useAgentSocket(token: string) {
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [servers, setServers] = useState<ServerInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const push = useCallback((item: FeedItem) => setFeed((f) => [...f, item]), []);

  useEffect(() => {
    if (!token) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`);
    wsRef.current = ws;
    setStatus("connecting");

    ws.onopen = () => setStatus("open");
    ws.onclose = (e) => setStatus(e.code === 1008 ? "unauthorized" : "closed");
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      switch (m.type) {
        case "ready":
          setServers(m.servers || []);
          break;
        case "assistant_text":
          push({ kind: "assistant", text: m.text });
          break;
        case "tool_use":
          push({ kind: "tool_use", tool: m.tool, server: m.server, command: m.command, purpose: m.purpose, note: m.note });
          break;
        case "tool_result":
          push({ kind: "tool_result", text: m.text, is_error: !!m.is_error });
          break;
        case "approval_request":
          setApprovals((a) => [...a, m as ApprovalRequest]);
          break;
        case "approval_resolved":
          if (m.notice) push({ kind: "notice", text: m.notice });
          break;
        case "error":
          push({ kind: "error", text: m.message });
          break;
        case "turn_end":
          setBusy(false);
          break;
      }
    };
    return () => ws.close();
  }, [token, push]);

  const send = (obj: unknown) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  };

  const sendDirective = useCallback((text: string) => {
    const t = text.trim();
    if (!t) return;
    push({ kind: "user", text: t });
    setBusy(true);
    send({ type: "directive", text: t });
  }, [push]);

  const respondApproval = useCallback((id: string, choice: Choice) => {
    setApprovals((a) => a.filter((req) => req.id !== id));
    send({ type: "approval_response", id, choice });
  }, []);

  const interrupt = useCallback(() => send({ type: "interrupt" }), []);
  const reload = useCallback(() => {
    send({ type: "reload" });
    push({ kind: "notice", text: "Session reloaded — picked up inventory/memory changes." });
  }, [push]);

  return { status, feed, approvals, servers, busy, sendDirective, respondApproval, interrupt, reload };
}
