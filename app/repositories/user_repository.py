"""Persistence for users."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def get(self, user_id: str) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def list(self) -> Sequence[User]:
        return (await self._session.execute(select(User).order_by(User.created_at))).scalars().all()

    async def count(self) -> int:
        return int((await self._session.execute(select(func.count(User.id)))).scalar_one())

    async def save(self, user: User) -> User:
        await self._session.commit()
        await self._session.refresh(user)
        return user
