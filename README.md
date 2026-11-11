# Autonomous Atlassian AI Agent

An AI administrator for **Jira Software**, **Jira Service Management (JSM)** and **Confluence
Cloud**. You type or speak an instruction in **English, Urdu or Roman Urdu**. The agent:

1. works out what you want,
2. builds a step-by-step plan from a fixed catalog of Atlassian operations,
3. checks the plan against your live site,
4. waits for your approval,
5. carries it out through Atlassian's official REST APIs,
6. re-reads your site to verify every change, and
7. reports only what verification confirmed.

It is not a chatbot that writes instructions for you. It makes real changes in your Atlassian
site, and only after you approve them.

> Design, agent contracts, API map and security model: see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Contents

- [What it can do](#what-it-can-do)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration (`.env`)](#configuration-env)
- [Running the app](#running-the-app)
- [First run: connect your Atlassian site](#first-run-connect-your-atlassian-site)
- [Using the dashboard](#using-the-dashboard)
- [Example commands](#example-commands)
- [Approvals, risk and roles](#approvals-risk-and-roles)
- [Supported operations](#supported-operations)
- [What Atlassian's API cannot do](#what-atlassians-api-cannot-do)
- [Voice input and output](#voice-input-and-output)
- [REST API](#rest-api)
- [Production deployment (Docker)](#production-deployment-docker)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Security notes](#security-notes)
- [Roman Urdu mein khulasa](#roman-urdu-mein-khulasa)

---

## What it can do

| Area | Examples |
|---|---|
| **Jira Software** | Create Scrum/Kanban projects, issue types and schemes, custom fields, screens, field configurations, priorities, statuses, workflows (validated by Jira before creation), boards, sprints, epics/stories/tasks/bugs/sub-tasks, dependencies ("blocks"), start/due dates, filters, dashboards, reports, automation rules |
| **Jira Service Management** | Create service projects (ITSM, general, customer service, HR, facilities), request types, organizations, customers, requests/incidents, participants, SLA and request reports |
| **Confluence** | Create spaces, KB articles, IT/HR policies, SOPs, troubleshooting guides, technical and project documentation, requirement pages and index pages. Page content is written by the AI from a short brief. Also page hierarchies, labels, space permissions |
| **Cross-product** | Link issues to Confluence pages, turn JSM incidents into development bugs and link them, embed live Jira issue lists in pages, connect a project to its documentation space |
| **Reporting** | Project summary, workload, created-vs-resolved, sprint progress, SLA breached/met counts, request volume |

The catalog has **64 operations**. 10 of them are features Atlassian exposes **no public API**
for (for example SLA configuration and queue creation). The agent never fakes these: it reports
them as skipped and gives you the exact manual steps. See
[What Atlassian's API cannot do](#what-atlassians-api-cannot-do).

---

## How it works

```
 You (text / voice: English, Urdu, Roman Urdu)
   │
   ▼
 Input Understanding Agent ── detects language, restates the request in English,
   │                          asks clarification questions when something is missing
   ▼
 Planning Agent ───────────── builds a plan only from catalog operations, using your site's
   │                          capabilities and existing projects/spaces
   ▼
 Preflight ────────────────── validates params, references and dependencies; checks product
   │                          availability, admin rights and key conflicts; dry-runs workflows
   ▼
 Plan preview + approval ──── you choose which steps run
   │
   ▼
 Jira / JSM / Confluence / Integration Agents ── execute one step at a time via REST APIs
   │
   ▼
 Verification Agent ───────── re-reads each resource from your live site
   │                          (a step is "Completed" only if this passes)
   ▼
 Response Agent ───────────── final report in your language: created resources with
                              links, failures, manual next steps
```

All agents are coordinated by **LangGraph** orchestrators; agents never call each other.

| Step status | Meaning |
|---|---|
| Pending | Waiting for earlier steps |
| Requires approval | Waiting for you |
| In progress | An agent is executing it right now (shown live in the dashboard) |
| Completed | Executed **and** verified on your site |
| Failed | Atlassian rejected it, or verification found a mismatch (the reason is shown) |
| Skipped | Not approved, depends on a failed step, or has no public API (manual steps shown) |

Safety properties:
- **Nothing runs before approval**, except read-only steps such as reports.
- **Retries never create duplicates.** Every create first looks up the resource by its natural
  key (project key, space key, page title, board/filter/dashboard/rule name). Created issues
  carry an `aiagent-<run>-<step>` label so a retried step finds what it already made. Issues
  have no natural key, so submitting the same command as a **new** run creates them again.
- **A server restart never resumes a run half-way.** Runs that were planning or executing are
  marked failed with "Interrupted by a server restart".

---

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | `python --version` |
| Node.js | 20+ | `node --version` (ships with npm) |
| Atlassian Cloud site | — | `https://<your-site>.atlassian.net`, with an account that has **Jira administrator** rights for admin tasks |
| Atlassian API token | — | Create one at <https://id.atlassian.com/manage-profile/security/api-tokens> |
| Google Gemini API key | — | Create one at <https://aistudio.google.com/apikey> (an OpenAI-compatible key also works) |

---

## Installation

### Windows (PowerShell)

```powershell
cd "F:\Autonomous Atlassian AI Agent"

# 1. Python environment
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned   # allows activating the venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 2. Dashboard dependencies
npm run setup

# 3. Configuration
Copy-Item .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#    paste the printed key into .env as CREDENTIAL_ENCRYPTION_KEY=...
#    and put your Gemini key into .env as GEMINI_API_KEY=...
```

### macOS / Linux

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
npm run setup
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# edit .env: CREDENTIAL_ENCRYPTION_KEY=..., GEMINI_API_KEY=...
```

> **Edit `.env`, not `.env.example`.** The app only reads `.env`, and `.env` is gitignored.
> `.env.example` is the template that gets committed, so a key written there ends up public.

---

## Configuration (`.env`)

Only the first two variables are required for local use. Everything else has a sensible default.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `CREDENTIAL_ENCRYPTION_KEY` | **yes** | — | Fernet key that encrypts stored Atlassian API tokens. Generate it with the command above. Changing it later makes saved connections unreadable, so you would need to re-add them. |
| `GEMINI_API_KEY` | **yes** | — | LLM used by the agents (and for speech-to-text). |
| `GEMINI_MODEL` | | `gemini-3-flash-preview` | Must be a model your key can use (see [Troubleshooting](#troubleshooting)). |
| `LLM_PROVIDER` | | `gemini` | `gemini` or `openai` (any OpenAI-compatible endpoint). |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | | — / `gpt-4.1-mini` / OpenAI | Used when `LLM_PROVIDER=openai`, or for OpenAI speech. |
| `ENVIRONMENT` | | `development` | `production` refuses to start without `ADMIN_API_KEY`, `CREDENTIAL_ENCRYPTION_KEY` and `JWT_SECRET`. |
| `ADMIN_API_KEY` | prod | — | Service-account key (`Authorization: Bearer <key>`, admin role). **If empty outside production, every request acts as a local admin**, which is convenient for development only. |
| `JWT_SECRET` | prod | random per start | Signs dashboard login tokens. |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | | — | Creates the first admin user on startup when there are no users. Password must be at least 12 characters. |
| `DATABASE_URL` | | `sqlite+aiosqlite:///./data/app.db` | PostgreSQL: `postgresql+asyncpg://user:pass@host:5432/db` (install with `pip install -e ".[postgres]"`). |
| `DB_AUTO_CREATE` | | `true` | Creates tables on startup. In production set it to `false` and use `alembic upgrade head`. |
| `AUTO_APPROVE_RISKS` | | `["read"]` | Risk classes that run without approval (`read`, `create`, `modify`). Destructive and security steps **always** need approval. |
| `MAX_PLAN_OPERATIONS` | | `40` | Upper bound on steps per plan. |
| `STT_PROVIDER` | | `gemini` | Speech-to-text: `gemini`, `openai` or `none`. |
| `TTS_PROVIDER` | | `none` | Text-to-speech: `openai` or `none` (the dashboard then uses the browser's own voice). |
| `ATLASSIAN_ALLOWED_HOST_SUFFIXES` | | `[".atlassian.net"]` | Credentials are only ever sent to these hosts. |
| `ATLASSIAN_TIMEOUT_SECONDS` / `ATLASSIAN_MAX_RETRIES` | | `30` / `4` | HTTP behaviour towards Atlassian. |
| `LOG_LEVEL` / `LOG_JSON` | | `INFO` / `false` | Logging. Secrets are redacted from logs. |
| `CORS_ORIGINS` | | `["http://localhost:5173", …]` | Only needed when the dashboard is served from another origin. |

---

## Running the app

From the project folder:

```powershell
npm start
```

This starts both parts and prefixes their logs with `[api]` and `[web]`:

| Part | Address |
|---|---|
| Dashboard | <http://localhost:5173> |
| API | <http://127.0.0.1:8765> |
| Interactive API docs | <http://127.0.0.1:8765/docs> |

Wait for `Application startup complete` and `Local: http://localhost:5173`, then open the
dashboard. **Ctrl+C** stops both.

To run them separately (two terminals):

```powershell
npm run api    # API with auto-reload on port 8765
npm run dev    # dashboard on port 5173
```

The dashboard forwards `/api` to the backend set by `API_URL` in `web/.env.local` (default
`http://127.0.0.1:8765`). Port 8765 is used instead of 8000 because 8000 is often taken by other
local projects.

---

## First run: connect your Atlassian site

1. Create an API token at <https://id.atlassian.com/manage-profile/security/api-tokens>
   (**Create API token** → give it a name → copy it; it is shown only once).
2. Open the dashboard → **Settings** → **Connect a site**:
   - **Name:** any label, e.g. `Test`
   - **Site URL:** `https://your-site.atlassian.net`
   - **Account email:** the email you log in to Atlassian with
   - **API token:** the token from step 1
3. Click **Save and test**. You should see:
   - `ok`, plus badges for the products available on the site (`jira`, `jsm`, `confluence`);
   - **Jira admin**, which is needed for projects, workflows, schemes and automation.

> Try it on a **test site** first. A free site can be created at
> <https://www.atlassian.com/try>.

The API token is encrypted before it is stored and is never shown again or returned by the
API. Only **Settings** asks for the Atlassian token; the dashboard's own login form (used only
when you configure users) is a different account.

---

## Using the dashboard

| Page | What you do there |
|---|---|
| **Command center** | Type a command or press the 🎙 microphone. Review the plan, preflight findings, warnings and assumptions. Tick the steps to approve, then click **Approve and execute** (or **Reject plan**). Watch which agent is working, step by step. Read the verified report; **Read aloud** speaks the summary. If the agent asks a question, answer in the same box; you can also reply with changes to the plan before approving. |
| **Jira / Service Management / Confluence / Integrations** | Existing projects, service desks and spaces on your site; one-click example commands; the full list of operations with their risk and API support. |
| **History** | Every run with its status, input mode (text/voice) and author. Click one to reopen its plan and report. |
| **Settings** | Add, test and select Atlassian connections. |

The sidebar footer shows the connected site, API health and the current user.

---

## Example commands

You can mix languages freely; technical words can stay in English.

**English**
- *Create a Scrum project "Mobile App" with key MOB, with Epic, Story, Bug, Task and Sub-task issue types.*
- *Create 2 epics in AIDEMO. Under each epic create 1 story, 1 task and 1 bug, with due dates at the end of next month.*
- *Make the "Payments API" story block the "Checkout UI" story in MOB.*
- *Create a Bank IT Service Desk (key BITSD) using the ITSM template with request types for password reset and VPN access.*
- *Create a Confluence space "IT Knowledge Base" (key ITKB) with an index page, an acceptable-use policy and a password reset guide.*
- *Create an automation in MOB: when a High or Highest priority bug is created, assign it to me and comment "Triaged automatically".*
- *Show a workload report for MOB.*
- *Create a bug in MOB from incident BITSD-12 and link them.*

**Roman Urdu**
- *Jira mein ek Scrum project banao, usmein Epic, Story, Bug aur Task issue types configure karo aur Scrum board create karo.*
- *JSM ke tamam incidents ka Jira dashboard banao aur SLA reports add karo.*
- *Confluence mein IT policies ke liye ek space banao aur password reset ka guide likho.*

**Urdu**
- *جیرا میں ایک نیا اسکرم پروجیکٹ بناؤ اور اس میں ایک ایپک اور تین اسٹوریز شامل کرو۔*

Tips:
- **Give keys and names** when you care about them (`key MOB`). Otherwise the planner picks them
  and lists its choices under **Assumptions**.
- **"Me" / "mujhe"** means the connected Atlassian account (used for assignment and project lead).
- **"Backlog" is not a status.** New Scrum issues are already in the backlog. To pull issues out
  of a sprint, say *"move AIDEMO-4 and AIDEMO-5 back to the backlog"*.
- For large requests such as *"a complete ITSM environment"*, review the plan carefully: anything
  in the [no-API list](#what-atlassians-api-cannot-do) is shown with manual steps.

---

## Approvals, risk and roles

Every operation has a risk class:

| Risk | Examples | Approval |
|---|---|---|
| `read` | reports, searches, listings | runs automatically (configurable) |
| `create` | projects, issues, pages, boards, rules | approval required by default |
| `modify` | workflows, issue type schemes, transitions, updates | approval required by default |
| `destructive` | delete issue, delete page | **always** explicit, step-by-step approval by an **admin** |
| `security` | customer portal access, space permissions | **always** explicit, step-by-step approval by an **admin** |

Unapproved steps, and every step that depends on them, are skipped.

User roles (when users are configured):

| Role | Can |
|---|---|
| `viewer` | see runs, history, connections, catalog |
| `operator` | submit commands; approve `create`/`modify` steps; reply to clarifications |
| `admin` | everything, plus connections, users, audit log, and `destructive`/`security` approvals |

Create users with `BOOTSTRAP_ADMIN_*` (first admin) and then `POST /api/v1/users`. Logins are
throttled: 10 failures per email per 15 minutes returns HTTP 429.

---

## Supported operations

These tables list the operations the planner can use. Each one has a typed parameter schema
(see `GET /api/v1/operations`) and a verifier that re-checks the result on your site.

#### Jira Software

| Operation | Risk | What it does |
|---|---|---|
| `jira.list_projects` | read | List Jira projects. |
| `jira.create_project` | create | Create a company-managed Jira Software or business project. (Jira admin) |
| `jira.update_project` | modify | Update project name/description/lead. (Jira admin) |
| `jira.create_issue_type` | create | Create a global issue type. (Jira admin) |
| `jira.configure_issue_types` | modify | Give a company-managed project exactly these issue types (creates missing types, builds an issue type scheme and assigns it). (Jira admin) |
| `jira.create_custom_field` | create | Create a custom field (with options for select types). (Jira admin) |
| `jira.create_screen` | create | Create a screen with fields. (Jira admin) |
| `jira.add_field_to_screen` | modify | Add a field to a screen tab. (Jira admin) |
| `jira.create_field_configuration` | create | Create a field configuration with required/hidden fields. (Jira admin) |
| `jira.create_priority` | create | Create an issue priority. (Jira admin) |
| `jira.create_statuses` | create | Create global statuses. (Jira admin) |
| `jira.create_workflow` | create | Create a workflow with statuses and transitions (validated by Jira before creation). (Jira admin) |
| `jira.assign_workflow` | modify | Create a workflow scheme and assign it to a project that has no issues yet. (Jira admin) |
| `jira.create_issue` | create | Create an Epic, Story, Task, Bug or Sub-task (`parent_key` links it to the epic or parent; supports start/due dates for timelines). |
| `jira.update_issue` | modify | Update issue fields. |
| `jira.transition_issue` | modify | Move an issue to a workflow status. |
| `jira.link_issues` | create | Link issues, e.g. from_issue *blocks* to_issue (dependencies). |
| `jira.delete_issue` | destructive | Permanently delete an issue. |
| `jira.search_issues` | read | Run a JQL search. |
| `jira.create_filter` | create | Create a saved JQL filter. |
| `jira.create_board` | create | Create a Scrum or Kanban board (creates its filter when none is given). |
| `jira.create_sprint` | create | Create a sprint on a Scrum board. |
| `jira.start_sprint` | modify | Start a future sprint. |
| `jira.move_issues_to_sprint` | modify | Move issues into a sprint. |
| `jira.move_issues_to_backlog` | modify | Take issues out of their sprint and put them back in the backlog. |
| `jira.create_dashboard` | create | Create a dashboard and add gadgets. |
| `jira.generate_report` | read | Project summary, workload, issue-tracking or sprint report. |
| `jira.create_automation_rule` | create | Automation rule: trigger (issue created/updated/transitioned), JQL condition, actions (assign, transition, comment, set priority, email) with smart values. (Jira admin) |
| `jira.whoami` | read | Show the connected Atlassian account. |

#### Jira Service Management

| Operation | Risk | What it does |
|---|---|---|
| `jsm.list_service_desks` | read | List service projects. |
| `jsm.create_service_project` | create | Create a service project from a template. The ITSM template includes incident, service request, problem and change workflows, queues and default SLAs. (Jira admin) |
| `jsm.create_request_type` | create | Create a portal request type backed by an issue type. |
| `jsm.list_request_types` | read | List request types. |
| `jsm.list_queues` | read | List queues with issue counts. |
| `jsm.create_organization` | create | Create a customer organization (optionally add it to a service desk). |
| `jsm.add_customers` | security | Grant portal access to customers (creates customer accounts when needed). |
| `jsm.create_request` | create | Raise a customer request / incident. |
| `jsm.add_participants` | modify | Add request participants. |
| `jsm.sla_report` | read | Count breached / running / met SLAs per SLA metric. |
| `jsm.request_report` | read | Request/incident volume grouped by status, priority, assignee or type. |

#### Confluence

| Operation | Risk | What it does |
|---|---|---|
| `confluence.list_spaces` | read | List spaces. |
| `confluence.create_space` | create | Create a space. |
| `confluence.update_space` | modify | Update space name/description. |
| `confluence.create_page` | create | KB article, IT/HR policy, SOP, troubleshooting guide, technical/project documentation or requirements. The AI writes the content from a brief (headings, tables, panels); defaults to a child of the space home. |
| `confluence.update_page` | modify | Update a page (new version). |
| `confluence.add_labels` | modify | Add labels to a page. |
| `confluence.create_index_page` | create | Documentation index page listing its child pages. |
| `confluence.set_space_permission` | security | Grant a user/group a space permission. |
| `confluence.delete_page` | destructive | Move a page to the space trash. |

#### Cross-product integration

| Operation | Risk | What it does |
|---|---|---|
| `integration.link_issue_to_page` | create | Link a Jira/JSM issue to a Confluence page (remote link on the issue). |
| `integration.link_incident_to_issue` | create | Link a JSM incident with a development issue for traceability. |
| `integration.create_dev_issue_from_incident` | create | Create a development issue from a JSM incident and link them. |
| `integration.embed_issues_in_page` | modify | Append a live Jira issues (JQL) macro to a Confluence page. |
| `integration.link_project_to_space` | modify | Reference a Confluence space from a Jira project's description and add a project issues macro to the space home page. (Jira admin) |

---

## What Atlassian's API cannot do

The following features exist only in the Atlassian UI. When a request needs them, the plan
includes the step and it is reported as **Skipped** with the manual instructions below. It is
never reported as done.

| Operation | Why | Do this manually |
|---|---|---|
| `jira.configure_board_columns` | Board configuration is read-only in the public API. | Board settings → Columns. |
| `jira.configure_swimlanes` | No public API for swimlanes or quick filters. | Board settings → Swimlanes / Quick filters (saved filters from `jira.create_filter` can provide the JQL). |
| `jira.configure_dashboard_layout` | Layout and legacy gadget preferences are not settable. | Dashboard → Edit layout / gadget menu → Configure. |
| `jsm.configure_sla` | No public API for SLA configuration. | Project settings → SLAs. The ITSM template already ships "Time to first response" and "Time to resolution"; `jsm.sla_report` verifies they run. |
| `jsm.configure_sla_calendar` | No public API for SLA calendars. | Project settings → SLAs → Calendars. |
| `jsm.create_queue` | Queues are read-only in the public API. | Queues → Manage queues (`jsm.list_queues` verifies). |
| `jsm.configure_request_form` | Request form layout is not writable. | Project settings → Request types → Request form (or Forms). |
| `jsm.configure_approvals` | Approval configuration is not exposed. | Workflow editor → status → Add approval. |
| `jsm.configure_portal` | Help center / portal configuration has no API. | Project settings → Portal settings / Portal groups. |
| `jsm.link_knowledge_base` | Linking a KB space is UI-only. | Project settings → Knowledge base → Link space (the agent can create the space and articles first). |

Other partial limitations:
- **Dashboard gadgets** are added, but their data source (filter) must be picked in each gadget's
  Configure menu.
- **Workflow scheme assignment** only works while the project has no issues (a Jira rule).
  The planner orders it before issue creation.
- **Team-managed projects** do not support issue type schemes; the agent creates company-managed
  projects by default.

---

## Voice input and output

- Press the 🎙 button, speak, and press it again to stop. The recording is transcribed (Gemini by
  default; Urdu, Roman Urdu and English) and then goes through **exactly the same** planning and
  approval pipeline as typed text. The run is marked `voice` in History.
- **Read aloud** on the report uses OpenAI text-to-speech when `TTS_PROVIDER=openai`; otherwise
  it uses the browser's built-in speech synthesis.
- The browser asks for microphone permission the first time.

---

## REST API

Interactive docs: <http://127.0.0.1:8765/docs>. All endpoints are under `/api/v1`. Send
`Authorization: Bearer <token-or-ADMIN_API_KEY>`; this is not needed in local development
mode.

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/auth/login` · GET `/auth/me` | — | Sign in / current user |
| GET · POST · PATCH | `/users`, `/users/{id}` | admin | User management |
| GET · POST · DELETE | `/connections`, `/connections/{id}` | viewer / admin | Atlassian sites |
| POST | `/connections/{id}/test` | admin | Probe products and permissions |
| GET | `/connections/{id}/overview` | viewer | Projects, service desks, spaces |
| POST | `/runs` (optional `Idempotency-Key` header) | operator | Submit a text command |
| POST | `/voice/command` (multipart `audio`, `connection_id`) | operator | Submit a voice command |
| GET | `/runs`, `/runs/{id}` | viewer | History; live status, plan, operations, report |
| POST | `/runs/{id}/approve` `{ "operation_ids": ["s1","s2"] }` | operator (admin for elevated steps) | Approve steps and execute |
| POST | `/runs/{id}/reject` · `/runs/{id}/clarify` | operator | Reject, or answer / request plan changes |
| GET | `/operations` | viewer | Operation catalog with schemas and API limitations |
| POST | `/voice/transcribe` · `/voice/speak` · GET `/voice/capabilities` | operator / viewer | Speech in / out |
| GET | `/audit-logs` | admin | Audit trail |
| GET | `/health`, `/health/ready` (no prefix) | — | Liveness / readiness |

Example: a full command from the command line (PowerShell):

```powershell
$api = "http://127.0.0.1:8765/api/v1"
$conn = (Invoke-RestMethod "$api/connections")[0].id
$run = Invoke-RestMethod "$api/runs" -Method Post -ContentType "application/json" `
  -Body (@{ connection_id = $conn; text = "Create a Kanban project 'Ops' with key OPS" } | ConvertTo-Json)
# poll until status is awaiting_approval
Invoke-RestMethod "$api/runs/$($run.id)" | Select-Object status, current_agent, progress_message
# approve every non-elevated step
Invoke-RestMethod "$api/runs/$($run.id)/approve" -Method Post -ContentType "application/json" -Body '{}'
```

Run statuses: `planning`, `needs_clarification`, `blocked` (the plan has errors; reply to revise
it), `awaiting_approval`, `executing`, `completed`, `completed_with_errors`, `failed`,
`rejected`.

---

## Production deployment (Docker)

```bash
cp .env.example .env
# set: ADMIN_API_KEY, CREDENTIAL_ENCRYPTION_KEY, JWT_SECRET, GEMINI_API_KEY,
#      POSTGRES_PASSWORD, BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD
docker compose up --build
```

- Dashboard: <http://localhost:8080> (nginx serves the built React app and proxies `/api`).
- The stack runs PostgreSQL 16, the API (runs `alembic upgrade head`, then serves as a non-root
  user) and the dashboard.
- `ENVIRONMENT=production` is set by compose, so the API refuses to start without the required
  secrets.
- Put HTTPS (a reverse proxy or load balancer) in front of port 8080 before exposing it.

Database migrations outside Docker:

```bash
alembic upgrade head                                   # apply
alembic revision --autogenerate -m "describe change"   # after changing models
```

---

## Testing

```bash
pytest                                         # unit tests (fake Atlassian + fake LLM)
ruff check app tests migrations                # lint
ruff format --check app tests migrations       # formatting
mypy                                           # strict type checking
npm run build                                  # dashboard type-check + production build
```

The unit tests cover:
- full runs (plan → approval → execution → verification → report);
- approvals and roles;
- idempotency;
- clarification;
- voice;
- LLM output repair;
- rate-limit handling;
- plan validation;
- every handler/verifier pairing.

**Integration tests** talk to a real site. Use a dedicated **test** site, never production:

```powershell
$env:ATLASSIAN_TEST_SITE_URL = "https://your-test-site.atlassian.net"
$env:ATLASSIAN_TEST_EMAIL = "you@example.com"
$env:ATLASSIAN_TEST_API_TOKEN = "<token>"
pytest -m integration                      # read-only probes

$env:ATLASSIAN_TEST_ALLOW_WRITES = "1"
$env:ATLASSIAN_TEST_PROJECT_KEY = "TEST"   # an existing test project
$env:ATLASSIAN_TEST_SPACE_KEY = "TEST"     # an existing test space
pytest -m integration                      # + create → verify → delete cycles
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `npm error ENOENT ... package.json` | npm run outside the project folder | `cd "F:\Autonomous Atlassian AI Agent"` first. |
| Dashboard shows **Backend not reachable** | The API is not running | Run `npm start` (or `npm run api`) and click **Retry**. |
| A login page appears unexpectedly | The dashboard is talking to a different app (often something else on port 8000), or `ADMIN_API_KEY` is set | Use `npm start` (API on 8765). In development leave `ADMIN_API_KEY` empty, or create users with `BOOTSTRAP_ADMIN_*`. |
| Log says `No LLM configured` | `GEMINI_API_KEY` missing from `.env` (keys in `.env.example` are ignored) | Put the key in `.env` and restart. |
| Gemini **HTTP 404** "model … no longer available" | The model is retired or not enabled for your key | Set `GEMINI_MODEL` to a model your key supports, e.g. `gemini-3-flash-preview`. List them with `GET https://generativelanguage.googleapis.com/v1beta/models?key=…`. |
| Gemini **ReadTimeout** | The model name is not in your key's model list (the request hangs) | Same as above. |
| Gemini **HTTP 429** / report summary looks plain | Free-tier rate limit (a few requests per minute) | The agent waits and retries automatically (honouring Google's `retryDelay`). For heavy use, enable billing in Google AI Studio. Plain reports are still accurate: counts and links come from verified data. |
| Connection test `failed`, `atlassian_auth_failed` | Wrong email or API token | Use the Atlassian login email and a fresh token. |
| `jira`/`jsm`/`confluence` badge missing | That product is not enabled on the site | Plans that need it are blocked during preflight. |
| "Requires Jira administrator permission" | The connected account is not a Jira admin | Use an admin account for projects, workflows, schemes and automation. |
| Plan status **blocked** | Preflight found errors (invalid params, key conflict, missing product) | Read the red box and reply in the chat with a correction; the run is re-planned. |
| Transition to "Backlog" fails | Backlog is a board location, not a status | New issues are already in the backlog; use "move … back to the backlog" for issues in a sprint. |
| Automation step failed with rule JSON | Atlassian rejected the rule | The generated rule is in the step's details. Import it via Project settings → Automation → Import rules, or adjust the command. |
| Run failed with "Interrupted by a server restart" | The API restarted (for example after a code change with auto-reload) | Check what the run already created (its steps link to them), then submit again. Projects, spaces, pages, boards, filters, dashboards and rules with the same key/name are reused; **issues are created again**, so leave them out of the new command. |
| "Stored credential cannot be decrypted" | `CREDENTIAL_ENCRYPTION_KEY` changed | Restore the old key, or delete and re-add the connection. |

---

## Project structure

```
app/
  main.py              app factory: wires DB, LLM, speech, run engine, middleware, routers
  core/                config, logging (redaction), exceptions, security (encryption, JWT,
                       passwords), prompt loader, dependency injection
  middlewares/         request IDs + access log, global error envelope
  routers/             HTTP endpoints only (auth, connections, runs, voice, audit, health)
  schemas/             Pydantic contracts; operations/ = the 64-operation catalog
  services/            runs, background run engine, approvals, auth, connections,
                       workspace overview, voice, audit, login throttle
  orchestrators/       LangGraph planning + execution graphs, plan validation,
                       ${sN.output} references, approval policy
  agents/              8 agents (base_agent.py + one file each)
    handlers/          deterministic tool layer used by the execution agents
    verifiers/         live re-checks used by the Verification Agent
  prompts/             agent system prompts (Markdown, never in Python code)
  clients/             the only code that calls external APIs:
    atlassian/         shared HTTP client (auth, retries, rate limits, pagination, errors)
    jira/ jsm/ confluence/   product REST clients
    llm/               Gemini + OpenAI-compatible clients
    speech/            speech-to-text / text-to-speech providers
  repositories/        database access
  models/  db/         SQLAlchemy models, engine and sessions
migrations/            Alembic migrations
scripts/dev.mjs        `npm start`: runs API + dashboard together
tests/unit/            fast tests with fake Atlassian / LLM / speech
tests/integration/     opt-in tests against a real test site
web/                   React + TypeScript + Vite dashboard
Dockerfile, docker-compose.yml, web/Dockerfile, web/nginx.conf
```

Layering rule: `main.py → middlewares → routers → services → orchestrators → agents → clients`.
Repositories are used only by services. Details: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Security notes

- **Secrets:**
  - Atlassian tokens are Fernet-encrypted at rest, never returned by the API, and never logged.
    A redaction filter masks tokens and passwords in every log line.
  - Never put secrets in `.env.example` or in any committed file. If a key ever ends up in a
    chat, screenshot or commit, rotate it.
- **Credential safety:** API tokens are only sent to `https://*.atlassian.net`
  (`ATLASSIAN_ALLOWED_HOST_SUFFIXES`). The Atlassian HTTP client never follows pagination links
  to other hosts.
- **Audit:** logins, connection changes, run creation, approvals, rejections and every completed
  or failed operation are recorded in `audit_logs`, with request IDs.
- **AI output never executes directly:** it must map to a catalog operation with validated
  parameters, and destructive or security-sensitive steps need explicit approval by an admin.
- **Production:** set `ENVIRONMENT=production`, all required secrets, PostgreSQL and HTTPS.

---

## Roman Urdu mein khulasa

1. **Install:** `python -m venv .venv` → `.\.venv\Scripts\Activate.ps1` →
   `pip install -e ".[dev]"` → `npm run setup`.
2. **`.env` banayein** (`.env.example` ki copy). Usmein `CREDENTIAL_ENCRYPTION_KEY` (upar wali
   command se generate karein) aur `GEMINI_API_KEY` daalein. Keys **`.env`** mein hi daalein,
   `.env.example` mein nahi.
3. **Chalayein:** project folder mein `npm start`, phir browser mein <http://localhost:5173>.
4. **Settings** mein apni Atlassian site, email aur API token daal kar **Save and test** dabayein.
5. **Command center** mein Urdu, Roman Urdu ya English mein command likhein ya bolein. Plan
   dekhein, steps tick karke **Approve** karein, aur verified report padhein.
6. Masla ho to upar [Troubleshooting](#troubleshooting) ka table dekhein.
