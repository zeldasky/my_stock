"""시세·환율 조회. FinanceDataReader 를 호출하는 유일한 지점이다.

가져온 값은 price_daily / fx_daily 에 캐시하므로,
과거 자산추이를 다시 계산할 때 네트워크를 타지 않는다.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from functools import lru_cache

import FinanceDataReader as fdr
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import FxDaily, Instrument, Market, PriceDaily

logger = logging.getLogger(__name__)

KRW = "KRW"


class QuoteError(RuntimeError):
    """시세를 확보하지 못했을 때."""


def _to_decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    return Decimal(str(float(value)))


def _fetch_close(symbol: str, start: dt.date, end: dt.date) -> dict[dt.date, Decimal]:
    """FDR 에서 [start, end] 종가를 읽어 {날짜: 종가} 로 돌려준다.

    FDR 은 소스마다 end 경계 처리가 다르다. 미국 주식은 end 가 배타적이라
    요청한 마지막 날 종가가 빠지고, 국내 주식·환율은 포함된다.
    그래서 하루 더 요청한 뒤 우리가 직접 end 까지로 잘라낸다.
    (이 처리가 없으면 해외 종목 현재가가 항상 하루씩 밀린다.)
    """
    try:
        df = fdr.DataReader(symbol, start, end + dt.timedelta(days=1))
    except Exception as exc:  # 네트워크·심볼 오류를 도메인 예외로 바꾼다
        raise QuoteError(f"{symbol} 시세 조회 실패: {exc}") from exc

    if df is None or df.empty or "Close" not in df.columns:
        return {}

    out: dict[dt.date, Decimal] = {}
    for index, close in df["Close"].items():
        day = pd.Timestamp(index).date()
        if day < start or day > end:
            continue
        value = _to_decimal(close)
        if value is None or value <= 0:
            continue
        out[day] = value
    return out


def _fetch_window(
    cached_min: dt.date | None,
    cached_max: dt.date | None,
    start: dt.date,
    end: dt.date,
) -> tuple[dt.date, dt.date] | None:
    """[start, end] 를 덮으려면 새로 받아야 할 구간. 받을 게 없으면 None.

    캐시는 [min, max] 한 덩어리로 유지한다. 중간에 빈 구간이 생기면 get_price_on 이
    몇 달 전 종가를 그날 종가로 돌려주는데, min/max 만 보면 덮인 것처럼 보여
    다시 받지도 않는다. 그래서 앞구간을 채울 때는 기존 캐시 첫날까지 이어서 받는다.
    """
    if cached_min is None:
        return start, end
    if start < cached_min:
        return start, max(end, cached_min)
    if end < cached_max:
        return None  # 이미 덮인 과거 구간
    return cached_max, end  # 꼬리만 이어받는다. 마지막 날은 장중 변동을 반영해 갱신


# --------------------------------------------------------------------------- #
# 주가
# --------------------------------------------------------------------------- #


def sync_prices(
    session: Session,
    instrument: Instrument,
    start: dt.date,
    end: dt.date,
    *,
    force: bool = False,
) -> int:
    """[start, end] 구간 종가를 캐시에 채운다. 새로 저장한 행 수를 반환."""
    if start > end:
        return 0

    if force:
        session.execute(
            delete(PriceDaily).where(
                PriceDaily.instrument_id == instrument.id,
                PriceDaily.date >= start,
                PriceDaily.date <= end,
            )
        )
        session.flush()
        cached_min = cached_max = None
    else:
        cached_min, cached_max = session.execute(
            select(func.min(PriceDaily.date), func.max(PriceDaily.date)).where(
                PriceDaily.instrument_id == instrument.id
            )
        ).one()

    window = _fetch_window(cached_min, cached_max, start, end)
    if window is None:
        return 0
    fetch_start, fetch_end = window

    fetched = _fetch_close(instrument.symbol, fetch_start, fetch_end)
    if not fetched:
        return 0

    existing = {
        row.date: row
        for row in session.scalars(
            select(PriceDaily).where(
                PriceDaily.instrument_id == instrument.id,
                PriceDaily.date >= fetch_start,
                PriceDaily.date <= fetch_end,
            )
        )
    }

    changed = 0
    for day, close in fetched.items():
        row = existing.get(day)
        if row is None:
            session.add(
                PriceDaily(instrument_id=instrument.id, date=day, close=close)
            )
            changed += 1
        elif row.close != close:
            row.close = close
            changed += 1

    session.flush()
    logger.info(
        "%s 시세 %d건 갱신 (%s ~ %s)", instrument.symbol, changed, fetch_start, fetch_end
    )
    return changed


def get_price_series(
    session: Session, instrument_id: int, start: dt.date, end: dt.date
) -> dict[dt.date, Decimal]:
    rows = session.execute(
        select(PriceDaily.date, PriceDaily.close).where(
            PriceDaily.instrument_id == instrument_id,
            PriceDaily.date >= start,
            PriceDaily.date <= end,
        )
    ).all()
    return {row.date: row.close for row in rows}


def get_price_on(
    session: Session, instrument_id: int, on: dt.date
) -> Decimal | None:
    """해당 날짜 이하의 가장 최근 종가. 휴장일·연휴를 자연스럽게 흡수한다."""
    return session.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.date <= on)
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )


# --------------------------------------------------------------------------- #
# 환율
# --------------------------------------------------------------------------- #


def sync_fx(
    session: Session,
    start: dt.date,
    end: dt.date,
    *,
    pair: str | None = None,
    force: bool = False,
) -> int:
    pair = pair or settings.fx_pair
    if start > end:
        return 0

    if force:
        session.execute(
            delete(FxDaily).where(
                FxDaily.pair == pair, FxDaily.date >= start, FxDaily.date <= end
            )
        )
        session.flush()
        cached_min = cached_max = None
    else:
        cached_min, cached_max = session.execute(
            select(func.min(FxDaily.date), func.max(FxDaily.date)).where(
                FxDaily.pair == pair
            )
        ).one()

    window = _fetch_window(cached_min, cached_max, start, end)
    if window is None:
        return 0
    fetch_start, fetch_end = window

    fetched = _fetch_close(pair, fetch_start, fetch_end)
    if not fetched:
        return 0

    existing = {
        row.date: row
        for row in session.scalars(
            select(FxDaily).where(
                FxDaily.pair == pair,
                FxDaily.date >= fetch_start,
                FxDaily.date <= fetch_end,
            )
        )
    }

    changed = 0
    for day, rate in fetched.items():
        row = existing.get(day)
        if row is None:
            session.add(FxDaily(pair=pair, date=day, rate=rate))
            changed += 1
        elif row.rate != rate:
            row.rate = rate
            changed += 1

    session.flush()
    logger.info("%s 환율 %d건 갱신 (%s ~ %s)", pair, changed, fetch_start, fetch_end)
    return changed


def get_fx_on(
    session: Session, on: dt.date, *, pair: str | None = None
) -> Decimal | None:
    pair = pair or settings.fx_pair
    return session.scalar(
        select(FxDaily.rate)
        .where(FxDaily.pair == pair, FxDaily.date <= on)
        .order_by(FxDaily.date.desc())
        .limit(1)
    )


def require_fx_on(session: Session, on: dt.date, *, pair: str | None = None) -> Decimal:
    """거래 입력 시점에 쓰는 환율. 캐시에 없으면 그 자리에서 받아온다."""
    pair = pair or settings.fx_pair
    rate = get_fx_on(session, on, pair=pair)
    if rate is not None:
        return rate

    lookback = on - dt.timedelta(days=settings.quote_lookback_days)
    sync_fx(session, lookback, on, pair=pair)
    rate = get_fx_on(session, on, pair=pair)
    if rate is None:
        raise QuoteError(f"{on} 기준 {pair} 환율을 구하지 못했습니다")
    return rate


def get_fx_series(
    session: Session, start: dt.date, end: dt.date, *, pair: str | None = None
) -> dict[dt.date, Decimal]:
    pair = pair or settings.fx_pair
    rows = session.execute(
        select(FxDaily.date, FxDaily.rate).where(
            FxDaily.pair == pair, FxDaily.date >= start, FxDaily.date <= end
        )
    ).all()
    return {row.date: row.rate for row in rows}


# --------------------------------------------------------------------------- #
# 종목 검색 (KRX 상장 목록)
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _krx_listing() -> pd.DataFrame:
    """KRX 전체 상장 목록. 기존 코드는 실행마다 두 번 받았지만 여기선 프로세스당 1회."""
    return fdr.StockListing("KRX")


def find_krx_code(name: str) -> str:
    """정확한 종목명 -> 종목코드."""
    listing = _krx_listing()
    hit = listing.loc[listing["Name"] == name]
    if hit.empty:
        raise QuoteError(f"KRX 에서 '{name}' 종목을 찾지 못했습니다")
    return str(hit["Code"].values[0])


def search_krx(query: str, limit: int = 20) -> list[dict[str, str]]:
    """웹 UI 종목 자동완성용. 종목명·코드 부분 일치."""
    listing = _krx_listing()
    query = query.strip()
    if not query:
        return []
    mask = listing["Name"].str.contains(query, case=False, na=False) | listing[
        "Code"
    ].str.startswith(query)
    rows = listing.loc[mask].head(limit)
    return [
        {
            "symbol": str(row.Code),
            "name_ko": str(row.Name),
            "market": Market.KRX.value,
            "currency": KRW,
        }
        for row in rows.itertuples()
    ]
