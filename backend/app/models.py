from __future__ import annotations

from pydantic import BaseModel, Field


class ConvertibleBond(BaseModel):
    bond_code: str = Field(..., description="债券代码 f12")
    bond_market: int | None = Field(None, description="债券市场 f13 (1=沪, 0=深)")
    bond_name: str = Field(..., description="债券简称 f14")
    bond_price: float | None = Field(None, description="转债最新价 f2")
    bond_change_pct: float | None = Field(None, description="转债涨跌幅(%) f3")

    stock_code: str | None = Field(None, description="正股代码 f232")
    stock_market: int | None = Field(None, description="正股市场 f233 (1=沪, 0=深)")
    stock_name: str | None = Field(None, description="正股简称 f234")
    stock_price: float | None = Field(None, description="正股最新价 f229")
    stock_change_pct: float | None = Field(None, description="正股涨跌幅(%) f230")

    conversion_price: float | None = Field(None, description="转股价 f235")
    conversion_value: float | None = Field(None, description="转股价值 f236")
    conversion_premium_pct: float | None = Field(None, description="转股溢价率(%) f237")
    pure_bond_premium_pct: float | None = Field(None, description="纯债溢价率(%) f238")

    put_trigger_price: float | None = Field(None, description="回售触发价 f239")
    call_trigger_price: float | None = Field(None, description="强赎触发价 f240")
    maturity_redemption_price: float | None = Field(None, description="到期赎回价 f241")
    pure_bond_value: float | None = Field(None, description="纯债价值 f227")

    conversion_market_value_per_100: float | None = Field(
        None,
        description="每百元现价转股市值: 100 / 转债现价 * (100 / 转股价 * 正股价)",
    )

    conversion_start_date: str | None = Field(None, description="开始转股日 f242")
    listing_date: str | None = Field(None, description="上市日期 f26")
    subscription_date: str | None = Field(None, description="申购日期 f243")


class BondListResponse(BaseModel):
    total: int
    fetched_at: str | None = None
    source: str = "datacenter-web.eastmoney.com"
    pages_fetched: int = 0
    from_cache: bool = False
    items: list[ConvertibleBond] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    has_data: bool
    total: int
    fetched_at: str | None = None
