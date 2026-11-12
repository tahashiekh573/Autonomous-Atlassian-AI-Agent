"""Planner housekeeping: duplicate warnings collapse, distinct limitations survive."""

from app.agents.planning_agent import tidy_warnings


def test_duplicate_and_noise_warnings_are_collapsed() -> None:
    warnings = [
        "SLA calendar hours (9 AM-6 PM) must be configured manually in the SLA settings.",
        "SLA calendar hours (9 AM - 6 PM) cannot be set via API; Sample 9-5 Calendar is used.",
        "Linking the Confluence space to the JSM project must be done manually.",
        "Linking the Confluence space 'Docs' to the JSM project 'X' must be done manually.",
        "Automation rules and queues require manual verification after creation.",
        "Request form field layout cannot be configured via API.",
    ]
    kept = tidy_warnings(warnings)
    assert len(kept) == 3
    assert kept[0].startswith("SLA calendar") and kept[1].startswith("Linking")
    assert kept[2].startswith("Request form")


def test_failed_step_outside_the_checklist_still_lowers_completion() -> None:
    from app.agents.requirements import judge
    from app.schemas.agents import CoverageItem, OperationSummary

    coverage = [CoverageItem(requirement="Project X", operation_ids=["s1"])]
    ops = [
        OperationSummary(
            op_id="s1",
            operation="jsm.create_service_project",
            description="p",
            status="completed",
            message="ok",
            verified=True,
        ),
        OperationSummary(
            op_id="s2",
            operation="jsm.create_form",
            description="Laptop form",
            status="failed",
            message="jsm-forms: resource not found",
        ),
    ]
    results, pct = judge(coverage, ops)
    assert [(r.requirement, r.status) for r in results] == [
        ("Project X", "done"),
        ("Laptop form", "failed"),
    ]
    assert pct == 50
