import { api } from "../api";
import { useLoad } from "../hooks";
import { ACTIVE } from "../types";
import { human, RunBadge } from "./Badges";

export function History({ onOpen }: { onOpen: (id: string) => void }) {
  const { data: runs, error, refresh } = useLoad(() => api.runs(100), [], (r) => r.some((x) => ACTIVE.includes(x.status)), 3000);
  return (
    <div className="stack">
      <div className="page-head">
        <div><h1>Execution history</h1><p>Every command, its plan, approvals and verified results.</p></div>
        <button onClick={() => void refresh()}>Refresh</button>
      </div>
      {error && <div className="alert err">{error}</div>}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>When</th><th>Command</th><th>Input</th><th>By</th><th>Status</th><th>Agent</th></tr></thead>
          <tbody>
            {(runs ?? []).map((r) => (
              <tr key={r.id}>
                <td className="small">{new Date(r.created_at).toLocaleString()}</td>
                <td><button className="link" onClick={() => onOpen(r.id)} style={{ textAlign: "left" }}>{r.input_text.slice(0, 110)}</button></td>
                <td><span className="badge">{r.input_mode}</span></td>
                <td className="small">{r.created_by}</td>
                <td><RunBadge status={r.status} /></td>
                <td className="small muted">{r.current_agent ? human(r.current_agent) : "—"}</td>
              </tr>
            ))}
            {runs && runs.length === 0 && <tr><td colSpan={6} className="muted">No runs yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
