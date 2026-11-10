# Architecture — Autonomous Atlassian AI Agent

An execution-based AI administrator for Jira Software, Jira Service Management (JSM) and
Confluence Cloud. Voice or text instructions (English, Urdu, Roman Urdu) become a validated,
approved execution plan. The agents carry it out through Atlassian REST APIs, re-read the live
instance to verify every change, and report only what verification confirmed.

## 1. Layering and request flow

```
main.py → middlewares → routers → services → orchestrators → agents → clients
                                     │
                                     └──→ repositories → db
```

| Layer | Responsibility | Lives in |
|---|---|---|
| `main.py` | App factory, lifespan (DB, LLM, speech, engine), middleware + router wiring | `app/main.py` |
| middlewares | Request IDs + access log, global JSON error envelope, CORS | `app/middlewares/` |
| routers | HTTP in/out and role checks only | `app/routers/` |
| services | Business rules: runs, approvals, auth, connections, voice, audit | `app/services/` |
| orchestrators | LangGraph planning and execution graphs, plan validation, approval policy | `app/orchestrators/` |
| agents | One task each, `run(input) -> output` with Pydantic I/O | `app/agents/` |
| clients | The only code that talks to Atlassian, Gemini/OpenAI or speech providers | `app/clients/` |
| repositories | Database access | `app/repositories/` |
| prompts | Markdown system prompts, loaded at runtime | `app/prompts/` |

Deliberate exceptions: two pieces call clients directly from services, because neither is an AI
task. They are connection probing (`services/atlassian_probe.py`) and the read-only workspace
overview (`services/workspace_service.py`). Every AI-driven change goes orchestrator → agent →
client.

## 2. Agents

Agents never call each other. Orchestrators pass typed data between them.

| Agent | Input → Output | How |
|---|---|---|
| InputUnderstandingAgent | `UnderstandingInput` → `Intent` | LLM; detects en/ur/roman_ur/mixed, normalises to English, finds missing info, writes clarification questions |
| PlanningAgent | `PlanningInput` → `ExecutionPlan` | LLM, given the operation catalog, site capabilities and discovered resources; uses `planning_system.md` + product playbooks (`jira_/jsm_/integration_agent_system.md`) |
| JiraAgent / JsmAgent / ConfluenceAgent / IntegrationAgent | `OperationRequest` → `OperationOutcome` | Deterministic handlers per catalog operation; `mode="check"` runs read-only preflight. The Confluence agent writes page content with the LLM (`confluence_agent_system.md`) and validates the XHTML |
| VerificationAgent | `VerificationRequest` → `VerificationResult` | Re-reads the resource from the live instance and compares expected vs actual fields; one retry for eventual consistency |
| ResponseAgent | `ReportInput` → `ExecutionReport` | Counts and resource IDs come from the data; the LLM writes only the narrative, in the user's language |

### Operation catalog (`app/schemas/operations/`)

There is a single registry of 63 operations. Each has an owning agent, a risk class, a Pydantic
params model, the products it requires, and whether it needs Jira admin rights. The 10
operations Atlassian exposes no public API for are kept in the catalog with
`supported=False`, a limitation and a manual alternative. The planner can therefore include
them, and the user sees exactly what must be done by hand. Tests enforce that every supported
operation has a handler and every state-changing one has a verifier.

## 3. Execution workflow

```
POST /runs ─▶ planning graph:  understand ─┬─▶ (needs clarification) → wait for /clarify
                                           └─▶ discover → plan → preflight
          ─▶ status awaiting_approval (or blocked / auto-executing)
POST /approve ─▶ execution graph:  select → execute → verify ─┐
                                      ▲────────────────────────┘ … → respond
```

* **Preflight (step 4)** validates the plan statically: catalog names, params, `${sN.output}`
  references, dependency DAG, product availability and Jira-admin requirements. It then runs
  read-only checks per step: key conflicts, Jira's own workflow validation, and what a delete
  would remove. Any error blocks approval.
* **Approval (steps 5–6):** risk classes `read | create | modify | destructive | security`.
  `AUTO_APPROVE_RISKS` (default `["read"]`) lists the classes that run without approval.
  `destructive` and `security` steps always need explicit, per-step approval by an **admin**.
  Unapproved steps, and anything depending on them, are skipped.
* **Execution (steps 7–9):** steps run one at a time in order. `${s3.key}` references resolve
  from verified outputs only. A step counts as `completed` **only after the Verification
  Agent confirms it**; otherwise it is `failed`. Dependents of failed or skipped steps are
  skipped with a reason.
* **Statuses:** Pending, Requires Approval, In Progress, Completed, Failed, Skipped. Each change
  is persisted live, including the current agent and a progress message, for the dashboard.
* **Idempotency:** every create first looks for its natural key (project key, space key, page
  title, filter/board/dashboard name). Created issues carry a label
  `aiagent-<run>-<step>`, so a retried step finds what it already made. `POST /runs` also
  accepts an `Idempotency-Key` header.
* **Restart safety:** runs left `planning` or `executing` by a crash are marked failed on
  startup, never silently resumed.

## 4. Atlassian API map

Auth: Atlassian account email + API token (HTTP Basic), stored encrypted.

| Area | Endpoints used | Notes |
|---|---|---|
| Projects (software, business, service) | `POST/GET/PUT /rest/api/3/project` | Company-managed templates by default |
| Issue types + schemes | `/rest/api/3/issuetype`, `/issuetypescheme`, `/issuetypescheme/project`, `/mapping` | Team-managed projects reported as unsupported |
| Fields, screens, field configs | `/rest/api/3/field`, `/field/{id}/context/.../option`, `/screens`, `/fieldconfiguration` | |
| Priorities, statuses | `/rest/api/3/priority`, `/statuses` | |
| Workflows | `/rest/api/3/workflows/create/validation`, `/workflows/create`, `/workflowscheme`, `/workflowscheme/project` | Validated before creation; scheme assignment only while the project has no issues |
| Issues, links, transitions, search | `/rest/api/3/issue`, `/issueLink`, `/transitions`, `/search/jql`, `/search/approximate-count` | ADF descriptions |
| Boards, sprints, filters | `/rest/agile/1.0/board`, `/sprint`, `/rest/api/3/filter` | Board columns, swimlanes and quick filters are UI-only |
| Dashboards | `/rest/api/3/dashboard`, `/dashboard/{id}/gadget` | Gadget data sources must be set in the UI |
| Automation | `/gateway/api/automation/public/jira/{cloudId}/rest/v1/rule` | If unavailable, the step fails and the rule JSON is returned for manual import |
| JSM | `/rest/servicedeskapi/servicedesk`, `/requesttype`, `/queue`, `/organization`, `/customer`, `/request`, `/participant` | SLA configuration, queue creation, request form layout, approvals, portal and KB linking are UI-only |
| Confluence | v2 `/wiki/api/v2/spaces`, `/pages`, `/labels`, `/permissions`; v1 `/wiki/rest/api/space`, `/content/{id}/label`, `/space/{key}/permission` | |
| Cross-product | `/rest/api/3/issue/{key}/remotelink`, Jira issues macro in Confluence storage format | |

Reliability (`clients/atlassian/http_client.py`):
* 429s are always retried, honouring `Retry-After`. 5xx responses and network errors are retried
  only for idempotent requests, with exponential backoff and jitter.
* Errors become typed exceptions with parsed messages.
* Offset and cursor pagination are both supported.
* Path segments are URL-encoded.
* Request logs never include credentials, and a redaction filter on all logs backs this up.

## 5. Security

* **Users and roles:** `viewer` (read), `operator` (run commands, approve create/modify steps),
  `admin` (connections, users, audit, destructive and security-sensitive approvals).
  Passwords are hashed with scrypt; sessions use HS256 JWTs. `ADMIN_API_KEY` acts as an admin
  service account. Logins are throttled to 10 failures per 15 minutes per email.
* Production refuses to start without `ADMIN_API_KEY`, `CREDENTIAL_ENCRYPTION_KEY` and
  `JWT_SECRET`. Outside production, if no API key is set, requests act as a local dev admin.
* Atlassian tokens are Fernet-encrypted at rest and never returned. `site_url` must be `https`
  on an allow-listed host suffix (`.atlassian.net`), which prevents sending credentials to
  arbitrary hosts.
* The audit log records logins, connection changes, run creation, approvals, rejections and
  every completed or failed operation (with the resource and verification result), all with
  request IDs.
* Validation errors never echo submitted input. LLM output never executes directly: it must
  map to catalog operations with validated params.

## 6. Data model

`atlassian_connections`, `users`, `execution_runs` (conversation, intent, plan, plan issues,
report, live agent/progress), `execution_operations` (risk, approval, params, resolved params,
preflight, outcome, verification), `audit_logs`. Migrations live in `migrations/` (Alembic);
`DB_AUTO_CREATE=true` is a dev/test convenience.

## 7. Delivery status

| Phase | Scope | Status |
|---|---|---|
| 1–2 | Foundation, config, DB, logging, errors, audit; Atlassian auth + capability probe | ✅ |
| 3 | Jira client + Jira Agent (projects, config, workflows, issues, agile, dashboards, reports, automation) | ✅ |
| 4 | JSM client + JSM Agent (service projects, request types, orgs, customers, requests, SLA/request reports) | ✅ |
| 5 | Confluence client + Confluence Agent (spaces, LLM-written pages, hierarchy, labels, permissions) | ✅ |
| 6 | LLM abstraction (Gemini, OpenAI-compatible), Input Understanding + Planning agents, prompts | ✅ |
| 7 | LangGraph planning/execution orchestrators, preflight, approval policy, run engine | ✅ |
| 8 | Integration Agent (issue↔page, incident↔bug, issue macros, project↔space) | ✅ |
| 9 | Verification Agent, execution history, operation-level audit | ✅ |
| 10 | Voice: Gemini/OpenAI STT, optional OpenAI TTS (browser speech fallback) | ✅ |
| 11 | React dashboard: command center, voice, plan preview, approvals, live status, reports, product sections, history, connections | ✅ |
| 12 | Users/roles/JWT, login throttling, Alembic, Docker + Compose (PostgreSQL), live integration tests | ✅ |

Not yet verified against a live site: the endpoints and payloads above are built from
Atlassian's documentation and covered by fake-transport tests. Run `pytest -m integration`
against a test site before relying on them in production, especially for Automation rules,
the workflow bulk API and JSM customer management (an experimental API).
