"""CLI. 기존 myStock.py 의 출력 포맷을 유지하면서 원장 기반 계산으로 바뀌었다."""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import logging
import os
import sys
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import bootstrap, valuation
from ..core.ledger import LedgerError
from ..core.quotes import QuoteError
from ..db import session_scope
from ..models import Account

LINE = "-" * 45


def _won(value: Decimal | int) -> str:
    rounded = Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(rounded):,}"


def _num(value: Decimal, places: int = 2) -> str:
    quantum = Decimal(1).scaleb(-places)
    return f"{Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP):,}"


def _pct(value: Decimal) -> str:
    return f"{Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def default_account(session: Session) -> Account:
    account = session.scalars(select(Account).order_by(Account.id)).first()
    if account is None:
        raise SystemExit(
            "계좌가 없습니다. 먼저 초기화하세요:\n"
            "  python -m app.cli init --email you@example.com"
        )
    return account


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #


def cmd_init(args: argparse.Namespace) -> int:
    password = args.password or os.environ.get("MY_STOCK_PASSWORD")
    if not password:
        password = getpass.getpass("웹 로그인에 쓸 비밀번호: ")
        if password != getpass.getpass("비밀번호 확인: "):
            raise SystemExit("비밀번호가 일치하지 않습니다")
    if len(password) < 8:
        raise SystemExit("비밀번호는 8자 이상이어야 합니다")

    with session_scope() as session:
        user = bootstrap.ensure_user(
            session,
            email=args.email,
            password=password,
            display_name=args.name,
        )
        account = bootstrap.ensure_account(session, user)

        if args.skip_seed:
            print(f"계정 준비 완료: {user.email} / {account.name}")
            return 0

        print("기존 하드코딩 포트폴리오를 기초잔고로 적재하는 중... (시세 조회 포함)")
        created = bootstrap.seed_legacy_portfolio(session, account)
        if not created:
            print("이미 거래 내역이 있어 적재를 건너뛰었습니다.")
        else:
            print(f"{len(created)}건 등록 완료 (기준일 {bootstrap.LEGACY_OPENING_DATE})")
            for tx in created:
                symbol = tx.instrument.symbol if tx.instrument else "-"
                print(
                    f"  {tx.instrument.name_ko:<10} {symbol:<8} "
                    f"{_num(tx.quantity, 0):>6}주 @ {_num(tx.price)} "
                    f"(환율 {_num(tx.fx_rate)})"
                )
    return 0


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #


def cmd_sync(args: argparse.Namespace) -> int:
    with session_scope() as session:
        account = default_account(session)
        end = dt.date.today()
        start = args.since or bootstrap.LEGACY_OPENING_DATE
        print(f"시세·환율 동기화: {start} ~ {end}")
        valuation.ensure_quotes(session, account.id, start, end, force=args.force)
        print("완료")
    return 0


# --------------------------------------------------------------------------- #
# report (기본 명령)
# --------------------------------------------------------------------------- #


def cmd_report(args: argparse.Namespace) -> int:
    with session_scope() as session:
        account = default_account(session)
        report = valuation.value_portfolio(
            session, account.id, refresh=not args.offline
        )

        if not report.positions:
            print("보유 종목이 없습니다.")
            return 0

        for item in report.positions:
            position = item.position
            unit = "원" if not item.is_foreign else "달러"
            places = 2 if item.is_foreign else 0
            current = _num(item.price_local, places)
            bought = _num(position.avg_price_local, places)
            print(f"{position.name_ko}(투자금액 : {_won(item.cost_krw)}원)")
            print(f"--> 현재가격 : {current}{unit} ,매수가격: {bought}{unit}")
            print(
                f"--> 수익률: {_pct(item.return_pct_krw)} -> "
                f"{_won(item.unrealized_krw)}원"
            )
            if item.is_foreign:
                print(
                    f"    (종목 {_pct(item.return_pct_local)} / "
                    f"환차손익 {_won(item.fx_effect_krw)}원, "
                    f"매입환율 {_num(position.avg_fx_rate)} → {_num(item.fx_rate)})"
                )
            print(f"    비중 {_pct(report.weight_pct(item))}\n")

        print(LINE)
        print(f"-------- {account.user.display_name} 주식 투자 내역 ---------")
        print(f"{LINE}\n")
        print(f"기준일 : {report.as_of}   적용환율 : {_num(report.fx_rate)}원\n")
        print("시드 : ")
        print(f"{_won(report.cost_krw):>20} 원")
        print("평가액 : ")
        print(f"{_won(report.market_value_krw):>20} 원")
        print("수익율 : ")
        print(f"{_won(report.unrealized_krw):>20} 원({_pct(report.return_pct):>7})")
        if report.fx_effect_krw:
            print("  환차손익 : ")
            print(f"{_won(report.fx_effect_krw):>20} 원")
        if report.realized_krw:
            print("  실현손익 : ")
            print(f"{_won(report.realized_krw):>20} 원")
        if report.dividend_krw:
            print("  배당금 : ")
            print(f"{_won(report.dividend_krw):>20} 원")
        print(f"\n{LINE}\n")
    return 0


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #


def cmd_history(args: argparse.Namespace) -> int:
    with session_scope() as session:
        account = default_account(session)
        end = dt.date.today()
        start = end - dt.timedelta(days=args.days)
        points = valuation.daily_history(
            session, account.id, start, end, refresh=not args.offline
        )
        if not points:
            print("거래 내역이 없습니다.")
            return 0

        print(f"{'날짜':<12}{'평가액':>16}{'평가손익':>16}{'수익률':>10}")
        print("-" * 54)
        step = max(1, len(points) // args.rows)
        sampled = points[::step]
        if sampled[-1] is not points[-1]:
            sampled.append(points[-1])  # 마지막 날은 항상 보여준다
        for point in sampled:
            print(
                f"{point.date!s:<12}"
                f"{_won(point.market_value_krw):>16}"
                f"{_won(point.unrealized_krw):>16}"
                f"{_pct(point.return_pct):>10}"
            )

        best = max(points, key=lambda p: p.market_value_krw)
        worst = min(points, key=lambda p: p.market_value_krw)
        print(f"\n최고 {_won(best.market_value_krw)}원 ({best.date})")
        print(f"최저 {_won(worst.market_value_krw)}원 ({worst.date})")
    return 0


# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="my_stock", description="주식 포트폴리오 관리 (거래 원장 기반)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="로그 출력")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="계정 생성 + 기존 포트폴리오 이관")
    p_init.add_argument("--email", required=True)
    p_init.add_argument("--name", default="상규", help="표시 이름")
    p_init.add_argument("--password", help="미지정 시 입력 프롬프트")
    p_init.add_argument("--skip-seed", action="store_true", help="기초잔고 적재 생략")
    p_init.set_defaults(func=cmd_init)

    p_sync = sub.add_parser("sync", help="시세·환율 캐시 갱신")
    p_sync.add_argument(
        "--since", type=dt.date.fromisoformat, help="YYYY-MM-DD (기본: 기초잔고 기준일)"
    )
    p_sync.add_argument("--force", action="store_true", help="구간을 지우고 다시 받는다")
    p_sync.set_defaults(func=cmd_sync)

    p_report = sub.add_parser("report", help="현재 수익 현황 (기본 명령)")
    p_report.add_argument("--offline", action="store_true", help="캐시된 시세만 사용")
    p_report.set_defaults(func=cmd_report)

    p_history = sub.add_parser("history", help="일별 자산추이")
    p_history.add_argument("--days", type=int, default=180)
    p_history.add_argument("--rows", type=int, default=20, help="출력 행 수")
    p_history.add_argument("--offline", action="store_true")
    p_history.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command is None:  # 인자 없이 실행하면 기존처럼 현황 출력
        args = parser.parse_args(["report"])
        args.verbose = False

    try:
        return args.func(args)
    except (QuoteError, LedgerError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
