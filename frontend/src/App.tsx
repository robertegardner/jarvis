import { useState } from "react";
import { clearToken, getToken, setToken } from "./api";
import { ConversationView } from "./components/ConversationView";
import { JournalPanel } from "./components/JournalPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { MessageInput } from "./components/MessageInput";
import { PermissionsPanel } from "./components/PermissionsPanel";
import { ServersPanel } from "./components/ServersPanel";
import { useAgentSocket } from "./useAgentSocket";

type Tab = "servers" | "permissions" | "memory" | "journal";

function TokenGate({ onSet }: { onSet: (t: string) => void }) {
  const [t, setT] = useState("");
  return (
    <div className="token-gate">
      <h1>Jarvis</h1>
      <p className="muted">Paste the token printed by <code>jarvis web</code> on startup.</p>
      <input value={t} onChange={(e) => setT(e.target.value)} placeholder="token"
        onKeyDown={(e) => e.key === "Enter" && t.trim() && onSet(t.trim())} />
      <button className="btn ok" disabled={!t.trim()} onClick={() => onSet(t.trim())}>Connect</button>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const cls = status === "open" ? "ok" : status === "unauthorized" ? "bad" : "warn";
  return <span className={`dot ${cls}`} title={status} />;
}

export default function App() {
  const [token, setTok] = useState(getToken());
  const [tab, setTab] = useState<Tab>("servers");

  if (!token) {
    return <TokenGate onSet={(t) => { setToken(t); setTok(t); }} />;
  }
  return <Workspace token={token} tab={tab} setTab={setTab} onSignOut={() => { clearToken(); setTok(""); }} />;
}

function Workspace({
  token, tab, setTab, onSignOut,
}: {
  token: string; tab: Tab; setTab: (t: Tab) => void; onSignOut: () => void;
}) {
  const a = useAgentSocket(token);

  if (a.status === "unauthorized") {
    return (
      <div className="token-gate">
        <h1>Rejected</h1>
        <p className="muted">That token was not accepted by the backend.</p>
        <button className="btn" onClick={onSignOut}>Enter a different token</button>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <strong>Jarvis</strong>
        <StatusDot status={a.status} />
        <span className="muted">{a.servers.length} server(s)</span>
        <div className="spacer" />
        <button className="btn small" onClick={a.reload}>Reload session</button>
        <button className="btn small" onClick={onSignOut}>Sign out</button>
      </header>

      <main className="main">
        <section className="chat">
          <ConversationView feed={a.feed} approvals={a.approvals} onRespond={a.respondApproval} />
          <MessageInput busy={a.busy} onSend={a.sendDirective} onInterrupt={a.interrupt} />
        </section>

        <aside className="side">
          <nav className="tabs">
            {(["servers", "permissions", "memory", "journal"] as Tab[]).map((t) => (
              <button key={t} className={"tab" + (tab === t ? " active" : "")} onClick={() => setTab(t)}>
                {t}
              </button>
            ))}
          </nav>
          {tab === "servers" && <ServersPanel onReload={a.reload} />}
          {tab === "permissions" && <PermissionsPanel servers={a.servers} />}
          {tab === "memory" && <MemoryPanel servers={a.servers} />}
          {tab === "journal" && <JournalPanel />}
        </aside>
      </main>
    </div>
  );
}
