import { useState } from "react";
import { api } from "../api";
import { errorText } from "../hooks";
import type { Connection, ConnectionTest, Role } from "../types";

interface Props {
  connections: Connection[];
  activeId: string | null;
  role: Role;
  onSelect: (id: string) => void;
  onChanged: () => void;
}

export function Settings({ connections, activeId, role, onSelect, onChanged }: Props) {
  const [form, setForm] = useState({ name: "", site_url: "https://", email: "", api_token: "" });
  const [test, setTest] = useState<Record<string, ConnectionTest>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = role === "admin";

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try { await fn(); } catch (e) { setError(errorText(e)); } finally { setBusy(null); }
  }

  const create = () => run("create", async () => {
    const conn = await api.createConnection(form);
    setForm({ name: "", site_url: "https://", email: "", api_token: "" });
    const result = await api.testConnection(conn.id);
    setTest((t) => ({ ...t, [conn.id]: result }));
    onSelect(conn.id);
    onChanged();
  });

  const retest = (id: string) => run(id, async () => {
    const result = await api.testConnection(id);
    setTest((t) => ({ ...t, [id]: result }));
    onChanged();
  });

  return (
    <div className="stack">
      <div className="page-head">
        <div><h1>Atlassian connections</h1><p>API tokens are encrypted at rest and never shown again.</p></div>
      </div>
      {error && <div className="alert err">{error}</div>}
      <div className="grid-2">
        <div className="card stack">
          <h2>Connected sites</h2>
          {connections.length === 0 && <div className="muted">No sites connected yet.</div>}
          {connections.map((c) => {
            const t = test[c.id];
            return (
              <div key={c.id} className="op">
                <div className="op-head">
                  <input type="radio" name="active" style={{ width: "auto" }} checked={c.id === activeId}
                    onChange={() => onSelect(c.id)} aria-label={`Use ${c.name}`} />
                  <b>{c.name}</b><span className="muted">{c.site_url}</span>
                  <span style={{ marginLeft: "auto" }} className={`badge ${c.last_test_status === "ok" ? "ok" : c.last_test_status === "partial" ? "warn" : c.last_test_status ? "err" : ""}`}>
                    {c.last_test_status ?? "untested"}
                  </span>
                </div>
                <div className="row small">
                  {["jira", "jsm", "confluence"].map((p) => (
                    <span key={p} className={`badge ${c.capabilities?.products?.[p] ? "ok" : ""}`}>{p}</span>
                  ))}
                  {c.capabilities?.is_jira_admin != null && (
                    <span className={`badge ${c.capabilities.is_jira_admin ? "ok" : "warn"}`}>
                      {c.capabilities.is_jira_admin ? "Jira admin" : "not Jira admin"}
                    </span>
                  )}
                  {isAdmin && <button disabled={busy === c.id} onClick={() => void retest(c.id)}>{busy === c.id ? "Testing…" : "Test"}</button>}
                </div>
                {t && <ul className="small" style={{ margin: 0 }}>{t.products.map((p) => <li key={p.product}><b>{p.product}</b>: {p.detail}</li>)}</ul>}
              </div>
            );
          })}
        </div>

        <form className="card stack" onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <h2>Connect a site</h2>
          {!isAdmin && <div className="alert warn">Only admins can add connections.</div>}
          <label>Name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Production" /></label>
          <label>Site URL<input required type="url" value={form.site_url} onChange={(e) => setForm({ ...form, site_url: e.target.value })} placeholder="https://your-site.atlassian.net" /></label>
          <label>Account email<input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>API token<input required type="password" autoComplete="off" value={form.api_token} onChange={(e) => setForm({ ...form, api_token: e.target.value })} /></label>
          <div className="small muted">Create a token at id.atlassian.com → Security → API tokens. Use an account with Jira administrator rights for admin tasks.</div>
          <button className="primary" disabled={!isAdmin || busy === "create"}>{busy === "create" ? "Connecting…" : "Save and test"}</button>
        </form>
      </div>
    </div>
  );
}
