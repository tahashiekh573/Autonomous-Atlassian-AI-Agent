"""Shared async HTTP client for Atlassian Cloud REST APIs.

Responsibilities: API-token auth, retries with backoff (honouring Retry-After), typed error
mapping, pagination, and request logging that never includes credentials.
"""

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from app.clients.atlassian.credentials import AtlassianCredentials, HttpPolicy
from app.clients.atlassian.errors import error_for_response
from app.core.exceptions import AtlassianConnectionError

logger = logging.getLogger(__name__)

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

SleepFn = Callable[[float], Awaitable[None]]


class AtlassianHttpClient:
    def __init__(
        self,
        credentials: AtlassianCredentials,
        policy: HttpPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._policy = policy
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            base_url=credentials.site_url,
            auth=httpx.BasicAuth(credentials.email, credentials.api_token.get_secret_value()),
            timeout=policy.timeout_seconds,
            headers={"Accept": "application/json", "User-Agent": "atlassian-ai-agent/0.1"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        service: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
        idempotent: bool | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Send a request and return the decoded JSON body (None for empty responses).

        Non-idempotent requests (POST) are only retried on 429, where Atlassian guarantees the
        request was rejected before processing. Pass ``idempotent=True`` to opt a POST in.
        """
        method = method.upper()
        retry_on_failure = idempotent if idempotent is not None else method in _IDEMPOTENT_METHODS
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                response = await self._client.request(
                    method, path, params=params, json=json, headers=headers
                )
            except httpx.TransportError as exc:
                if retry_on_failure and attempt < self._policy.max_retries:
                    await self._backoff(attempt, None, service, method, path, f"network: {exc!r}")
                    attempt += 1
                    continue
                raise AtlassianConnectionError(
                    f"{service}: could not reach Atlassian ({type(exc).__name__})", service=service
                ) from exc

            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "atlassian %s %s %s -> %s (%.0f ms, attempt %d)",
                service,
                method,
                path,
                response.status_code,
                elapsed_ms,
                attempt + 1,
            )

            status = response.status_code
            can_retry = status == 429 or (status in _RETRYABLE_STATUS and retry_on_failure)
            if can_retry and attempt < self._policy.max_retries:
                await self._backoff(attempt, response, service, method, path, f"HTTP {status}")
                attempt += 1
                continue

            if response.is_error:
                raise error_for_response(response, service)
            if status == 204 or not response.content:
                # Async Jira operations answer 303 with the task URL only in Location.
                location = response.headers.get("Location")
                return {"location": location} if location else None
            return response.json()

    async def _backoff(
        self,
        attempt: int,
        response: httpx.Response | None,
        service: str,
        method: str,
        path: str,
        reason: str,
    ) -> None:
        delay = self._retry_after(response)
        if delay is None:
            ceiling = min(
                self._policy.backoff_max_seconds, self._policy.backoff_base_seconds * 2**attempt
            )
            delay = random.uniform(0, ceiling)  # noqa: S311 - jitter, not cryptography
        delay = min(delay, self._policy.backoff_max_seconds)
        logger.warning(
            "atlassian %s %s %s: %s, retrying in %.2fs", service, method, path, reason, delay
        )
        await self._sleep(delay)

    @staticmethod
    def _retry_after(response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None

    # --- pagination ---------------------------------------------------------------------

    async def paginate_offset(
        self,
        path: str,
        *,
        service: str,
        params: dict[str, Any] | None = None,
        items_key: str = "values",
        start_param: str = "startAt",
        limit_param: str = "maxResults",
        last_page_key: str = "isLast",
        page_size: int = 50,
        max_items: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Offset pagination: Jira (startAt/maxResults/isLast) and JSM (start/limit/isLastPage)."""
        start = 0
        yielded = 0
        while True:
            page_params = {**(params or {}), start_param: start, limit_param: page_size}
            body = await self.request("GET", path, service=service, params=page_params)
            items = body.get(items_key) or []
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            start += len(items)
            total = body.get("total")
            if (
                not items
                or body.get(last_page_key) is True
                or (isinstance(total, int) and start >= total)
            ):
                return

    async def paginate_cursor(
        self,
        path: str,
        *,
        service: str,
        params: dict[str, Any] | None = None,
        items_key: str = "results",
        max_items: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Cursor pagination used by Confluence REST v2 (``_links.next``)."""
        next_path: str | None = path
        next_params = params
        yielded = 0
        while next_path:
            body = await self.request("GET", next_path, service=service, params=next_params)
            for item in body.get(items_key) or []:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            nxt = str((body.get("_links") or {}).get("next") or "")
            # Only follow site-relative links: an absolute URL could send credentials elsewhere.
            next_path = nxt if nxt.startswith("/") and not nxt.startswith("//") else None
            next_params = None  # the next link already carries the query string
