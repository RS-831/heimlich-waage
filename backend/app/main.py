"""Einstiegspunkt der FastAPI-App. Liefert API und Frontend aus."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings
from app.storage.db import connect, schema_version
from app.storage.repository import SqliteRepository

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect(settings.db_path)
    app.state.repo = SqliteRepository(conn)
    try:
        yield
    finally:
        conn.close()


app = FastAPI(title="heimlich · Waage", lifespan=lifespan)
app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "data_dir": str(settings.data_dir),
        "db_file": settings.db_file,
        "schema_version": schema_version(app.state.repo.conn),
        "auth_mode": settings.auth_mode,
    }


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
