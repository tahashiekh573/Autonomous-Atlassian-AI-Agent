"""The single registry of executable operations, and its LLM-facing description."""

import json
from typing import Any

from pydantic import BaseModel

from app.schemas.operations import confluence_ops, integration_ops, jira_ops, jsm_ops
from app.schemas.operations.spec import OperationSpec

CATALOG: dict[str, OperationSpec] = {
    spec.name: spec
    for spec in (*jira_ops.SPECS, *jsm_ops.SPECS, *confluence_ops.SPECS, *integration_ops.SPECS)
}


def get_spec(name: str) -> OperationSpec | None:
    return CATALOG.get(name)


def _compact_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})

    def simplify(prop: dict[str, Any]) -> Any:
        if "$ref" in prop:
            return _fields(defs[prop["$ref"].split("/")[-1]])
        if "anyOf" in prop:
            options = [simplify(p) for p in prop["anyOf"] if p.get("type") != "null"]
            return options[0] if len(options) == 1 else options
        if prop.get("type") == "array":
            return [simplify(prop.get("items", {}))]
        if "enum" in prop:
            return "|".join(map(str, prop["enum"]))
        return prop.get("type", "any")

    def _fields(s: dict[str, Any]) -> dict[str, Any]:
        required = set(s.get("required", []))
        out: dict[str, Any] = {}
        for name, prop in (s.get("properties") or {}).items():
            label = name if name in required else f"{name}?"
            value = simplify(prop)
            if prop.get("description") and isinstance(value, str):
                value = f"{value} — {prop['description']}"
            out[label] = value
        return out

    return _fields(schema)


def describe_catalog() -> str:
    """Compact, deterministic catalog text for the Planning Agent prompt."""
    lines: list[str] = []
    for spec in CATALOG.values():
        header = f"### {spec.name}  [risk={spec.risk}"
        header += ", needs Jira admin" if spec.needs_jira_admin else ""
        header += ", NOT SUPPORTED BY API" if not spec.supported else ""
        lines.append(header + "]")
        lines.append(spec.description)
        if spec.supported:
            lines.append("params: " + json.dumps(_compact_schema(spec.params), ensure_ascii=False))
        if spec.limitation:
            lines.append(f"limitation: {spec.limitation}")
        lines.append("")
    return "\n".join(lines)
