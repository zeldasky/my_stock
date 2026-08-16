from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from ...core.security import verify_password
from ...models import Account, User
from ..deps import SESSION_USER_KEY, CurrentUser, DbSession
from ..schemas import LoginRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(session, user: User) -> UserOut:
    account = session.scalars(
        select(Account).where(Account.user_id == user.id).order_by(Account.id)
    ).first()
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        account_id=account.id if account else 0,
        account_name=account.name if account else "",
    )


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, session: DbSession) -> UserOut:
    user = session.scalar(select(User).where(User.email == payload.email))
    # 이메일 존재 여부를 노출하지 않도록 같은 메시지를 쓴다.
    if user is None or not user.is_active or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다",
        )

    request.session[SESSION_USER_KEY] = user.id
    return _user_out(session, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> None:
    request.session.clear()


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser, session: DbSession) -> UserOut:
    return _user_out(session, user)
