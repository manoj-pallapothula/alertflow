from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.db.database import engine, Base
from app.routers.ingest import router as ingest_router
from app.routers.dashboard import router as dashboard_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("\n🚀 AlertFlow is running!")
    print("📖 API docs:  http://localhost:8000/docs")
    print("📊 Dashboard: http://localhost:8000/ui\n")
    yield
    print("\n👋 AlertFlow shutting down...")


app = FastAPI(
    title="AlertFlow",
    description="Intelligent alert routing engine",
    version="0.1.0",
    lifespan=lifespan,
)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register routers
app.include_router(ingest_router)
app.include_router(dashboard_router)


@app.get("/ui")
async def dashboard_ui():
    return FileResponse("static/dashboard.html")


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "AlertFlow",
        "version": "0.1.0",
        "status": "running",
        "docs": "http://localhost:8000/docs",
        "dashboard": "http://localhost:8000/ui",
    }


@app.get("/health", tags=["Root"])
async def health():
    return {"status": "ok"}