"""Translate Atlassian HTTP error responses into typed application exceptions."""

from typing import Any

import httpx

from app.core.exceptions import (
    AtlassianApiError,
    AtlassianAuthError,
    AtlassianError,
    AtlassianNotFoundError,
    AtlassianPermissionError,
    AtlassianRateLimitError,
)


def extract_error_message(response: httpx.Response) -> str:
    """Pull a human-readable message out of Jira, JSM or Confluence error bodies."""
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:500] or response.reason_phrase

    parts: list[str] = []
    if isinstance(body, dict):
        # Jira: {"errorMessages": [...], "errors": {"field": "msg"}}
        parts.extend(str(m) for m in body.get("errorMessages") or [])
        errors = body.get("errors")
        if isinstance(errors, dict):
            parts.extend(f"{k}: {v}" for k, v in errors.items())
        # Confluence v2: {"errors": [{"title": ..., "detail": ...}]}
        elif isinstance(errors, list):
            for err in errors:
                if isinstance(err, dict):
                    parts.append(str(err.get("detail") or err.get("title") or err))
        # JSM: {"errorMessage": "..."}; Confluence v1 / generic: {"message": "..."}
        for key in ("errorMessage", "message"):
            if isinstance(body.get(key), str):
                parts.append(body[key])
    return "; ".join(p for p in parts if p) or response.reason_phrase


def error_for_response(response: httpx.Response, service: str) -> AtlassianError:
    status = response.status_code
    message = extract_error_message(response)
    kwargs: dict[str, Any] = {"service": service, "upstream_status": status}
    if status == 401:
        return AtlassianAuthError(
            f"{service}: authentication failed - check email and API token ({message})", **kwargs
        )
    if status == 403:
        return AtlassianPermissionError(f"{service}: permission denied ({message})", **kwargs)
    if status == 404:
        return AtlassianNotFoundError(f"{service}: resource not found ({message})", **kwargs)
    if status == 429:
        return AtlassianRateLimitError(f"{service}: rate limit exceeded ({message})", **kwargs)
    return AtlassianApiError(f"{service}: HTTP {status} ({message})", **kwargs)
