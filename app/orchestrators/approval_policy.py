"""Which operations need human approval, and who may give it."""

from collections.abc import Iterable

from app.schemas.agents import RiskClass

NEVER_AUTO_APPROVED: frozenset[str] = frozenset({"destructive", "security"})
ELEVATED_RISKS: frozenset[str] = NEVER_AUTO_APPROVED


def requires_approval(risk: RiskClass, auto_approve: Iterable[str]) -> bool:
    if risk in NEVER_AUTO_APPROVED:
        return True
    return risk not in set(auto_approve)


def required_role(risk: RiskClass) -> str:
    """Destructive and security-sensitive changes need an admin; the rest an operator."""
    return "admin" if risk in ELEVATED_RISKS else "operator"
