# Cross-product playbook (owned by the Integration Agent and Confluence Agent)

Atlassian products must be connected, not built in isolation. When a request involves more
than one product, plan the links explicitly:

- Jira project + documentation: create the Confluence space, a documentation index page
  (`confluence.create_index_page`), requirement / technical pages as children, then
  `integration.link_project_to_space`.
- Epics/stories ↔ documentation: `integration.link_issue_to_page` for each important pair, and
  `integration.embed_issues_in_page` (e.g. JQL `parent = ${s5.key}`) on the requirements page.
- JSM + knowledge base: create the KB space and articles (`page_kind: kb_article`,
  `troubleshooting`, `how_to`), label them by topic (e.g. `password-reset`, `vpn`), and include
  `jsm.link_knowledge_base` so the user sees the one manual step.
- Incidents ↔ development: `integration.create_dev_issue_from_incident` (creates the bug and the
  link) or `integration.link_incident_to_issue` for existing issues.
- Always reference created resources through `${sN.output}` so IDs and keys stay correct.

# Confluence page planning

- Default parent is the space home page; use `parent_title` or `parent_page_id` for deeper
  hierarchies, creating parents first.
- Typical IT knowledge base: index page → "IT Policies" (it_policy pages), "How-to Guides"
  (how_to), "Troubleshooting" (troubleshooting), each article with labels.
- Titles must be unique within a space.
