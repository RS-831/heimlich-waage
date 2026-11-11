"""Kennzahlen, Prognose und Diagrammreihen aus den Einträgen eines Nutzers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Sequence

from app.analytics.trend import ewma, linear_fit, moving_average
from app.core.models import Entry, Goal

FORECAST_WINDOW_DAYS = 28   # Regression über den Trend der letzten 4 Wochen
FORECAST_MIN_POINTS = 7     # mindestens eine Woche Messwerte
FORECAST_MIN_SPAN_DAYS = 10
MAX_FORECAST_DAYS = 3 * 365
MIN_SLOPE = 0.002           # kg/Tag; flacher gilt als "stabil", keine Zieldatumsprognose

BMI_CATEGORIES = [  # WHO, Obergrenze exklusiv
    (18.5, "Untergewicht"),
    (25.0, "Normalgewicht"),
    (30.0, "Übergewicht"),
    (35.0, "Adipositas Grad I"),
    (40.0, "Adipositas Grad II"),
    (float("inf"), "Adipositas Grad III"),
]

TREND_METHODS = ("ewma", "sma7")


def bmi_category(bmi: float) -> str:
    return next(label for limit, label in BMI_CATEGORIES if bmi < limit)


def compute_trend(entries: Sequence[Entry], method: str = "ewma") -> list[float]:
    points = [(e.date, e.weight_kg) for e in entries]
    if method == "sma7":
        return moving_average(points, 7)
    if method == "ewma":
        return ewma(points)
    raise ValueError(f"Unbekannte Trendmethode: {method}")


def _value_on_or_before(days: list[date], values: list[float], day: date) -> float | None:
    """Wert des letzten Eintrags am oder vor ``day``."""
    result = None
    for d, v in zip(days, values):
        if d > day:
            break
        result = v
    return result


def _streak(days: list[date], today: date) -> int:
    """Aufeinanderfolgende Tage mit Eintrag, die heute oder gestern enden."""
    if not days or (today - days[-1]).days > 1:
        return 0
    count = 1
    for prev, cur in zip(reversed(days[:-1]), reversed(days)):
        if (cur - prev).days != 1:
            break
        count += 1
    return count


@dataclass
class Forecast:
    slope_kg_per_day: float
    rate_kg_per_week: float
    line: list[dict] = field(default_factory=list)  # gestrichelte Prognoselinie
    goal_date: str | None = None                    # voraussichtliches Erreichen des Ziels


def summarize(
    entries: Sequence[Entry],
    *,
    height_cm: float | None = None,
    goal: Goal | None = None,
    method: str = "ewma",
    today: date | None = None,
) -> dict:
    today = today or date.today()
    trend = compute_trend(entries, method)
    series = [
        {
            "date": e.date.isoformat(),
            "weight": e.weight_kg,
            "trend": round(t, 3),
            "waist": e.waist_cm,
            "note": e.note,
        }
        for e, t in zip(entries, trend)
    ]
    result: dict = {"method": method, "series": series, "stats": None, "forecast": None,
                    "goal": None}
    if not entries:
        return result

    days = [e.date for e in entries]
    weights = [e.weight_kg for e in entries]
    last_day, trend_now = days[-1], trend[-1]

    def change(n: int) -> float | None:
        past = _value_on_or_before(days, trend, last_day - timedelta(days=n))
        return None if past is None else round(trend_now - past, 2)

    waists = [(e.date, e.waist_cm) for e in entries if e.waist_cm is not None]
    stats = {
        "current_weight": weights[-1],
        "current_date": last_day.isoformat(),
        "trend_weight": round(trend_now, 2),
        "change_7d": change(7),
        "change_30d": change(30),
        "change_total": round(trend_now - trend[0], 2),
        "start_date": days[0].isoformat(),
        "min_weight": min(weights),
        "max_weight": max(weights),
        "count": len(entries),
        "streak": _streak(days, today),
        "days_since_last": (today - last_day).days,
        "waist_current": waists[-1][1] if waists else None,
        "waist_change_total": round(waists[-1][1] - waists[0][1], 1) if len(waists) > 1 else None,
        "bmi": None,
        "bmi_category": None,
    }
    if height_cm:
        bmi = trend_now / (height_cm / 100) ** 2
        stats["bmi"] = round(bmi, 1)
        stats["bmi_category"] = bmi_category(bmi)
    result["stats"] = stats

    # Prognose: Regression über den Trend des letzten Fensters
    window_start = last_day - timedelta(days=FORECAST_WINDOW_DAYS)
    recent = [(d, t) for d, t in zip(days, trend) if d >= window_start]
    forecast: Forecast | None = None
    if len(recent) >= FORECAST_MIN_POINTS and (recent[-1][0] - recent[0][0]).days >= FORECAST_MIN_SPAN_DAYS:
        fit = linear_fit(recent)
        if fit:
            slope, at_last = fit
            forecast = Forecast(slope_kg_per_day=round(slope, 4),
                                rate_kg_per_week=round(slope * 7, 2))
            stats["rate_kg_per_week"] = forecast.rate_kg_per_week
    if "rate_kg_per_week" not in stats:
        stats["rate_kg_per_week"] = None

    if goal:
        g = _goal_status(goal, trend_now, last_day, forecast, today)
        result["goal"] = g
    if forecast:
        horizon = 30
        if result["goal"] and result["goal"].get("projected_date"):
            projected = date.fromisoformat(result["goal"]["projected_date"])
            horizon = max(horizon, (projected - last_day).days)
        if goal and goal.target_date:
            horizon = max(horizon, (goal.target_date - last_day).days)
        horizon = min(horizon, MAX_FORECAST_DAYS)
        forecast.line = [
            {"date": last_day.isoformat(), "weight": round(trend_now, 2)},
            {"date": (last_day + timedelta(days=horizon)).isoformat(),
             "weight": round(trend_now + forecast.slope_kg_per_day * horizon, 2)},
        ]
        forecast.goal_date = result["goal"]["projected_date"] if result["goal"] else None
        result["forecast"] = asdict(forecast)
    return result


def _goal_status(goal: Goal, trend_now: float, last_day: date, forecast: Forecast | None,
                 today: date) -> dict:
    target, start = goal.target_weight_kg, goal.start_weight_kg
    losing = target < start
    total = start - target
    done = (start - trend_now) if losing else (trend_now - start)
    progress = 100.0 if total == 0 else max(0.0, min(100.0, done / abs(total) * 100))
    reached = trend_now <= target if losing else trend_now >= target

    status = {
        "target_weight_kg": target,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "start_date": goal.start_date.isoformat(),
        "start_weight_kg": start,
        "remaining_kg": round(trend_now - target, 2),
        "progress_pct": round(progress, 1),
        "reached": reached,
        "projected_date": None,
        "required_rate_kg_per_week": None,
        "on_track": None,
    }
    if reached:
        return status

    if forecast and abs(forecast.slope_kg_per_day) >= MIN_SLOPE:
        days_needed = (target - trend_now) / forecast.slope_kg_per_day
        if 0 < days_needed <= MAX_FORECAST_DAYS:
            status["projected_date"] = (last_day + timedelta(days=round(days_needed))).isoformat()

    if goal.target_date:
        days_left = (goal.target_date - today).days
        if days_left > 0:
            status["required_rate_kg_per_week"] = round((target - trend_now) / days_left * 7, 2)
        if status["projected_date"]:
            status["on_track"] = date.fromisoformat(status["projected_date"]) <= goal.target_date
        else:
            status["on_track"] = False if forecast else None
    return status
