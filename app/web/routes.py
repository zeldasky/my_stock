"""웹 페이지. 서버 렌더 + 폼 POST 방식이라 JS 없이도 전 기능이 동작한다."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from ..api.deps import SESSION_USER_KEY, DbSession, optional_user
from ..config import BASE_DIR
from ..core import instruments as instruments_svc
from ..core import quotes, valuation
from ..core import targets as targets_svc
from ..core import transactions as tx_svc
from ..core.ledger import LedgerError
from ..core.quotes import QuoteError
from ..core.security import verify_password
from ..models import (
    Account,
    Instrument,
    Market,
    Target,
    TargetKind,
    Transaction,
    TxType,
    User,
)
from .charts import build_chart, format_krw_short

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "web" / "templates"))

PERIODS = [(90, "3개월"), (365, "1년"), (1095, "3년"), (3650, "전체")]


# --------------------------------------------------------------------------- #
# 템플릿 필터
# --------------------------------------------------------------------------- #


def _won(value) -> str:
    return f"{round(float(value)):,}"


def _num(value, places: int = 2) -> str:
    return f"{float(value):,.{places}f}"


def _pct(value) -> str:
    return f"{float(value):+,.1f}%"


def _sign(value) -> str:
    """한국 관례: 상승 빨강 / 하락 파랑."""
    number = float(value)
    return "up" if number > 0 else ("down" if number < 0 else "flat")


templates.env.filters["won"] = _won
templates.env.filters["num"] = _num
templates.env.filters["pct"] = _pct
templates.env.filters["sign"] = _sign
templates.env.filters["short"] = format_krw_short


def _decimal(value: str | None, default: str = "0") -> Decimal:
    text = (value or "").strip().replace(",", "")
    if not text:
        text = default
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise LedgerError(f"숫자 형식이 올바르지 않습니다: {value}") from exc


def _redirect(url: str, message: str | None = None, error: str | None = None):
    if message:
        url += ("&" if "?" in url else "?") + f"msg={message}"
    if error:
        url += ("&" if "?" in url else "?") + f"err={error}"
    return RedirectResponse(url, status_code=303)


# --------------------------------------------------------------------------- #
# 인증
# --------------------------------------------------------------------------- #


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    session: DbSession,
    email: str = Form(...),
    password: str = Form(...),
):
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(
        password, user.password_hash
    ):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "이메일 또는 비밀번호가 올바르지 않습니다"},
            status_code=401,
        )
    request.session[SESSION_USER_KEY] = user.id
    return _redirect("/")


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return _redirect("/login")


def require_account(request: Request, session: DbSession) -> Account | None:
    user = optional_user(request, session)
    if user is None:
        return None
    return session.scalars(
        select(Account).where(Account.user_id == user.id).order_by(Account.id)
    ).first()


# --------------------------------------------------------------------------- #
# 대시보드
# --------------------------------------------------------------------------- #


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    session: DbSession,
    days: int = 365,
    refresh: int = 0,
    msg: str | None = None,
    err: str | None = None,
):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    try:
        report = valuation.value_portfolio(session, account.id, refresh=bool(refresh))
    except QuoteError as exc:
        report = None
        err = err or str(exc)

    history = []
    chart = build_chart([])
    if report is not None:
        end = dt.date.today()
        history = valuation.daily_history(
            session, account.id, end - dt.timedelta(days=days), end, refresh=False
        )
        chart = build_chart(history)

    statuses = (
        targets_svc.evaluate(session, account.id, report) if report is not None else []
    )
    hits = [s for s in statuses if s.is_hit]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "account": account,
            "report": report,
            "chart": chart,
            "history": history,
            "days": days,
            "hits": hits,
            "msg": msg,
            "err": err,
            "periods": PERIODS,
            "period_base": "/?",
            "refresh_url": f"/?days={days}&refresh=1",
            "price_label": "현재가",
        },
    )


# --------------------------------------------------------------------------- #
# 예상 평가액 — 고른 날짜 기준 평가. 대시보드와 같은 화면을 그날 종가로 그린다.
# --------------------------------------------------------------------------- #


@router.get("/valuation", response_class=HTMLResponse)
def valuation_page(
    request: Request,
    session: DbSession,
    on: str | None = None,
    days: int = 365,
):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    today = dt.date.today()
    first_day = session.scalar(
        select(func.min(Transaction.traded_on)).where(
            Transaction.account_id == account.id
        )
    )

    err = None
    try:
        day = dt.date.fromisoformat(on) if on else today
    except ValueError:
        day, err = today, f"날짜 형식이 올바르지 않습니다: {on}"
    day = min(day, today)
    if first_day is not None:
        day = max(day, first_day)

    # 오늘은 대시보드처럼 캐시만 쓴다. 지난 날짜는 캐시에 없는 구간만 받아온다.
    refresh = day < today
    report = None
    history = []
    try:
        report = valuation.value_portfolio(session, account.id, day, refresh=refresh)
        start = day - dt.timedelta(days=days)
        if first_day is not None:
            start = max(start, first_day)
        history = valuation.daily_history(session, account.id, start, day, refresh=refresh)
    except QuoteError as exc:
        err = err or str(exc)

    return templates.TemplateResponse(
        request,
        "valuation.html",
        {
            "account": account,
            "report": report,
            "chart": build_chart(history),
            "history": history,
            "days": days,
            "on": day.isoformat(),
            "today": today.isoformat(),
            "first_day": first_day.isoformat() if first_day else "",
            "err": err,
            "periods": PERIODS,
            "period_base": f"/valuation?on={day.isoformat()}&",
            "refresh_url": None,
            "price_label": "종가",
        },
    )


# --------------------------------------------------------------------------- #
# 거래 내역
# --------------------------------------------------------------------------- #


@router.get("/transactions", response_class=HTMLResponse)
def transactions_page(
    request: Request,
    session: DbSession,
    instrument_id: int | None = None,
    msg: str | None = None,
    err: str | None = None,
):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    rows = tx_svc.history(session, account.id, instrument_id=instrument_id, limit=500)
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "account": account,
            "transactions": rows,
            "instruments": instruments_svc.list_active(session),
            "instrument_id": instrument_id,
            "today": dt.date.today().isoformat(),
            "tx_types": [
                (TxType.BUY.value, "매수"),
                (TxType.SELL.value, "매도"),
                (TxType.DIVIDEND.value, "배당"),
                (TxType.SPLIT.value, "액면분할"),
            ],
            "markets": [m.value for m in Market],
            "msg": msg,
            "err": err,
        },
    )


@router.post("/transactions")
def transaction_create(
    request: Request,
    session: DbSession,
    tx_type: str = Form(...),
    traded_on: str = Form(...),
    instrument_id: str = Form(""),
    new_symbol: str = Form(""),
    new_market: str = Form(Market.KRX.value),
    new_name: str = Form(""),
    quantity: str = Form("0"),
    price: str = Form("0"),
    fee: str = Form("0"),
    tax: str = Form("0"),
    fx_rate: str = Form(""),
    memo: str = Form(""),
):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    try:
        if instrument_id.strip():
            instrument = session.get(Instrument, int(instrument_id))
        elif new_symbol.strip():
            market = Market(new_market)
            instrument = instruments_svc.get_or_create(
                session,
                symbol=new_symbol.strip().upper()
                if market != Market.KRX
                else new_symbol.strip(),
                market=market,
                name_ko=new_name.strip() or new_symbol.strip(),
                currency="KRW" if market == Market.KRX else "USD",
            )
        else:
            return _redirect("/transactions", err="종목을 선택하거나 새로 입력하세요")

        if instrument is None:
            return _redirect("/transactions", err="종목을 찾을 수 없습니다")

        tx_svc.create(
            session,
            account_id=account.id,
            instrument=instrument,
            tx_type=TxType(tx_type),
            traded_on=dt.date.fromisoformat(traded_on),
            quantity=_decimal(quantity),
            price=_decimal(price),
            fee=_decimal(fee),
            tax=_decimal(tax),
            fx_rate=_decimal(fx_rate) if fx_rate.strip() else None,
            memo=memo.strip() or None,
        )
    except (LedgerError, QuoteError, ValueError) as exc:
        return _redirect("/transactions", err=str(exc))

    return _redirect("/transactions", message="거래를 등록했습니다")


@router.post("/transactions/{tx_id}/delete")
def transaction_delete(tx_id: int, request: Request, session: DbSession):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    tx = tx_svc.get(session, account.id, tx_id)
    if tx is None:
        return _redirect("/transactions", err="거래를 찾을 수 없습니다")
    try:
        tx_svc.delete(session, tx)
    except LedgerError as exc:
        return _redirect("/transactions", err=str(exc))
    return _redirect("/transactions", message="거래를 삭제했습니다")


# --------------------------------------------------------------------------- #
# 종목 상세
# --------------------------------------------------------------------------- #


@router.get("/stocks/{instrument_id}", response_class=HTMLResponse)
def instrument_page(
    instrument_id: int, request: Request, session: DbSession, days: int = 365
):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        return _redirect("/", err="종목을 찾을 수 없습니다")

    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    series = sorted(quotes.get_price_series(session, instrument_id, start, end).items())

    # 주가 차트도 자산추이와 같은 좌표 계산기를 쓴다.
    class _P:
        def __init__(self, day, close):
            self.date = day
            self.market_value_krw = close
            self.cost_krw = close
            self.return_pct = Decimal("0")

    chart = build_chart([_P(day, close) for day, close in series])

    report = valuation.value_portfolio(session, account.id, refresh=False)
    item = next(
        (p for p in report.positions if p.position.instrument_id == instrument_id), None
    )
    rows = tx_svc.history(session, account.id, instrument_id=instrument_id)

    return templates.TemplateResponse(
        request,
        "instrument.html",
        {
            "account": account,
            "instrument": instrument,
            "item": item,
            "chart": chart,
            "transactions": rows,
            "days": days,
            "periods": [(90, "3개월"), (365, "1년"), (1095, "3년"), (3650, "전체")],
        },
    )


# --------------------------------------------------------------------------- #
# 목표
# --------------------------------------------------------------------------- #


@router.get("/targets", response_class=HTMLResponse)
def targets_page(
    request: Request,
    session: DbSession,
    msg: str | None = None,
    err: str | None = None,
):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    report = valuation.value_portfolio(session, account.id, refresh=False)
    statuses = targets_svc.evaluate(session, account.id, report)

    return templates.TemplateResponse(
        request,
        "targets.html",
        {
            "account": account,
            "statuses": statuses,
            "positions": report.positions,
            "kinds": [
                (TargetKind.PRICE_ABOVE.value, "목표가 이상"),
                (TargetKind.PRICE_BELOW.value, "손절가 이하"),
                (TargetKind.RETURN_ABOVE.value, "수익률 % 이상"),
                (TargetKind.RETURN_BELOW.value, "수익률 % 이하"),
            ],
            "msg": msg,
            "err": err,
        },
    )


@router.post("/targets")
def target_create(
    request: Request,
    session: DbSession,
    instrument_id: int = Form(...),
    kind: str = Form(...),
    value: str = Form(...),
    note: str = Form(""),
):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    try:
        session.add(
            Target(
                account_id=account.id,
                instrument_id=instrument_id,
                kind=TargetKind(kind),
                value=_decimal(value),
                note=note.strip() or None,
            )
        )
        session.flush()
    except (LedgerError, ValueError) as exc:
        return _redirect("/targets", err=str(exc))
    return _redirect("/targets", message="목표를 등록했습니다")


@router.post("/targets/{target_id}/delete")
def target_delete(target_id: int, request: Request, session: DbSession):
    account = require_account(request, session)
    if account is None:
        return _redirect("/login")

    target = session.get(Target, target_id)
    if target is None or target.account_id != account.id:
        return _redirect("/targets", err="목표를 찾을 수 없습니다")
    session.delete(target)
    return _redirect("/targets", message="목표를 삭제했습니다")
