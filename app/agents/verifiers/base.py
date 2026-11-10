"""Verifier type and helpers."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.handlers.base import HandlerContext, same_name
from app.schemas.agents import OperationOutcome, VerificationCheck

Verifier = Callable[[HandlerContext, Any, OperationOutcome], Awaitable[list[VerificationCheck]]]


def check(name: str, expected: Any, actual: Any, passed: bool | None = None) -> VerificationCheck:
    if passed is None:
        passed = (
            same_name(str(expected), str(actual))
            if isinstance(expected, str)
            else expected == actual
        )
    return VerificationCheck(name=name, expected=expected, actual=actual, passed=passed)


def exists(name: str, found: bool, detail: Any = None) -> VerificationCheck:
    return VerificationCheck(
        name=name, expected="exists", actual=detail if found else "missing", passed=found
    )


def out(outcome: OperationOutcome, key: str) -> str:
    return str(outcome.outputs.get(key) or "")
