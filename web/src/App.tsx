import { useCallback, useEffect, useState } from "react";
import { api, ApiError, setToken } from "./api";
import { CommandCenter } from "./components/CommandCenter";
import { Icon, type IconName } from "./components/Icons";
import { fxEnabled, setFx } from "./fx";
import { History } from "./components/History";
import { Login } from "./components/Login";
import { ProductSection, type Product } from "./components/ProductSection";
import { Settings } from "./components/Settings";
import type { CatalogEntry, Connection, User } from "./types";

type View = "command" | Product | "history" | "settings";

const NAV: { id: View; label: string; icon: IconName; tint: string }[] = [
  { id: "command", label: "Command center", icon: "spark", tint: "#7c5cff" },
  { id: "jira", label: "Jira", icon: "jira", tint: "#2684ff" },
  { id: "jsm", label: "Service Management", icon: "lifebuoy", tint: "#00b8a9" },
  { id: "confluence", label: "Confluence", icon: "book", tint: "#1d7afc" },
  { id: "integration", label: "Integrations", icon: "link", tint: "#f5a623" },
  { id: "history", label: "History", icon: "clock", tint: "#e5487b" },
  { id: "settings", label: "Settings", icon: "gear", tint: "#8a94a6" },
];

const THEME_KEY = "aaa.theme";
type Theme = "light" | "dark" | null;

function storedTheme(): Theme {
  try { const t = localStorage.getItem(THEME_KEY); return t === "light" || t === "dark" ? t : null; } catch { return null; }
}

function isDark(theme: Theme): boolean {
  return theme ? theme === "dark" : window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

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
  const [theme, setTheme] = useState<Theme>(storedTheme());

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try { if (theme) localStorage.setItem(THEME_KEY, theme); } catch { /* optional */ }
  }, [theme]);
  const toggleTheme = () => setTheme(isDark(theme) ? "light" : "dark");
  const [motion, setMotion] = useState(fxEnabled());
  const toggleMotion = () => { setFx(!motion); setMotion(!motion); };

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
        <div className="card stack login-card" role="alert">
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
        <div className="brand">
          <div className="brand-logo" aria-hidden="true"><Icon name="bolt" size={18} /></div>
          <div><b>Atlassian AI Admin</b><small>Jira · JSM · Confluence</small></div>
        </div>
        <div className="nav-label">Workspace</div>
        {NAV.map((n) => (
          <button key={n.id} className={`nav-item ${view === n.id ? "active" : ""}`} aria-current={view === n.id ? "page" : undefined}
            style={{ "--tint": n.tint } as React.CSSProperties}
            onClick={() => setView(n.id)}><span className="ico"><Icon name={n.icon} /></span>{n.label}</button>
        ))}
        <div className="sidebar-footer">
          <div>
            <span className={`badge ${connection?.last_test_status === "ok" ? "ok" : connection ? "warn" : "err"}`}>
              {connection ? connection.last_test_status ?? "untested" : "no site"}
            </span>{" "}
            {connection ? new URL(connection.site_url).host : "Not connected"}
          </div>
          <div>API: <span className={`badge ${health === "ok" ? "ok" : "err"}`}>{health}</span></div>
          <div className="user-chip">
            <span className="avatar" aria-hidden="true">{(user.display_name || "?").slice(0, 1).toUpperCase()}</span>
            <span className="user-meta"><b>{user.display_name}</b><small>{user.role}</small></span>
            <button className={`icon-btn ${motion ? "" : "off"}`} onClick={toggleMotion}
              title={motion ? "Animations on (click to turn off)" : "Animations off (click to turn on)"}
              aria-label="Toggle background animations" aria-pressed={motion}>
              <Icon name="spark" size={16} />
            </button>
            <button className="icon-btn" onClick={toggleTheme} title="Toggle light / dark" aria-label="Toggle light or dark theme">
              <Icon name={isDark(theme) ? "sun" : "moon"} size={16} />
            </button>
            {user.id !== "dev" && user.id !== "service" && (
              <button className="icon-btn" onClick={() => { setToken(null); setUser(null); }} title="Sign out" aria-label="Sign out">
                <Icon name="logout" size={16} />
              </button>
            )}
          </div>
        </div>
      </nav>

      <main className="main">
        {view === "command" && (
          <>
            <section className="hero">
              <div className="hero-text">
                <span className="eyebrow"><Icon name="spark" size={14} /> {greeting()}, {user.display_name.split(" ")[0]}</span>
                <h1>What should your agents build today?</h1>
                <p>Plan, approve and execute real changes in <b>{connection ? new URL(connection.site_url).host : "your Atlassian site"}</b>. Every step is verified against the live system.</p>
              </div>
              <div className="hero-stats">
                <div className="hero-stat"><Icon name="brain" /><b>8</b><small>AI agents</small></div>
                <div className="hero-stat"><Icon name="bolt" /><b>{catalog.length || "—"}</b><small>operations</small></div>
                <div className="hero-stat"><Icon name="globe" /><b>3</b><small>languages</small></div>
                <div className="hero-stat"><Icon name="shield" /><b>{connection?.last_test_status === "ok" ? "Live" : "Off"}</b><small>site link</small></div>
              </div>
            </section>
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
