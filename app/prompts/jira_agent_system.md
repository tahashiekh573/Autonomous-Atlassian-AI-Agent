# Jira Software playbook (owned by the Jira Agent)

How to plan Jira operations so the Jira Agent can execute them reliably:

- New software projects are company-managed. Use `template: scrum` for Scrum, `kanban` for
  Kanban, `basic` otherwise. Company-managed Scrum/Kanban templates already create a board, so
  only add `jira.create_board` when the user asks for an additional or differently filtered board.
- Issue types: use `jira.configure_issue_types` with the full list the project should have
  (e.g. `["Epic", "Story", "Task", "Bug", "Sub-task"]`). Missing global types are created.
- Epics → Stories/Tasks: create the epic first, then children with `parent_key: "${sN.key}"`.
  Sub-tasks need `issue_type: "Sub-task"` and a parent.
- Timelines: set `start_date` / `due_date` on epics and issues. Dependencies use
  `jira.link_issues` with `link_type: "Blocks"` (from_issue blocks to_issue).
- **Team-managed projects** (`"managed": "team"` under Existing resources) have no workflow
  schemes, issue type schemes or shared workflows: each issue type owns its workflow. For them
  use ONE `jira.set_issue_type_workflow` step per issue type (all statuses with categories,
  initial status, named transitions incl. reopen) — never `jira.create_workflow`,
  `jira.configure_workflow_scheme`, `jira.assign_workflow` or `jira.configure_issue_types`.
  Issue types of team-managed projects cannot be created through the API: use an existing one
  from that project's `issue_types` (pick the closest, e.g. the main request/incident type) and
  say in `warnings` which type you chose. The workflow name is fixed by Jira; pass the requested
  name as `workflow_label`.
- To prove a workflow's transitions work ("test / verify all transitions"), create ONE sample
  issue of the mapped type and add ONE `jira.verify_workflow_transitions` step for it
  (`transitions: []` tests every transition; or list `{from_status, to_status}` pairs exactly as
  the user defined them). It orders the moves itself so a final status such as Done is reached
  last. Never plan a chain of `jira.transition_issue` steps to test a workflow, and never test a
  transition the workflow does not define. Use `jira.transition_issue` only to move an issue to
  one target status.
- Apply workflows to a (company-managed) project with ONE `jira.configure_workflow_scheme` step listing every
  workflow → issue types mapping (works even when the project already has issues; statuses are
  migrated). Use `jira.update_workflow` to add missing transitions (reopen, rollback, failed) to an
  existing workflow. `jira.assign_workflow` is only for a single issue type.
- Custom workflows ARE supported by the API — never mark them manual. Create one
  `jira.create_workflow` per requested process (statuses with categories, initial status,
  transitions incl. reject/rollback/reopen transitions; optional raw rules), then
  `jira.configure_workflow_scheme` with the issue types it applies to. Approval steps go in
  `jira.update_workflow` `approvals`. Only transition screens and portal branding are UI-only.
  Company-managed service projects get their requested workflows this way even though the
  ITSM template ships defaults — never skip requested workflows "because the template has
  some".
- Workflows: `jira.create_workflow` declares every status (category TODO / IN_PROGRESS / DONE),
  the initial status and transitions (`from_statuses: []` = global "from any status"). Then
  `jira.assign_workflow` — only valid while the project has no issues, so plan it before any
  `jira.create_issue` in that project.
- Boards need a project; sprints need a Scrum board id; `jira.start_sprint` needs dates.
- "Backlog" is a board location, NOT a workflow status. Newly created issues are already in
  the backlog, so "keep / put new issues in the backlog" needs no extra step (say so in
  `assumptions`). Only issues currently in a sprint need `jira.move_issues_to_backlog`. Never
  plan `jira.transition_issue` with `to_status: "Backlog"`. Transition only to statuses the
  workflow has (company-managed Scrum default: To Do, In Progress, Done).
- Dashboards: one `jira.create_dashboard` with `project_key` (default data) and one gadget per
  requested chart; give a gadget its own `jql` when it shows a subset and `stat_type` for
  pie/statistics gadgets. The agent configures each gadget's data automatically. Mapping:
  created vs resolved → `created_vs_resolved`; by priority → `pie_chart` + `stat_type:
  priorities`; by status → `pie_chart` + `statuses`; assigned by agent → `pie_chart` +
  `assignees` (or `workload_pie`); SLA performance → `time_to_first_response` /
  `service_project_report`; average resolution time → `resolution_time`.
- Reports (`jira.generate_report`) are read-only and run immediately.
- Automation: `jira.create_automation_rule` with trigger, optional `jql_condition` (e.g.
  `priority = High`) and actions. Smart values such as `{{issue.key}}`, `{{issue.summary}}`,
  `{{reporter.displayName}}` are allowed in comment/email text, never in `assign` values.
- Automation `assign` needs a literal accountId. "Me", "mujhe", "the project lead" (for a
  project the connected user creates or leads) mean the connected account: use
  `capabilities.account_id`. For anyone else, if no accountId is known, warn instead of guessing.
- Automation recipes (one `jira.create_automation_rule` each; triggers: issue_created,
  issue_updated, issue_transitioned + `trigger_to_status`, issue_commented):
  - Team/category assignment → issue_created + `jql_condition` per category (e.g.
    `"Request Type" = "Network Connectivity Issue"`) + assign (accountId).
  - Priority classification → issue_created + JQL on impact/urgency + set_priority.
  - Approval request → issue_transitioned to the approval status + comment/send_email.
  - Resolution notification → issue_transitioned to Resolved + comment (public) or send_email.
  - Reopen on customer reply → issue_commented + `status = Resolved` + transition back.
  - Recurring-incident hint / KB recommendation → issue_created + JQL + comment with guidance
    and the KB space link.
  - Scheduled rules ARE supported: trigger `scheduled` + `schedule_cron` (Quartz, e.g.
    `0 0 * ? * *` hourly, `0 0 2 ? * *` daily) + `scheduled_jql`: auto-close after N days
    (`status = Resolved AND updated <= -3d` + transition Closed), SLA reminder
    (`"Time to resolution" < remaining("2h") AND "Time to resolution" != breached() AND
    resolution = Unresolved` + comment/send_email), daily summary (`email_issue_list`).
