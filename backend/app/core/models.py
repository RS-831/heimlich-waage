"""Fachliche Datentypen, unabhängig von Datenbank und Web-Framework."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class User:
    id: int
    name: str
    role: str
    height_cm: float | None
    unit: str = "kg"
    username: str | None = None  # Login-Name aus dem Proxy; None = noch keinem Login zugeordnet


@dataclass(frozen=True)
class Entry:
    date: date
    weight_kg: float
    waist_cm: float | None = None
    body_fat_pct: float | None = None
    note: str = ""
    source: str = "manual"


@dataclass(frozen=True)
class Goal:
    target_weight_kg: float
    target_date: date | None
    start_date: date
    start_weight_kg: float
