"""포지션 + 시세 -> 평가액 / 수익률 / 일별 자산추이.

환차손익 분리 공식:
    환차손익 = cost_local x (현재환율 - 평균매입환율)
원가를 두 통화로 들고 있으면 이 한 줄로 "종목이 오른 몫"과 "환율이 오른 몫"이 갈린다.
원화 종목은 두 환율이 모두 1이라 자동으로 0이 된다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Instrument, Transaction
from . import quotes
from .ledger import ONE, ZERO, Position, iter_daily_positions, load_transactions

HUNDRED = Decimal("100")


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    return numerator / denominator * HUNDRED if denominator else ZERO


@dataclass
class PositionValuation:
    position: Position
    price_local: Decimal
    fx_rate: Decimal

    @property
    def quantity(self) -> Decimal:
        return self.position.quantity

    @property
    def market_value_local(self) -> Decimal:
        return self.position.quantity * self.price_local

    @property
    def market_value_krw(self) -> Decimal:
        return self.market_value_local * self.fx_rate

    @property
    def cost_local(self) -> Decimal:
        return self.position.cost_local

    @property
    def cost_krw(self) -> Decimal:
        return self.position.cost_krw

    @property
    def unrealized_local(self) -> Decimal:
        return self.market_value_local - self.cost_local

    @property
    def unrealized_krw(self) -> Decimal:
        return self.market_value_krw - self.cost_krw

    @property
    def fx_effect_krw(self) -> Decimal:
        """평가손익 중 환율 변동이 기여한 몫."""
        return self.cost_local * (self.fx_rate - self.position.avg_fx_rate)

    @property
    def return_pct_local(self) -> Decimal:
        """종목 자체 수익률 (환율 영향 제거)."""
        return _pct(self.unrealized_local, self.cost_local)

    @property
    def return_pct_krw(self) -> Decimal:
        """내 지갑 기준 수익률 (환율 포함)."""
        return _pct(self.unrealized_krw, self.cost_krw)

    @property
    def is_foreign(self) -> bool:
        return self.position.currency != settings.base_currency


@dataclass
class PortfolioValuation:
    as_of: dt.date
    fx_rate: Decimal
    positions: list[PositionValuation] = field(default_factory=list)
    closed: list[Position] = field(default_factory=list)

    @property
    def cost_krw(self) -> Decimal:
        return sum((p.cost_krw for p in self.positions), ZERO)

    @property
    def market_value_krw(self) -> Decimal:
        return sum((p.market_value_krw for p in self.positions), ZERO)

    @property
    def unrealized_krw(self) -> Decimal:
        return self.market_value_krw - self.cost_krw

    @property
    def fx_effect_krw(self) -> Decimal:
        return sum((p.fx_effect_krw for p in self.positions), ZERO)

    @property
    def realized_krw(self) -> Decimal:
        open_realized = sum((p.position.realized_pnl_krw for p in self.positions), ZERO)
        return open_realized + sum((p.realized_pnl_krw for p in self.closed), ZERO)

    @property
    def dividend_krw(self) -> Decimal:
        open_div = sum((p.position.dividend_krw for p in self.positions), ZERO)
        return open_div + sum((p.dividend_krw for p in self.closed), ZERO)

    @property
    def total_pnl_krw(self) -> Decimal:
        return self.unrealized_krw + self.realized_krw + self.dividend_krw

    @property
    def return_pct(self) -> Decimal:
        return _pct(self.unrealized_krw, self.cost_krw)

    def weight_pct(self, item: PositionValuation) -> Decimal:
        return _pct(item.market_value_krw, self.market_value_krw)


# --------------------------------------------------------------------------- #
# 시세 확보
# --------------------------------------------------------------------------- #


def instruments_of(session: Session, account_id: int) -> list[Instrument]:
    return list(
        session.scalars(
            select(Instrument)
            .join(Transaction, Transaction.instrument_id == Instrument.id)
            .where(Transaction.account_id == account_id)
            .distinct()
        )
    )


def ensure_quotes(
    session: Session,
    account_id: int,
    start: dt.date,
    end: dt.date,
    *,
    force: bool = False,
) -> None:
    """평가에 필요한 시세·환율을 캐시에 채운다."""
    lookback = start - dt.timedelta(days=settings.quote_lookback_days)
    quotes.sync_fx(session, lookback, end, force=force)
    for instrument in instruments_of(session, account_id):
        quotes.sync_prices(session, instrument, lookback, end, force=force)


# --------------------------------------------------------------------------- #
# 현재 평가
# --------------------------------------------------------------------------- #


def value_portfolio(
    session: Session,
    account_id: int,
    on: dt.date | None = None,
    *,
    refresh: bool = True,
) -> PortfolioValuation:
    on = on or dt.date.today()
    if refresh:
        ensure_quotes(session, account_id, on, on)

    fx_now = quotes.get_fx_on(session, on) or ONE
    positions = _positions_map(session, account_id, on)

    result = PortfolioValuation(as_of=on, fx_rate=fx_now)
    for position in positions.values():
        if not position.is_open:
            if position.realized_pnl_krw or position.dividend_krw:
                result.closed.append(position)
            continue

        price = quotes.get_price_on(session, position.instrument_id, on)
        if price is None:
            raise quotes.QuoteError(
                f"{position.name_ko}({position.symbol}) 의 {on} 이하 시세가 없습니다"
            )
        fx = ONE if position.currency == settings.base_currency else fx_now
        result.positions.append(
            PositionValuation(position=position, price_local=price, fx_rate=fx)
        )

    result.positions.sort(key=lambda p: p.market_value_krw, reverse=True)
    return result


def _positions_map(
    session: Session, account_id: int, on: dt.date
) -> dict[int, Position]:
    from .ledger import compute_positions

    return compute_positions(load_transactions(session, account_id, until=on))


# --------------------------------------------------------------------------- #
# 일별 자산추이
# --------------------------------------------------------------------------- #


@dataclass
class DailyPoint:
    date: dt.date
    cost_krw: Decimal
    market_value_krw: Decimal
    unrealized_krw: Decimal
    realized_krw: Decimal
    fx_effect_krw: Decimal

    @property
    def return_pct(self) -> Decimal:
        return _pct(self.unrealized_krw, self.cost_krw)


def _forward_fill(
    series: dict[dt.date, Decimal], start: dt.date, end: dt.date, seed: Decimal | None
) -> dict[dt.date, Decimal]:
    """휴장일을 직전 종가로 메운다. 주말에도 선이 끊기지 않게."""
    filled: dict[dt.date, Decimal] = {}
    last = seed
    day = start
    while day <= end:
        last = series.get(day, last)
        if last is not None:
            filled[day] = last
        day += dt.timedelta(days=1)
    return filled


def daily_history(
    session: Session,
    account_id: int,
    start: dt.date | None = None,
    end: dt.date | None = None,
    *,
    refresh: bool = True,
) -> list[DailyPoint]:
    """[start, end] 일별 자산추이. 거래 원장에서 소급 계산하므로 과거까지 그려진다."""
    transactions = load_transactions(session, account_id)
    if not transactions:
        return []

    start = start or transactions[0].traded_on
    end = end or dt.date.today()
    if start > end:
        return []

    if refresh:
        ensure_quotes(session, account_id, start, end)

    # 시세·환율을 한 번에 메모리로 올린 뒤 forward-fill 한다 (날짜마다 쿼리하지 않는다).
    lookback = start - dt.timedelta(days=settings.quote_lookback_days * 3)
    fx_filled = _forward_fill(
        quotes.get_fx_series(session, lookback, end),
        start,
        end,
        quotes.get_fx_on(session, start),
    )

    price_filled: dict[int, dict[dt.date, Decimal]] = {}
    for instrument in instruments_of(session, account_id):
        price_filled[instrument.id] = _forward_fill(
            quotes.get_price_series(session, instrument.id, lookback, end),
            start,
            end,
            quotes.get_price_on(session, instrument.id, start),
        )

    points: list[DailyPoint] = []
    for day, positions in iter_daily_positions(transactions, start, end):
        fx_now = fx_filled.get(day, ONE)
        cost = market = realized = fx_effect = ZERO

        for position in positions.values():
            realized += position.realized_pnl_krw
            if not position.is_open:
                continue
            price = price_filled.get(position.instrument_id, {}).get(day)
            if price is None:
                continue  # 상장 전이거나 시세 공백
            fx = ONE if position.currency == settings.base_currency else fx_now
            cost += position.cost_krw
            market += position.quantity * price * fx
            fx_effect += position.cost_local * (fx - position.avg_fx_rate)

        points.append(
            DailyPoint(
                date=day,
                cost_krw=cost,
                market_value_krw=market,
                unrealized_krw=market - cost,
                realized_krw=realized,
                fx_effect_krw=fx_effect,
            )
        )

    return points
