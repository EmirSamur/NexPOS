"""
Vardiya ve mesai hesapları (9. ekran).

Sunucudaki karşılığı firebase/functions/src/shifts.js'tir; ikisi de
firebase/functions/test/shift_vectors.json'daki ortak senaryolarla test edilir.
Saatler terminalin yerel saatidir (ISO'nun ilk 19 karakteri). Süreler dakikadır.
"""
from datetime import datetime, timedelta

DAY_START_HOUR = 5
WEEKLY_LIMIT_MINUTES = 45 * 60
LEAVE_TYPES = {'annual': 'Yıllık izin', 'sick': 'Rapor', 'unpaid': 'Ücretsiz izin', 'holiday': 'Resmi tatil'}
_EPOCH = datetime(1970, 1, 1)


def local_minutes(iso):
    return (datetime.fromisoformat(iso[:19]) - _EPOCH).total_seconds() / 60


def business_day_of(iso):
    return (datetime.fromisoformat(iso[:19]) - timedelta(hours=DAY_START_HOUR)).strftime('%Y-%m-%d')


def hm(text):
    h, m = text.split(':')
    return int(h) * 60 + int(m)


def plan_window(plan):
    if not plan or plan.get('leave') or not plan.get('start') or not plan.get('end'):
        return None
    day = (datetime.fromisoformat(plan['date']) - _EPOCH).total_seconds() / 60
    start = day + hm(plan['start'])
    if hm(plan['start']) < DAY_START_HOUR * 60:
        start += 24 * 60
    end = day + hm(plan['end'])
    if hm(plan['end']) < DAY_START_HOUR * 60:
        end += 24 * 60
    if end <= start:
        end += 24 * 60
    return start, end


def planned_minutes(plan):
    w = plan_window(plan)
    return max(int(w[1] - w[0]) - (plan.get('breakMinutes') or 0), 0) if w else 0


def late_minutes(plan, clock_in, tolerance):
    w = plan_window(plan)
    if not w or not clock_in:
        return 0
    diff = int((local_minutes(clock_in) - w[0]) // 1)
    return diff if diff > tolerance else 0


def break_minutes(entry, plan):
    breaks = entry.get('breaks') or []
    end = entry.get('clockOut')
    if breaks:
        # süren mola (mesai de sürüyorsa) henüz sayılmaz
        return sum(max(int((local_minutes(b.get('end') or end) - local_minutes(b['start'])) // 1), 0)
                   for b in breaks if b.get('end') or end)
    if not end:
        return 0
    gross = int((local_minutes(end) - local_minutes(entry['clockIn'])) // 1)
    planned = (plan.get('breakMinutes') or 0) if plan and not plan.get('leave') else 0
    return min(planned, gross // 2)


def worked_minutes(entry, plan):
    if not entry or not entry.get('clockIn') or not entry.get('clockOut'):
        return 0
    gross = int((local_minutes(entry['clockOut']) - local_minutes(entry['clockIn'])) // 1)
    return max(gross - break_minutes(entry, plan), 0)


def overtime_minutes(week_worked):
    return max(week_worked - WEEKLY_LIMIT_MINUTES, 0)


def format_minutes(minutes):
    """475 → '7 sa 55 dk', 480 → '8 sa', 15 → '15 dk'"""
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} sa {m} dk"
    return f"{h} sa" if h else f"{m} dk"
