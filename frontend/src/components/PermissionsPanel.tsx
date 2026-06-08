import { useEffect, useState } from "react";
import { api } from "../api";
import type { PermissionRule, ServerInfo } from "../types";

// List, add, and delete saved-authority rules. Strict-posture servers ignore
// these (the backend re-asks regardless), which we note for the operator.
export function PermissionsPanel({ servers }: { servers: ServerInfo[] }) {
  const [rules, setRules] = useState<PermissionRule[]>([]);
  const [draft, setDraft] = useState({ server: "*", match: "binary", value: "", note: "" });
  const [msg, setMsg] = useState("");

  const load = () => api.getPermissions().then(setRules).catch((e) => setMsg(String(e.message)));
  useEffect(() => { load(); }, []);

  const add = async () => {
    try {
      setRules(await api.addPermission(draft));
      setDraft({ ...draft, value: "", note: "" });
      setMsg("");
    } catch (e) {
      setMsg(String((e as Error).message));
    }
  };
  const del = async (i: number) => setRules(await api.deletePermission(i));

  return (
    <div className="panel-body">
      <div className="rule-form">
        <select value={draft.server} onChange={(e) => setDraft({ ...draft, server: e.target.value })}>
          <option value="*">all servers</option>
          {servers.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
        <select value={draft.match} onChange={(e) => setDraft({ ...draft, match: e.target.value })}>
          <option value="binary">binary</option>
          <option value="prefix">prefix</option>
          <option value="exact">exact</option>
        </select>
        <input placeholder="value (e.g. apt)" value={draft.value}
          onChange={(e) => setDraft({ ...draft, value: e.target.value })} />
        <input placeholder="note (optional)" value={draft.note}
          onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
        <button className="btn ok" onClick={add} disabled={!draft.value.trim()}>Add rule</button>
      </div>
      {msg && <div className="muted">{msg}</div>}
      <table className="rules">
        <thead><tr><th>server</th><th>match</th><th>value</th><th>note</th><th></th></tr></thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.index}>
              <td>{r.server}</td>
              <td>{r.match}</td>
              <td><code>{r.value}</code></td>
              <td className="muted">{r.note}</td>
              <td><button className="btn danger small" onClick={() => del(r.index)}>✕</button></td>
            </tr>
          ))}
          {rules.length === 0 && (
            <tr><td colSpan={5} className="muted">No saved rules yet.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
