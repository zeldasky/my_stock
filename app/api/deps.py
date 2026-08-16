"""FastAPI 의존성: DB 세션 / 로그인 사용자 / 기본 계좌."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Account, User

SESSION_USER_KEY = "user_id"


def db(session: Session = Depends(get_session)) -> Session:
    return session


DbSession = Annotated[Session, Depends(db)]


def current_user(request: Request, session: DbSession) -> User:
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다"
        )
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다"
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def current_account(user: CurrentUser, session: DbSession) -> Account:
    account = session.scalars(
        select(Account).where(Account.user_id == user.id).order_by(Account.id)
    ).first()
    if account is None:
        raise HTTPException(status_code=404, detail="계좌가 없습니다")
    return account


CurrentAccount = Annotated[Account, Depends(current_account)]


def optional_user(request: Request, session: DbSession) -> User | None:
    """웹 페이지용 — 비로그인이면 예외 대신 None."""
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    return session.get(User, user_id)


OptionalUser = Annotated["User | None", Depends(optional_user)]
