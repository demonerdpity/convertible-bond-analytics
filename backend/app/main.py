from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.models import BondListResponse, HealthResponse
from app.services.eastmoney import EastmoneyFetchError, bond_store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bond_store.start_background_refresh()
    try:
        yield
    finally:
        await bond_store.stop_background_refresh()


app = FastAPI(
    title="东方财富可转债比价看板 API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    snapshot = bond_store.get_snapshot()
    return HealthResponse(
        status="ok",
        has_data=snapshot.total > 0,
        total=snapshot.total,
        fetched_at=snapshot.fetched_at,
        base_fetched_at=snapshot.base_fetched_at,
        is_trading_time=snapshot.is_trading_time,
    )


@app.get("/api/bonds", response_model=BondListResponse)
async def get_bonds(
    fetch: bool = Query(
        default=False,
        description="是否主动触发一次拉取；默认直接返回后端自动维护的最新快照",
    ),
) -> BondListResponse:
    snapshot = bond_store.get_snapshot()
    if fetch or snapshot.total == 0:
        try:
            return await bond_store.fetch_once()
        except EastmoneyFetchError as exc:
            # 如果已有旧快照则优先返回，避免页面空白
            if snapshot.total > 0:
                return snapshot
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return snapshot


@app.post("/api/bonds/fetch", response_model=BondListResponse)
async def fetch_bonds() -> BondListResponse:
    try:
        return await bond_store.fetch_once()
    except EastmoneyFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
