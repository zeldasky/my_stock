from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from ...core import valuation
from ..deps import CurrentAccount, DbSession
from ..schemas import HistoryPointOut, PortfolioOut

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioOut)
def get_portfolio(
    account: CurrentAccount,
    session: DbSession,
    refresh: bool = Query(True, description="false 면 캐시된 시세만 사용"),
) -> PortfolioOut:
    report = valuation.value_portfolio(session, account.id, refresh=refresh)
    return PortfolioOut.build(report)


@router.get("/history", response_model=list[HistoryPointOut])
def get_history(
    account: CurrentAccount,
    session: DbSession,
    days: int = Query(365, ge=7, le=3650),
    refresh: bool = Query(False),
) -> list[HistoryPointOut]:
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    points = valuation.daily_history(
        session, account.id, start, end, refresh=refresh
    )
    return [HistoryPointOut.build(p) for p in points]


@router.post("/sync")
def sync_quotes(
    account: CurrentAccount,
    session: DbSession,
    days: int = Query(30, ge=1, le=3650),
    force: bool = Query(False),
) -> dict[str, str]:
    end = dt.date.today()
    valuation.ensure_quotes(
        session, account.id, end - dt.timedelta(days=days), end, force=force
    )
    return {"status": "ok", "as_of": end.isoformat()}
