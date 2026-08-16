"""DB 스키마.

설계 원칙: 진실의 원천은 transactions 하나뿐이다.
보유수량·평균단가·실현손익·일별 자산추이는 전부 거래에서 파생 계산하며,
price_daily / fx_daily / valuation_daily 는 언제든 지우고 다시 채울 수 있는 캐시다.
"""

from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# 수량·금액 공용 타입. 소수 8자리면 해외주식 소수점 매수까지 커버된다.
MONEY = Numeric(20, 8)


class TxType(enum.StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    # 1단계에서는 쓰지 않지만 나중에 예수금·실질수익률(TWR/MWR)을 넣을 때를 위해 열어둔다.
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"


class Market(enum.StrEnum):
    KRX = "KRX"
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"
    AMEX = "AMEX"


class TargetKind(enum.StrEnum):
    PRICE_ABOVE = "PRICE_ABOVE"  # 목표가 도달
    PRICE_BELOW = "PRICE_BELOW"  # 손절가 이탈
    RETURN_ABOVE = "RETURN_ABOVE"  # 수익률 % 이상
    RETURN_BELOW = "RETURN_BELOW"  # 수익률 % 이하


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    accounts: Mapped[list[Account]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Account(Base):
    """증권 계좌. 지금은 하나지만 국내/해외 계좌 분리를 대비해 테이블로 둔다."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    base_currency: Mapped[str] = mapped_column(String(3), default="KRW")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Instrument(Base):
    """종목 마스터. symbol 은 FDR 조회 키와 동일하게 유지한다 (005930 / AAPL)."""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("symbol", "market", name="uq_instrument_symbol_market"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[Market] = mapped_column(String(16))
    name_ko: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str | None] = mapped_column(String(128), default=None)
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def is_foreign(self) -> bool:
        return self.currency != "KRW"


class Transaction(Base):
    """거래 원장. 이 테이블만이 진실의 원천이다.

    fx_rate 는 '거래일의 환율'을 그 자리에 고정 저장한다.
    이래야 과거 원화 원가가 재현되고, 현재 환율과의 차이가 환차손익으로 분리된다.
    원화 종목은 항상 1.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_tx_quantity_non_negative"),
        CheckConstraint("price >= 0", name="ck_tx_price_non_negative"),
        CheckConstraint("fx_rate > 0", name="ck_tx_fx_rate_positive"),
        Index("ix_tx_account_traded_on", "account_id", "traded_on"),
        Index("ix_tx_instrument_traded_on", "instrument_id", "traded_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    # DEPOSIT/WITHDRAW 는 종목이 없으므로 nullable.
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), default=None, index=True
    )

    tx_type: Mapped[TxType] = mapped_column(String(16))
    traded_on: Mapped[dt.date] = mapped_column(Date, index=True)

    quantity: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    fx_rate: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("1"))

    fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))

    memo: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="transactions")
    instrument: Mapped[Instrument | None] = relationship(lazy="joined")


class PriceDaily(Base):
    """일별 종가 캐시. FDR 호출을 줄이고 과거 자산추이 계산을 빠르게 한다."""

    __tablename__ = "price_daily"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(MONEY)


class FxDaily(Base):
    """일별 환율 캐시."""

    __tablename__ = "fx_daily"

    pair: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(MONEY)


class ValuationDaily(Base):
    """일별 평가 결과 캐시. 거래에서 재계산 가능하므로 언제든 버려도 된다."""

    __tablename__ = "valuation_daily"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)

    cost_krw: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    market_value_krw: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    realized_pnl_krw: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    unrealized_pnl_krw: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    fx_effect_krw: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))


class Target(Base):
    """목표가 / 손절가 / 목표수익률."""

    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[TargetKind] = mapped_column(String(16))
    value: Mapped[Decimal] = mapped_column(MONEY)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    instrument: Mapped[Instrument] = relationship(lazy="joined")
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("target_id", "triggered_on", name="uq_alert_target_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), index=True
    )
    triggered_on: Mapped[dt.date] = mapped_column(Date)
    observed_value: Mapped[Decimal] = mapped_column(MONEY)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    target: Mapped[Target] = relationship(back_populates="alerts")
