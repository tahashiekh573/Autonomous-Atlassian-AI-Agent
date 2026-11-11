"""Retrying POST helper shared by LLM and speech provider clients."""

import asyncio
import logging
import random
import re
from typing import Any

import httpx

from app.clients.llm.rate_limiter import RateLimiter
from app.core.exceptions import AppError, LLMQuotaExhaustedError

logger = logging.getLogger(__name__)

_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_MAX_WAIT_SECONDS = 60.0


def _is_daily_quota(response: httpx.Response) -> str | None:
    """Return the quota id when a 429 is a per-day limit (e.g. ...PerDay...FreeTier)."""
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return None
    for detail in details:
        for violation in detail.get("violations", []) or []:
            quota_id = str(violation.get("quotaId", ""))
            if "PerDay" in quota_id:
                return quota_id
    return None


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """How long to wait before retrying.

    Rate limits (429) on free tiers are per minute, so short jittered backoff just burns
    retries. Prefer the server's hint: the ``Retry-After`` header, or Gemini's
    ``RetryInfo.retryDelay`` (e.g. "27s") in the error body.
    """
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(_MAX_WAIT_SECONDS, float(header))
        except ValueError:
            pass
    if response.status_code == 429:
        try:
            details = response.json().get("error", {}).get("details", [])
        except ValueError:
            details = []
        for detail in details:
            match = re.fullmatch(r"([\d.]+)s", str(detail.get("retryDelay", "")))
            if match:
                return min(_MAX_WAIT_SECONDS, float(match.group(1)) + 1)
        return min(_MAX_WAIT_SECONDS, 10.0 * 2.0**attempt)
    if response.status_code == 503:
        return min(30.0, 5.0 * 2.0**attempt) + random.uniform(0, 1)  # noqa: S311
    return random.uniform(0, 2.0**attempt)  # noqa: S311 - jitter, not cryptography


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    error_cls: type[AppError],
    provider: str,
    max_retries: int = 3,
    rate_limit_retries: int = 6,
    limiter: RateLimiter | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """POST with retries. 429s get more attempts (``rate_limit_retries``) because quota
    windows are about a minute long; other errors use ``max_retries``."""
    attempt = 0
    while True:
        if limiter is not None:
            await limiter.acquire()
        try:
            response = await client.post(url, **kwargs)
        except httpx.TransportError as exc:
            if attempt < max_retries:
                await asyncio.sleep(random.uniform(0, 2**attempt))  # noqa: S311
                attempt += 1
                continue
            raise error_cls(f"{provider}: network error ({type(exc).__name__})") from exc
        logger.info("%s POST %s -> %s", provider, url.split("?")[0], response.status_code)
        daily = _is_daily_quota(response) if response.status_code == 429 else None
        if daily:
            raise LLMQuotaExhaustedError(
                f"{provider}: daily quota exhausted ({daily}). It resets after Google's daily "
                "window; use another model (GEMINI_FALLBACK_MODELS) or enable billing.",
                details={"provider": provider, "quota_id": daily},
            )
        # 429 (rate limit) and 503 (model overloaded) are transient on Gemini: retry longer.
        budget = rate_limit_retries if response.status_code in (429, 503) else max_retries
        if response.status_code in _RETRYABLE and attempt < budget:
            delay = _retry_delay(response, attempt)
            logger.warning("%s: HTTP %s, retrying in %.0fs", provider, response.status_code, delay)
            await asyncio.sleep(delay)
            attempt += 1
            continue
        if response.is_error:
            message = f"{provider}: HTTP {response.status_code}"
            if response.status_code == 429:
                message = (
                    f"{provider}: rate limit / quota exceeded (HTTP 429). The free tier allows "
                    "only a few requests per minute; wait a minute and retry, or enable billing."
                )
            raise error_cls(message, details={"provider": provider, "body": response.text[:300]})
        return response
