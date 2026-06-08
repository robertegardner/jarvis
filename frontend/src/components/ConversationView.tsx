import { useEffect, useRef } from "react";
import type { ApprovalRequest, Choice, FeedItem } from "../types";
import { ApprovalCard } from "./ApprovalCard";

function FeedRow({ item }: { item: FeedItem }) {
  switch (item.kind) {
    case "user":
      return <div className="row user"><div className="bubble">{item.text}</div></div>;
    case "assistant":
      return <div className="row assistant"><div className="bubble">{item.text}</div></div>;
    case "tool_use":
      if (item.tool === "ssh_run")
        return (
          <div className="row tool">
            <span className="badge">{item.server}</span>
            <code className="cmd">{item.command}</code>
          </div>
        );
      if (item.tool === "remember")
        return <div className="row tool muted">remembering ({item.server}): {item.note}</div>;
      if (item.tool === "recall")
        return <div className="row tool muted">recalling what's known about {item.server}…</div>;
      return <div className="row tool muted">{item.tool}</div>;
    case "tool_result":
      return <pre className={"output" + (item.is_error ? " err" : "")}>{item.text}</pre>;
    case "notice":
      return <div className="row notice">{item.text}</div>;
    case "error":
      return <div className="row error">⚠ {item.text}</div>;
  }
}

export function ConversationView({
  feed,
  approvals,
  onRespond,
}: {
  feed: FeedItem[];
  approvals: ApprovalRequest[];
  onRespond: (id: string, choice: Choice) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [feed, approvals]);

  return (
    <div className="conversation">
      {feed.length === 0 && approvals.length === 0 && (
        <div className="empty muted">
          Give Jarvis a directive — e.g. “check disk usage on dockerhost” or
          “are there package updates on nas?”
        </div>
      )}
      {feed.map((item, i) => (
        <FeedRow key={i} item={item} />
      ))}
      {approvals.map((req) => (
        <ApprovalCard key={req.id} req={req} onRespond={onRespond} />
      ))}
      <div ref={endRef} />
    </div>
  );
}
