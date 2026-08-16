"""거래 원장 CRUD.

저장 후 해당 종목의 원장 전체를 다시 접어 정합성을 검증한다.
과거 날짜 거래를 나중에 끼워 넣어도(소급 입력) 매도 초과 같은 오류를 그 자리에서 잡기 위함이다.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Instrument, Transaction, TxType
from . import quotes
from .ledger import ONE, ZERO, LedgerError, compute_positions, load_transactions


def _resolve_fx_rate(
    session: Session,
    instrument: Instrument | None,
    traded_on: dt.date,
    fx_rate: Decimal | None,
) -> Decimal:
    """거래일 환율. 원화 종목은 1, 해외 종목은 그날 고시환율을 고정 저장한다."""
    if fx_rate is not None:
        return Decimal(fx_rate)
    if instrument is None or instrument.currency == settings.base_currency:
        return ONE
    return quotes.require_fx_on(session, traded_on)


def _validate(session: Session, account_id: int, instrument_id: int | None) -> None:
    if instrument_id is None:
        return
    session.flush()
    compute_positions(
        load_transactions(session, account_id, instrument_id=instrument_id)
    )  # 매도 초과 등은 여기서 LedgerError 로 터진다


def create(
    session: Session,
    *,
    account_id: int,
    instrument: Instrument | None,
    tx_type: TxType | str,
    traded_on: dt.date,
    quantity: Decimal = ZERO,
    price: Decimal = ZERO,
    fee: Decimal = ZERO,
    tax: Decimal = ZERO,
    fx_rate: Decimal | None = None,
    memo: str | None = None,
) -> Transaction:
    tx_type = TxType(tx_type) if not isinstance(tx_type, TxType) else tx_type

    tx = Transaction(
        account_id=account_id,
        instrument_id=instrument.id if instrument else None,
        tx_type=tx_type,
        traded_on=traded_on,
        quantity=Decimal(quantity),
        price=Decimal(price),
        currency=instrument.currency if instrument else settings.base_currency,
        fx_rate=_resolve_fx_rate(session, instrument, traded_on, fx_rate),
        fee=Decimal(fee),
        tax=Decimal(tax),
        memo=memo,
    )
    session.add(tx)
    _validate(session, account_id, tx.instrument_id)
    return tx


def get(session: Session, account_id: int, tx_id: int) -> Transaction | None:
    return session.scalar(
        select(Transaction).where(
            Transaction.id == tx_id, Transaction.account_id == account_id
        )
    )


def update(session: Session, tx: Transaction, **changes) -> Transaction:
    """환율을 명시하지 않은 채 거래일을 바꾸면 그 날짜 환율로 다시 잡는다."""
    date_changed = "traded_on" in changes and changes["traded_on"] != tx.traded_on

    for key, value in changes.items():
        if value is None and key in {"traded_on", "tx_type", "quantity", "price"}:
            continue
        setattr(tx, key, value)

    if date_changed and "fx_rate" not in changes:
        tx.fx_rate = _resolve_fx_rate(session, tx.instrument, tx.traded_on, None)

    _validate(session, tx.account_id, tx.instrument_id)
    return tx


def delete(session: Session, tx: Transaction) -> None:
    account_id, instrument_id = tx.account_id, tx.instrument_id
    session.delete(tx)
    _validate(session, account_id, instrument_id)


def history(
    session: Session,
    account_id: int,
    *,
    instrument_id: int | None = None,
    tx_type: TxType | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int | None = None,
) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .order_by(Transaction.traded_on.desc(), Transaction.id.desc())
    )
    if instrument_id is not None:
        stmt = stmt.where(Transaction.instrument_id == instrument_id)
    if tx_type is not None:
        stmt = stmt.where(Transaction.tx_type == tx_type)
    if start is not None:
        stmt = stmt.where(Transaction.traded_on >= start)
    if end is not None:
        stmt = stmt.where(Transaction.traded_on <= end)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


__all__ = [
    "LedgerError",
    "create",
    "delete",
    "get",
    "history",
    "update",
]
