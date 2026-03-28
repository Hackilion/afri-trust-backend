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


def _sqlite_workflows_short_code(sync_conn) -> None:
    """Add workflows.short_code for DBs created before that column existed."""
    import secrets

    from sqlalchemy import text

    from app.core.config import settings

    if not str(settings.DATABASE_URL).startswith("sqlite"):
        return
    rows = sync_conn.execute(text("PRAGMA table_info(workflows)")).fetchall()
    names = {r[1] for r in rows}
    if "short_code" in names:
        return

    sync_conn.execute(
        text(
            "ALTER TABLE workflows ADD COLUMN short_code VARCHAR(6) NOT NULL DEFAULT '000000'"
        )
    )
    wf_rows = sync_conn.execute(
        text("SELECT id, org_id FROM workflows ORDER BY org_id, created_at")
    ).fetchall()
    used_by_org: dict[str, set[str]] = {}
    for wid, oid in wf_rows:
        org_key = str(oid)
        used = used_by_org.setdefault(org_key, set())
        for _ in range(200):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if code not in used:
                used.add(code)
                sync_conn.execute(
                    text("UPDATE workflows SET short_code = :code WHERE id = :id"),
                    {"code": code, "id": wid},
                )
                break
        else:
            raise RuntimeError(
                "SQLite migration: could not assign unique workflow short_code"
            )

    sync_conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_workflows_org_short_code "
            "ON workflows (org_id, short_code)"
        )
    )
    _log.info("SQLite: added workflows.short_code and assigned unique codes")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db.base import Base
    from app.db.session import async_session_factory, engine
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sqlite_add_org_user_otp_columns)
        await conn.run_sync(_sqlite_org_workspace_columns)
        await conn.run_sync(_sqlite_workflows_short_code)

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
    assistant,
    audit_logs,
    auth,
    consent,
    dashboard,
    kyc_data,
    org,
    sdk_demo,
    tier_profiles,
    verification_live,
    verifications,
    webhooks,
    workflows,
)

PREFIX = settings.API_V1_PREFIX
app.include_router(auth.router, prefix=PREFIX)
app.include_router(org.router, prefix=PREFIX)
app.include_router(sdk_demo.router, prefix=PREFIX)
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
app.include_router(assistant.router, prefix=PREFIX)


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
