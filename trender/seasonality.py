"""Kalendarz okazji sprzedażowych w Polsce i sezonowe wzmocnienie trendów.

Każde wydarzenie ma okno sprzedaży: zaczyna się kilka tygodni przed datą (czas na
wydruk, wystawienie i wysyłkę) i kończy kilka dni przed nią (ostatni termin dostawy).
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class Event(BaseModel):
    tag: str
    name: str
    date: dt.date
    window_start: dt.date
    window_end: dt.date


def easter(year: int) -> dt.date:
    """Data Wielkanocy (algorytm Meeusa/Jonesa/Butchera)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _black_friday(year: int) -> dt.date:
    d = dt.date(year, 11, 30)
    while d.weekday() != 4:
        d -= dt.timedelta(days=1)
    return d


def events_for_year(year: int) -> list[Event]:
    D = dt.date
    w = dt.timedelta

    def ev(tag, name, date, before_days, after_days=-2):
        return Event(tag=tag, name=name, date=date, window_start=date - w(days=before_days),
                     window_end=date + w(days=after_days))

    e = easter(year)
    bf = _black_friday(year)
    return [
        ev("valentines", "Walentynki", D(year, 2, 14), 45),
        ev("womens_day", "Dzień Kobiet", D(year, 3, 8), 21),
        ev("easter", "Wielkanoc", e, 42, -4),
        ev("mothers_day", "Dzień Matki", D(year, 5, 26), 35, -3),
        ev("childrens_day", "Dzień Dziecka", D(year, 6, 1), 30, -3),
        ev("fathers_day", "Dzień Ojca", D(year, 6, 23), 30, -3),
        Event(tag="summer", name="Lato / wakacje", date=D(year, 7, 15), window_start=D(year, 5, 15),
              window_end=D(year, 8, 20)),
        ev("back_to_school", "Powrót do szkoły", D(year, 9, 1), 35, 10),
        ev("halloween", "Halloween", D(year, 10, 31), 50, -3),
        ev("black_friday", "Black Friday", bf, 21, 3),
        ev("christmas", "Boże Narodzenie", D(year, 12, 24), 70, -6),
        ev("new_year", "Sylwester", D(year, 12, 31), 21, -2),
    ]


def upcoming(today: dt.date | None = None, days: int = 120) -> list[dict]:
    today = today or dt.date.today()
    out = []
    for year in (today.year, today.year + 1):
        for e in events_for_year(year):
            if e.window_end < today or (e.window_start - today).days > days:
                continue
            out.append({
                "tag": e.tag, "name": e.name, "date": e.date.isoformat(),
                "days_to_event": (e.date - today).days,
                "window_start": e.window_start.isoformat(), "window_end": e.window_end.isoformat(),
                "in_window": e.window_start <= today <= e.window_end,
                "boost": round(event_boost(e, today), 2),
            })
    return sorted(out, key=lambda x: x["date"])


def event_boost(e: Event, today: dt.date) -> float:
    """0-1: rośnie od początku okna do szczytu (ok. 10 dni przed wydarzeniem), potem spada."""
    if not (e.window_start <= today <= e.window_end):
        # tuż przed oknem: czas zacząć drukować zapasy
        lead = (e.window_start - today).days
        return 0.3 if 0 < lead <= 14 else 0.0
    peak = e.date - dt.timedelta(days=10)
    if today <= peak:
        span = max((peak - e.window_start).days, 1)
        return 0.5 + 0.5 * (today - e.window_start).days / span
    span = max((e.window_end - peak).days, 1)
    return 1.0 - 0.5 * (today - peak).days / span


def season_boost(tags: list[str], today: dt.date | None = None) -> tuple[float, str | None]:
    """Największe wzmocnienie spośród tagów produktu i nazwa wydarzenia, które je daje."""
    today = today or dt.date.today()
    if "all_year" in tags and len(tags) == 1:
        return 0.4, None
    best, name = (0.4, None) if "all_year" in tags else (0.0, None)
    for year in (today.year, today.year + 1):
        for e in events_for_year(year):
            if e.tag in tags:
                b = event_boost(e, today)
                if b > best:
                    best, name = b, e.name
    return best, name
