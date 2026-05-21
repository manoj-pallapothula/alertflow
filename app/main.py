from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.database import engine, Base
from app.routers.ingest import router as ingest_router
from app.routers.dashboard import router as dashboard_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup and shutdown.
    Creates all tables if they don't exist yet.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("\n🚀 AlertFlow is running!")
    print("📖 API docs: http://localhost:8000/docs\n")
    yield
    print("\n👋 AlertFlow shutting down...")


app = FastAPI(
    title="AlertFlow",
    description="Intelligent alert routing engine",
    version="0.1.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(ingest_router)
app.include_router(dashboard_router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "AlertFlow",
        "version": "0.1.0",
        "status": "running",
        "docs": "http://localhost:8000/docs",
        "endpoints": {
            "ingest_prometheus": "POST /ingest/prometheus",
            "ingest_pagerduty": "POST /ingest/pagerduty",
            "dashboard_summary": "GET /dashboard/summary",
            "dashboard_alerts": "GET /dashboard/alerts",
        }
    }


@app.get("/health", tags=["Root"])
async def health():
    return {"status": "ok"}