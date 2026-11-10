"""`${s3.key}`-style references between plan steps."""

import re
from typing import Any

from app.core.exceptions import OperationInputError

REF_PATTERN = re.compile(r"\$\{(s\d{1,3})\.([A-Za-z0-9_.]+)\}")


def find_refs(value: Any) -> set[str]:
    """Step ids referenced anywhere inside a params structure."""
    if isinstance(value, str):
        return {m.group(1) for m in REF_PATTERN.finditer(value)}
    if isinstance(value, dict):
        return set().union(*(find_refs(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(find_refs(v) for v in value)) if value else set()
    return set()


def contains_ref(value: Any) -> bool:
    return bool(find_refs(value))


def _lookup(outputs: dict[str, dict[str, Any]], step: str, path: str) -> Any:
    if step not in outputs:
        raise OperationInputError(f"Step {step} has no outputs (it did not complete).")
    current: Any = outputs[step]
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current or current[part] in (None, ""):
            raise OperationInputError(f"Step {step} produced no output '{path}'.")
        current = current[part]
    return current


def resolve(value: Any, outputs: dict[str, dict[str, Any]]) -> Any:
    """Replace references with real values. A string that is exactly one reference keeps the
    referenced value's type (ids stay ints, lists stay lists)."""
    if isinstance(value, str):
        whole = REF_PATTERN.fullmatch(value)
        if whole:
            return _lookup(outputs, whole.group(1), whole.group(2))
        return REF_PATTERN.sub(lambda m: str(_lookup(outputs, m.group(1), m.group(2))), value)
    if isinstance(value, dict):
        return {k: resolve(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, outputs) for v in value]
    return value
