# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Правилата на закона за поставянето на хора в смени (Росен 15.10.2026: „искам да
видиш закона … да вградиш в алгоритъма как се слагат хората“).

Източници (claude.ai/specs/poligroup-crew-rotation/LEGAL.md): Кодекс на труда — чл. 140,
140а, 141, 142, 146, 147, 152, 153; Наредба за работното време, почивките и отпуските —
чл. 7, 9а–9г; Наредба за структурата и организацията на работната заплата — чл. 9, ал. 2.
Решение на Росен 15.10.2026: нарушенията само ПРЕДУПРЕЖДАВАТ; неподходящ заместник
се прескача.
"""
from datetime import datetime, time, timedelta

import pytz

NIGHT_START_HOUR = 22             # чл. 140, ал. 2 КТ — нощен е трудът от 22:00 до 06:00
NIGHT_END_HOUR = 6
NIGHT_COEFFICIENT = 1.143         # чл. 9а, ал. 4 НРВПО; чл. 9, ал. 2 НСОРЗ
NIGHT_CONVERSION_MIN_HOURS = 4.0  # превръщане само за смени с ≥ 4 ч нощен труд (чл. 9а, ал. 4)
NIGHT_WORKER_MIN_HOURS = 3.0      # чл. 140а, ал. 1 КТ — нощен работник при ≥ 3 ч в смяната
MIN_DAILY_REST_HOURS = 12.0       # чл. 152 КТ
MIN_WEEKLY_REST_HOURS = 36.0      # чл. 153, ал. 2 КТ (сумирано изчисляване)
MIN_WEEKLY_REST_SHIFT_CHANGE_HOURS = 24.0  # чл. 153, ал. 3 КТ (при смяна на смените)
MAX_WEEK_HOURS = 56.0             # чл. 142, ал. 6 КТ
MAX_OVERTIME_YEAR_HOURS = 150.0   # чл. 146, ал. 1 КТ (до 300 с колективен трудов договор)
ADULT_AGE = 18                    # чл. 140, ал. 4, т. 1 КТ


def local_bounds(start_utc, end_utc, tz_name):
    """UTC (без tz) → местно време (без tz)."""
    tz = pytz.timezone(tz_name or "Europe/Sofia")
    to_local = lambda dt: pytz.utc.localize(dt).astimezone(tz).replace(tzinfo=None)
    return to_local(start_utc), to_local(end_utc)


def night_hours(start_local, end_local):
    """Часовете в интервала, които са между 22:00 и 06:00 (местно време)."""
    total = 0.0
    day = start_local.date() - timedelta(days=1)
    while datetime.combine(day, time()) < end_local:
        night_from = datetime.combine(day, time(NIGHT_START_HOUR))
        night_to = datetime.combine(day + timedelta(days=1), time(NIGHT_END_HOUR))
        overlap = (min(end_local, night_to) - max(start_local, night_from)).total_seconds()
        if overlap > 0:
            total += overlap / 3600.0
        day += timedelta(days=1)
    return total


def converted_hours(start_local, end_local):
    """Часовете на смяната за сравнение с нормата: нощните ×1,143, ако са ≥ 4."""
    hours = (end_local - start_local).total_seconds() / 3600.0
    nights = night_hours(start_local, end_local)
    if nights >= NIGHT_CONVERSION_MIN_HOURS:
        hours += nights * (NIGHT_COEFFICIENT - 1.0)
    return hours


def age_on(birthday, day):
    if not birthday:
        return None
    return day.year - birthday.year - ((day.month, day.day) < (birthday.month, birthday.day))


def schedule_issues(intervals, start, end):
    """Почивките и седмичните часове за смяната [start, end) спрямо другите
    смени на човека `intervals` (списък от (start, end), UTC без tz, без самата
    смяна). Връща списък от кодове: rest, weekly_rest, week_hours."""
    issues = []
    others = sorted(i for i in intervals if not (i[0] == start and i[1] == end))
    for s, e in others:
        if s < end and e > start:
            issues.append("overlap")
            continue
        gap = (start - e).total_seconds() / 3600.0 if e <= start else (s - end).total_seconds() / 3600.0
        if gap < MIN_DAILY_REST_HOURS:
            issues.append("rest")
    # 56 ч и седмична почивка — в 7-дневния прозорец, който свършва с края на смяната
    window_from = end - timedelta(days=7)
    inside = sorted([(max(s, window_from), min(e, end)) for s, e in others + [(start, end)]
                     if e > window_from and s < end])
    worked = sum((e - s).total_seconds() for s, e in inside) / 3600.0
    if worked > MAX_WEEK_HOURS:
        issues.append("week_hours")
    longest, cursor = 0.0, window_from
    for s, e in inside:
        longest = max(longest, (s - cursor).total_seconds() / 3600.0)
        cursor = max(cursor, e)
    longest = max(longest, (end - cursor).total_seconds() / 3600.0)
    # 24–36 ч е позволено при смяна на смените (чл. 153, ал. 3) — цикълът сменя
    # смените (напр. Конфекция: 2-ра → 1-ва след 32 ч), затова само под 24 ч
    if longest < MIN_WEEKLY_REST_SHIFT_CHANGE_HOURS:
        issues.append("weekly_rest")
    return sorted(set(issues))
