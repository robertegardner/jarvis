import { useEffect, useState } from "react";
import { api } from "../api";
import type { TaskEntry } from "../types";

// The append-only task journal across all servers (the seed for future learned
// automation). Read-only here; refreshable.
export function JournalPanel() {
  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const load = () => api.getTasks(100).then(setTasks).catch(() => {});
  useEffect(() => { load(); }, []);

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button className="btn" onClick={load}>Refresh</button>
        <span className="muted">{tasks.length} most recent</span>
      </div>
      <table className="rules">
        <thead><tr><th>when</th><th>server</th><th>decision</th><th>exit</th><th>command</th></tr></thead>
        <tbody>
          {tasks.slice().reverse().map((t, i) => (
            <tr key={i} className={t.exit_code ? "exit-bad" : ""}>
              <td className="muted">{t.ts.replace("T", " ").replace("+00:00", "")}</td>
              <td>{t.server}</td>
              <td>{t.decision}</td>
              <td>{t.exit_code ?? "—"}</td>
              <td><code>{t.command}</code></td>
            </tr>
          ))}
          {tasks.length === 0 && <tr><td colSpan={5} className="muted">Journal is empty.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
