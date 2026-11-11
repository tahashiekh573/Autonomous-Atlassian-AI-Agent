"""Planning Agent: turns a request into an ordered, dependency-aware execution plan.

Large requests (e.g. a full ITSM "master prompt") do not fit one model answer, and smaller models
tend to stop early. The agent therefore plans in passes: a first plan, then up to
``EXPANSION_PASSES`` follow-ups that add only the requested items still missing.
"""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base_agent import LLMAgent
from app.core.exceptions import LLMError, LLMQuotaExhaustedError
from app.core.prompts import load_prompt
from app.schemas.agents import ExecutionPlan, PlanExpansion, PlannedOperation, PlanningInput
from app.schemas.operations.catalog import get_spec, param_errors

EXPANSION_PASSES = 6


class ParamFix(BaseModel):
    id: str
    params: dict[str, Any]


class ParamFixes(BaseModel):
    fixes: list[ParamFix] = Field(default_factory=list)


class PlanningAgent(LLMAgent[PlanningInput, ExecutionPlan]):
    name = "planning_agent"
    prompt_name = "planning_system"

    @property
    def system_prompt(self) -> str:
        # Each product agent owns a playbook describing how its operations should be planned.
        playbooks = ("jira_agent_system", "jsm_agent_system", "integration_agent_system")
        return "\n\n".join([load_prompt(self.prompt_name), *(load_prompt(p) for p in playbooks)])

    def _context(self, data: PlanningInput) -> str:
        capabilities = json.dumps(data.capabilities, ensure_ascii=False)
        workspace = json.dumps(data.workspace, ensure_ascii=False)[:12000]
        original = data.request_text or data.intent.normalized_instruction
        return (
            f"Today: {datetime.now(UTC).date().isoformat()}\n"
            f"Maximum operations: {data.max_operations}\n\n"
            "## Original request (authoritative — plan from this, item by item)\n"
            f"{original}\n\n"
            f"## Understood intent\n{data.intent.model_dump_json(indent=1)}\n\n"
            f"## Connected instance capabilities\n{capabilities}\n\n"
            f"## Existing resources (discovered)\n{workspace}\n\n"
            f"## Operation catalog\n{data.catalog}"
        )

    async def run(self, data: PlanningInput) -> ExecutionPlan:
        context = self._context(data)
        sections = split_sections(data.request_text)
        if len(sections) >= MIN_SECTIONS:
            plan = await self._plan_by_section(context, sections, data)
        else:
            plan = await self._structured(context, ExecutionPlan)
            for _ in range(EXPANSION_PASSES):
                if len(plan.operations) >= data.max_operations:
                    break
                expansion = await self._structured(
                    _expansion_prompt(context, plan, data.max_operations), PlanExpansion
                )
                added = _merge(plan, expansion)
                if expansion.complete or not added:
                    break
        await self._repair_params(context, plan)
        if len(plan.operations) > data.max_operations:
            dropped = plan.operations[data.max_operations :]
            plan.operations = plan.operations[: data.max_operations]
            plan.warnings.append(
                f"The request needs more than {data.max_operations} steps; only the first "
                f"{data.max_operations} are planned. Not planned: "
                + ", ".join(f"{o.id} {o.description}" for o in dropped)
                + ". Run them as a follow-up command after this plan completes."
            )
        return plan

    async def _repair_params(self, context: str, plan: ExecutionPlan) -> None:
        """One focused call to fix steps whose params fail validation (e.g. a bad colour code),
        so a single typo does not block a 60-step plan."""
        broken: list[str] = []
        for op in plan.operations:
            spec = get_spec(op.operation)
            if spec is None or not spec.supported:
                continue
            errors = param_errors(spec.params, op.params)
            if errors:
                schema = json.dumps(spec.params.model_json_schema(), ensure_ascii=False)[:1500]
                broken.append(
                    f"{op.id} {op.operation}\n  params: {json.dumps(op.params, ensure_ascii=False)}"
                    f"\n  errors: {'; '.join(errors)}\n  schema: {schema}"
                )
        if not broken:
            return
        fixes = await self._structured(
            f"{context}\n\n## Steps with invalid params\n" + "\n\n".join(broken) + "\n\n## Task\n"
            "Return corrected params for each listed step (same intent, valid against its schema). "
            "Keep ${sN.output} references unchanged.",
            ParamFixes,
        )
        by_id = {op.id: op for op in plan.operations}
        for fix in fixes.fixes:
            if fix.id in by_id:
                by_id[fix.id].params = fix.params

    async def _plan_by_section(
        self, context: str, sections: list[tuple[str, str]], data: PlanningInput
    ) -> ExecutionPlan:
        """Long structured requests: plan each `##` section on its own so nothing is dropped."""
        plan = ExecutionPlan(summary=data.intent.normalized_instruction)
        for title, body in sections:
            if len(plan.operations) >= data.max_operations:
                plan.warnings.append(f"Section '{title}' not planned: operation limit reached.")
                continue
            try:
                expansion = await self._structured(
                    _section_prompt(context, plan, title, body, data.max_operations),
                    PlanExpansion,
                )
                start = len(plan.operations)
                added = _merge(plan, expansion)
                # Smaller models stop early on long lists: ask once more for what is missing.
                if added and len(plan.operations) < data.max_operations:
                    follow_up = await self._structured(
                        _section_followup_prompt(
                            context, plan, title, body, start, data.max_operations
                        ),
                        PlanExpansion,
                    )
                    _merge(plan, follow_up)
            except LLMQuotaExhaustedError:
                raise  # nothing later can succeed either
            except LLMError as exc:
                plan.warnings.append(
                    f"Section '{title}' could not be planned ({exc.message}); submit it as a "
                    "separate command."
                )
        counts = Counter(op.operation for op in plan.operations)
        plan.summary = (
            f"{data.intent.normalized_instruction.strip()} — {len(plan.operations)} steps planned "
            f"section by section ({', '.join(f'{n} x {op}' for op, n in counts.most_common(6))})."
        )
        return plan


SECTION_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
MIN_SECTIONS = 3


def split_sections(text: str) -> list[tuple[str, str]]:
    """`## Heading` sections of a long, structured request (empty for short requests)."""
    if len(text) < 2500:
        return []
    matches = list(SECTION_HEADING.finditer(text))
    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body:
            sections.append((match.group(1).strip(), body))
    return sections


def _natural_key(op: PlannedOperation) -> tuple[str, str, str] | None:
    """What makes two planned steps "the same thing" (same operation, scope and name)."""
    p = op.params
    label = p.get("name") or p.get("summary") or p.get("title") or p.get("key")
    if not isinstance(label, str) or not label.strip():
        return None
    scope = p.get("project_key") or p.get("space_key") or p.get("service_desk") or ""
    return (op.operation, str(scope).casefold(), label.strip().casefold())


def _merge(plan: ExecutionPlan, expansion: PlanExpansion) -> int:
    """Append an expansion to the plan, dropping steps that duplicate existing ones (follow-up
    passes sometimes re-plan items) and pointing references at the surviving step."""
    added = _renumber(expansion, plan)
    seen = {k: op.id for op in plan.operations if (k := _natural_key(op))}
    duplicates: dict[str, str] = {}
    keep: list[PlannedOperation] = []
    for op in added.operations:
        key = _natural_key(op)
        if key and key in seen:
            duplicates[op.id] = seen[key]
            continue
        if key:
            seen[key] = op.id
        keep.append(op)
    if duplicates:
        pattern = re.compile(r"\$\{(" + "|".join(map(re.escape, duplicates)) + r")\.")
        for op in keep:
            text = pattern.sub(lambda m: "${" + duplicates[m.group(1)] + ".", json.dumps(op.params))
            op.params = json.loads(text)
            op.depends_on = sorted({duplicates.get(d, d) for d in op.depends_on})
        for item in added.coverage:
            item.operation_ids = [duplicates.get(i, i) for i in item.operation_ids]
    plan.operations.extend(keep)
    known = {c.requirement.casefold() for c in plan.coverage}
    plan.coverage.extend(c for c in added.coverage if c.requirement.casefold() not in known)
    plan.warnings.extend(w for w in added.warnings if w not in plan.warnings)
    return len(keep)


def _plan_listing(plan: ExecutionPlan) -> str:
    return (
        "\n".join(
            f"{op.id} {op.operation}: {op.description} "
            f"{json.dumps(op.params, ensure_ascii=False)[:160]}"
            for op in plan.operations
        )
        or "(no steps yet)"
    )


def _section_prompt(
    context: str, plan: ExecutionPlan, title: str, body: str, max_operations: int
) -> str:
    last = len(plan.operations)
    return (
        f"{context}\n\n## Steps planned so far ({last})\n{_plan_listing(plan)}\n\n"
        f"## Section to plan now: {title}\n{body}\n\n"
        "## Task\nPlan ONLY this section. Add one step for EVERY concrete item this section "
        "asks for that a catalog operation can deliver (each request type, workflow, form, "
        "automation rule, article, dashboard, filter, sample ticket, ...). Reuse resources "
        "created by earlier steps via ${sN.output} references instead of creating them again. "
        "If the section only gives instructions or asks for things no catalog operation can do, "
        "return no steps and add coverage entries with a manual_reason. "
        f"Number new steps from s{last + 1}. Stay within {max_operations - last} more steps. "
        "Set complete=true."
    )


def _section_followup_prompt(
    context: str, plan: ExecutionPlan, title: str, body: str, start: int, max_operations: int
) -> str:
    planned = "\n".join(
        f"{op.id} {op.operation}: {op.description}" for op in plan.operations[start:]
    )
    last = len(plan.operations)
    return (
        f"{context}\n\n## Steps planned so far ({last})\n{_plan_listing(plan)}\n\n"
        f"## Section: {title}\n{body}\n\n"
        f"## Steps already planned for this section\n{planned}\n\n"
        "## Task\nList every concrete item this section names (count them). Return ONLY steps "
        "for the items that are still missing above and that a catalog operation can deliver; "
        "add coverage entries with a manual_reason for items no operation can deliver. Return no "
        f"steps if nothing is missing. Number new steps from s{last + 1}. Stay within "
        f"{max_operations - last} more steps. Set complete=true."
    )


def _expansion_prompt(context: str, plan: ExecutionPlan, max_operations: int) -> str:
    steps = "\n".join(
        f"{op.id} {op.operation}: {op.description} "
        f"{json.dumps(op.params, ensure_ascii=False)[:160]}"
        for op in plan.operations
    )
    manual = "\n".join(f"- {c.requirement}" for c in plan.coverage if not c.operation_ids)
    tally = ", ".join(
        f"{name}: {n}"
        for name, n in sorted(Counter(op.operation for op in plan.operations).items())
    )
    last = len(plan.operations)
    return (
        f"{context}\n\n## Current plan ({last} steps)\n{steps}\n\n"
        f"## Steps per operation so far\n{tally}\n\n"
        f"## Already marked manual\n{manual or '(none)'}\n\n"
        "## Task\nCount every list in the ORIGINAL REQUEST (request types, workflows, forms, "
        "automation rules, articles, dashboards, filters, sample tickets, ...) and compare each "
        "count with the steps per operation above. Return ONLY additional "
        "steps for explicitly requested items that a catalog operation can deliver and that the "
        "plan does not cover yet (e.g. remaining request types, workflows, forms, automation "
        "rules, articles, dashboards, filters, sample tickets). Do not repeat existing steps. "
        f"Number new steps from s{last + 1}; depends_on and ${{sN.output}} references may point "
        "to existing steps. Add coverage entries for the new steps and for newly found manual "
        "items. Set complete=true when nothing requested is left uncovered. Stay within "
        f"{max_operations - last} more steps."
    )


def _renumber(expansion: PlanExpansion, plan: ExecutionPlan) -> PlanExpansion:
    """Give new steps ids after the current plan; rewrite references between new steps."""
    existing = {op.id for op in plan.operations}
    next_number = len(plan.operations) + 1
    renamed: dict[str, str] = {}
    for op in expansion.operations:
        number = int(op.id[1:])
        if op.id in existing or number < next_number:
            renamed[op.id] = f"s{next_number}"
            number = next_number
        next_number = number + 1
    if not renamed:
        return expansion
    pattern = re.compile(r"\$\{(" + "|".join(map(re.escape, renamed)) + r")\.")

    def fix(text: str) -> str:
        return pattern.sub(lambda m: "${" + renamed[m.group(1)] + ".", text)

    for op in expansion.operations:
        op.params = json.loads(fix(json.dumps(op.params)))
        op.depends_on = [renamed.get(d, d) for d in op.depends_on]
        op.id = renamed.get(op.id, op.id)
    for item in expansion.coverage:
        item.operation_ids = [renamed.get(i, i) for i in item.operation_ids]
    return expansion
