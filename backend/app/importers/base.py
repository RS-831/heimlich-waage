"""Gemeinsame Schnittstelle für alle Importquellen.

Ein Importer wandelt fremde Daten (CSV, später Withings-API, Garmin- oder Apple-Health-Export)
in ``Entry``-Objekte mit gesetztem ``source`` um. Das Speichern übernimmt
``Repository.import_entries`` – ein neuer Importer muss also nur parsen.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.models import Entry


@dataclass(frozen=True)
class ImportError_:
    line: int
    message: str


@dataclass
class ImportResult:
    entries: list[Entry]
    errors: list[ImportError_] = field(default_factory=list)
