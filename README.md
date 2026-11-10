# Autonomous Atlassian AI Agent

An AI administrator for Jira Software, Jira Service Management and Confluence Cloud. You type
or speak an instruction in English, Urdu or Roman Urdu. The agent plans the work, shows you the
plan, waits for your approval, carries it out through Atlassian's REST APIs, re-reads your site
to verify every change, and reports only what it verified.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design, agents, API map, security model and
known Atlassian API limitations.

## Quick start (development)

Requires Python 3.11+ and Node 20+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill in `.env`. At minimum you need these two:

| Variable | How to get it |
|---|---|
| `CREDENTIAL_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GEMINI_API_KEY` | Google AI Studio → API keys |

Optional: set `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` to create a login. Without
`ADMIN_API_KEY`, development mode lets you in as a local admin.

```bash
npm run setup   # once: install dashboard dependencies
npm start       # API on :8765 + dashboard on http://localhost:5173 (Ctrl+C stops both)
```

API docs are at http://localhost:8765/docs. To run the two parts separately, use
`npm run api` and `npm run dev`; the dashboard proxies `/api` to `API_URL`
(default `http://127.0.0.1:8765` via `web/.env.local`).

Then, in the dashboard:

1. **Settings:** add your site (`https://<site>.atlassian.net`, account email, and an
   [API token](https://id.atlassian.com/manage-profile/security/api-tokens)). It is tested
   right away. Use an account with Jira administrator rights for admin work.
2. **Command center:** type or record a command, for example *"Jira mein ek Scrum project
   banao, usmein Epic, Story, Bug aur Task issue types configure karo aur Scrum board create
   karo."*
3. Review the plan, its preflight findings and warnings. Approve the steps you want to run;
   destructive and permission steps must be selected one by one by an admin. Then watch each
   agent work and read the verified report.

## Production (Docker)

```bash
cp .env.example .env   # set ADMIN_API_KEY, CREDENTIAL_ENCRYPTION_KEY,
                       # JWT_SECRET, GEMINI_API_KEY, POSTGRES_PASSWORD, BOOTSTRAP_ADMIN_*
docker compose up --build    # dashboard on http://localhost:8080
```

The API container runs `alembic upgrade head` before starting. nginx serves the dashboard and
proxies `/api`.

## API overview

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/login`, GET `/auth/me` | – | Sign in / current user |
| GET/POST/PATCH | `/api/v1/users` | admin | User management |
| POST/GET/DELETE | `/api/v1/connections[/{id}]` | admin / viewer | Atlassian sites |
| POST | `/api/v1/connections/{id}/test` | admin | Probe products and permissions |
| GET | `/api/v1/connections/{id}/overview` | viewer | Projects, service desks, spaces |
| POST | `/api/v1/runs` (`Idempotency-Key` header) | operator | Submit a text command |
| POST | `/api/v1/voice/command` (multipart `audio`, `connection_id`) | operator | Submit a voice command |
| GET | `/api/v1/runs`, `/runs/{id}` | viewer | History, live status, plan, report |
| POST | `/api/v1/runs/{id}/approve` · `/reject` · `/clarify` | operator (admin for elevated steps) | Approval loop |
| GET | `/api/v1/operations` | viewer | Operation catalog with API limitations |
| POST | `/api/v1/voice/transcribe` · `/voice/speak` | operator / viewer | Speech in / out |
| GET | `/api/v1/audit-logs` | admin | Audit trail |

## Quality checks

```bash
pytest                               # unit tests (fake Atlassian/LLM); integration tests skip
ruff check app tests migrations && ruff format --check app tests migrations
mypy                                 # strict
cd web && npm run build              # type-check + build the dashboard
```

Integration tests run against a dedicated **test** site, never production:

```bash
export ATLASSIAN_TEST_SITE_URL=https://your-test-site.atlassian.net
export ATLASSIAN_TEST_EMAIL=you@company.com ATLASSIAN_TEST_API_TOKEN=...
pytest -m integration                                   # read-only probes
export ATLASSIAN_TEST_ALLOW_WRITES=1 ATLASSIAN_TEST_PROJECT_KEY=TEST ATLASSIAN_TEST_SPACE_KEY=TEST
pytest -m integration                                   # + create → verify → delete cycles
```

## Project layout

```
app/
  main.py            app factory and wiring
  core/              config, logging, exceptions, security, prompts loader, DI
  middlewares/       request IDs, error handlers
  routers/           HTTP endpoints only
  schemas/           Pydantic contracts; operations/ = the operation catalog
  services/          runs, run engine, approvals, auth, connections, voice, audit
  orchestrators/     LangGraph planning + execution graphs, plan validation, approval policy
  agents/            8 agents; handlers/ (tool layer), verifiers/ (live re-checks)
  prompts/           agent system prompts (Markdown)
  clients/           atlassian (HTTP core), jira, jsm, confluence, llm, speech
  repositories/      database access
  models/, db/       SQLAlchemy models, engine/session
migrations/          Alembic
tests/unit, tests/integration
web/                 React + Vite dashboard
```
