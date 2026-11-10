"""Login, current user and user administration."""

from fastapi import APIRouter, Request, status

from app.core.dependencies import AdminDep, AuthServiceDep, PrincipalDep
from app.core.exceptions import AuthenticationError
from app.schemas.auth import LoginRequest, TokenResponse, UserCreate, UserRead, UserUpdate
from app.services.login_throttle import LoginThrottle

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest, service: AuthServiceDep, request: Request) -> TokenResponse:
    throttle: LoginThrottle = request.app.state.login_throttle
    throttle.check(payload.email)
    try:
        result = await service.login(payload.email, payload.password.get_secret_value())
    except AuthenticationError:
        throttle.failed(payload.email)
        raise
    throttle.succeeded(payload.email)
    return result


@router.get("/auth/me", response_model=UserRead)
async def me(principal: PrincipalDep) -> UserRead:
    return UserRead(
        id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        role=principal.role,
    )


@router.get("/users", response_model=list[UserRead])
async def list_users(service: AuthServiceDep, _: AdminDep) -> list[UserRead]:
    return await service.list_users()


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, service: AuthServiceDep, _: AdminDep) -> UserRead:
    return await service.create_user(payload)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str, payload: UserUpdate, service: AuthServiceDep, _: AdminDep
) -> UserRead:
    return await service.update_user(user_id, payload)
