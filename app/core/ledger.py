"""거래 원장 -> 보유수량 / 평균단가 / 실현손익.

원가 계산법: 이동평균법.

원가를 두 통화로 동시에 추적하는 것이 핵심이다.
  - cost_local : 종목 통화 기준 (애플이면 달러) — 종목 자체를 잘 골랐는지
  - cost_krw   : 거래일 환율로 고정된 원화 기준 — 실제 내 지갑 기준

둘의 차이가 곧 환차손익이므로, 별도 계산 없이 "종목 수익"과 "환율 수익"이 갈린다.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Instrument, Transaction, TxType

ZERO = Decimal("0")
ONE = Decimal("1")


class LedgerError(ValueError):
    """원장 정합성이 깨졌을 때 (보유수량보다 많이 매도 등)."""


@dataclass
class Position:
    """특정 시점의 한 종목 상태. 전부 거래에서 파생된 값이다."""

    instrument_id: int
    symbol: str
    name_ko: str
    currency: str

    quantity: Decimal = ZERO
    cost_local: Decimal = ZERO  # 보유분의 종목통화 원가 (수수료 포함)
    cost_krw: Decimal = ZERO  # 보유분의 원화 원가 (거래일 환율 고정)

    realized_pnl_local: Decimal = ZERO
    realized_pnl_krw: Decimal = ZERO
    dividend_local: Decimal = ZERO
    dividend_krw: Decimal = ZERO

    first_traded_on: dt.date | None = None
    last_traded_on: dt.date | None = None

    @property
    def is_open(self) -> bool:
        return self.quantity > ZERO

    @property
    def avg_price_local(self) -> Decimal:
        return self.cost_local / self.quantity if self.quantity else ZERO

    @property
    def avg_price_krw(self) -> Decimal:
        return self.cost_krw / self.quantity if self.quantity else ZERO

    @property
    def avg_fx_rate(self) -> Decimal:
        """이 종목 원가에 녹아있는 평균 매입 환율."""
        return self.cost_krw / self.cost_local if self.cost_local else ONE


def _amount(tx: Transaction) -> Decimal:
    return tx.quantity * tx.price


def apply_transaction(position: Position, tx: Transaction) -> None:
    """거래 하나를 포지션에 반영한다 (in-place)."""
    fx = tx.fx_rate if tx.fx_rate and tx.fx_rate > ZERO else ONE

    if position.first_traded_on is None:
        position.first_traded_on = tx.traded_on
    position.last_traded_on = tx.traded_on

    if tx.tx_type == TxType.BUY:
        # 매수 부대비용은 원가에 포함한다 (실제 지출액 기준).
        gross_local = _amount(tx) + tx.fee + tax_of(tx)
        position.quantity += tx.quantity
        position.cost_local += gross_local
        position.cost_krw += gross_local * fx

    elif tx.tx_type == TxType.SELL:
        if tx.quantity > position.quantity:
            raise LedgerError(
                f"{position.symbol}: {tx.traded_on} 매도 {tx.quantity}주가 "
                f"보유 {position.quantity}주를 초과합니다"
            )
        # 이동평균 원가를 매도 수량만큼 덜어낸다.
        avg_local = position.avg_price_local
        avg_krw = position.avg_price_krw
        cost_out_local = avg_local * tx.quantity
        cost_out_krw = avg_krw * tx.quantity

        proceeds_local = _amount(tx) - tx.fee - tax_of(tx)
        proceeds_krw = proceeds_local * fx

        position.realized_pnl_local += proceeds_local - cost_out_local
        position.realized_pnl_krw += proceeds_krw - cost_out_krw

        position.quantity -= tx.quantity
        position.cost_local -= cost_out_local
        position.cost_krw -= cost_out_krw

        if position.quantity == ZERO:
            # 나눗셈 잔여를 남기지 않는다.
            position.cost_local = ZERO
            position.cost_krw = ZERO

    elif tx.tx_type == TxType.DIVIDEND:
        # quantity 를 넣으면 주당 배당금 x 주수, 비우면 price 를 총액으로 본다.
        gross_local = _amount(tx) if tx.quantity else tx.price
        net_local = gross_local - tx.fee - tax_of(tx)
        position.dividend_local += net_local
        position.dividend_krw += net_local * fx

    elif tx.tx_type == TxType.SPLIT:
        # price 에 분할 비율을 넣는다 (2 = 1주 -> 2주). 원가 총액은 그대로라 평단가만 내려간다.
        ratio = tx.price
        if ratio <= ZERO:
            raise LedgerError(f"{position.symbol}: 액면분할 비율이 잘못되었습니다 ({ratio})")
        position.quantity *= ratio

    # DEPOSIT / WITHDRAW 는 1단계에서 포지션에 영향을 주지 않는다.


def tax_of(tx: Transaction) -> Decimal:
    return tx.tax or ZERO


def _new_position(instrument: Instrument) -> Position:
    return Position(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        name_ko=instrument.name_ko,
        currency=instrument.currency,
    )


def compute_positions(transactions: Iterable[Transaction]) -> dict[int, Position]:
    """거래 목록 전체를 접어 종목별 최종 포지션을 만든다.

    거래는 (거래일, id) 오름차순으로 들어와야 한다.
    """
    positions: dict[int, Position] = {}
    for tx in transactions:
        if tx.instrument_id is None or tx.instrument is None:
            continue  # 예수금 거래
        position = positions.get(tx.instrument_id)
        if position is None:
            position = positions[tx.instrument_id] = _new_position(tx.instrument)
        apply_transaction(position, tx)
    return positions


def load_transactions(
    session: Session,
    account_id: int,
    *,
    until: dt.date | None = None,
    instrument_id: int | None = None,
) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .order_by(Transaction.traded_on, Transaction.id)
    )
    if until is not None:
        stmt = stmt.where(Transaction.traded_on <= until)
    if instrument_id is not None:
        stmt = stmt.where(Transaction.instrument_id == instrument_id)
    return list(session.scalars(stmt))


def positions_as_of(
    session: Session, account_id: int, on: dt.date | None = None
) -> dict[int, Position]:
    """해당 날짜 장 마감 시점의 포지션."""
    return compute_positions(load_transactions(session, account_id, until=on))


def iter_daily_positions(
    transactions: Iterable[Transaction], start: dt.date, end: dt.date
) -> Iterator[tuple[dt.date, dict[int, Position]]]:
    """[start, end] 각 날짜의 장 마감 포지션을 순서대로 흘려보낸다.

    자산추이 그래프용. 거래를 한 번만 훑으므로 기간이 길어도 O(거래수 + 일수).
    """
    ordered = list(transactions)
    positions: dict[int, Position] = {}
    cursor = 0

    # start 이전 거래를 먼저 접어 기초 포지션을 만든다.
    while cursor < len(ordered) and ordered[cursor].traded_on < start:
        tx = ordered[cursor]
        cursor += 1
        if tx.instrument_id is None or tx.instrument is None:
            continue
        position = positions.get(tx.instrument_id)
        if position is None:
            position = positions[tx.instrument_id] = _new_position(tx.instrument)
        apply_transaction(position, tx)

    day = start
    while day <= end:
        while cursor < len(ordered) and ordered[cursor].traded_on == day:
            tx = ordered[cursor]
            cursor += 1
            if tx.instrument_id is None or tx.instrument is None:
                continue
            position = positions.get(tx.instrument_id)
            if position is None:
                position = positions[tx.instrument_id] = _new_position(tx.instrument)
            apply_transaction(position, tx)

        yield day, {pid: replace(p) for pid, p in positions.items()}
        day += dt.timedelta(days=1)
