"""Credential and HTTP-policy value objects shared by all Atlassian clients."""

from dataclasses import dataclass, field

from pydantic import SecretStr


@dataclass(frozen=True)
class AtlassianCredentials:
    site_url: str  # e.g. https://acme.atlassian.net (no trailing slash)
    email: str
    api_token: SecretStr = field(repr=False)


@dataclass(frozen=True)
class HttpPolicy:
    timeout_seconds: float = 30.0
    max_retries: int = 4
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
