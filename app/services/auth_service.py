"""Login, token validation and user management."""

import logging

from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.security import TokenService, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import Principal, TokenResponse, UserCreate, UserRead, UserUpdate
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

# Spent on unknown emails too, so response time does not reveal which accounts exist.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-password")


class AuthService:
    def __init__(self, users: UserRepository, tokens: TokenService, audit: AuditService) -> None:
        self._users = users
        self._tokens = tokens
        self._audit = audit

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self._users.get_by_email(email.strip().lower())
        valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
        if user is None or not valid or not user.is_active:
            await self._audit.record(
                action="auth.login",
                resource_type="user",
                resource_id=None,
                outcome="denied",
                details={"email": email.strip().lower()},
            )
            raise AuthenticationError("Invalid email or password.")
        token, expires = self._tokens.issue(user.id, user.role)
        await self._audit.record(
            action="auth.login", resource_type="user", resource_id=user.id, outcome="success"
        )
        return TokenResponse(
            access_token=token, expires_at=expires, user=UserRead.model_validate(user)
        )

    async def principal_from_token(self, token: str) -> Principal:
        payload = self._tokens.decode(token)
        user = await self._users.get(str(payload.get("sub")))
        if user is None or not user.is_active:
            raise AuthenticationError("User is inactive or no longer exists.")
        return Principal(
            user_id=user.id,
            email=user.email,
            role=user.role,  # type: ignore[arg-type]
            display_name=user.display_name,
        )

    async def create_user(self, data: UserCreate) -> UserRead:
        email = data.email.strip().lower()
        if await self._users.get_by_email(email):
            raise ConflictError(f"User {email} already exists.")
        user = await self._users.add(
            User(
                email=email,
                display_name=data.display_name,
                password_hash=hash_password(data.password.get_secret_value()),
                role=data.role,
            )
        )
        await self._audit.record(
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            outcome="success",
            details={"email": email, "role": data.role},
        )
        return UserRead.model_validate(user)

    async def update_user(self, user_id: str, data: UserUpdate) -> UserRead:
        user = await self._users.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found.")
        changes: dict[str, object] = {}
        if data.display_name is not None:
            user.display_name = changes["display_name"] = data.display_name
        if data.role is not None:
            user.role = changes["role"] = data.role
        if data.is_active is not None:
            user.is_active = changes["is_active"] = data.is_active
        if data.password is not None:
            user.password_hash = hash_password(data.password.get_secret_value())
            changes["password"] = "changed"  # noqa: S105 - audit marker
        await self._users.save(user)
        await self._audit.record(
            action="user.update",
            resource_type="user",
            resource_id=user_id,
            outcome="success",
            details=changes,
        )
        return UserRead.model_validate(user)

    async def list_users(self) -> list[UserRead]:
        return [UserRead.model_validate(u) for u in await self._users.list()]

    async def bootstrap_admin(self, email: str | None, password: str | None) -> None:
        """Create the first admin from configuration when no users exist yet."""
        if not email or not password or await self._users.count() > 0:
            return
        await self._users.add(
            User(
                email=email.strip().lower(),
                display_name="Administrator",
                password_hash=hash_password(password),
                role="admin",
            )
        )
        logger.info("Bootstrap admin user %s created.", email)
