"""Static checks on a generated plan: catalog, params, references, DAG, capabilities."""

from typing import Any

from pydantic import ValidationError

from app.orchestrators.references import contains_ref, find_refs
from app.schemas.agents import ExecutionPlan, PlanIssue
from app.schemas.operations.catalog import get_spec


def _param_errors(model: Any, params: dict[str, Any]) -> list[str]:
    try:
        model.model_validate(params)
    except ValidationError as exc:
        errors: list[str] = []
        for err in exc.errors():
            value: Any = params
            for part in err["loc"]:
                value = (
                    value.get(part)
                    if isinstance(value, dict)
                    else (
                        value[part]
                        if isinstance(value, list) and isinstance(part, int) and part < len(value)
                        else None
                    )
                )
            if contains_ref(value):
                continue  # resolved at execution time
            errors.append(f"{'.'.join(map(str, err['loc']))}: {err['msg']}")
        return errors
    return []


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
        for err in _param_errors(spec.params, op.params):
            issues.append(
                PlanIssue(severity="error", operation_id=op.id, message=f"Invalid param {err}")
            )
        for product in spec.requires_products:
            if products and not products.get(product, False):
                issues.append(
                    PlanIssue(
                        severity="error",
                        operation_id=op.id,
                        message=f"{product} is not available on this site.",
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

    if _has_cycle({op.id: op.depends_on for op in plan.operations}):
        issues.append(PlanIssue(severity="error", operation_id=None, message="Dependency cycle."))
    return issues
