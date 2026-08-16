"""평가 계산 테스트 — 특히 환차손익 분리."""

from __future__ import annotations

from decimal import Decimal

from app.core.ledger import Position
from app.core.valuation import PortfolioValuation, PositionValuation

D = Decimal


def position(currency="USD", quantity="100", cost_local="10000", cost_krw="13000000"):
    return Position(
        instrument_id=1,
        symbol="AAPL",
        name_ko="애플",
        currency=currency,
        quantity=D(quantity),
        cost_local=D(cost_local),
        cost_krw=D(cost_krw),
    )


def test_fx_effect_splits_stock_gain_from_currency_gain():
    # $100 -> $120 (종목 +20%), 환율 1300 -> 1400
    item = PositionValuation(
        position=position(), price_local=D("120"), fx_rate=D("1400")
    )

    assert item.market_value_local == D("12000")
    assert item.market_value_krw == D("16800000")
    assert item.unrealized_krw == D("3800000")

    # 환율 기여분 = 원가 10000달러 x (1400 - 1300)
    assert item.fx_effect_krw == D("1000000")
    # 나머지는 순수 종목 상승분
    assert item.unrealized_krw - item.fx_effect_krw == item.unrealized_local * D("1400")

    assert item.return_pct_local == D("20")
    assert round(item.return_pct_krw, 4) == round(D("3800000") / D("13000000") * 100, 4)


def test_krw_stock_has_no_fx_effect():
    item = PositionValuation(
        position=position(currency="KRW", cost_local="1000000", cost_krw="1000000"),
        price_local=D("15000"),
        fx_rate=D("1"),
    )
    assert item.fx_effect_krw == D("0")
    assert item.return_pct_local == item.return_pct_krw


def test_weaker_won_at_purchase_produces_negative_fx_effect():
    # 1400 에 사서 지금 1300 이면 환율에서는 손해
    item = PositionValuation(
        position=position(cost_krw="14000000"), price_local=D("100"), fx_rate=D("1300")
    )
    assert item.position.avg_fx_rate == D("1400")
    assert item.fx_effect_krw == D("-1000000")
    assert item.unrealized_local == D("0")  # 종목은 본전인데
    assert item.unrealized_krw == D("-1000000")  # 원화로는 손실


def test_portfolio_totals_and_weights():
    a = PositionValuation(
        position=position(), price_local=D("120"), fx_rate=D("1400")
    )
    b = PositionValuation(
        position=position(currency="KRW", cost_local="1000000", cost_krw="1000000"),
        price_local=D("12000"),
        fx_rate=D("1"),
    )
    report = PortfolioValuation(as_of=None, fx_rate=D("1400"), positions=[a, b])

    assert report.cost_krw == D("14000000")
    assert report.market_value_krw == D("16800000") + D("1200000")
    assert report.unrealized_krw == report.market_value_krw - report.cost_krw
    assert report.fx_effect_krw == D("1000000")  # 원화 종목은 0 이므로 그대로
    assert round(report.weight_pct(a) + report.weight_pct(b), 6) == D("100")
