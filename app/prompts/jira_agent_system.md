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
