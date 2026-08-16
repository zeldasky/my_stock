"""초기 계정 생성 + 기존 하드코딩 포트폴리오의 DB 이관.

기존 myStock.py 의 stock_list 에는 수량과 평균단가만 있고 매수일자가 없었다.
그래서 2024-01-02 를 '기초잔고 기준일'로 잡고 그날 평단가로 일괄 매수한 것으로 등록한다.
수량·평단가는 원본 그대로 보존되고, 해외 종목 환율만 그날(1,293.54원) 기준으로 통일된다.
실제 매수일을 알게 되면 웹 UI 에서 거래를 수정하면 원가와 자산추이가 자동 재계산된다.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, Market, Transaction, TxType, User
from . import instruments as instruments_svc
from . import transactions as tx_svc
from .security import hash_password

logger = logging.getLogger(__name__)

# 기초잔고 기준일. 이 날짜부터 자산추이 그래프가 그려진다.
LEGACY_OPENING_DATE = dt.date(2024, 1, 2)

# 원본: myStock.py 의 stock_list (en_name, 수량, 매수단가, 한글명, ...)
LEGACY_HOLDINGS: list[dict] = [
    {"krx_name": "SK하이닉스", "quantity": 65, "price": "131677"},
    {"krx_name": "삼성전자", "quantity": 150, "price": "71326"},
    {"symbol": "AAPL", "market": Market.NASDAQ, "name_ko": "애플",
     "name_en": "Apple Inc.", "quantity": 110, "price": "185"},
    {"symbol": "AMD", "market": Market.NASDAQ, "name_ko": "AMD",
     "name_en": "Advanced Micro Devices", "quantity": 32, "price": "183"},
    {"symbol": "GOOGL", "market": Market.NASDAQ, "name_ko": "구글",
     "name_en": "Alphabet Inc.", "quantity": 100, "price": "138"},
    {"symbol": "MSFT", "market": Market.NASDAQ, "name_ko": "마이크로소프트",
     "name_en": "Microsoft Corp.", "quantity": 56, "price": "326"},
]

DEFAULT_ACCOUNT_NAME = "기본계좌"


def ensure_user(
    session: Session, *, email: str, password: str, display_name: str
) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is not None:
        return user

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    session.add(user)
    session.flush()
    logger.info("사용자 생성: %s", email)
    return user


def ensure_account(
    session: Session, user: User, name: str = DEFAULT_ACCOUNT_NAME
) -> Account:
    account = session.scalar(
        select(Account).where(Account.user_id == user.id, Account.name == name)
    )
    if account is not None:
        return account

    account = Account(user_id=user.id, name=name)
    session.add(account)
    session.flush()
    logger.info("계좌 생성: %s", name)
    return account


def seed_legacy_portfolio(
    session: Session,
    account: Account,
    *,
    opening_date: dt.date = LEGACY_OPENING_DATE,
) -> list[Transaction]:
    """하드코딩 6종목을 기초잔고 매수 거래로 등록한다. 이미 있으면 건너뛴다."""
    already = session.scalar(
        select(Transaction.id).where(Transaction.account_id == account.id).limit(1)
    )
    if already is not None:
        logger.info("거래 내역이 이미 있어 기초잔고 적재를 건너뜁니다")
        return []

    created: list[Transaction] = []
    for row in LEGACY_HOLDINGS:
        if "krx_name" in row:
            instrument = instruments_svc.resolve_krx_by_name(session, row["krx_name"])
        else:
            instrument = instruments_svc.get_or_create(
                session,
                symbol=row["symbol"],
                market=row["market"],
                name_ko=row["name_ko"],
                name_en=row.get("name_en"),
                currency="USD",
            )

        tx = tx_svc.create(
            session,
            account_id=account.id,
            instrument=instrument,
            tx_type=TxType.BUY,
            traded_on=opening_date,
            quantity=Decimal(str(row["quantity"])),
            price=Decimal(row["price"]),
            memo="기초잔고 (기존 myStock.py 하드코딩 데이터 이관)",
        )
        created.append(tx)
        logger.info(
            "기초잔고: %s %s주 @ %s", instrument.name_ko, row["quantity"], row["price"]
        )

    return created
