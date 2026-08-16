from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query, status

from ...core import instruments as instruments_svc
from ...core import transactions as tx_svc
from ...models import Instrument, Market, TxType
from ..deps import CurrentAccount, DbSession
from ..schemas import TransactionIn, TransactionOut, TransactionPatch

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _resolve_instrument(session, payload: TransactionIn) -> Instrument | None:
    if payload.instrument_id is not None:
        instrument = session.get(Instrument, payload.instrument_id)
        if instrument is None:
            raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다")
        return instrument

    if payload.tx_type in (TxType.DEPOSIT, TxType.WITHDRAW):
        return None

    if not (payload.symbol and payload.market and payload.name_ko):
        raise HTTPException(
            status_code=422,
            detail="instrument_id 또는 (symbol, market, name_ko) 가 필요합니다",
        )

    return instruments_svc.get_or_create(
        session,
        symbol=payload.symbol,
        market=payload.market,
        name_ko=payload.name_ko,
        currency="KRW" if payload.market == Market.KRX else "USD",
    )


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    account: CurrentAccount,
    session: DbSession,
    instrument_id: int | None = None,
    tx_type: TxType | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int = Query(200, ge=1, le=2000),
) -> list[TransactionOut]:
    rows = tx_svc.history(
        session,
        account.id,
        instrument_id=instrument_id,
        tx_type=tx_type,
        start=start,
        end=end,
        limit=limit,
    )
    return [TransactionOut.build(tx) for tx in rows]


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionIn, account: CurrentAccount, session: DbSession
) -> TransactionOut:
    instrument = _resolve_instrument(session, payload)
    tx = tx_svc.create(
        session,
        account_id=account.id,
        instrument=instrument,
        tx_type=payload.tx_type,
        traded_on=payload.traded_on,
        quantity=payload.quantity,
        price=payload.price,
        fee=payload.fee,
        tax=payload.tax,
        fx_rate=payload.fx_rate,
        memo=payload.memo,
    )
    session.flush()
    return TransactionOut.build(tx)


@router.patch("/{tx_id}", response_model=TransactionOut)
def update_transaction(
    tx_id: int, payload: TransactionPatch, account: CurrentAccount, session: DbSession
) -> TransactionOut:
    tx = tx_svc.get(session, account.id, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="거래를 찾을 수 없습니다")

    changes = payload.model_dump(exclude_unset=True)
    tx_svc.update(session, tx, **changes)
    session.flush()
    return TransactionOut.build(tx)


@router.delete("/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    tx_id: int, account: CurrentAccount, session: DbSession
) -> None:
    tx = tx_svc.get(session, account.id, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="거래를 찾을 수 없습니다")
    tx_svc.delete(session, tx)
