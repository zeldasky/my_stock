"""종목 마스터 조회 / 등록."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Instrument, Market
from . import quotes


def get_by_symbol(
    session: Session, symbol: str, market: Market | str
) -> Instrument | None:
    market = Market(market) if not isinstance(market, Market) else market
    return session.scalar(
        select(Instrument).where(
            Instrument.symbol == symbol, Instrument.market == market
        )
    )


def get_or_create(
    session: Session,
    *,
    symbol: str,
    market: Market | str,
    name_ko: str,
    currency: str,
    name_en: str | None = None,
) -> Instrument:
    market = Market(market) if not isinstance(market, Market) else market
    instrument = get_by_symbol(session, symbol, market)
    if instrument is not None:
        return instrument

    instrument = Instrument(
        symbol=symbol,
        market=market,
        name_ko=name_ko,
        name_en=name_en,
        currency=currency,
    )
    session.add(instrument)
    session.flush()
    return instrument


def resolve_krx_by_name(session: Session, name_ko: str) -> Instrument:
    """'SK하이닉스' 처럼 종목명으로 등록한다. 코드는 KRX 상장목록에서 찾는다."""
    existing = session.scalar(
        select(Instrument).where(
            Instrument.market == Market.KRX, Instrument.name_ko == name_ko
        )
    )
    if existing is not None:
        return existing

    code = quotes.find_krx_code(name_ko)
    return get_or_create(
        session,
        symbol=code,
        market=Market.KRX,
        name_ko=name_ko,
        currency="KRW",
    )


def list_active(session: Session) -> list[Instrument]:
    return list(
        session.scalars(
            select(Instrument)
            .where(Instrument.is_active.is_(True))
            .order_by(Instrument.market, Instrument.name_ko)
        )
    )
