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
- Apply workflows to a project with ONE `jira.configure_workflow_scheme` step listing every
  workflow → issue types mapping (works even when the project already has issues; statuses are
  migrated). Use `jira.update_workflow` to add missing transitions (reopen, rollback, failed) to an
  existing workflow. `jira.assign_workflow` is only for a single issue type.
- Custom workflows ARE supported by the API — never mark them manual. Create one
  `jira.create_workflow` per requested process (statuses with categories, initial status,
  transitions incl. reject/rollback/reopen transitions; optional raw rules), then
  `jira.assign_workflow` with the issue types it applies to. Only SLA goals, approval steps
  inside workflows, transition screens and portal branding are UI-only.
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
- Dashboards: create the filters the gadgets should show first (`jira.create_filter`), then
  `jira.create_dashboard` with gadgets. Mention in `warnings` that gadget data sources must be
  picked in the UI.
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
  - NOT possible with these triggers (mark manual, name it): scheduled rules (auto-close after
    N days, daily summaries) and SLA-threshold triggers.
