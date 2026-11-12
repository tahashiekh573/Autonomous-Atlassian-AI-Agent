"""Semantic plan rules shared by the Planning Agent (to repair steps) and plan validation."""

from typing import Any

# Actions that change an issue. On an "issue updated/commented" trigger without a condition they
# would fire on every edit of every issue (e.g. an "auto-close" closing tickets on any update).
_CHANGING_ACTIONS = {"transition", "assign", "set_priority", "send_email"}
# On "issue created" the rule touches only the new ticket, so routing it is the normal intent
# (auto-assign, default priority, notify); only an unconditional transition is suspicious.
_RISKY_ON_CREATE = {"transition"}


def automation_problem(params: dict[str, Any]) -> str | None:
    """Why an automation rule as planned would misbehave, or None when it is safe."""
    if params.get("jql_condition") or params.get("trigger_to_status"):
        return None
    actions = {str(a.get("type")) for a in params.get("actions") or [] if isinstance(a, dict)}
    trigger = params.get("trigger")
    if trigger == "scheduled":
        if params.get("scheduled_jql") or actions <= {"email_issue_list"}:
            return None
        return (
            "A scheduled rule needs scheduled_jql (which issues to act on, e.g. "
            '`"Time to resolution" < remaining("1h")` or `status = Resolved AND updated <= -3d`).'
        )
    risky = sorted(
        actions & (_RISKY_ON_CREATE if trigger == "issue_created" else _CHANGING_ACTIONS)
    )
    if risky:
        return (
            f"The rule would run {', '.join(risky)} on every issue ({trigger}); add a "
            "jql_condition (or trigger_to_status) that limits it to the intended tickets."
        )
    return None
