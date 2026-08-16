from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ...core import instruments as instruments_svc
from ...core import quotes
from ...models import Instrument, Market
from ..deps import CurrentAccount, DbSession
from ..schemas import InstrumentOut, InstrumentSearchOut, PricePointOut

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
def list_instruments(account: CurrentAccount, session: DbSession):
    return [
        InstrumentOut.model_validate(i) for i in instruments_svc.list_active(session)
    ]


@router.get("/search", response_model=list[InstrumentSearchOut])
def search(
    account: CurrentAccount,
    session: DbSession,
    q: str = Query(min_length=1),
    limit: int = Query(15, ge=1, le=50),
) -> list[InstrumentSearchOut]:
    """이미 등록된 종목을 먼저, 그 다음 KRX 상장목록에서 찾는다."""
    registered = session.scalars(
        select(Instrument)
        .where(Instrument.symbol.ilike(f"{q}%") | Instrument.name_ko.contains(q))
        .limit(limit)
    ).all()

    results = [
        InstrumentSearchOut(
            symbol=i.symbol,
            name_ko=i.name_ko,
            market=Market(i.market),
            currency=i.currency,
            instrument_id=i.id,
        )
        for i in registered
    ]
    seen = {(r.symbol, r.market) for r in results}

    for row in quotes.search_krx(q, limit=limit):
        key = (row["symbol"], Market.KRX)
        if key in seen:
            continue
        results.append(InstrumentSearchOut(**row, instrument_id=None))
        if len(results) >= limit:
            break

    return results


@router.get("/{instrument_id}/prices", response_model=list[PricePointOut])
def prices(
    instrument_id: int,
    account: CurrentAccount,
    session: DbSession,
    days: int = Query(180, ge=7, le=3650),
    refresh: bool = Query(False),
) -> list[PricePointOut]:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다")

    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    if refresh:
        quotes.sync_prices(session, instrument, start, end)

    series = quotes.get_price_series(session, instrument_id, start, end)
    return [
        PricePointOut(date=day, close=float(close))
        for day, close in sorted(series.items())
    ]
