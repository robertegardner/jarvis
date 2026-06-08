import { useEffect, useState } from "react";
import { api } from "../api";
import type { ServerInfo, TaskEntry } from "../types";

// Per-server facts (markdown) plus a recent-action history, with a box to append
// a fact. Picking a server reloads both.
export function MemoryPanel({ servers }: { servers: ServerInfo[] }) {
  const [server, setServer] = useState(servers[0]?.name || "");
  const [facts, setFacts] = useState("");
  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [note, setNote] = useState("");

  const load = (s: string) => {
    if (!s) return;
    api.getMemory(s).then((m) => { setFacts(m.facts); setTasks(m.tasks); }).catch(() => {});
  };

  useEffect(() => {
    if (!server && servers[0]) setServer(servers[0].name);
  }, [servers, server]);
  useEffect(() => { load(server); }, [server]);

  const addFact = async () => {
    if (!note.trim()) return;
    const m = await api.addFact(server, note);
    setFacts(m.facts);
    setNote("");
  };

  return (
    <div className="panel-body">
      <label>server
        <select value={server} onChange={(e) => setServer(e.target.value)}>
          {servers.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
      </label>

      <h4>Facts</h4>
      <pre className="facts">{facts.trim() || "(nothing remembered yet)"}</pre>
      <div className="rule-form">
        <input className="wide" placeholder="Remember a fact about this server…"
          value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn ok" onClick={addFact} disabled={!note.trim()}>Remember</button>
      </div>

      <h4>Recent actions</h4>
      <table className="rules">
        <thead><tr><th>when</th><th>decision</th><th>exit</th><th>command</th></tr></thead>
        <tbody>
          {tasks.map((t, i) => (
            <tr key={i}>
              <td className="muted">{t.ts.replace("T", " ").replace("+00:00", "")}</td>
              <td>{t.decision}</td>
              <td>{t.exit_code ?? "—"}</td>
              <td><code>{t.command}</code></td>
            </tr>
          ))}
          {tasks.length === 0 && <tr><td colSpan={4} className="muted">No recorded actions.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
