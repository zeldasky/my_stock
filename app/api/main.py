"""FastAPI 진입점.

    uvicorn app.api.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from ..config import BASE_DIR, settings
from ..core.ledger import LedgerError
from ..core.quotes import QuoteError
from .routers import auth, instruments, portfolio, targets, transactions

logger = logging.getLogger(__name__)

STATIC_DIR = BASE_DIR / "app" / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if settings.scheduler_enabled:
        from .scheduler import start_scheduler

        scheduler = start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(
    title="my_stock",
    description="거래 원장 기반 주식 포트폴리오 관리",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=False,  # AWS 배포 시 True 로 (HTTPS 전용 쿠키)
)


@app.exception_handler(LedgerError)
async def _ledger_error(request: Request, exc: LedgerError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(QuoteError)
async def _quote_error(request: Request, exc: QuoteError) -> JSONResponse:
    logger.warning("시세 조회 실패: %s", exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


api = APIRouter(prefix="/api/v1")
api.include_router(auth.router)
api.include_router(portfolio.router)
api.include_router(transactions.router)
api.include_router(instruments.router)
api.include_router(targets.router)
app.include_router(api)

# 웹 페이지는 API 아래가 아니라 루트에 붙는다.
from ..web.routes import router as web_router  # noqa: E402

app.include_router(web_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}
