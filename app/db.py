"""DB 엔진 / 세션 / Base."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# SQLite는 Decimal을 네이티브 타입으로 저장하지 못해 SQLAlchemy가 경고를 낸다.
# 우리가 쓰는 자릿수(수량·가격 소수 8자리)는 float64로 손실 없이 표현되고,
# Postgres로 옮기면 사라지는 경고라 여기서 눌러둔다.
warnings.filterwarnings(
    "ignore", r".*does \*not\* support Decimal objects natively.*", SAWarning
)

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


@contextmanager
def session_scope() -> Iterator[Session]:
    """CLI·스크립트용 트랜잭션 컨텍스트."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI 의존성."""
    with session_scope() as session:
        yield session
