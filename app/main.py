import logging
import sys

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Sumsub-style multi-tenant identity verification platform for Africa.",
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.on_event("startup")
async def _create_tables():
    from app.db.base import Base
    from app.db.session import engine
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.v1 import (  # noqa: E402
    api_keys,
    applicants,
    audit_logs,
    auth,
    consent,
    dashboard,
    kyc_data,
    tier_profiles,
    verifications,
    webhooks,
    workflows,
)

PREFIX = settings.API_V1_PREFIX
app.include_router(auth.router, prefix=PREFIX)
app.include_router(api_keys.router, prefix=PREFIX)
app.include_router(tier_profiles.router, prefix=PREFIX)
app.include_router(workflows.router, prefix=PREFIX)
app.include_router(applicants.router, prefix=PREFIX)
app.include_router(verifications.router, prefix=PREFIX)
app.include_router(kyc_data.router, prefix=PREFIX)
app.include_router(consent.router, prefix=PREFIX)
app.include_router(webhooks.router, prefix=PREFIX)
app.include_router(audit_logs.router, prefix=PREFIX)
app.include_router(dashboard.router, prefix=PREFIX)


SDK_DIR = Path(__file__).parent / "sdk"
app.mount("/sdk", StaticFiles(directory=str(SDK_DIR)), name="sdk")


@app.get("/verify", response_class=HTMLResponse)
def sdk_demo():
    return (SDK_DIR / "demo.html").read_text()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "afri-trust-backend", "version": settings.VERSION}
