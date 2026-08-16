from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ...core import targets as targets_svc
from ...core import valuation
from ...models import Instrument, Target
from ..deps import CurrentAccount, DbSession
from ..schemas import TargetIn, TargetOut

router = APIRouter(tags=["targets"])


@router.get("/targets", response_model=list[TargetOut])
def list_targets(account: CurrentAccount, session: DbSession) -> list[TargetOut]:
    report = valuation.value_portfolio(session, account.id, refresh=False)
    statuses = targets_svc.evaluate(session, account.id, report)
    return [TargetOut.build(s) for s in statuses]


@router.post("/targets", response_model=TargetOut, status_code=status.HTTP_201_CREATED)
def create_target(
    payload: TargetIn, account: CurrentAccount, session: DbSession
) -> TargetOut:
    if session.get(Instrument, payload.instrument_id) is None:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다")

    target = Target(
        account_id=account.id,
        instrument_id=payload.instrument_id,
        kind=payload.kind,
        value=payload.value,
        note=payload.note,
    )
    session.add(target)
    session.flush()

    report = valuation.value_portfolio(session, account.id, refresh=False)
    statuses = targets_svc.evaluate(session, account.id, report)
    status_of = next(s for s in statuses if s.target.id == target.id)
    return TargetOut.build(status_of)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(
    target_id: int, account: CurrentAccount, session: DbSession
) -> None:
    target = session.get(Target, target_id)
    if target is None or target.account_id != account.id:
        raise HTTPException(status_code=404, detail="목표를 찾을 수 없습니다")
    session.delete(target)


@router.get("/alerts")
def list_alerts(account: CurrentAccount, session: DbSession) -> list[dict]:
    alerts = targets_svc.unread_alerts(session, account.id)
    return [
        {
            "id": alert.id,
            "target_id": alert.target_id,
            "name_ko": alert.target.instrument.name_ko,
            "triggered_on": alert.triggered_on.isoformat(),
            "observed_value": float(alert.observed_value),
        }
        for alert in alerts
    ]
