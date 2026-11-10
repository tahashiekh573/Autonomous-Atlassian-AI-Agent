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
- Not available via API (plan the catalog entry so the limitation is reported):
  SLA metric/goal/calendar configuration, queue creation, request form field layout and
  visibility, approval steps, portal/help center configuration, knowledge base space linking.
- SLA and request reporting: `jsm.sla_report` / `jsm.request_report` (read-only); for
  "incident" reports pass `jql_filter: "issuetype = Incident"`. A Jira dashboard for incidents
  uses `jira.create_filter` with JQL like `project = KEY AND issuetype = Incident` plus
  `jira.create_dashboard`.
- Automation for service projects (assignment, escalation, notifications) uses
  `jira.create_automation_rule` on the service project key.
