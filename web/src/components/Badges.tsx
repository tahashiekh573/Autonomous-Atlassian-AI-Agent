import type { Operation, RunStatus } from "../types";

const RUN_TONE: Record<RunStatus, string> = {
  planning: "info", executing: "info", needs_clarification: "warn", blocked: "err",
  awaiting_approval: "warn", completed: "ok", completed_with_errors: "warn", failed: "err",
  rejected: "",
};

const OP_TONE: Record<Operation["status"], string> = {
  pending: "", requires_approval: "warn", in_progress: "info", completed: "ok", failed: "err",
  skipped: "",
};

const OP_LABEL: Record<Operation["status"], string> = {
  pending: "Pending", requires_approval: "Requires approval", in_progress: "In progress",
  completed: "Completed", failed: "Failed", skipped: "Skipped",
};

const RISK_TONE: Record<string, string> = {
  read: "", create: "info", modify: "warn", destructive: "err", security: "err",
};

export const human = (s: string) => s.replace(/_/g, " ");

export function RunBadge({ status }: { status: RunStatus }) {
  return <span className={`badge ${RUN_TONE[status]}`}>{human(status)}</span>;
}

export function OpBadge({ status }: { status: Operation["status"] }) {
  return <span className={`badge ${OP_TONE[status]}`}>{OP_LABEL[status]}</span>;
}

export function RiskBadge({ risk }: { risk: string }) {
  return <span className={`badge ${RISK_TONE[risk] ?? ""}`}>{risk}</span>;
}
