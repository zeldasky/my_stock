"""API 입출력 스키마.

내부 계산은 전부 Decimal 이지만, 응답은 float 로 내보낸다.
차트 라이브러리가 문자열 숫자를 그대로 못 쓰기 때문이며,
금액 정확도는 DB·계산 계층에서 이미 보장된다.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ..core.ledger import Position
from ..core.targets import TargetStatus
from ..core.valuation import DailyPoint, PortfolioValuation, PositionValuation
from ..models import Market, TargetKind, Transaction, TxType


def f(value: Decimal | float | None) -> float:
    return float(value) if value is not None else 0.0


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    account_id: int
    account_name: str


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    market: Market
    name_ko: str
    name_en: str | None = None
    currency: str


class InstrumentSearchOut(BaseModel):
    symbol: str
    name_ko: str
    market: Market
    currency: str
    instrument_id: int | None = None


class PositionOut(BaseModel):
    instrument_id: int
    symbol: str
    name_ko: str
    currency: str
    is_foreign: bool

    quantity: float
    avg_price_local: float
    price_local: float
    avg_fx_rate: float
    fx_rate: float

    cost_krw: float
    market_value_krw: float
    unrealized_krw: float
    fx_effect_krw: float
    return_pct_local: float
    return_pct_krw: float
    weight_pct: float

    @classmethod
    def build(cls, item: PositionValuation, weight: Decimal) -> PositionOut:
        position = item.position
        return cls(
            instrument_id=position.instrument_id,
            symbol=position.symbol,
            name_ko=position.name_ko,
            currency=position.currency,
            is_foreign=item.is_foreign,
            quantity=f(position.quantity),
            avg_price_local=f(position.avg_price_local),
            price_local=f(item.price_local),
            avg_fx_rate=f(position.avg_fx_rate),
            fx_rate=f(item.fx_rate),
            cost_krw=f(item.cost_krw),
            market_value_krw=f(item.market_value_krw),
            unrealized_krw=f(item.unrealized_krw),
            fx_effect_krw=f(item.fx_effect_krw),
            return_pct_local=f(item.return_pct_local),
            return_pct_krw=f(item.return_pct_krw),
            weight_pct=f(weight),
        )


class ClosedPositionOut(BaseModel):
    instrument_id: int
    symbol: str
    name_ko: str
    realized_pnl_krw: float
    dividend_krw: float

    @classmethod
    def build(cls, position: Position) -> ClosedPositionOut:
        return cls(
            instrument_id=position.instrument_id,
            symbol=position.symbol,
            name_ko=position.name_ko,
            realized_pnl_krw=f(position.realized_pnl_krw),
            dividend_krw=f(position.dividend_krw),
        )


class PortfolioOut(BaseModel):
    as_of: dt.date
    fx_rate: float

    cost_krw: float
    market_value_krw: float
    unrealized_krw: float
    realized_krw: float
    dividend_krw: float
    fx_effect_krw: float
    total_pnl_krw: float
    return_pct: float

    positions: list[PositionOut]
    closed: list[ClosedPositionOut]

    @classmethod
    def build(cls, report: PortfolioValuation) -> PortfolioOut:
        return cls(
            as_of=report.as_of,
            fx_rate=f(report.fx_rate),
            cost_krw=f(report.cost_krw),
            market_value_krw=f(report.market_value_krw),
            unrealized_krw=f(report.unrealized_krw),
            realized_krw=f(report.realized_krw),
            dividend_krw=f(report.dividend_krw),
            fx_effect_krw=f(report.fx_effect_krw),
            total_pnl_krw=f(report.total_pnl_krw),
            return_pct=f(report.return_pct),
            positions=[
                PositionOut.build(item, report.weight_pct(item))
                for item in report.positions
            ],
            closed=[ClosedPositionOut.build(p) for p in report.closed],
        )


class HistoryPointOut(BaseModel):
    date: dt.date
    cost_krw: float
    market_value_krw: float
    unrealized_krw: float
    realized_krw: float
    fx_effect_krw: float
    return_pct: float

    @classmethod
    def build(cls, point: DailyPoint) -> HistoryPointOut:
        return cls(
            date=point.date,
            cost_krw=f(point.cost_krw),
            market_value_krw=f(point.market_value_krw),
            unrealized_krw=f(point.unrealized_krw),
            realized_krw=f(point.realized_krw),
            fx_effect_krw=f(point.fx_effect_krw),
            return_pct=f(point.return_pct),
        )


class TransactionIn(BaseModel):
    instrument_id: int | None = None
    # 아직 등록되지 않은 종목은 아래 3개로 즉석 등록한다.
    symbol: str | None = None
    market: Market | None = None
    name_ko: str | None = None

    tx_type: TxType
    traded_on: dt.date
    quantity: Decimal = Decimal("0")
    price: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    fx_rate: Decimal | None = Field(default=None, description="미지정 시 거래일 환율 자동 적용")
    memo: str | None = None


class TransactionPatch(BaseModel):
    traded_on: dt.date | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    fee: Decimal | None = None
    tax: Decimal | None = None
    fx_rate: Decimal | None = None
    memo: str | None = None


class TransactionOut(BaseModel):
    id: int
    instrument: InstrumentOut | None
    tx_type: TxType
    traded_on: dt.date
    quantity: float
    price: float
    currency: str
    fx_rate: float
    fee: float
    tax: float
    amount_krw: float
    memo: str | None

    @classmethod
    def build(cls, tx: Transaction) -> TransactionOut:
        return cls(
            id=tx.id,
            instrument=InstrumentOut.model_validate(tx.instrument)
            if tx.instrument
            else None,
            tx_type=TxType(tx.tx_type),
            traded_on=tx.traded_on,
            quantity=f(tx.quantity),
            price=f(tx.price),
            currency=tx.currency,
            fx_rate=f(tx.fx_rate),
            fee=f(tx.fee),
            tax=f(tx.tax),
            amount_krw=f(tx.quantity * tx.price * tx.fx_rate),
            memo=tx.memo,
        )


class TargetIn(BaseModel):
    instrument_id: int
    kind: TargetKind
    value: Decimal
    note: str | None = None


class TargetOut(BaseModel):
    id: int
    instrument_id: int
    name_ko: str
    kind: TargetKind
    label: str
    value: float
    observed: float | None
    is_hit: bool
    note: str | None
    is_active: bool

    @classmethod
    def build(cls, status: TargetStatus) -> TargetOut:
        target = status.target
        return cls(
            id=target.id,
            instrument_id=target.instrument_id,
            name_ko=target.instrument.name_ko,
            kind=TargetKind(target.kind),
            label=status.label,
            value=f(target.value),
            observed=f(status.observed) if status.observed is not None else None,
            is_hit=status.is_hit,
            note=target.note,
            is_active=target.is_active,
        )


class PricePointOut(BaseModel):
    date: dt.date
    close: float
