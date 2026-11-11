"""Trendberechnung. Reines Python, ohne Framework-Abhängigkeiten.

Eingabe ist immer eine nach Datum sortierte Liste von (Datum, Gewicht).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

Point = tuple[date, float]

EWMA_FACTOR = 0.1  # "Hacker's Diet": 10 % des neuen Werts fließen in den Trend


def ewma(points: Sequence[Point], factor: float = EWMA_FACTOR) -> list[float]:
    """Exponentiell geglätteter Trend, ein Wert je Eingabepunkt.

    Fehlende Tage werden linear zwischen den Nachbarwerten aufgefüllt und täglich geglättet,
    damit Lücken den Trend weder einfrieren noch einen einzelnen Wert übergewichten.
    Der Trend startet beim ersten Messwert.
    """
    if not points:
        return []
    result = [points[0][1]]
    trend = points[0][1]
    for (prev_day, prev_w), (day, w) in zip(points, points[1:]):
        gap = (day - prev_day).days
        for step in range(1, gap + 1):
            value = prev_w + (w - prev_w) * step / gap
            trend += factor * (value - trend)
        result.append(trend)
    return result


def moving_average(points: Sequence[Point], days: int = 7) -> list[float]:
    """Durchschnitt aller Messwerte der letzten ``days`` Kalendertage (inkl. des Tags selbst)."""
    result: list[float] = []
    start = 0
    total = 0.0
    for i, (day, w) in enumerate(points):
        total += w
        while points[start][0] <= day - timedelta(days=days):
            total -= points[start][1]
            start += 1
        result.append(total / (i - start + 1))
    return result


def linear_fit(points: Sequence[Point]) -> tuple[float, float] | None:
    """Kleinste-Quadrate-Gerade: (Steigung kg/Tag, Wert am letzten Tag)."""
    if len(points) < 2:
        return None
    origin = points[-1][0]
    xs = [(d - origin).days for d, _ in points]
    ys = [w for _, w in points]
    n = len(points)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return slope, my - slope * mx
