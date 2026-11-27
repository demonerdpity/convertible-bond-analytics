from __future__ import annotations

from pydantic import BaseModel, Field


class ConvertibleBond(BaseModel):
    bond_code: str = Field(..., description="债券代码")
    bond_market: int | None = Field(None, description="债券市场 (1=沪, 0=深)")
    bond_name: str = Field(..., description="债券简称")
    bond_price: float | None = Field(None, description="转债最新价")
    bond_change_pct: float | None = Field(None, description="转债涨跌幅(%)")

    stock_code: str | None = Field(None, description="正股代码")
    stock_market: int | None = Field(None, description="正股市场 (1=沪, 0=深)")
    stock_name: str | None = Field(None, description="正股简称")
    stock_price: float | None = Field(None, description="正股最新价")
    stock_change_pct: float | None = Field(None, description="正股涨跌幅(%)")

    conversion_price: float | None = Field(None, description="转股价")
    conversion_value: float | None = Field(None, description="转股价值")
    conversion_premium_pct: float | None = Field(None, description="转股溢价率(%)")
    pure_bond_premium_pct: float | None = Field(None, description="纯债溢价率(%)")

    put_trigger_price: float | None = Field(None, description="回售触发价")
    call_trigger_price: float | None = Field(None, description="强赎触发价")
    maturity_redemption_price: float | None = Field(None, description="到期赎回价")
    pure_bond_value: float | None = Field(None, description="纯债价值")

    conversion_market_value_per_100: float | None = Field(
        None,
        description="每百元现价转股市值: 100 / 转债现价 * (100 / 转股价 * 正股价)",
    )

    conversion_start_date: str | None = Field(None, description="开始转股日")
    listing_date: str | None = Field(None, description="上市日期")
    subscription_date: str | None = Field(None, description="申购日期")


class BondListResponse(BaseModel):
    total: int
    fetched_at: str | None = None
    base_fetched_at: str | None = None
    source: str = "datacenter-web.eastmoney.com"
    pages_fetched: int = 0
    from_cache: bool = False
    is_trading_time: bool = False
    quote_refresh_seconds: int = 45
    base_refresh_seconds: int = 900
    items: list[ConvertibleBond] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    has_data: bool
    total: int
    fetched_at: str | None = None
    base_fetched_at: str | None = None
    is_trading_time: bool = False
