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
    app.state.settings = settings
    app.state.repo = SqliteRepository(conn)
    try:
        yield
    finally:
        conn.close()


app = FastAPI(title="heimlich · Waage", lifespan=lifespan)
app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    s = app.state.settings
    info = {
        "status": "ok",
        "schema_version": schema_version(app.state.repo.conn),
        "auth_mode": s.auth_mode,
    }
    if s.auth_mode == "none":  # Pfade nur im lokalen Betrieb zeigen
        info.update(data_dir=str(s.data_dir), db_file=s.db_file)
    return info


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
