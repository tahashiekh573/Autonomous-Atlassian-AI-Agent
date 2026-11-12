"""Static checks on a generated plan: catalog, params, references, DAG, capabilities."""

import re
from typing import Any

from app.orchestrators.references import find_refs
from app.schemas.agents import ExecutionPlan, PlanIssue
from app.schemas.operations.catalog import get_spec, param_errors
from app.schemas.operations.rules import automation_problem


def _has_cycle(deps: dict[str, list[str]]) -> bool:
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        if any(visit(d) for d in deps.get(node, [])):
            return True
        state[node] = 2
        return False

    return any(visit(n) for n in deps)


_ANY_REF = re.compile(r"\$\{[^}]*\}")
_STEP_REF = re.compile(r"\$\{s\d{1,3}\.[A-Za-z0-9_.]+\}")


def _bad_refs(value: Any) -> set[str]:
    if isinstance(value, str):
        return {m for m in _ANY_REF.findall(value) if not _STEP_REF.fullmatch(m)}
    if isinstance(value, dict):
        return set().union(*(_bad_refs(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_bad_refs(v) for v in value)) if value else set()
    return set()


def fill_missing_names(plan: ExecutionPlan) -> list[str]:
    """Steps whose params model needs a ``name`` but the model left it out get the step
    description as name (a label only). Returns the affected step ids."""
    fixed: list[str] = []
    for op in plan.operations:
        spec = get_spec(op.operation)
        if spec is None or "name" not in spec.params.model_fields:
            continue
        if not op.params.get("name") and op.description.strip():
            op.params["name"] = op.description.strip()[:255]
            fixed.append(op.id)
    return fixed


def validate_plan(
    plan: ExecutionPlan, capabilities: dict[str, Any], max_operations: int
) -> list[PlanIssue]:
    """Validate in place (dependencies implied by references are added)."""
    issues: list[PlanIssue] = []
    products: dict[str, bool] = capabilities.get("products") or {}
    is_admin = capabilities.get("is_jira_admin")
    ids = [op.id for op in plan.operations]
    if len(ids) != len(set(ids)):
        issues.append(PlanIssue(severity="error", operation_id=None, message="Duplicate step ids."))
    if len(plan.operations) > max_operations:
        issues.append(
            PlanIssue(
                severity="error",
                operation_id=None,
                message=f"Plan exceeds {max_operations} operations.",
            )
        )
    if not plan.operations:
        issues.append(PlanIssue(severity="error", operation_id=None, message="The plan is empty."))

    seen: set[str] = set()
    for op in plan.operations:
        spec = get_spec(op.operation)
        if spec is None:
            issues.append(
                PlanIssue(
                    severity="error",
                    operation_id=op.id,
                    message=f"Unknown operation '{op.operation}'.",
                )
            )
            seen.add(op.id)
            continue
        refs = find_refs(op.params)
        op.depends_on = sorted(set(op.depends_on) | refs, key=lambda s: int(s[1:]))
        for dep in op.depends_on:
            if dep not in seen:
                issues.append(
                    PlanIssue(
                        severity="error",
                        operation_id=op.id,
                        message=f"Depends on {dep}, which is not an earlier step.",
                    )
                )
        seen.add(op.id)
        if not spec.supported:
            issues.append(
                PlanIssue(
                    severity="warning",
                    operation_id=op.id,
                    message=f"Not supported by the API and will be skipped: "
                    f"{spec.limitation} Alternative: {spec.alternative}",
                )
            )
            continue
        if (
            op.operation == "jira.transition_issue"
            and str(op.params.get("to_status", "")).strip().casefold() == "backlog"
        ):
            issues.append(
                PlanIssue(
                    severity="error",
                    operation_id=op.id,
                    message=(
                        "'Backlog' is not a status. New issues are already in the backlog; use "
                        "jira.move_issues_to_backlog for issues that are in a sprint."
                    ),
                )
            )
        for err in param_errors(spec.params, op.params):
            issues.append(
                PlanIssue(severity="error", operation_id=op.id, message=f"Invalid param {err}")
            )
        for product in spec.requires_products:
            if products and not products.get(product, False):
                issues.append(
                    PlanIssue(
                        severity="error",
                        operation_id=op.id,
                        message=f"{product} is not available on this site (re-run the "
                        "connection test in Settings if that changed).",
                    )
                )
        if spec.needs_jira_admin and is_admin is False:
            issues.append(
                PlanIssue(
                    severity="error",
                    operation_id=op.id,
                    message="Requires Jira administrator permission, which the "
                    "connected account does not have.",
                )
            )

    for op in plan.operations:
        for bad in sorted(_bad_refs(op.params)):
            issues.append(
                PlanIssue(
                    severity="error",
                    operation_id=op.id,
                    message=f"Invalid reference {bad}: only earlier step outputs "
                    "like ${s3.key} can be referenced.",
                )
            )
        if op.operation == "jira.create_automation_rule":
            problem = automation_problem(op.params)
            if problem:
                issues.append(PlanIssue(severity="error", operation_id=op.id, message=problem))

    known_ids = {op.id for op in plan.operations}
    for item in plan.coverage:
        if not item.operation_ids and not item.manual_reason:
            issues.append(
                PlanIssue(
                    severity="warning",
                    operation_id=None,
                    message=f"Requested item not covered by the plan: {item.requirement}",
                )
            )
        for ref in item.operation_ids:
            if ref not in known_ids:
                issues.append(
                    PlanIssue(
                        severity="warning",
                        operation_id=None,
                        message=f"Coverage for '{item.requirement}' points to missing step {ref}.",
                    )
                )

    if _has_cycle({op.id: op.depends_on for op in plan.operations}):
        issues.append(PlanIssue(severity="error", operation_id=None, message="Dependency cycle."))
    return issues
