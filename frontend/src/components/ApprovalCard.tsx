import type { ApprovalRequest, Choice } from "../types";

// The web equivalent of the terminal's y/n/b/e/g prompt. Each button maps to the
// same canonical choice the gate's apply_choice expects, so the saved-authority
// behavior is identical to the REPL.
export function ApprovalCard({
  req,
  onRespond,
}: {
  req: ApprovalRequest;
  onRespond: (id: string, choice: Choice) => void;
}) {
  const r = (c: Choice) => () => onRespond(req.id, c);
  return (
    <div className="approval">
      <div className="approval-head">
        APPROVAL NEEDED
        <span className="muted"> · {req.server} ({req.posture})</span>
      </div>
      {req.purpose && <div className="muted">purpose: {req.purpose}</div>}
      <div className="muted">reason: {req.reason}</div>
      <pre className="command">{req.command}</pre>
      <div className="approval-actions">
        <button className="btn ok" onClick={r("y")}>Run once</button>
        <button className="btn danger" onClick={r("n")}>Deny</button>
        <button className="btn" onClick={r("b")}>Always <code>{req.binary}</code> on {req.server}</button>
        <button className="btn" onClick={r("e")}>Always this exact cmd</button>
        <button className="btn" onClick={r("g")}>Always <code>{req.binary}</code> on ALL</button>
      </div>
    </div>
  );
}
