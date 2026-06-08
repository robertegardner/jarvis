import { useEffect, useState } from "react";
import { api } from "../api";
import type { ServerRow } from "../types";

// View/edit the inventory. Saving writes inventory.yaml; the running agent session
// only picks changes up on reload, so we nudge the user to reload after saving.
export function ServersPanel({ onReload }: { onReload: () => void }) {
  const [rows, setRows] = useState<ServerRow[]>([]);
  const [postures, setPostures] = useState<string[]>(["strict", "normal", "trusted"]);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");

  const load = () =>
    api.getInventory().then((r) => {
      setRows(r.servers);
      setDirty(false);
    });

  useEffect(() => {
    load().catch((e) => setMsg(String(e.message)));
    api.postures().then(setPostures).catch(() => {});
  }, []);

  const edit = (i: number, patch: Partial<ServerRow>) => {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    setDirty(true);
  };

  const save = async () => {
    try {
      const r = await api.putInventory(rows);
      setRows(r.servers);
      setDirty(false);
      setMsg("Saved. Reload the session to apply.");
    } catch (e) {
      setMsg(String((e as Error).message));
    }
  };

  return (
    <div className="panel-body">
      <div className="panel-actions">
        <button className="btn ok" onClick={save} disabled={!dirty}>Save inventory</button>
        <button className="btn" onClick={onReload}>Reload session</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
      {rows.map((s, i) => (
        <div className="server-card" key={s.name}>
          <div className="server-name">{s.name}</div>
          <label>host
            <input value={s.host} onChange={(e) => edit(i, { host: e.target.value })} />
          </label>
          <label>user
            <input value={s.user} onChange={(e) => edit(i, { user: e.target.value })} />
          </label>
          <label>port
            <input type="number" value={s.port}
              onChange={(e) => edit(i, { port: Number(e.target.value) })} />
          </label>
          <label>posture
            <select value={s.posture} onChange={(e) => edit(i, { posture: e.target.value })}>
              {postures.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label className="wide">description
            <input value={s.description}
              onChange={(e) => edit(i, { description: e.target.value })} />
          </label>
        </div>
      ))}
    </div>
  );
}
