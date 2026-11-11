"""REST-API. Alle Endpunkte arbeiten auf dem Nutzer aus ``current_user``."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.analytics.summary import TREND_METHODS, summarize
from app.core.models import Entry, Goal, User
from app.importers.csv_format import parse_csv, to_csv, validate_waist, validate_weight
from app.storage.repository import Repository

router = APIRouter(prefix="/api")

MAX_IMPORT_BYTES = 5 * 1024 * 1024


# --- Abhängigkeiten -----------------------------------------------------------
def get_repo(request: Request) -> Repository:
    return request.app.state.repo


def current_user(repo: Annotated[Repository, Depends(get_repo)]) -> User:
    """Phase 1 (AUTH_MODE=none): immer der Standardnutzer. Später: Nutzer aus der Session."""
    return repo.default_user()


Repo = Annotated[Repository, Depends(get_repo)]
CurrentUser = Annotated[User, Depends(current_user)]


# --- Schemas ------------------------------------------------------------------
class EntryIn(BaseModel):
    weight_kg: float
    waist_cm: float | None = None
    note: str = Field(default="", max_length=500)

    @field_validator("weight_kg")
    @classmethod
    def _weight(cls, v: float) -> float:
        validate_weight(v)
        return round(v, 2)

    @field_validator("waist_cm")
    @classmethod
    def _waist(cls, v: float | None) -> float | None:
        if v is not None:
            validate_waist(v)
            return round(v, 1)
        return v


class EntryOut(BaseModel):
    date: date
    weight_kg: float
    waist_cm: float | None
    note: str
    source: str


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    height_cm: float | None = Field(default=None, ge=100, le=250)


class ProfileOut(BaseModel):
    name: str
    height_cm: float | None
    role: str


class GoalIn(BaseModel):
    target_weight_kg: float
    target_date: date | None = None

    @field_validator("target_weight_kg")
    @classmethod
    def _weight(cls, v: float) -> float:
        validate_weight(v)
        return round(v, 1)


def _entry_out(e: Entry) -> EntryOut:
    return EntryOut(date=e.date, weight_kg=e.weight_kg, waist_cm=e.waist_cm, note=e.note,
                    source=e.source)


# --- Einträge -----------------------------------------------------------------
@router.get("/entries", response_model=list[EntryOut])
def list_entries(repo: Repo, user: CurrentUser):
    return [_entry_out(e) for e in reversed(repo.list_entries(user.id))]


@router.get("/entries/{day}", response_model=EntryOut)
def get_entry(day: date, repo: Repo, user: CurrentUser):
    entry = repo.get_entry(user.id, day)
    if not entry:
        raise HTTPException(404, "Kein Eintrag an diesem Tag")
    return _entry_out(entry)


@router.put("/entries/{day}", response_model=EntryOut)
def put_entry(day: date, data: EntryIn, repo: Repo, user: CurrentUser):
    """Legt den Eintrag für ``day`` an oder überschreibt ihn (ein Wert pro Tag)."""
    # +1 Tag Toleranz: der Server läuft evtl. in UTC, der Browser in lokaler Zeit
    if day > date.today() + timedelta(days=1):
        raise HTTPException(422, "Datum liegt in der Zukunft")
    entry = Entry(date=day, weight_kg=data.weight_kg, waist_cm=data.waist_cm,
                  note=data.note.strip(), source="manual")
    return _entry_out(repo.upsert_entry(user.id, entry))


@router.delete("/entries/{day}", status_code=204)
def delete_entry(day: date, repo: Repo, user: CurrentUser):
    if not repo.delete_entry(user.id, day):
        raise HTTPException(404, "Kein Eintrag an diesem Tag")
    return Response(status_code=204)


# --- Auswertung ---------------------------------------------------------------
@router.get("/summary")
def get_summary(repo: Repo, user: CurrentUser,
                method: Annotated[str, Query(pattern="^(" + "|".join(TREND_METHODS) + ")$")] = "ewma",
                today: date | None = None):
    """``today`` übergibt der Browser (lokales Datum), sonst gilt das Serverdatum."""
    return summarize(repo.list_entries(user.id), height_cm=user.height_cm,
                     goal=repo.get_goal(user.id), method=method, today=today)


# --- Profil -------------------------------------------------------------------
@router.get("/profile", response_model=ProfileOut)
def get_profile(user: CurrentUser):
    return ProfileOut(name=user.name, height_cm=user.height_cm, role=user.role)


@router.put("/profile", response_model=ProfileOut)
def put_profile(data: ProfileIn, repo: Repo, user: CurrentUser):
    updated = repo.update_profile(user.id, name=data.name.strip(), height_cm=data.height_cm)
    return ProfileOut(name=updated.name, height_cm=updated.height_cm, role=updated.role)


# --- Ziel ---------------------------------------------------------------------
@router.get("/goal")
def get_goal(repo: Repo, user: CurrentUser):
    goal = repo.get_goal(user.id)
    return None if goal is None else {
        "target_weight_kg": goal.target_weight_kg,
        "target_date": goal.target_date,
        "start_date": goal.start_date,
        "start_weight_kg": goal.start_weight_kg,
    }


@router.put("/goal")
def put_goal(data: GoalIn, repo: Repo, user: CurrentUser):
    """Setzt ein neues Ziel. Startpunkt ist das aktuelle Trendgewicht."""
    if data.target_date and data.target_date <= date.today():
        raise HTTPException(422, "Zieldatum muss in der Zukunft liegen")
    entries = repo.list_entries(user.id)
    if not entries:
        raise HTTPException(409, "Bitte zuerst mindestens ein Gewicht eintragen")
    trend = summarize(entries)["stats"]["trend_weight"]
    goal = Goal(target_weight_kg=data.target_weight_kg, target_date=data.target_date,
                start_date=entries[-1].date, start_weight_kg=trend)
    repo.set_goal(user.id, goal)
    return get_goal(repo, user)


@router.delete("/goal", status_code=204)
def delete_goal(repo: Repo, user: CurrentUser):
    repo.clear_goal(user.id)
    return Response(status_code=204)


# --- CSV ----------------------------------------------------------------------
@router.get("/export.csv")
def export_csv(repo: Repo, user: CurrentUser):
    body = "﻿" + to_csv(repo.list_entries(user.id))  # BOM: Excel erkennt UTF-8
    filename = f"gewicht-{date.today().isoformat()}.csv"
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/import")
async def import_csv(request: Request, repo: Repo, user: CurrentUser,
                     overwrite: bool = False, dry_run: bool = False):
    """Erwartet den CSV-Text direkt im Body (Content-Type text/csv)."""
    raw = await request.body()
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "Datei ist größer als 5 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    parsed = parse_csv(text)
    errors = [{"line": e.line, "message": e.message} for e in parsed.errors]
    if not parsed.entries:
        raise HTTPException(422, {"message": "Keine gültigen Zeilen gefunden", "errors": errors})
    if dry_run:
        return {"valid": len(parsed.entries), "errors": errors}
    counts = repo.import_entries(user.id, parsed.entries, overwrite=overwrite)
    return {**counts, "errors": errors}
