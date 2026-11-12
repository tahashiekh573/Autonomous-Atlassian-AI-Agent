# Jira Service Management playbook (owned by the JSM Agent)

- Service projects: `jsm.create_service_project` with `template: itsm` for IT service
  management. The ITSM template ships incident, service request, problem and change management
  (issue types, workflows, queues and the default SLAs "Time to first response" and
  "Time to resolution"). Say this in `assumptions` instead of planning unsupported steps for
  things the template already provides.
- Request types: `jsm.create_request_type` with the service project key as `service_desk` and an
  issue type that exists in that project (ITSM: "Incident", "Service request",
  "Service request with approvals", "Problem", "Change").
- Organizations: `jsm.create_organization` (optionally adding it to the service desk), then
  `jsm.add_customers` (security-sensitive: grants portal access).
- **Queues ARE automatable:** one `jsm.create_queue` per requested queue (`jql` without the
  project clause, e.g. `assignee is EMPTY AND resolution = Unresolved`, `priority in (Highest,
  High) AND resolution = Unresolved`, `"Time to resolution" = breached()`, `status = "Waiting for
  customer"`, `resolution is not EMPTY`). Use the status names of the project's workflow.
- **SLA goals ARE automatable:** one `jsm.configure_sla` per metric ("Time to first response",
  "Time to resolution"), one goal per priority (`priority = Highest` → `15m`, ...), `calendar`
  "business hours" for working-hours SLAs (else "24/7"), `pause_statuses` (waiting for customer
  / approval) and `stop_statuses` (Resolved, Closed, Done, Canceled...). Plan it after the
  workflows exist. Only *creating or editing a calendar's hours* is UI-only
  (`jsm.configure_sla_calendar`): the ITSM template's "Sample 9-5 Calendar" is used; if the user
  asked other hours (e.g. 9-18) add that one manual adjustment to `warnings`.
- **Approval steps ARE automatable** with `jira.update_workflow` `approvals` (company-managed).
- Not available via API (plan the catalog entry so the limitation is reported): request form
  field layout and visibility, portal/help center branding, knowledge base space linking,
  email channel, SLA calendar hours.
- SLA and request reporting: `jsm.sla_report` / `jsm.request_report` (read-only); for
  "incident" reports pass `jql_filter: "issuetype = Incident"`. A Jira dashboard for incidents
  uses `jira.create_filter` with JQL like `project = KEY AND issuetype = Incident` plus
  `jira.create_dashboard`.
- Automation for service projects (assignment, escalation, notifications) uses
  `jira.create_automation_rule` on the service project key.

- Request types: create each one with `jsm.create_request_type`; then build the portal form
  for them with `jsm.create_form` (questions with types short_text, long_text, rich_text, email,
  number, date, dropdown/single_choice/multi_choice with `choices`, attachment; mark mandatory
  ones `required`). One form can serve several request types via `request_types` (names). Plan
  forms after the request types they reference. `jsm.configure_request_form` (built-in field
  layout) stays unsupported — prefer `jsm.create_form`.
- Assets (CMDB): only when capabilities show `assets` available. Use one
  `assets.create_schema` with all object types (parents before children, e.g. Hardware →
  Laptop, Server) and their attributes, then `assets.create_objects` per object type with
  sample or provided records (every object needs "Name"). Schema keys are 2–10 uppercase
  letters/digits. If `assets` is unavailable, say so in `warnings` instead of planning Assets
  steps.
- Sample tickets: one `jsm.create_request` per requested ticket (10 asked → 10 steps), each
  with its request type and a realistic summary/description; to show different workflow
  statuses add `jira.transition_issue` steps on some of them (`${sN.key}`).
- Dashboards for service desks: gadget types include `service_project_report`,
  `filter_counts`, `time_to_first_response`, `created_vs_resolved`, `pie_chart`,
  `two_dimensional`, `filter_results`, `resolution_time`, `workload_pie`.
