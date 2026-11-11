"""CSV-Import und -Export.

Export: ``date;weight_kg;waist_cm;note`` mit Semikolon und Dezimalkomma (öffnet sich in einem
deutschen Excel/LibreOffice direkt richtig). Der Import ist toleranter: Komma oder Semikolon als
Trenner, Punkt oder Komma als Dezimalzeichen, Datum als ``2026-11-11`` oder ``11.11.2026``,
deutsche oder englische Spaltennamen.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Iterable

from app.core.models import Entry
from app.importers.base import ImportError_, ImportResult

COLUMN_ALIASES = {
    "date": {"date", "datum", "tag", "day"},
    "weight_kg": {"weight_kg", "weight", "gewicht", "gewicht_kg", "kg"},
    "waist_cm": {"waist_cm", "waist", "bauchumfang", "bauchumfang_cm", "taille"},
    "note": {"note", "notiz", "bemerkung", "kommentar", "comment"},
}
DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%Y/%m/%d")


def _parse_date(text: str) -> date:
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    # Zeitstempel wie "2026-11-11 07:12" oder "2026-11-11T07:12:00"
    try:
        return datetime.fromisoformat(text.replace(" ", "T")).date()
    except ValueError:
        raise ValueError(f"Datum nicht erkannt: {text!r}") from None


def _parse_number(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    return float(text.strip().replace(" ", "").replace(",", "."))


def _normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("(", "").replace(")", "").lstrip("﻿")


def parse_csv(text: str, source: str = "csv") -> ImportResult:
    lines = text.strip().splitlines()
    if not lines:
        return ImportResult(entries=[], errors=[ImportError_(0, "Datei ist leer.")])
    header = lines[0]
    delimiter = ";" if header.count(";") >= header.count(",") and ";" in header else ","
    reader = csv.reader(io.StringIO(text.strip()), delimiter=delimiter)
    raw_header = next(reader)

    mapping: dict[str, int] = {}
    for idx, name in enumerate(raw_header):
        norm = _normalize(name)
        for field, aliases in COLUMN_ALIASES.items():
            if norm in aliases and field not in mapping:
                mapping[field] = idx
    missing = [f for f in ("date", "weight_kg") if f not in mapping]
    if missing:
        return ImportResult(entries=[], errors=[ImportError_(
            1, "Spalten fehlen: " + ", ".join(missing)
               + f". Gefunden: {', '.join(raw_header)}. Erwartet z. B. 'date;weight_kg;waist_cm;note'.")])

    by_date: dict[date, Entry] = {}
    errors: list[ImportError_] = []
    for line_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue

        def cell(field: str) -> str | None:
            i = mapping.get(field)
            return row[i] if i is not None and i < len(row) else None

        try:
            day = _parse_date(cell("date") or "")
            weight = _parse_number(cell("weight_kg"))
            if weight is None:
                raise ValueError("Gewicht fehlt")
            validate_weight(weight)
            waist = _parse_number(cell("waist_cm"))
            if waist is not None:
                validate_waist(waist)
        except ValueError as exc:
            errors.append(ImportError_(line_no, str(exc)))
            continue
        # Mehrere Werte am selben Tag: der letzte in der Datei gilt
        by_date[day] = Entry(date=day, weight_kg=round(weight, 2), waist_cm=waist,
                             note=(cell("note") or "").strip(), source=source)
    return ImportResult(entries=sorted(by_date.values(), key=lambda e: e.date), errors=errors)


def validate_weight(weight: float) -> None:
    if not 20 <= weight <= 400:
        raise ValueError(f"Gewicht {weight} kg ist unplausibel (20–400 kg)")


def validate_waist(waist: float) -> None:
    if not 30 <= waist <= 250:
        raise ValueError(f"Bauchumfang {waist} cm ist unplausibel (30–250 cm)")


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}".replace(".", ",")


def to_csv(entries: Iterable[Entry]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(["date", "weight_kg", "waist_cm", "note"])
    for e in entries:
        writer.writerow([e.date.isoformat(), _fmt(e.weight_kg), _fmt(e.waist_cm), e.note])
    return out.getvalue()
