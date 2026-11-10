"""Minimal plain-text → Atlassian Document Format (ADF) conversion for Jira v3 fields."""

from typing import Any


def _text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def to_adf(text: str) -> dict[str, Any]:
    """Paragraphs split on blank lines; lines starting with "- " or "* " become bullet lists."""
    content: list[dict[str, Any]] = []
    for block in [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]:
        lines = [ln.rstrip() for ln in block.split("\n") if ln.strip()]
        if all(ln.lstrip().startswith(("- ", "* ")) for ln in lines):
            content.append(
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [{"type": "paragraph", "content": [_text(ln.lstrip()[2:])]}],
                        }
                        for ln in lines
                    ],
                }
            )
        else:
            parts: list[dict[str, Any]] = []
            for i, ln in enumerate(lines):
                if i:
                    parts.append({"type": "hardBreak"})
                parts.append(_text(ln))
            content.append({"type": "paragraph", "content": parts})
    return {"type": "doc", "version": 1, "content": content or [{"type": "paragraph"}]}


def adf_to_text(doc: Any) -> str:
    """Flatten ADF to plain text (for verification and summaries)."""
    if isinstance(doc, str):
        return doc
    if not isinstance(doc, dict):
        return ""
    if doc.get("type") == "text":
        return str(doc.get("text", ""))
    children = doc.get("content") or []
    sep = "\n" if doc.get("type") in ("doc", "bulletList", "orderedList") else ""
    return sep.join(adf_to_text(c) for c in children)
