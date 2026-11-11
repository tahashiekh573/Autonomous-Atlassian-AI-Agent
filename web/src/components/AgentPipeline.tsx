import type { RunDetail } from "../types";

const STAGES: { id: string; label: string; icon: string; agents: string[] }[] = [
  { id: "understand", label: "Understand", icon: "🧠", agents: ["input_understanding_agent"] },
  { id: "plan", label: "Plan", icon: "🗺️", agents: ["planning_agent"] },
  { id: "jira", label: "Jira", icon: "🧩", agents: ["jira_agent"] },
  { id: "jsm", label: "Service Mgmt", icon: "🛟", agents: ["jsm_agent"] },
  { id: "confluence", label: "Confluence", icon: "📘", agents: ["confluence_agent"] },
  { id: "integration", label: "Integrate", icon: "🔗", agents: ["integration_agent"] },
  { id: "verify", label: "Verify", icon: "✅", agents: ["verification_agent"] },
  { id: "report", label: "Report", icon: "📝", agents: ["response_agent"] },
];

const PLANNED = ["awaiting_approval", "executing", "completed", "completed_with_errors", "failed", "blocked"];
const FINISHED = ["completed", "completed_with_errors", "failed"];

/** Eight agents in order; the one currently working glows, finished stages turn green. */
export function AgentPipeline({ run }: { run: RunDetail }) {
  const usedAgents = new Set(run.operations.filter((o) => o.status !== "pending" && o.status !== "requires_approval").map((o) => o.agent));
  const doneFor = (id: string, agents: string[]) => {
    if (id === "understand") return !!run.intent;
    if (id === "plan") return PLANNED.includes(run.status);
    if (id === "verify") return run.operations.some((o) => o.verification);
    if (id === "report") return !!run.report;
    return agents.some((a) => usedAgents.has(a)) && (FINISHED.includes(run.status) || run.current_agent !== agents[0]);
  };
  return (
    <div className="pipeline" aria-label="Agent pipeline">
      {STAGES.map((s) => {
        const active = !!run.current_agent && s.agents.includes(run.current_agent);
        const done = !active && doneFor(s.id, s.agents);
        return (
          <div key={s.id} className={`agent-node ${active ? "active" : ""} ${done ? "done" : ""}`}
            aria-current={active ? "step" : undefined}>
            <div className="agent-dot" aria-hidden="true">{s.icon}</div>
            <span>{s.label}</span>
          </div>
        );
      })}
    </div>
  );
}

export function RunProgress({ run }: { run: RunDetail }) {
  const total = run.operations.length;
  if (!total || !["executing", "completed", "completed_with_errors", "failed"].includes(run.status)) return null;
  const finished = run.operations.filter((o) => ["completed", "failed", "skipped"].includes(o.status)).length;
  const pct = Math.round((finished / total) * 100);
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row small muted" style={{ justifyContent: "space-between" }}>
        <span>{finished} of {total} steps finished</span><span>{pct}%</span>
      </div>
      <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
