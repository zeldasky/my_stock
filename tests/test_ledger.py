"""이동평균 원장 엔진 테스트. 네트워크 없이 순수 계산만 검증한다."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.core.ledger import LedgerError, compute_positions
from app.models import Instrument, Market, Transaction, TxType

D = Decimal


def krw_stock() -> Instrument:
    inst = Instrument(
        symbol="005930", market=Market.KRX, name_ko="삼성전자", currency="KRW"
    )
    inst.id = 1
    return inst


def usd_stock() -> Instrument:
    inst = Instrument(
        symbol="AAPL", market=Market.NASDAQ, name_ko="애플", currency="USD"
    )
    inst.id = 2
    return inst


def tx(
    instrument: Instrument,
    tx_type: TxType,
    day: str,
    quantity="0",
    price="0",
    fx_rate="1",
    fee="0",
    tax="0",
) -> Transaction:
    row = Transaction(
        account_id=1,
        instrument_id=instrument.id,
        tx_type=tx_type,
        traded_on=dt.date.fromisoformat(day),
        quantity=D(quantity),
        price=D(price),
        currency=instrument.currency,
        fx_rate=D(fx_rate),
        fee=D(fee),
        tax=D(tax),
    )
    row.instrument = instrument
    return row


def only(positions):
    assert len(positions) == 1
    return next(iter(positions.values()))


def test_moving_average_across_buys():
    stock = krw_stock()
    position = only(
        compute_positions(
            [
                tx(stock, TxType.BUY, "2024-01-02", "10", "1000"),
                tx(stock, TxType.BUY, "2024-02-02", "10", "2000"),
            ]
        )
    )
    assert position.quantity == D("20")
    assert position.cost_local == D("30000")
    assert position.avg_price_local == D("1500")


def test_buy_fee_is_included_in_cost():
    stock = krw_stock()
    position = only(
        compute_positions([tx(stock, TxType.BUY, "2024-01-02", "10", "1000", fee="100")])
    )
    assert position.cost_local == D("10100")
    assert position.avg_price_local == D("1010")


def test_partial_sell_realizes_pnl_and_keeps_average():
    stock = krw_stock()
    position = only(
        compute_positions(
            [
                tx(stock, TxType.BUY, "2024-01-02", "10", "1000"),
                tx(stock, TxType.BUY, "2024-02-02", "10", "2000"),
                tx(stock, TxType.SELL, "2024-03-02", "5", "3000"),
            ]
        )
    )
    # 평단 1500 에서 5주를 3000 에 팔았으므로 (3000-1500)*5 = 7500
    assert position.realized_pnl_local == D("7500")
    assert position.quantity == D("15")
    assert position.avg_price_local == D("1500")  # 이동평균은 매도로 변하지 않는다
    assert position.cost_local == D("22500")


def test_full_sell_zeroes_cost_exactly():
    stock = krw_stock()
    position = only(
        compute_positions(
            [
                tx(stock, TxType.BUY, "2024-01-02", "3", "1000"),
                tx(stock, TxType.SELL, "2024-03-02", "3", "1500"),
            ]
        )
    )
    assert position.quantity == D("0")
    assert position.cost_local == D("0")  # 나눗셈 잔여가 남지 않아야 한다
    assert position.cost_krw == D("0")
    assert position.realized_pnl_local == D("1500")
    assert not position.is_open


def test_rebuy_after_full_sell_resets_average():
    stock = krw_stock()
    position = only(
        compute_positions(
            [
                tx(stock, TxType.BUY, "2024-01-02", "10", "1000"),
                tx(stock, TxType.SELL, "2024-02-02", "10", "1500"),
                tx(stock, TxType.BUY, "2024-03-02", "5", "2000"),
            ]
        )
    )
    assert position.avg_price_local == D("2000")
    assert position.realized_pnl_local == D("5000")


def test_sell_more_than_held_raises():
    stock = krw_stock()
    with pytest.raises(LedgerError, match="초과"):
        compute_positions(
            [
                tx(stock, TxType.BUY, "2024-01-02", "10", "1000"),
                tx(stock, TxType.SELL, "2024-02-02", "11", "1500"),
            ]
        )


def test_split_multiplies_quantity_and_halves_average():
    stock = krw_stock()
    position = only(
        compute_positions(
            [
                tx(stock, TxType.BUY, "2024-01-02", "20", "1500"),
                tx(stock, TxType.SPLIT, "2024-02-02", price="2"),
            ]
        )
    )
    assert position.quantity == D("40")
    assert position.cost_local == D("30000")  # 총원가는 그대로
    assert position.avg_price_local == D("750")


def test_dividend_is_tracked_separately_from_cost():
    stock = usd_stock()
    position = only(
        compute_positions(
            [
                tx(stock, TxType.BUY, "2024-01-02", "100", "150", fx_rate="1300"),
                tx(
                    stock,
                    TxType.DIVIDEND,
                    "2024-03-02",
                    quantity="100",
                    price="0.25",
                    fx_rate="1400",
                    tax="3.75",
                ),
            ]
        )
    )
    assert position.cost_local == D("15000")  # 배당은 원가를 건드리지 않는다
    assert position.dividend_local == D("21.25")  # 25 - 3.75 세금
    assert position.dividend_krw == D("21.25") * D("1400")


class TestForeignCurrencyCostBasis:
    """해외 종목은 원가를 달러·원화 두 갈래로 들고 있어야 환차손익이 갈린다."""

    def test_dual_currency_cost_and_average_fx(self):
        stock = usd_stock()
        position = only(
            compute_positions(
                [
                    tx(stock, TxType.BUY, "2024-01-02", "100", "100", fx_rate="1300"),
                    tx(stock, TxType.BUY, "2024-06-02", "100", "100", fx_rate="1400"),
                ]
            )
        )
        assert position.cost_local == D("20000")
        assert position.cost_krw == D("27000000")  # 10000*1300 + 10000*1400
        assert position.avg_price_local == D("100")
        assert position.avg_fx_rate == D("1350")  # 가중평균 매입환율

    def test_sell_uses_trade_date_fx_for_krw_realized_pnl(self):
        stock = usd_stock()
        position = only(
            compute_positions(
                [
                    tx(stock, TxType.BUY, "2024-01-02", "100", "100", fx_rate="1300"),
                    tx(stock, TxType.SELL, "2024-06-02", "100", "100", fx_rate="1400"),
                ]
            )
        )
        # 달러 기준으로는 본전
        assert position.realized_pnl_local == D("0")
        # 원화 기준으로는 환율만큼 이익 (10000 * (1400-1300))
        assert position.realized_pnl_krw == D("1000000")
