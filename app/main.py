import asyncio
import contextlib
import logging
import sys

from contextlib import asynccontextmanager
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

_log = logging.getLogger(__name__)

is_prod = settings.ENVIRONMENT == "production"


def _sqlite_add_org_user_otp_columns(sync_conn) -> None:
    from sqlalchemy import text

    from app.core.config import settings

    if not str(settings.DATABASE_URL).startswith("sqlite"):
        return
    rows = sync_conn.execute(text("PRAGMA table_info(org_users)")).fetchall()
    names = {r[1] for r in rows}
    if "email_verify_otp" not in names:
        sync_conn.execute(
            text("ALTER TABLE org_users ADD COLUMN email_verify_otp VARCHAR(6)")
        )
    if "email_verify_otp_expires_at" not in names:
        sync_conn.execute(
            text(
                "ALTER TABLE org_users ADD COLUMN email_verify_otp_expires_at DATETIME"
            )
        )


def _sqlite_org_workspace_columns(sync_conn) -> None:
    from sqlalchemy import text

    from app.core.config import settings

    if not str(settings.DATABASE_URL).startswith("sqlite"):
        return
    org_rows = sync_conn.execute(text("PRAGMA table_info(organizations)")).fetchall()
    org_cols = {r[1] for r in org_rows}
    if "settings" not in org_cols:
        sync_conn.execute(text("ALTER TABLE organizations ADD COLUMN settings TEXT"))

    user_rows = sync_conn.execute(text("PRAGMA table_info(org_users)")).fetchall()
    ucols = {r[1] for r in user_rows}
    if "display_name" not in ucols:
        sync_conn.execute(text("ALTER TABLE org_users ADD COLUMN display_name VARCHAR(255)"))
    if "invite_token" not in ucols:
        sync_conn.execute(text("ALTER TABLE org_users ADD COLUMN invite_token VARCHAR(255)"))
    if "invite_expires_at" not in ucols:
        sync_conn.execute(text("ALTER TABLE org_users ADD COLUMN invite_expires_at DATETIME"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db.base import Base
    from app.db.session import async_session_factory, engine
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sqlite_add_org_user_otp_columns)
        await conn.run_sync(_sqlite_org_workspace_columns)

    async def webhook_worker():
        from app.services import webhook_dispatcher

        while True:
            await asyncio.sleep(10)
            try:
                async with async_session_factory() as db:
                    n = await webhook_dispatcher.process_pending_deliveries(db)
                    await db.commit()
                    if n > 0:
                        _log.info("Webhook worker processed %s delivery attempt(s)", n)
            except Exception:
                _log.exception("Webhook worker tick failed")

    worker_task = asyncio.create_task(webhook_worker())
    yield
    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Sumsub-style multi-tenant identity verification platform for Africa.",
    version=settings.VERSION,
    docs_url=None if is_prod else "/docs",
    redoc_url=None if is_prod else "/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
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
    org,
    tier_profiles,
    verification_live,
    verifications,
    webhooks,
    workflows,
)

PREFIX = settings.API_V1_PREFIX
app.include_router(auth.router, prefix=PREFIX)
app.include_router(org.router, prefix=PREFIX)
app.include_router(api_keys.router, prefix=PREFIX)
app.include_router(tier_profiles.router, prefix=PREFIX)
app.include_router(workflows.router, prefix=PREFIX)
app.include_router(applicants.router, prefix=PREFIX)
app.include_router(verifications.router, prefix=PREFIX)
app.include_router(verification_live.router, prefix=PREFIX)
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
