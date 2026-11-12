export type Role = "viewer" | "operator" | "admin";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
}

export interface Connection {
  id: string;
  name: string;
  site_url: string;
  email: string;
  last_tested_at: string | null;
  last_test_status: "ok" | "partial" | "failed" | null;
  capabilities: {
    account_id?: string | null;
    is_jira_admin?: boolean | null;
    products?: Record<string, boolean>;
  } | null;
}

export interface ProductStatus {
  product: string;
  available: boolean;
  detail: string;
  error_code: string | null;
}

export interface ConnectionTest {
  status: "ok" | "partial" | "failed";
  account: { display_name: string } | null;
  is_jira_admin: boolean | null;
  products: ProductStatus[];
}

export interface Resource {
  type: string;
  id?: string | null;
  key?: string | null;
  title?: string | null;
  url?: string | null;
}

export interface Operation {
  op_id: string;
  position: number;
  operation: string;
  agent: string;
  description: string;
  risk: "read" | "create" | "modify" | "destructive" | "security";
  supported: boolean;
  requires_approval: boolean;
  approved: boolean;
  status: "pending" | "requires_approval" | "in_progress" | "completed" | "failed" | "skipped";
  message: string | null;
  params: Record<string, unknown>;
  resolved_params: Record<string, unknown> | null;
  depends_on: string[];
  preflight: { message: string; conflict: boolean } | null;
  outcome: { message: string; resource: Resource | null; outputs: Record<string, unknown>; reused_existing: boolean; error_code: string | null } | null;
  verification: { verified: boolean; message: string; checks: { name: string; passed: boolean; expected: unknown; actual: unknown }[] } | null;
}

export type RunStatus =
  | "planning" | "needs_clarification" | "blocked" | "awaiting_approval" | "executing"
  | "completed" | "completed_with_errors" | "failed" | "rejected";

export interface RunSummary {
  id: string;
  connection_id: string;
  created_by: string;
  input_mode: "text" | "voice";
  input_text: string;
  status: RunStatus;
  current_agent: string | null;
  progress_message: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface RequirementStatus {
  requirement: string;
  status: "done" | "partial" | "failed" | "manual" | "missing";
  operation_ids: string[];
  note: string;
}

export interface Report {
  requirements?: RequirementStatus[];
  completion_percent?: number | null;
  summary: string;
  created_resources: Resource[];
  completed: number;
  failed: number;
  skipped: number;
  issues: string[];
  next_steps: string[];
}

export interface RunDetail extends RunSummary {
  conversation: { role: "user" | "assistant"; content: string }[];
  intent: { language: string; normalized_instruction: string; goals: string[]; clarification_questions: string[] } | null;
  plan: { summary: string; assumptions: string[]; warnings: string[] } | null;
  plan_issues: { severity: "error" | "warning"; operation_id: string | null; message: string }[];
  report: Report | null;
  error: string | null;
  approved_by: string | null;
  operations: Operation[];
}

export interface CatalogEntry {
  name: string;
  agent: "jira" | "jsm" | "confluence" | "integration";
  risk: string;
  description: string;
  supported: boolean;
  needs_jira_admin: boolean;
  limitation: string | null;
  alternative: string | null;
}

export interface Overview {
  site_url: string;
  jira_projects?: { key: string; name: string; project_type_key: string | null }[];
  service_desks?: { id: string; project_key: string; project_name: string }[];
  spaces?: { key: string; name: string; type: string | null }[];
  errors: Record<string, string>;
}

export const ACTIVE: RunStatus[] = ["planning", "executing"];
