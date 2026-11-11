import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { errorText } from "../hooks";
import type { Operation, Role, RunDetail } from "../types";
import { AgentPipeline, RunProgress } from "./AgentPipeline";
import { human, OpBadge, RiskBadge, RunBadge } from "./Badges";

const ELEVATED = new Set(["destructive", "security"]);

interface Props {
  run: RunDetail;
  role: Role;
  onChange: (run: RunDetail) => void;
  speak: (text: string) => void;
}

export function RunView({ run, role, onChange, speak }: Props) {
  const awaiting = run.status === "awaiting_approval";
  const pending = run.operations.filter((o) => o.requires_approval && !o.approved);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Default selection: everything except destructive / security-sensitive steps.
    setSelected(new Set(pending.filter((o) => !ELEVATED.has(o.risk)).map((o) => o.op_id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, run.status]);

  const errors = run.plan_issues.filter((i) => i.severity === "error");
  const warnings = [...run.plan_issues.filter((i) => i.severity === "warning").map((i) => i.message),
    ...(run.plan?.warnings ?? [])];

  async function act(fn: () => Promise<RunDetail>) {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const canApproveElevated = role === "admin";
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  return (
    <div className="stack">
      <div className="card stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Execution plan</h2>
          <RunBadge status={run.status} />
        </div>

        <AgentPipeline run={run} />
        <RunProgress run={run} />

        {run.current_agent && (
          <div className="agent-live" role="status" aria-live="polite">
            <span className="pulse" aria-hidden="true" />
            <span><b>{human(run.current_agent)}</b> · {run.progress_message}</span>
          </div>
        )}
        {!run.current_agent && run.status === "planning" && (
          <div className="stack" style={{ gap: 8 }} aria-label="Loading">
            <div className="skeleton" style={{ width: "70%" }} />
            <div className="skeleton" style={{ width: "90%" }} />
            <div className="skeleton" style={{ width: "55%" }} />
          </div>
        )}

        {run.plan && <p style={{ margin: 0 }}>{run.plan.summary}</p>}
        {run.intent && run.intent.language !== "en" && (
          <div className="small muted">Understood ({run.intent.language}): {run.intent.normalized_instruction}</div>
        )}
        {run.error && <div className="alert err">{run.error}</div>}
        {errors.length > 0 && (
          <div className="alert err">
            <b>The plan cannot run yet:</b>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {errors.map((i, n) => <li key={n}>{i.operation_id ? `${i.operation_id}: ` : ""}{i.message}</li>)}
            </ul>
            <div className="small">Reply in the chat to revise the request.</div>
          </div>
        )}
        {warnings.length > 0 && (
          <div className="alert warn">
            <ul style={{ margin: 0, paddingLeft: 18 }}>{warnings.map((w, n) => <li key={n}>{w}</li>)}</ul>
          </div>
        )}
        {run.plan && run.plan.assumptions.length > 0 && (
          <details>
            <summary>Assumptions ({run.plan.assumptions.length})</summary>
            <ul>{run.plan.assumptions.map((a, n) => <li key={n}>{a}</li>)}</ul>
          </details>
        )}

        <div className="ops">
          {run.operations.map((op, i) => (
            <OperationRow
              index={i}
              key={op.op_id}
              op={op}
              selectable={awaiting && op.requires_approval && !op.approved}
              checked={selected.has(op.op_id)}
              lockedReason={ELEVATED.has(op.risk) && !canApproveElevated ? "Needs an admin" : null}
              onToggle={() => toggle(op.op_id)}
            />
          ))}
        </div>

        {awaiting && (
          <div className="row">
            <button className="primary" disabled={busy || selected.size === 0 || role === "viewer"}
              onClick={() => act(() => api.approve(run.id, [...selected]))}>
              Approve {selected.size} step{selected.size === 1 ? "" : "s"} and execute
            </button>
            <button disabled={busy || role === "viewer"} onClick={() => act(() => api.reject(run.id, "Rejected in dashboard"))}>
              Reject plan
            </button>
            <span className="small muted">Unselected steps (and steps depending on them) are skipped.</span>
          </div>
        )}
        {error && <div className="alert err">{error}</div>}
      </div>

      {run.report && <ReportCard run={run} speak={speak} />}
    </div>
  );
}

function OperationRow({ op, index, selectable, checked, lockedReason, onToggle }: {
  op: Operation; index: number; selectable: boolean; checked: boolean; lockedReason: string | null;
  onToggle: () => void;
}) {
  const resource = op.outcome?.resource;
  const params = op.resolved_params ?? op.params;
  return (
    <div className={`op ${op.status}`} style={{ animationDelay: `${Math.min(index, 20) * 35}ms` }}>
      <div className="op-head">
        {selectable && (
          <input type="checkbox" style={{ width: "auto" }} checked={checked} disabled={!!lockedReason}
            onChange={onToggle} aria-label={`Approve ${op.op_id}`} />
        )}
        <b>{op.op_id}</b>
        <span>{op.description}</span>
        <span className="name">{op.operation}</span>
        <RiskBadge risk={op.risk} />
        {!op.supported && <span className="badge warn">API limitation</span>}
        <span style={{ marginLeft: "auto" }}><OpBadge status={op.status} /></span>
      </div>
      {lockedReason && selectable && <div className="small muted">{lockedReason} to approve this step.</div>}
      {op.preflight && op.status === "requires_approval" && (
        <div className={`small ${op.preflight.conflict ? "" : "muted"}`}>Preflight: {op.preflight.message}</div>
      )}
      {op.message && op.status !== "requires_approval" && op.status !== "pending" && (
        <div className="small">{op.message}</div>
      )}
      {resource?.url && op.status === "completed" && (
        <a className="small" href={resource.url} target="_blank" rel="noreferrer">
          Open {human(resource.type)} {resource.key ?? resource.title ?? ""}
        </a>
      )}
      <details>
        <summary>Details{op.depends_on.length ? ` · depends on ${op.depends_on.join(", ")}` : ""}</summary>
        <pre>{JSON.stringify(params, null, 2)}</pre>
        {op.verification && (
          <>
            <div className="small"><b>Verification:</b> {op.verification.message}</div>
            <ul className="small">
              {op.verification.checks.map((c, n) => (
                <li key={n}>{c.passed ? "✓" : "✗"} {c.name}{!c.passed ? ` — expected ${JSON.stringify(c.expected)}, got ${JSON.stringify(c.actual)}` : ""}</li>
              ))}
            </ul>
          </>
        )}
        {op.outcome?.outputs && Object.keys(op.outcome.outputs).length > 0 && (
          <pre>{JSON.stringify(op.outcome.outputs, null, 2)}</pre>
        )}
      </details>
    </div>
  );
}

function ReportCard({ run, speak }: { run: RunDetail; speak: (text: string) => void }) {
  const report = run.report!;
  const resources = useMemo(() => report.created_resources, [report]);
  return (
    <div className={`card stack ${report.failed === 0 && report.completed > 0 ? "celebrate" : ""}`}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Execution report</h2>
        <button onClick={() => speak(report.summary)} aria-label="Read the summary aloud">🔊 Read aloud</button>
      </div>
      <p style={{ margin: 0 }}>{report.summary}</p>
      <div className="stats">
        <div className="stat"><b style={{ color: "var(--ok)" }}>{report.completed}</b>completed &amp; verified</div>
        <div className="stat"><b style={{ color: "var(--err)" }}>{report.failed}</b>failed</div>
        <div className="stat"><b>{report.skipped}</b>skipped</div>
      </div>
      {resources.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Resource</th><th>Key / ID</th><th>Name</th></tr></thead>
            <tbody>
              {resources.map((r, n) => (
                <tr key={n}>
                  <td>{human(r.type)}</td>
                  <td><code>{r.key ?? r.id}</code></td>
                  <td>{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> : r.title}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {report.issues.length > 0 && (
        <div><h3>Errors and unresolved items</h3><ul>{report.issues.map((i, n) => <li key={n}>{i}</li>)}</ul></div>
      )}
      {report.next_steps.length > 0 && (
        <div><h3>Next steps</h3><ul>{report.next_steps.map((i, n) => <li key={n}>{i}</li>)}</ul></div>
      )}
    </div>
  );
}
