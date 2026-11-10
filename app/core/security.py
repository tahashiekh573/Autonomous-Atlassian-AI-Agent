"""Credential encryption and API-key checks."""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core.exceptions import AuthenticationError, ConfigurationError


class CredentialCipher:
    """Encrypts secrets at rest with Fernet (AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key: SecretStr | None) -> None:
        self._fernet: Fernet | None = None
        if key is not None and key.get_secret_value():
            try:
                self._fernet = Fernet(key.get_secret_value().encode())
            except ValueError as exc:
                raise ConfigurationError(
                    "CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key."
                ) from exc

    def _require(self) -> Fernet:
        if self._fernet is None:
            raise ConfigurationError(
                "CREDENTIAL_ENCRYPTION_KEY is not set; refusing to store credentials unencrypted."
            )
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        return self._require().encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._require().decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ConfigurationError(
                "Stored credential cannot be decrypted; was CREDENTIAL_ENCRYPTION_KEY rotated?"
            ) from exc


def api_key_matches(provided: str | None, expected: SecretStr) -> bool:
    """Constant-time comparison of a presented API key."""
    if not provided:
        return False
    return secrets.compare_digest(provided.encode(), expected.get_secret_value().encode())


# --- Passwords --------------------------------------------------------------------------------

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return "$".join(
        [
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# --- Access tokens ----------------------------------------------------------------------------


class TokenService:
    """HS256 JWT access tokens."""

    def __init__(self, secret: SecretStr | None, ttl_minutes: int) -> None:
        self._secret = (
            secret.get_secret_value()
            if secret is not None and secret.get_secret_value()
            else secrets.token_urlsafe(48)  # dev fallback: tokens die with the process
        )
        self._ttl = timedelta(minutes=ttl_minutes)

    def issue(self, user_id: str, role: str) -> tuple[str, datetime]:
        expires = datetime.now(UTC) + self._ttl
        token = jwt.encode(
            {"sub": user_id, "role": role, "exp": expires, "iat": datetime.now(UTC)},
            self._secret,
            algorithm="HS256",
        )
        return token, expires

    def decode(self, token: str) -> dict[str, Any]:
        try:
            payload: dict[str, Any] = jwt.decode(token, self._secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid or expired access token.") from exc
        return payload
