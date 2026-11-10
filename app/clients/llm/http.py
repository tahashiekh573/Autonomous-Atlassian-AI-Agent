"""Retrying POST helper shared by LLM and speech provider clients."""

import asyncio
import logging
import random
from typing import Any

import httpx

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

_RETRYABLE = frozenset({429, 500, 502, 503, 504})


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    error_cls: type[AppError],
    provider: str,
    max_retries: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    for attempt in range(max_retries + 1):
        try:
            response = await client.post(url, **kwargs)
        except httpx.TransportError as exc:
            if attempt < max_retries:
                await asyncio.sleep(random.uniform(0, 2**attempt))  # noqa: S311
                continue
            raise error_cls(f"{provider}: network error ({type(exc).__name__})") from exc
        logger.info("%s POST %s -> %s", provider, url.split("?")[0], response.status_code)
        if response.status_code in _RETRYABLE and attempt < max_retries:
            await asyncio.sleep(random.uniform(0, 2**attempt))  # noqa: S311
            continue
        if response.is_error:
            raise error_cls(
                f"{provider}: HTTP {response.status_code}",
                details={"provider": provider, "body": response.text[:300]},
            )
        return response
    raise error_cls(f"{provider}: retries exhausted")  # pragma: no cover
