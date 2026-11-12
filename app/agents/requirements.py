"""Requirements ledger: judge each requested item from verified step results (no LLM).

The step counters ("23 of 25 completed") said nothing about items that were never planned, so a
run could look green while half of the request was missing. Every requirement extracted from the
user's text is mapped to the steps that deliver it and judged here from what actually happened.
"""

import re

from app.schemas.agents import CoverageItem, OperationSummary, RequirementStatus

# Steps that change something on a resource rather than create one: they do not count towards
# "10 sample tickets" style quantities.
_NON_CREATING = ("transition", "link", "assign", "move", "add_", "update", "configure", "start")


def requested_count(requirement: str) -> int:
    """'10 sample tickets' -> 10; items without a leading quantity count as 1."""
    match = re.match(r"\s*(\d{1,3})\b", requirement)
    return int(match.group(1)) if match else 1


def _creates(operation: str) -> bool:
    action = operation.split(".", 1)[-1]
    return not any(action.startswith(prefix) for prefix in _NON_CREATING)


def judge(
    coverage: list[CoverageItem], operations: list[OperationSummary]
) -> tuple[list[RequirementStatus], int | None]:
    """Status per requirement and the completion percentage of the automatable ones."""
    by_id = {o.op_id: o for o in operations}
    results: list[RequirementStatus] = []
    for item in coverage:
        ops = [by_id[i] for i in item.operation_ids if i in by_id]
        if not ops:
            results.append(
                RequirementStatus(
                    requirement=item.requirement,
                    status="manual" if item.manual_reason else "missing",
                    note=item.manual_reason or "No step was planned for this item.",
                )
            )
            continue
        good = [o for o in ops if o.status == "completed" and o.verified is not False]
        bad = [o for o in ops if o not in good]
        wanted = requested_count(item.requirement)
        made = len([o for o in good if _creates(o.operation)])
        short = wanted > 1 and made < wanted
        if not bad and not short:
            status, note = "done", ""
        elif not good:
            status = "failed"
            note = "; ".join(f"{o.op_id}: {o.message}"[:160] for o in bad[:3])
        else:
            status = "partial"
            parts = [f"{made} of {wanted} created"] if short else []
            parts += [f"{o.op_id} {o.status}: {o.message}"[:160] for o in bad[:3]]
            note = "; ".join(parts)
        results.append(
            RequirementStatus(
                requirement=item.requirement,
                status=status,
                operation_ids=[o.op_id for o in ops],
                note=note,
            )
        )
    claimed = {i for item in coverage for i in item.operation_ids}
    for o in operations:
        if o.op_id in claimed or o.status not in ("failed", "skipped"):
            continue
        unsupported = (
            "not supported" in o.message.casefold() or "manual step" in o.message.casefold()
        )
        results.append(
            RequirementStatus(
                requirement=o.description or o.operation,
                status="manual" if unsupported else "failed",
                operation_ids=[o.op_id],
                note=o.message[:200],
            )
        )
    automatable = [r for r in results if r.status != "manual"]
    if not automatable:
        return results, None
    score = sum(
        1.0 if r.status == "done" else 0.5 if r.status == "partial" else 0.0 for r in automatable
    )
    return results, round(100 * score / len(automatable))
