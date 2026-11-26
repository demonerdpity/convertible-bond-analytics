from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.models import BondListResponse, HealthResponse
from app.services.eastmoney import EastmoneyFetchError, bond_store

app = FastAPI(
    title="东方财富可转债比价看板 API",
    version="0.1.0",
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
    )


@app.get("/api/bonds", response_model=BondListResponse)
async def get_bonds(
    fetch: bool = Query(
        default=False,
        description="是否主动请求一次东方财富接口；默认只返回当前内存快照",
    ),
) -> BondListResponse:
    if fetch:
        try:
            return await bond_store.fetch_once()
        except EastmoneyFetchError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return bond_store.get_snapshot()


@app.post("/api/bonds/fetch", response_model=BondListResponse)
async def fetch_bonds() -> BondListResponse:
    try:
        return await bond_store.fetch_once()
    except EastmoneyFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
