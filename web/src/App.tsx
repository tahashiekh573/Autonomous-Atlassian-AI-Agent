import { useCallback, useEffect, useState } from "react";
import { api, ApiError, setToken } from "./api";
import { CommandCenter } from "./components/CommandCenter";
import { History } from "./components/History";
import { Login } from "./components/Login";
import { ProductSection, type Product } from "./components/ProductSection";
import { Settings } from "./components/Settings";
import type { CatalogEntry, Connection, User } from "./types";

type View = "command" | Product | "history" | "settings";

const NAV: { id: View; label: string }[] = [
  { id: "command", label: "Command center" },
  { id: "jira", label: "Jira" },
  { id: "jsm", label: "Service Management" },
  { id: "confluence", label: "Confluence" },
  { id: "integration", label: "Integrations" },
  { id: "history", label: "History" },
  { id: "settings", label: "Settings" },
];

const ACTIVE_CONN_KEY = "aaa.connection";

function remembered(): string | null {
  try { return localStorage.getItem(ACTIVE_CONN_KEY); } catch { return null; }
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [view, setView] = useState<View>("command");
  const [connections, setConnections] = useState<Connection[]>([]);
  const [activeId, setActiveId] = useState<string | null>(remembered());
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [health, setHealth] = useState<string>("…");
  const [tts, setTts] = useState<string | null>(null);

  const [bootError, setBootError] = useState<string | null>(null);

  const checkAuth = useCallback(() => {
    setBootError(null);
    api.me().then(setUser).catch((e) => {
      // Only a real 401 means "please sign in"; anything else is a connectivity problem.
      if (e instanceof ApiError && e.status === 401) return;
      setBootError(e instanceof ApiError ? e.message : String(e));
    }).finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => { checkAuth(); }, [checkAuth]);

  const loadConnections = useCallback(async () => {
    const list = await api.connections();
    setConnections(list);
    setActiveId((current) => (current && list.some((c) => c.id === current) ? current : list[0]?.id ?? null));
  }, []);

  useEffect(() => {
    if (!user) return;
    void loadConnections();
    api.catalog().then(setCatalog).catch(() => setCatalog([]));
    api.voiceCapabilities().then((c) => setTts(c.tts)).catch(() => setTts(null));
    api.health().then((h) => setHealth(h.status)).catch(() => setHealth("down"));
  }, [user, loadConnections]);

  useEffect(() => {
    try { if (activeId) localStorage.setItem(ACTIVE_CONN_KEY, activeId); } catch { /* optional */ }
  }, [activeId]);

  const speak = useCallback(async (text: string) => {
    if (tts) {
      const response = await fetch("/api/v1/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${sessionStorage.getItem("aaa.token") ?? ""}` },
        body: JSON.stringify({ text }),
      }).catch(() => null);
      if (response?.ok) {
        void new Audio(URL.createObjectURL(await response.blob())).play();
        return;
      }
    }
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
    }
  }, [tts]);

  if (!authChecked) return null;
  if (bootError) {
    return (
      <div className="login">
        <div className="card stack" role="alert">
          <h1>Backend not reachable</h1>
          <p className="muted" style={{ margin: 0 }}>{bootError}</p>
          <pre>cd "F:\Autonomous Atlassian AI Agent"{"\n"}npm start</pre>
          <button className="primary" onClick={checkAuth}>Retry</button>
        </div>
      </div>
    );
  }
  if (!user) return <Login onLogin={setUser} />;

  const connection = connections.find((c) => c.id === activeId) ?? null;
  const useCommand = (text: string) => { setDraft(text); setRunId(null); setView("command"); };

  return (
    <div className="layout">
      <nav className="sidebar" aria-label="Main">
        <div className="brand">Atlassian AI Admin<small>Jira · JSM · Confluence</small></div>
        {NAV.map((n) => (
          <button key={n.id} className={`nav-item ${view === n.id ? "active" : ""}`} aria-current={view === n.id ? "page" : undefined}
            onClick={() => setView(n.id)}>{n.label}</button>
        ))}
        <div className="sidebar-footer">
          <div>
            <span className={`badge ${connection?.last_test_status === "ok" ? "ok" : connection ? "warn" : "err"}`}>
              {connection ? connection.last_test_status ?? "untested" : "no site"}
            </span>{" "}
            {connection ? new URL(connection.site_url).host : "Not connected"}
          </div>
          <div>API: <span className={`badge ${health === "ok" ? "ok" : "err"}`}>{health}</span></div>
          <div>{user.display_name} · {user.role}</div>
          {user.id !== "dev" && user.id !== "service" && (
            <button className="link" style={{ textAlign: "left" }} onClick={() => { setToken(null); setUser(null); }}>Sign out</button>
          )}
        </div>
      </nav>

      <main className="main">
        {view === "command" && (
          <>
            <div className="page-head">
              <div><h1>Command center</h1><p>Plan, approve and execute real changes in {connection ? new URL(connection.site_url).host : "your Atlassian site"}.</p></div>
            </div>
            <CommandCenter connection={connection} role={user.role} runId={runId} onRunId={setRunId}
              draft={draft} setDraft={setDraft} speak={(t) => void speak(t)} />
          </>
        )}
        {(view === "jira" || view === "jsm" || view === "confluence" || view === "integration") && (
          <ProductSection product={view} connection={connection} catalog={catalog} onUse={useCommand} />
        )}
        {view === "history" && <History onOpen={(id) => { setRunId(id); setView("command"); }} />}
        {view === "settings" && (
          <Settings connections={connections} activeId={activeId} role={user.role} onSelect={setActiveId}
            onChanged={() => void loadConnections()} />
        )}
      </main>
    </div>
  );
}
