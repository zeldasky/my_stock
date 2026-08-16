"""목표가 / 손절가 / 목표수익률 판정.

평가 결과(PortfolioValuation)를 받아 판정하므로 시세를 다시 조회하지 않는다.
같은 목표가 같은 날 여러 번 울리지 않도록 alerts 에 (target, 날짜) 유니크로 기록한다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Target, TargetKind
from .valuation import PortfolioValuation, PositionValuation


@dataclass
class TargetStatus:
    target: Target
    position: PositionValuation | None
    observed: Decimal | None
    is_hit: bool

    @property
    def label(self) -> str:
        return {
            TargetKind.PRICE_ABOVE: "목표가 도달",
            TargetKind.PRICE_BELOW: "손절가 이탈",
            TargetKind.RETURN_ABOVE: "목표 수익률 도달",
            TargetKind.RETURN_BELOW: "손실률 도달",
        }[TargetKind(self.target.kind)]


def list_targets(session: Session, account_id: int, *, active_only: bool = True):
    stmt = select(Target).where(Target.account_id == account_id)
    if active_only:
        stmt = stmt.where(Target.is_active.is_(True))
    return list(session.scalars(stmt.order_by(Target.id)))


def evaluate(
    session: Session, account_id: int, report: PortfolioValuation
) -> list[TargetStatus]:
    by_instrument = {p.position.instrument_id: p for p in report.positions}
    statuses: list[TargetStatus] = []

    for target in list_targets(session, account_id):
        item = by_instrument.get(target.instrument_id)
        if item is None:
            statuses.append(TargetStatus(target, None, None, False))
            continue

        kind = TargetKind(target.kind)
        if kind in (TargetKind.PRICE_ABOVE, TargetKind.PRICE_BELOW):
            observed = item.price_local
        else:
            observed = item.return_pct_krw

        hit = (
            observed >= target.value
            if kind in (TargetKind.PRICE_ABOVE, TargetKind.RETURN_ABOVE)
            else observed <= target.value
        )
        statuses.append(TargetStatus(target, item, observed, hit))

    return statuses


def record_alerts(
    session: Session, statuses: list[TargetStatus], on: dt.date | None = None
) -> list[Alert]:
    """도달한 목표를 알림으로 남긴다. 같은 날 중복 기록은 건너뛴다."""
    on = on or dt.date.today()
    created: list[Alert] = []

    for status in statuses:
        if not status.is_hit or status.observed is None:
            continue
        exists = session.scalar(
            select(Alert.id).where(
                Alert.target_id == status.target.id, Alert.triggered_on == on
            )
        )
        if exists is not None:
            continue
        alert = Alert(
            target_id=status.target.id,
            triggered_on=on,
            observed_value=status.observed,
        )
        session.add(alert)
        created.append(alert)

    session.flush()
    return created


def unread_alerts(session: Session, account_id: int) -> list[Alert]:
    return list(
        session.scalars(
            select(Alert)
            .join(Target, Alert.target_id == Target.id)
            .where(Target.account_id == account_id, Alert.is_read.is_(False))
            .order_by(Alert.triggered_on.desc(), Alert.id.desc())
        )
    )
