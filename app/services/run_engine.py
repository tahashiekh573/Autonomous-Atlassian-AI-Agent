"""Runs planning and execution in the background, each step with its own DB session."""

import logging
from typing import Any

from pydantic import SecretStr

from app.clients.atlassian.credentials import AtlassianCredentials
from app.clients.atlassian.factory import AtlassianClientFactory
from app.clients.llm.base import LLMClient
from app.core.config import Settings
from app.core.exceptions import AppError, ConfigurationError, NotFoundError
from app.core.security import CredentialCipher
from app.db.base import utcnow
from app.db.session import Database
from app.models.execution_run import ExecutionOperation, ExecutionRun
from app.orchestrators.approval_policy import requires_approval
from app.orchestrators.execution_orchestrator import ExecutionOrchestrator
from app.orchestrators.planning_orchestrator import PlanningOrchestrator, PlanningResult
from app.repositories.connection_repository import ConnectionRepository
from app.repositories.run_repository import RunRepository
from app.schemas.agents import ConversationTurn, ExecutionPlan, UnderstandingInput
from app.schemas.operations.catalog import get_spec
from app.services.agent_factory import AgentSetBuilder, build_agent_set
from app.services.run_recorder import RunRecorder
from app.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


class RunEngine:
    def __init__(
        self,
        database: Database,
        cipher: CredentialCipher,
        client_factory: AtlassianClientFactory,
        llm: LLMClient | None,
        settings: Settings,
        tasks: TaskManager,
        agent_builder: AgentSetBuilder = build_agent_set,
    ) -> None:
        self._db = database
        self._cipher = cipher
        self._factory = client_factory
        self._llm = llm
        self._settings = settings
        self.tasks = tasks
        self._build_agents = agent_builder
        self._stop_requested: set[str] = set()

    def request_stop(self, run_id: str) -> None:
        """The executing run finishes its current step, then starts no further steps."""
        self._stop_requested.add(run_id)

    def stop_requested(self, run_id: str) -> bool:
        return run_id in self._stop_requested

    @property
    def llm_available(self) -> bool:
        return self._llm is not None

    def start_planning(self, run_id: str) -> None:
        self.tasks.spawn(run_id, self._guard(run_id, self._plan(run_id)))

    def start_execution(self, run_id: str) -> None:
        self.tasks.spawn(run_id, self._guard(run_id, self._execute(run_id)))

    async def _guard(self, run_id: str, work: Any) -> None:
        try:
            await work
        except AppError as exc:
            logger.warning("Run %s failed: %s", run_id, exc.message)
            await self._fail(run_id, exc.message)
        except Exception:
            logger.exception("Run %s crashed", run_id)
            await self._fail(run_id, "Internal error while processing the run; see server logs.")

    async def _fail(self, run_id: str, message: str) -> None:
        async with self._db.session() as session:
            await RunRepository(session).update_run(
                run_id, status="failed", error=message, current_agent=None, finished_at=utcnow()
            )

    async def _load(self, run_id: str) -> tuple[ExecutionRun, AtlassianCredentials, dict[str, Any]]:
        async with self._db.session() as session:
            run = await RunRepository(session).get(run_id)
            if run is None:
                raise NotFoundError(f"Run {run_id} not found.")
            connection = await ConnectionRepository(session).get(run.connection_id)
            if connection is None:
                raise NotFoundError("The run's Atlassian connection no longer exists.")
            credentials = AtlassianCredentials(
                site_url=connection.site_url,
                email=connection.email,
                api_token=SecretStr(self._cipher.decrypt(connection.encrypted_api_token)),
            )
            return run, credentials, dict(connection.capabilities or {})

    def _llm_or_fail(self) -> LLMClient:
        if self._llm is None:
            raise ConfigurationError("No LLM is configured (set GEMINI_API_KEY or OPENAI_API_KEY).")
        return self._llm

    # --- planning -------------------------------------------------------------------------

    async def _plan(self, run_id: str) -> None:
        run, credentials, capabilities = await self._load(run_id)
        recorder = RunRecorder(self._db, run.created_by)
        history = [ConversationTurn.model_validate(t) for t in run.conversation[:-1]]
        latest = run.conversation[-1]["content"] if run.conversation else run.input_text
        async with self._factory.open(credentials) as clients:
            agents = self._build_agents(
                clients,
                credentials.site_url,
                capabilities.get("account_id"),
                self._llm_or_fail(),
                self._settings.verification_retry_delay_seconds,
            )
            result = await PlanningOrchestrator(
                agents, recorder, self._settings.max_plan_operations
            ).run(
                run_id,
                UnderstandingInput(text=latest, input_mode=run.input_mode, history=history),
                capabilities,
            )
        await self._store_plan(run_id, result)

    async def _store_plan(self, run_id: str, result: PlanningResult) -> None:
        auto = self._settings.auto_approve_risks
        async with self._db.session() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            assert run is not None  # noqa: S101
            conversation = list(run.conversation)
            if result.outcome == "needs_clarification":
                questions = result.intent.clarification_questions
                conversation.append({"role": "assistant", "content": "\n".join(questions)})
                await repo.update_run(
                    run_id,
                    status="needs_clarification",
                    intent=result.intent.model_dump(mode="json"),
                    conversation=conversation,
                    current_agent=None,
                    progress_message="Waiting for your answer",
                )
                return
            plan = result.plan
            assert plan is not None  # noqa: S101
            operations: list[ExecutionOperation] = []
            step_errors: dict[str, list[str]] = {}
            for issue in result.issues:
                if issue.severity == "error" and issue.operation_id:
                    step_errors.setdefault(issue.operation_id, []).append(issue.message)
            for position, op in enumerate(plan.operations):
                spec = get_spec(op.operation)
                risk = spec.risk if spec else "modify"
                invalid = op.id in step_errors
                needs = (
                    requires_approval(risk, auto)
                    if spec and spec.supported and not invalid
                    else False
                )
                check = result.checks.get(op.id)
                operations.append(
                    ExecutionOperation(
                        op_id=op.id,
                        position=position,
                        operation=op.operation,
                        agent=f"{spec.agent}_agent" if spec else "unknown",
                        description=op.description,
                        risk=risk,
                        supported=bool(spec and spec.supported),
                        requires_approval=needs,
                        approved=False,
                        status="skipped"
                        if invalid
                        else ("requires_approval" if needs else "pending"),
                        message="Not executable: " + " ".join(step_errors[op.id])
                        if invalid
                        else None,
                        params=op.params,
                        depends_on=op.depends_on,
                        preflight=check.model_dump(mode="json") if check else None,
                    )
                )
            await repo.replace_operations(run, operations)
            conversation.append({"role": "assistant", "content": plan.summary})
            blocked = result.outcome == "blocked"
            needs_approval = any(o.requires_approval for o in operations)
            status = (
                "blocked" if blocked else ("awaiting_approval" if needs_approval else "executing")
            )
            await repo.update_run(
                run_id,
                status=status,
                intent=result.intent.model_dump(mode="json"),
                plan=plan.model_dump(mode="json"),
                plan_issues=[i.model_dump() for i in result.issues],
                conversation=conversation,
                current_agent=None,
                progress_message={
                    "blocked": "Plan has blocking issues",
                    "awaiting_approval": "Waiting for approval",
                    "executing": "Auto-approved; executing",
                }[status],
            )
        if status == "executing":
            await self._execute(run_id)

    # --- execution ------------------------------------------------------------------------

    async def _execute(self, run_id: str) -> None:
        run, credentials, capabilities = await self._load(run_id)
        assert run.plan is not None  # noqa: S101
        plan = ExecutionPlan.model_validate(run.plan)
        preskipped = {o.op_id: o.message or "" for o in run.operations if o.status == "skipped"}
        approved = {
            o.op_id
            for o in run.operations
            if (o.approved or not o.requires_approval) and o.op_id not in preskipped
        }
        language = (run.intent or {}).get("language", "en")
        instruction = (run.intent or {}).get("normalized_instruction") or run.input_text
        recorder = RunRecorder(self._db, run.created_by)
        async with self._factory.open(credentials) as clients:
            agents = self._build_agents(
                clients,
                credentials.site_url,
                capabilities.get("account_id"),
                self._llm_or_fail(),
                self._settings.verification_retry_delay_seconds,
            )
            try:
                result = await ExecutionOrchestrator(
                    agents, recorder, should_stop=lambda: self.stop_requested(run_id)
                ).run(run_id, plan, approved, instruction, language, preskipped)
            finally:
                stopped = self.stop_requested(run_id)
                self._stop_requested.discard(run_id)
        statuses = list(result.statuses.values())
        if any(s == "failed" for s in statuses) or any(s == "skipped" for s in statuses):
            final = (
                "failed" if not any(s == "completed" for s in statuses) else "completed_with_errors"
            )
        else:
            final = "completed"
        async with self._db.session() as session:
            await RunRepository(session).update_run(
                run_id,
                status=final,
                report=result.report.model_dump(mode="json"),
                current_agent=None,
                progress_message="Stopped by you" if stopped else "Finished",
                finished_at=utcnow(),
            )
