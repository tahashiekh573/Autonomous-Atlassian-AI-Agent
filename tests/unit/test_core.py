import json
import logging

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.core.logging import _JsonFormatter, redact, request_id_ctx
from app.core.security import CredentialCipher, api_key_matches


def test_redact_masks_auth_headers_and_tokens() -> None:
    text = 'Authorization: Basic YWRhOnNlY3JldA== api_token="abc123" password=hunter2'
    out = redact(text)
    assert "YWRhOnNlY3JldA==" not in out
    assert "abc123" not in out
    assert "hunter2" not in out


def test_json_formatter_includes_request_id_and_redacts() -> None:
    token = request_id_ctx.set("req-12345678")
    try:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "api_key=topsecret", None, None)
        record.request_id = request_id_ctx.get()
        payload = json.loads(_JsonFormatter().format(record))
    finally:
        request_id_ctx.reset(token)
    assert payload["request_id"] == "req-12345678"
    assert "topsecret" not in payload["message"]


def test_cipher_roundtrip() -> None:
    cipher = CredentialCipher(SecretStr(Fernet.generate_key().decode()))
    encrypted = cipher.encrypt("my-token")
    assert encrypted != "my-token"
    assert cipher.decrypt(encrypted) == "my-token"


def test_cipher_without_key_refuses_to_encrypt() -> None:
    with pytest.raises(ConfigurationError):
        CredentialCipher(None).encrypt("x")


def test_cipher_with_invalid_key_fails_fast() -> None:
    with pytest.raises(ConfigurationError):
        CredentialCipher(SecretStr("not-a-fernet-key"))


def test_cipher_detects_rotated_key() -> None:
    old = CredentialCipher(SecretStr(Fernet.generate_key().decode()))
    new = CredentialCipher(SecretStr(Fernet.generate_key().decode()))
    with pytest.raises(ConfigurationError, match="rotated"):
        new.decrypt(old.encrypt("x"))


def test_api_key_matches() -> None:
    assert api_key_matches("abc", SecretStr("abc"))
    assert not api_key_matches("abd", SecretStr("abc"))
    assert not api_key_matches(None, SecretStr("abc"))


def test_production_requires_secrets() -> None:
    with pytest.raises(ValidationError, match="ADMIN_API_KEY"):
        Settings(_env_file=None, environment="production")  # type: ignore[call-arg]
