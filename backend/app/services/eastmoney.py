from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.models import BondListResponse, ConvertibleBond

logger = logging.getLogger(__name__)

EASTMONEY_DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="

DC_COLUMNS = ",".join(
    [
        "SECURITY_CODE",
        "SECUCODE",
        "SECURITY_NAME_ABBR",
        "DELIST_DATE",
        "CEASE_DATE",
        "LISTING_DATE",
        "PUBLIC_START_DATE",
        "TRANSFER_START_DATE",
        "EXPIRE_DATE",
        "VALUE_DATE",
        "CONVERT_STOCK_CODE",
        "SECURITY_SHORT_NAME",
        "RATING",
        "INTEREST_RATE_EXPLAIN",
        "REDEEM_CLAUSE",
        "INITIAL_TRANSFER_PRICE",
        "TRANSFER_PRICE",
        "TRANSFER_VALUE",
        "CURRENT_BOND_PRICE",
        "CONVERT_STOCK_PRICE",
        "TRANSFER_PREMIUM_RATIO",
        "RESALE_TRIG_PRICE",
        "REDEEM_TRIG_PRICE",
    ]
)

DC_QUOTE_COLUMNS = ",".join(
    [
        "f2~10~SECURITY_CODE~CURRENT_BOND_PRICE",
        "f3~10~SECURITY_CODE~BOND_CHG",
        "f2~01~CONVERT_STOCK_CODE~CONVERT_STOCK_PRICE",
        "f3~01~CONVERT_STOCK_CODE~STOCK_CHG",
        "f235~10~SECURITY_CODE~TRANSFER_PRICE",
        "f236~10~SECURITY_CODE~TRANSFER_VALUE",
        "f237~10~SECURITY_CODE~TRANSFER_PREMIUM_RATIO",
        "f239~10~SECURITY_CODE~RESALE_TRIG_PRICE",
        "f240~10~SECURITY_CODE~REDEEM_TRIG_PRICE",
    ]
)

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/kzz/",
    "Accept": "application/json, text/plain, */*",
}

# 按信用评级映射参考贴现率（用于本地估算纯债价值）
RATING_DISCOUNT_RATES: dict[str, float] = {
    "AAA": 0.0185,
    "AA+": 0.0195,
    "AA": 0.0206,
    "AA-": 0.0282,
    "A+": 0.0420,
    "A": 0.0520,
    "A-": 0.0650,
    "BBB+": 0.0800,
    "BBB": 0.0950,
}
DEFAULT_DISCOUNT_RATE = 0.0280

DC_PAGE_SIZE = 500
DC_MAX_PAGES = 5
TENCENT_BATCH_SIZE = 80
TENCENT_BATCH_DELAY_SECONDS = 0.15
PAGE_DELAY_SECONDS = 0.3

# 分级刷新节律（兼顾实时性与低风控）：
# - 基础与条款数据（datacenter-web）：盘中每 15 分钟刷新一次，收盘后补一次收盘定格
# - 实时行情报价（qt.gtimg.cn）：仅盘中每 45 秒刷新一次；午休/盘后/周末停止上游请求
# - 手动刷新防抖冷却：20 秒内复用当前缓存
BASE_REFRESH_INTERVAL_SECONDS = 900
QUOTE_REFRESH_INTERVAL_SECONDS = 45
MANUAL_COOLDOWN_SECONDS = 20.0
SCHEDULER_TICK_SECONDS = 15

REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
RETRY_ATTEMPTS = 1
RETRY_DELAY_SECONDS = 1.5
CN_TZ = timezone(timedelta(hours=8))
CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "latest_bonds.json"


class EastmoneyFetchError(RuntimeError):
    """Raised when upstream convertible bond data cannot be fetched or parsed."""


def is_cn_trading_time(now: datetime | None = None) -> bool:
    """判断当前是否处于 A 股可转债盘中交易窗口（周一至周五 09:20-11:32、12:58-15:05）。"""
    dt = now or datetime.now(CN_TZ)
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    morning = dt_time(9, 20) <= t <= dt_time(11, 32)
    afternoon = dt_time(12, 58) <= t <= dt_time(15, 5)
    return morning or afternoon


def is_post_close_sync_window(now: datetime | None = None) -> bool:
    """收盘定格窗口（工作日 15:05-15:20），确保盘后数据为当日最终收盘价。"""
    dt = now or datetime.now(CN_TZ)
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    return dt_time(15, 5) < t <= dt_time(15, 20)


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS + 1):
        try:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = exc
            if attempt < RETRY_ATTEMPTS:
                logger.warning(
                    "Transient network error fetching %s (attempt %d/%d): %s; retrying in %.1fs",
                    url,
                    attempt + 1,
                    RETRY_ATTEMPTS + 1,
                    exc,
                    RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            else:
                raise
    assert last_exc is not None
    raise last_exc


def _to_float(value: Any) -> float | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_str(value: Any) -> str | None:
    if value is None or value == "" or value == "-":
        return None
    text = str(value).strip()
    return text or None


def _format_date(value: Any) -> str | None:
    raw = _to_str(value)
    if not raw:
        return None
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


def _bond_market_from_secucode(secucode: str | None, bond_code: str) -> int | None:
    if secucode:
        upper = secucode.upper()
        if upper.endswith(".SH"):
            return 1
        if upper.endswith(".SZ"):
            return 0
    if bond_code.startswith(("11", "13")):
        return 1
    if bond_code.startswith("12"):
        return 0
    return None


def _stock_market_from_code(stock_code: str | None) -> int | None:
    if not stock_code:
        return None
    if stock_code.startswith(("6", "9")):
        return 1
    if stock_code.startswith(("0", "3")):
        return 0
    return None


def _qt_symbol(code: str | None, market: int | None) -> str | None:
    if not code or market not in (0, 1):
        return None
    prefix = "sh" if market == 1 else "sz"
    return f"{prefix}{code}"


def _parse_redemption_price(redeem_clause: str | None) -> float | None:
    if not redeem_clause:
        return None
    for pattern in (
        r"(?:票面)?面值的?\s*(\d+(?:\.\d+)?)\s*%",
        r"(\d{3}(?:\.\d+)?)\s*元",
        r"(\d{3}(?:\.\d+)?)\s*%",
    ):
        match = re.search(pattern, redeem_clause)
        if match:
            val = float(match.group(1))
            if 100.0 <= val <= 150.0:
                return val
    return None


def _parse_coupons(rate_explain: str | None) -> list[float]:
    if not rate_explain:
        return []
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", rate_explain)]


def _add_years(base: date, years: int) -> date:
    try:
        return base.replace(year=base.year + years)
    except ValueError:
        return base.replace(year=base.year + years, day=28)


def _compute_pure_bond_value(
    value_date_str: str | None,
    expire_date_str: str | None,
    rate_explain: str | None,
    redemption_price: float | None,
    rating: str | None,
    today: date,
) -> float | None:
    if not value_date_str or not expire_date_str or redemption_price is None:
        return None
    try:
        value_dt = date.fromisoformat(value_date_str[:10])
        expire_dt = date.fromisoformat(expire_date_str[:10])
    except ValueError:
        return None

    if expire_dt <= today:
        return None

    coupons = _parse_coupons(rate_explain)
    if not coupons:
        return None

    discount_rate = RATING_DISCOUNT_RATES.get((rating or "").strip().upper(), DEFAULT_DISCOUNT_RATE)
    total_years = len(coupons)
    pv = 0.0

    for idx, coupon in enumerate(coupons, start=1):
        pay_dt = expire_dt if idx == total_years else _add_years(value_dt, idx)
        if pay_dt <= today:
            continue
        t_years = (pay_dt - today).days / 365.0
        cash_flow = redemption_price if idx == total_years else coupon
        pv += cash_flow / ((1.0 + discount_rate) ** t_years)

    return round(pv, 4) if pv > 0 else None


def _compute_conversion_market_value_per_100(
    bond_price: float | None,
    stock_price: float | None,
    conversion_price: float | None,
) -> float | None:
    if (
        bond_price is not None
        and bond_price > 0
        and stock_price is not None
        and stock_price > 0
        and conversion_price is not None
        and conversion_price > 0
    ):
        return round((100.0 / bond_price) * (100.0 / conversion_price) * stock_price, 4)
    return None


def _recalculate_derived_fields(bond: ConvertibleBond) -> ConvertibleBond:
    """当现价/正股价更新后，重新计算转股价值、溢价率与每百元现价转股市值。"""
    conversion_value = bond.conversion_value
    if (
        bond.stock_price is not None
        and bond.stock_price > 0
        and bond.conversion_price is not None
        and bond.conversion_price > 0
    ):
        conversion_value = round((100.0 / bond.conversion_price) * bond.stock_price, 4)

    conversion_premium_pct = bond.conversion_premium_pct
    if (
        bond.bond_price is not None
        and conversion_value is not None
        and conversion_value > 0
    ):
        conversion_premium_pct = round((bond.bond_price / conversion_value - 1.0) * 100.0, 2)

    pure_bond_premium_pct = bond.pure_bond_premium_pct
    if (
        bond.bond_price is not None
        and bond.pure_bond_value is not None
        and bond.pure_bond_value > 0
    ):
        pure_bond_premium_pct = round((bond.bond_price / bond.pure_bond_value - 1.0) * 100.0, 2)

    per_100 = _compute_conversion_market_value_per_100(
        bond.bond_price, bond.stock_price, bond.conversion_price
    )

    return bond.model_copy(
        update={
            "conversion_value": conversion_value,
            "conversion_premium_pct": conversion_premium_pct,
            "pure_bond_premium_pct": pure_bond_premium_pct,
            "conversion_market_value_per_100": per_100,
        }
    )


async def _fetch_tencent_quotes(
    client: httpx.AsyncClient,
    symbols: list[str],
) -> dict[str, tuple[float | None, float | None]]:
    """Batch-fetch (latest_price, change_pct) from Tencent qt.gtimg.cn."""
    result: dict[str, tuple[float | None, float | None]] = {}
    unique_symbols = list(dict.fromkeys(symbols))
    for i in range(0, len(unique_symbols), TENCENT_BATCH_SIZE):
        batch = unique_symbols[i : i + TENCENT_BATCH_SIZE]
        url = TENCENT_QUOTE_URL + ",".join(batch)
        resp = await _get_with_retry(
            client, url, headers={"User-Agent": COMMON_HEADERS["User-Agent"]}
        )
        text = resp.content.decode("gbk", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line or '="' not in line:
                continue
            head, body = line.split('="', 1)
            sym = head.removeprefix("v_").strip()
            parts = body.rstrip('";').split("~")
            if len(parts) < 33:
                continue
            price = _to_float(parts[3])
            chg_pct = _to_float(parts[32])
            if price is not None and price > 0:
                result[sym] = (price, chg_pct)
        if i + TENCENT_BATCH_SIZE < len(unique_symbols):
            await asyncio.sleep(TENCENT_BATCH_DELAY_SECONDS)
    return result


def _parse_dc_row(
    row: dict[str, Any],
    today: date,
    tencent_quotes: dict[str, tuple[float | None, float | None]],
) -> ConvertibleBond | None:
    bond_code = _to_str(row.get("SECURITY_CODE"))
    bond_name = _to_str(row.get("SECURITY_NAME_ABBR"))
    if not bond_code or not bond_name:
        return None

    secucode = _to_str(row.get("SECUCODE"))
    if secucode and not secucode.upper().endswith((".SH", ".SZ")):
        return None

    bond_market = _bond_market_from_secucode(secucode, bond_code)
    stock_code = _to_str(row.get("CONVERT_STOCK_CODE"))
    stock_market = _stock_market_from_code(stock_code)
    stock_name = _to_str(row.get("SECURITY_SHORT_NAME"))

    listing_date = _format_date(row.get("LISTING_DATE"))
    is_listed = bool(listing_date and listing_date <= today.isoformat())

    bond_price = _to_float(row.get("CURRENT_BOND_PRICE"))
    bond_change_pct = _to_float(row.get("BOND_CHG"))
    stock_price = _to_float(row.get("CONVERT_STOCK_PRICE"))
    stock_change_pct = _to_float(row.get("STOCK_CHG"))

    if is_listed and bond_price is None:
        b_sym = _qt_symbol(bond_code, bond_market)
        if b_sym and b_sym in tencent_quotes:
            bond_price, bond_change_pct = tencent_quotes[b_sym]
    if stock_price is None:
        s_sym = _qt_symbol(stock_code, stock_market)
        if s_sym and s_sym in tencent_quotes:
            stock_price, stock_change_pct = tencent_quotes[s_sym]

    conversion_price = _to_float(row.get("TRANSFER_PRICE")) or _to_float(
        row.get("INITIAL_TRANSFER_PRICE")
    )

    conversion_value = _to_float(row.get("TRANSFER_VALUE"))
    if (
        conversion_value is None
        and stock_price is not None
        and stock_price > 0
        and conversion_price is not None
        and conversion_price > 0
    ):
        conversion_value = round((100.0 / conversion_price) * stock_price, 4)

    conversion_premium_pct = _to_float(row.get("TRANSFER_PREMIUM_RATIO"))
    if (
        conversion_premium_pct is None
        and bond_price is not None
        and conversion_value is not None
        and conversion_value > 0
    ):
        conversion_premium_pct = round((bond_price / conversion_value - 1.0) * 100.0, 2)

    maturity_redemption_price = _parse_redemption_price(_to_str(row.get("REDEEM_CLAUSE")))
    pure_bond_value = _compute_pure_bond_value(
        value_date_str=_format_date(row.get("VALUE_DATE")),
        expire_date_str=_format_date(row.get("EXPIRE_DATE")),
        rate_explain=_to_str(row.get("INTEREST_RATE_EXPLAIN")),
        redemption_price=maturity_redemption_price,
        rating=_to_str(row.get("RATING")),
        today=today,
    )

    pure_bond_premium_pct: float | None = None
    if bond_price is not None and pure_bond_value is not None and pure_bond_value > 0:
        pure_bond_premium_pct = round((bond_price / pure_bond_value - 1.0) * 100.0, 2)

    return ConvertibleBond(
        bond_code=bond_code,
        bond_market=bond_market,
        bond_name=bond_name,
        bond_price=bond_price,
        bond_change_pct=bond_change_pct,
        stock_code=stock_code,
        stock_market=stock_market,
        stock_name=stock_name,
        stock_price=stock_price,
        stock_change_pct=stock_change_pct,
        conversion_price=conversion_price,
        conversion_value=conversion_value,
        conversion_premium_pct=conversion_premium_pct,
        pure_bond_premium_pct=pure_bond_premium_pct,
        put_trigger_price=_to_float(row.get("RESALE_TRIG_PRICE")),
        call_trigger_price=_to_float(row.get("REDEEM_TRIG_PRICE")),
        maturity_redemption_price=maturity_redemption_price,
        pure_bond_value=pure_bond_value,
        conversion_market_value_per_100=_compute_conversion_market_value_per_100(
            bond_price, stock_price, conversion_price
        ),
        conversion_start_date=_format_date(row.get("TRANSFER_START_DATE")),
        listing_date=listing_date,
        subscription_date=_format_date(row.get("PUBLIC_START_DATE")),
    )


class ConvertibleBondStore:
    """Tiered auto-refresh snapshot store:
    - Full base/clause sync via datacenter-web (every 15m in trading hours + post-close)
    - Fast live quote sync via Tencent qt.gtimg.cn (every 45s in trading hours only)
    - Atomic replacement: failed refreshes never overwrite valid data.
    """

    def __init__(self, cache_file: Path = CACHE_FILE) -> None:
        self._cache_file = cache_file
        self._snapshot = BondListResponse(
            total=0,
            fetched_at=None,
            base_fetched_at=None,
            source="datacenter-web.eastmoney.com",
            pages_fetched=0,
            is_trading_time=is_cn_trading_time(),
            quote_refresh_seconds=QUOTE_REFRESH_INTERVAL_SECONDS,
            base_refresh_seconds=BASE_REFRESH_INTERVAL_SECONDS,
            items=[],
        )
        self._last_base_epoch: float = 0.0
        self._last_quote_epoch: float = 0.0
        self._post_close_synced_date: str | None = None
        self._lock = asyncio.Lock()
        self._scheduler_task: asyncio.Task[None] | None = None
        self._load_disk_cache()

    def _load_disk_cache(self) -> None:
        if not self._cache_file.is_file():
            return
        try:
            raw = json.loads(self._cache_file.read_text(encoding="utf-8"))
            cached = BondListResponse.model_validate(raw)
            if cached.total > 0:
                mtime = self._cache_file.stat().st_mtime
                base_at = cached.base_fetched_at or cached.fetched_at
                self._snapshot = cached.model_copy(
                    update={
                        "base_fetched_at": base_at,
                        "from_cache": True,
                        "is_trading_time": is_cn_trading_time(),
                        "quote_refresh_seconds": QUOTE_REFRESH_INTERVAL_SECONDS,
                        "base_refresh_seconds": BASE_REFRESH_INTERVAL_SECONDS,
                    }
                )
                self._last_base_epoch = mtime
                self._last_quote_epoch = mtime
        except Exception:
            return

    def _save_disk_cache(self, snapshot: BondListResponse) -> None:
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self._cache_file.with_suffix(".tmp")
            payload = snapshot.model_copy(update={"from_cache": False}).model_dump_json(indent=2)
            tmp_file.write_text(payload, encoding="utf-8")
            tmp_file.replace(self._cache_file)
        except Exception:
            return

    def get_snapshot(self) -> BondListResponse:
        return self._snapshot.model_copy(
            update={
                "is_trading_time": is_cn_trading_time(),
                "quote_refresh_seconds": QUOTE_REFRESH_INTERVAL_SECONDS,
                "base_refresh_seconds": BASE_REFRESH_INTERVAL_SECONDS,
            }
        )

    def start_background_refresh(self) -> None:
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def stop_background_refresh(self) -> None:
        if self._scheduler_task is not None and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        self._scheduler_task = None

    async def _scheduler_loop(self) -> None:
        # 启动后如果尚无缓存数据，立即拉取一次全量快照，避免首次进入为空白
        if self._snapshot.total == 0:
            try:
                logger.info("Initial cache empty; fetching full convertible bond snapshot...")
                await self.fetch_full(ignore_cooldown=True)
            except Exception as exc:
                logger.warning("Initial startup fetch failed: %s", exc)

        while True:
            try:
                await asyncio.sleep(SCHEDULER_TICK_SECONDS)
                now_dt = datetime.now(CN_TZ)
                now_epoch = time.time()
                today_str = now_dt.date().isoformat()

                if self._snapshot.total == 0:
                    # 尚无有效数据时，每隔 60 秒重试一次初始化拉取
                    if now_epoch - self._last_base_epoch >= 60:
                        await self.fetch_full(ignore_cooldown=True)
                    continue

                if is_cn_trading_time(now_dt):
                    if now_epoch - self._last_base_epoch >= BASE_REFRESH_INTERVAL_SECONDS:
                        logger.info("Scheduled trading-hour full base refresh...")
                        await self.fetch_full(ignore_cooldown=True)
                    elif now_epoch - self._last_quote_epoch >= QUOTE_REFRESH_INTERVAL_SECONDS:
                        logger.info("Scheduled trading-hour live quote refresh...")
                        await self.refresh_quotes_only()
                elif (
                    is_post_close_sync_window(now_dt)
                    and self._post_close_synced_date != today_str
                ):
                    logger.info("Post-close final snapshot sync for %s...", today_str)
                    await self.fetch_full(ignore_cooldown=True)
                    self._post_close_synced_date = today_str
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Background refresh cycle failed (keeping existing snapshot): %s", exc)

    async def refresh_quotes_only(self) -> BondListResponse:
        """仅使用腾讯批量行情更新已上市转债和正股的实时价格，并本地重算衍生指标。"""
        async with self._lock:
            if self._snapshot.total == 0:
                raise EastmoneyFetchError("尚未加载基础数据，请先执行全量拉取")

            today_str = datetime.now(CN_TZ).date().isoformat()
            symbols: list[str] = []
            for item in self._snapshot.items:
                is_listed = bool(item.listing_date and item.listing_date <= today_str)
                if is_listed:
                    b_sym = _qt_symbol(item.bond_code, item.bond_market)
                    if b_sym:
                        symbols.append(b_sym)
                s_sym = _qt_symbol(item.stock_code, item.stock_market)
                if s_sym:
                    symbols.append(s_sym)

            if not symbols:
                return self.get_snapshot()

            try:
                async with httpx.AsyncClient(
                    headers={"User-Agent": COMMON_HEADERS["User-Agent"]},
                    timeout=REQUEST_TIMEOUT,
                    http2=False,
                    trust_env=True,
                ) as client:
                    quotes = await _fetch_tencent_quotes(client, symbols)
            except httpx.HTTPError as exc:
                logger.warning("Tencent quote refresh failed (%s): %s", type(exc).__name__, exc)
                raise EastmoneyFetchError(f"刷新实时行情失败（{type(exc).__name__}）：{exc}") from exc

            if not quotes:
                raise EastmoneyFetchError("实时行情返回为空，已保留旧数据")

            updated_items: list[ConvertibleBond] = []
            for item in self._snapshot.items:
                is_listed = bool(item.listing_date and item.listing_date <= today_str)
                updates: dict[str, Any] = {}
                if is_listed:
                    b_sym = _qt_symbol(item.bond_code, item.bond_market)
                    if b_sym and b_sym in quotes:
                        b_price, b_chg = quotes[b_sym]
                        updates["bond_price"] = b_price
                        updates["bond_change_pct"] = b_chg
                s_sym = _qt_symbol(item.stock_code, item.stock_market)
                if s_sym and s_sym in quotes:
                    s_price, s_chg = quotes[s_sym]
                    updates["stock_price"] = s_price
                    updates["stock_change_pct"] = s_chg

                next_item = item.model_copy(update=updates) if updates else item
                updated_items.append(_recalculate_derived_fields(next_item))

            now_str = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
            self._snapshot = self._snapshot.model_copy(
                update={
                    "fetched_at": now_str,
                    "source": "datacenter-web.eastmoney.com + qt.gtimg.cn",
                    "from_cache": False,
                    "is_trading_time": is_cn_trading_time(),
                    "items": updated_items,
                }
            )
            self._last_quote_epoch = time.time()
            self._save_disk_cache(self._snapshot)
            return self._snapshot

    async def fetch_full(self, *, ignore_cooldown: bool = False) -> BondListResponse:
        """执行全量数据中心拉取（含缺失现价腾讯补缺）；只有成功拿到非空数据时才替换旧快照。"""
        async with self._lock:
            now = time.time()
            if (
                not ignore_cooldown
                and self._snapshot.total > 0
                and (now - max(self._last_base_epoch, self._last_quote_epoch)) < MANUAL_COOLDOWN_SECONDS
            ):
                return self.get_snapshot().model_copy(update={"from_cache": True})

            today = datetime.now(CN_TZ).date()
            today_str = today.isoformat()
            raw_rows: list[dict[str, Any]] = []
            seen_codes: set[str] = set()
            pages_fetched = 0
            used_tencent = False

            try:
                async with httpx.AsyncClient(
                    headers=COMMON_HEADERS,
                    timeout=REQUEST_TIMEOUT,
                    http2=False,
                    trust_env=True,
                ) as client:
                    for page in range(1, DC_MAX_PAGES + 1):
                        params = {
                            "sortColumns": "PUBLIC_START_DATE",
                            "sortTypes": "-1",
                            "pageSize": str(DC_PAGE_SIZE),
                            "pageNumber": str(page),
                            "reportName": "RPT_BOND_CB_LIST",
                            "columns": DC_COLUMNS,
                            "quoteColumns": DC_QUOTE_COLUMNS,
                            "quoteType": "0",
                            "filter": f"(EXPIRE_DATE>='{today_str}')",
                            "source": "WEB",
                            "client": "WEB",
                        }
                        resp = await _get_with_retry(client, EASTMONEY_DC_URL, params=params)
                        payload = resp.json()
                        if not isinstance(payload, dict) or not payload.get("success"):
                            msg = payload.get("message") if isinstance(payload, dict) else "未知错误"
                            raise EastmoneyFetchError(f"东方财富数据中心返回异常：{msg}")

                        result = payload.get("result") or {}
                        data = result.get("data") or []
                        total_pages = int(result.get("pages") or 1)
                        pages_fetched += 1

                        for item in data:
                            if not isinstance(item, dict):
                                continue
                            delist = _format_date(item.get("DELIST_DATE"))
                            if delist and delist <= today_str:
                                continue
                            code = _to_str(item.get("SECURITY_CODE"))
                            if code and code not in seen_codes:
                                seen_codes.add(code)
                                raw_rows.append(item)

                        if page >= total_pages or len(data) < DC_PAGE_SIZE:
                            break
                        await asyncio.sleep(PAGE_DELAY_SECONDS)

                    missing_symbols: list[str] = []
                    for item in raw_rows:
                        code = _to_str(item.get("SECURITY_CODE"))
                        secucode = _to_str(item.get("SECUCODE"))
                        if not code or (secucode and not secucode.upper().endswith((".SH", ".SZ"))):
                            continue
                        listing_date = _format_date(item.get("LISTING_DATE"))
                        is_listed = bool(listing_date and listing_date <= today_str)
                        if is_listed and _to_float(item.get("CURRENT_BOND_PRICE")) is None:
                            sym = _qt_symbol(code, _bond_market_from_secucode(secucode, code))
                            if sym:
                                missing_symbols.append(sym)
                        s_code = _to_str(item.get("CONVERT_STOCK_CODE"))
                        if s_code and _to_float(item.get("CONVERT_STOCK_PRICE")) is None:
                            sym = _qt_symbol(s_code, _stock_market_from_code(s_code))
                            if sym:
                                missing_symbols.append(sym)

                    tencent_quotes: dict[str, tuple[float | None, float | None]] = {}
                    if missing_symbols:
                        try:
                            tencent_quotes = await _fetch_tencent_quotes(client, missing_symbols)
                            used_tencent = bool(tencent_quotes)
                        except httpx.HTTPError:
                            tencent_quotes = {}
            except EastmoneyFetchError as exc:
                logger.warning("Eastmoney fetch failed: %s", exc)
                raise
            except httpx.HTTPError as exc:
                logger.warning("Eastmoney HTTP error (%s): %s", type(exc).__name__, exc)
                raise EastmoneyFetchError(
                    f"请求东方财富数据中心失败（{type(exc).__name__}）：{exc}"
                ) from exc
            except Exception as exc:
                logger.exception("Unexpected error parsing convertible bond data")
                raise EastmoneyFetchError(f"解析可转债数据失败：{exc}") from exc

            items = [
                bond
                for raw in raw_rows
                if (bond := _parse_dc_row(raw, today, tencent_quotes)) is not None
            ]
            if not items:
                raise EastmoneyFetchError("上游返回有效可转债数量为 0，已保留旧数据")

            fetched_at = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
            source_label = (
                "datacenter-web.eastmoney.com + qt.gtimg.cn"
                if used_tencent
                else "datacenter-web.eastmoney.com"
            )
            self._snapshot = BondListResponse(
                total=len(items),
                fetched_at=fetched_at,
                base_fetched_at=fetched_at,
                source=source_label,
                pages_fetched=pages_fetched,
                from_cache=False,
                is_trading_time=is_cn_trading_time(),
                quote_refresh_seconds=QUOTE_REFRESH_INTERVAL_SECONDS,
                base_refresh_seconds=BASE_REFRESH_INTERVAL_SECONDS,
                items=items,
            )
            now_epoch = time.time()
            self._last_base_epoch = now_epoch
            self._last_quote_epoch = now_epoch
            self._save_disk_cache(self._snapshot)
            return self._snapshot

    async def fetch_once(self) -> BondListResponse:
        """兼容手动触发入口。"""
        return await self.fetch_full(ignore_cooldown=False)


bond_store = ConvertibleBondStore()
