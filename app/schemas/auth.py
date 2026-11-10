"""Authentication and user-management contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Role = Literal["viewer", "operator", "admin"]
ROLE_RANK: dict[str, int] = {"viewer": 0, "operator": 1, "admin": 2}


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    role: Role
    display_name: str

    def has_role(self, role: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


class LoginRequest(BaseModel):
    email: str
    password: SecretStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type
    expires_at: datetime
    user: "UserRead"


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    display_name: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=12)
    role: Role = "viewer"


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: SecretStr | None = Field(default=None, min_length=12)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    role: Role
    is_active: bool = True
    created_at: datetime | None = None
