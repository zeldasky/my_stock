"""일별 시세 수집 + 목표가 판정 스케줄러.

PC 가 꺼져 있어 며칠 건너뛰어도 문제없다.
자산추이는 거래 원장에서 소급 계산되므로, 다음 실행 때 빈 구간이 자동으로 메워진다.
"""

from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from ..config import settings
from ..core import targets as targets_svc
from ..core import valuation
from ..db import session_scope
from ..models import Account

logger = logging.getLogger(__name__)


def daily_job() -> None:
    with session_scope() as session:
        accounts = list(session.scalars(select(Account)))
        for account in accounts:
            try:
                end = dt.date.today()
                start = end - dt.timedelta(days=settings.quote_lookback_days)
                valuation.ensure_quotes(session, account.id, start, end)

                report = valuation.value_portfolio(session, account.id, refresh=False)
                statuses = targets_svc.evaluate(session, account.id, report)
                alerts = targets_svc.record_alerts(session, statuses, on=end)

                logger.info(
                    "[%s] 평가액 %s원, 알림 %d건",
                    account.name,
                    f"{int(report.market_value_krw):,}",
                    len(alerts),
                )
            except Exception:  # 한 계좌가 실패해도 나머지는 계속 돈다
                logger.exception("계좌 %s 일별 갱신 실패", account.name)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        daily_job,
        CronTrigger(hour=settings.scheduler_hour, minute=0),
        id="daily_quotes",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("스케줄러 시작: 매일 %02d:00 (%s)", settings.scheduler_hour, settings.timezone)
    return scheduler
