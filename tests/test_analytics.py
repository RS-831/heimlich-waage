from datetime import date, timedelta

import pytest

from app.analytics.summary import bmi_category, summarize
from app.analytics.trend import ewma, linear_fit, moving_average
from app.core.models import Entry, Goal

D0 = date(2026, 1, 1)


def entries(weights, start=D0, step=1):
    return [Entry(date=start + timedelta(days=i * step), weight_kg=w) for i, w in enumerate(weights)]


def test_ewma_constant_and_step():
    pts = [(D0 + timedelta(days=i), 80.0) for i in range(5)]
    assert ewma(pts) == [80.0] * 5
    pts = [(D0, 80.0), (D0 + timedelta(days=1), 90.0)]
    assert ewma(pts) == [80.0, pytest.approx(81.0)]


def test_ewma_gap_is_interpolated():
    # 2 Tage Lücke: wie zwei tägliche Werte 85 und 90
    gap = ewma([(D0, 80.0), (D0 + timedelta(days=2), 90.0)])
    daily = ewma([(D0, 80.0), (D0 + timedelta(days=1), 85.0), (D0 + timedelta(days=2), 90.0)])
    assert gap[-1] == pytest.approx(daily[-1])


def test_moving_average_uses_calendar_window():
    pts = [(D0, 80.0), (D0 + timedelta(days=1), 82.0), (D0 + timedelta(days=7), 90.0)]
    assert moving_average(pts, 7) == [80.0, 81.0, 86.0]  # Tag 0 fällt aus dem Fenster


def test_linear_fit():
    pts = [(D0 + timedelta(days=i), 100 - 0.1 * i) for i in range(10)]
    slope, at_last = linear_fit(pts)
    assert slope == pytest.approx(-0.1)
    assert at_last == pytest.approx(99.1)
    assert linear_fit(pts[:1]) is None


def test_summary_empty():
    s = summarize([])
    assert s["series"] == [] and s["stats"] is None


def test_summary_stats_and_streak():
    es = entries([90, 89.8, 89.6, 89.4, 89.2])
    s = summarize(es, height_cm=180, today=es[-1].date)
    st = s["stats"]
    assert st["count"] == 5
    assert st["streak"] == 5
    assert st["current_weight"] == 89.2
    assert st["min_weight"] == 89.2 and st["max_weight"] == 90
    assert st["bmi"] == pytest.approx(round(st["trend_weight"] / 1.8 ** 2, 1))
    assert st["bmi_category"] == "Übergewicht"
    assert st["change_7d"] is None  # keine Werte vor 7 Tagen
    assert s["forecast"] is None   # zu wenige Daten
    assert summarize(es, today=es[-1].date + timedelta(days=3))["stats"]["streak"] == 0


def test_forecast_and_goal_projection():
    es = entries([100 - 0.1 * i for i in range(80)])  # -0,7 kg/Woche, Trend eingeschwungen
    goal = Goal(target_weight_kg=85, target_date=es[-1].date + timedelta(days=200),
                start_date=D0, start_weight_kg=100)
    s = summarize(es, goal=goal, today=es[-1].date)
    assert s["forecast"]["rate_kg_per_week"] == pytest.approx(-0.7, abs=0.05)
    g = s["goal"]
    assert not g["reached"]
    assert 0 < g["progress_pct"] < 100
    projected = date.fromisoformat(g["projected_date"])
    assert es[-1].date < projected < goal.target_date
    assert g["on_track"] is True
    assert s["forecast"]["line"][-1]["date"] >= g["projected_date"]
    assert s["stats"]["change_30d"] == pytest.approx(-3.0, abs=0.3)


def test_goal_wrong_direction_has_no_projection():
    es = entries([80 + 0.1 * i for i in range(30)])  # nimmt zu
    goal = Goal(target_weight_kg=75, target_date=None, start_date=D0, start_weight_kg=80)
    g = summarize(es, goal=goal, today=es[-1].date)["goal"]
    assert g["projected_date"] is None
    assert g["progress_pct"] == 0


def test_goal_reached_and_gain_goal():
    es = entries([70, 70.5, 71, 71.5, 72] * 1)
    gain = Goal(target_weight_kg=70.2, target_date=None, start_date=D0, start_weight_kg=70)
    assert summarize(es, goal=gain)["goal"]["reached"] is True


def test_sma7_method():
    es = entries([80, 82])
    assert summarize(es, method="sma7")["series"][1]["trend"] == 81.0
    with pytest.raises(ValueError):
        summarize(es, method="foo")


@pytest.mark.parametrize("bmi,label", [(18.4, "Untergewicht"), (18.5, "Normalgewicht"),
                                       (29.9, "Übergewicht"), (41, "Adipositas Grad III")])
def test_bmi_category(bmi, label):
    assert bmi_category(bmi) == label
