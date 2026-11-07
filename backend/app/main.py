import asyncio, logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings,validate_runtime
from app.database import Base,engine
from app.routers import auth,applications,documents,ai,reviewer,admin,bank_admin,bank_registration,customer
from app.models import PlatformAdmin
from sqlalchemy import select, func
from app.migrations.runner import run_migrations
validate_runtime()
Base.metadata.create_all(bind=engine)
run_migrations()
# Provision the configured Platform Admin from backend environment only; no UI registration or password is involved.
if settings.initial_admin_email.strip():
    from app.database import SessionLocal
    with SessionLocal() as bootstrap_db:
        email = settings.initial_admin_email.strip().casefold()
        if "@" not in email:
            raise RuntimeError("INITIAL_ADMIN_EMAIL must be a valid email address.")
        if not bootstrap_db.scalar(select(PlatformAdmin.id).where(func.lower(PlatformAdmin.email) == email)):
            bootstrap_db.add(PlatformAdmin(full_name=settings.initial_admin_name.strip() or "Platform Admin", email=email, password_hash="otp-only", is_active=True))
            bootstrap_db.commit()
Path(settings.uploads_dir).mkdir(parents=True,exist_ok=True)
@asynccontextmanager
async def lifespan(_app):
    """Safety net: periodically retry applications awaiting reviewer assignment (idempotent; DB constraints prevent duplicates)."""
    from app.services.assignment import run_retry_cycle
    interval=settings.assignment_retry_interval_seconds
    async def loop():
        while True:
            try: await asyncio.to_thread(run_retry_cycle)
            except Exception: logging.getLogger("assignment").exception("Assignment retry cycle failed")
            await asyncio.sleep(interval)
    task=asyncio.create_task(loop()) if interval and interval>0 else None
    try: yield
    finally:
        if task: task.cancel()
app=FastAPI(title=settings.app_name,version="0.1.0",lifespan=lifespan)
frontend_origins=[settings.frontend_origin.rstrip("/")]
frontend_url=urlsplit(settings.frontend_origin)
if frontend_url.hostname in {"localhost", "127.0.0.1"}:
    loopback_alias="127.0.0.1" if frontend_url.hostname == "localhost" else "localhost"
    loopback_port=f":{frontend_url.port}" if frontend_url.port else ""
    frontend_origins.append(f"{frontend_url.scheme}://{loopback_alias}{loopback_port}")
@app.middleware("http")
async def security_headers(request,call_next):
    r=await call_next(request)
    r.headers.setdefault("X-Content-Type-Options","nosniff");r.headers.setdefault("X-Frame-Options","DENY");r.headers.setdefault("Referrer-Policy","no-referrer")
    return r
prefix="/api/v1"
app.include_router(auth.router,prefix=prefix)
app.include_router(customer.router,prefix=prefix)
app.include_router(applications.router,prefix=prefix)
app.include_router(documents.router,prefix=prefix)
app.include_router(ai.router,prefix=prefix)
app.include_router(reviewer.router,prefix=prefix)
app.include_router(admin.router,prefix=prefix)
app.include_router(bank_admin.router,prefix=prefix)
app.include_router(bank_registration.router,prefix=prefix)
@app.get("/health")
def health(): return {"status":"ok","phase":"integrated"}
@app.get("/api/v1/health")
def api_health(): return {"status":"ok","phase":"integrated"}

@app.get("/healthz")
def healthz(): return {"status":"ok","phase":"integrated"}

# Wrap the complete FastAPI application so even unhandled 500 responses receive
# CORS headers. Middleware registered with add_middleware sits inside Starlette's
# ServerErrorMiddleware, which can otherwise generate a response outside CORS.
app=CORSMiddleware(app,allow_origins=frontend_origins,allow_credentials=True,allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],allow_headers=["*"])
