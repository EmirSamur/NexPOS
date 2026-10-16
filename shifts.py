"""
NexPOS - Vardiya ve mesai (9. ekran)

- Vardiya planı bulutta (shiftPlans/{personel_tarih}); panelden düzenlenir, buradan okunur.
- Mesai kayıtları (giriş/çıkış/mola) bu bilgisayarda tutulur ve kuyrukla (timeClock, timeEdit) buluta
  gider; internetsiz çalışır. Saat hesapları shifts_logic.py'dedir (sunucuyla ortak senaryolar).
- PIN girişi mesai değildir: mesai ayrıca başlatılır ve bitirilir.
"""
import json
import uuid
from datetime import date, datetime, timedelta

import database
import shifts_logic as L
from cloud.orders import OrderError

WEEKDAYS_SHORT = ('Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz')


def enabled():
    return database.modules()['staff']['enabled']


def tolerance():
    return database.modules()['staff']['lateToleranceMinutes']


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def today():
    return L.business_day_of(now_iso())


def week_start(day=None):
    d = date.fromisoformat(day or today())
    return (d - timedelta(days=d.weekday())).isoformat()


def week_days(start):
    s = date.fromisoformat(start)
    return [(s + timedelta(days=i)).isoformat() for i in range(7)]


# =====================================================================
# Plan
# =====================================================================

def plans(day_from, day_to, published_only=False):
    """{(staffId, tarih): plan} — silinmiş hücreler hariç."""
    out = {}
    for p in database.cache_rows('shiftPlans', include_deleted=True):
        if p.get('deleted') or not day_from <= p.get('date', '') <= day_to:
            continue
        if published_only and not p.get('published'):
            continue
        out[(p['staffId'], p['date'])] = p
    return out


def plan_for(staff_id, day):
    return plans(day, day).get((staff_id, day))


def plan_label(plan):
    if not plan:
        return ""
    if plan.get('leave'):
        return L.LEAVE_TYPES.get(plan['leave'], 'İzin')
    return f"{plan['start']}–{'24:00' if plan['end'] == '00:00' else plan['end']}"


# =====================================================================
# Mesai kayıtları
# =====================================================================

def _save(conn, entry):
    conn.execute("""INSERT INTO time_entries (id,staff_id,business_day,data,open) VALUES (?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET data=excluded.data, open=excluded.open, business_day=excluded.business_day""",
        (entry['id'], entry['staffId'], entry['businessDay'], json.dumps(entry, ensure_ascii=False),
         0 if entry.get('clockOut') else 1))


def entries(day_from, day_to, staff_id=None):
    conn = database.get_connection()
    q = "SELECT data FROM time_entries WHERE business_day BETWEEN ? AND ?"
    args = [day_from, day_to]
    if staff_id:
        q += " AND staff_id=?"
        args.append(staff_id)
    rows = conn.execute(q + " ORDER BY business_day, id", args).fetchall()
    conn.close()
    return [json.loads(r['data']) for r in rows]


def open_entry(staff_id):
    conn = database.get_connection()
    row = conn.execute("SELECT data FROM time_entries WHERE staff_id=? AND open=1 ORDER BY business_day DESC LIMIT 1",
                       (staff_id,)).fetchone()
    conn.close()
    return json.loads(row['data']) if row else None


def status(staff_id):
    """('working'|'break'|'off', kayıt ya da None)"""
    e = open_entry(staff_id)
    if not e:
        return 'off', None
    breaks = e.get('breaks') or []
    return ('break' if breaks and not breaks[-1].get('end') else 'working'), e


def clock(user, action, at=None, auto=False):
    """action: 'in' | 'out' | 'breakStart' | 'breakEnd'. Kaydı ve kuyruk işlemini aynı anda yazar."""
    at = at or now_iso()
    staff_id = user['cloud_id']
    state, e = status(staff_id)
    if action == 'in' and e and e['businessDay'] < L.business_day_of(at):
        auto_close_forgotten(at)  # dünden açık kalan mesai önce kapanır
        state, e = status(staff_id)
    if action == 'in':
        if e:
            raise OrderError("Mesai zaten başlamış.")
        day = L.business_day_of(at)
        e = {'id': 'TE' + uuid.uuid4().hex[:20], 'staffId': staff_id, 'businessDay': day, 'clockIn': at,
             'clockOut': None, 'breaks': [], 'flags': [],
             'late': L.late_minutes(plan_for(staff_id, day), at, tolerance())}
    else:
        if not e:
            raise OrderError("Mesai başlamamış.")
        breaks = e['breaks']
        open_break = bool(breaks) and not breaks[-1].get('end')
        if action == 'breakStart':
            if open_break:
                raise OrderError("Zaten moladasınız.")
            breaks.append({'start': at, 'end': None})
        elif action == 'breakEnd':
            if not open_break:
                raise OrderError("Molada değilsiniz.")
            breaks[-1]['end'] = at
        elif action == 'out':
            if open_break:
                breaks[-1]['end'] = at
            e['clockOut'] = at
            if auto:
                e['flags'] = e.get('flags', []) + ['forgotClockOut']
        else:
            raise OrderError("Mesai işlemi geçersiz.")
    conn = database.get_connection()
    try:
        _save(conn, e)
        payload = {'entryId': e['id'], 'action': action, 'at': at}
        if auto:
            payload['auto'] = True
        database.enqueue_op('timeClock', payload, staff_id, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return e


def _last_activity(staff_id, day):
    """Personelin o iş günündeki son işlemi (adisyona ekleme/ödeme)."""
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM pos_orders WHERE business_day=?", (day,)).fetchall()
    conn.close()
    times = []
    for r in rows:
        o = json.loads(r['data'])
        times += [l.get('addedAt') for l in o['items'] if l.get('addedBy') == staff_id]
        times += [p.get('at') for p in o['payments'] if p.get('by') == staff_id]
    return max((t for t in times if t), default=None)


def auto_close_forgotten(now=None):
    """
    İş günü bitmiş (05:00 geçmiş) açık mesaileri kapatır: planlanan bitiş saatiyle, plan yoksa son işlem
    saatiyle (o da yoksa giriş saatiyle). "Çıkış unutuldu" olarak işaretlenir. Kapatılan sayıyı döndürür.
    """
    current = L.business_day_of(now or now_iso())
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM time_entries WHERE open=1 AND business_day<?", (current,)).fetchall()
    conn.close()
    closed = 0
    for r in rows:
        e = json.loads(r['data'])
        plan = plan_for(e['staffId'], e['businessDay'])
        w = L.plan_window(plan)
        if w:
            end = (datetime(1970, 1, 1) + timedelta(minutes=w[1])).isoformat() + e['clockIn'][19:]
        else:
            end = _last_activity(e['staffId'], e['businessDay']) or e['clockIn']
        if L.local_minutes(end) < L.local_minutes(e['clockIn']):
            end = e['clockIn']
        clock({'cloud_id': e['staffId']}, 'out', at=end, auto=True)
        closed += 1
    return closed


def to_fix():
    """Düzeltilmesi gereken kayıtlar: çıkışı unutulmuş ve henüz düzeltilmemiş."""
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM time_entries WHERE data LIKE '%forgotClockOut%' ORDER BY business_day DESC")
    out = [json.loads(r['data']) for r in rows]
    conn.close()
    return [e for e in out if 'forgotClockOut' in e.get('flags', []) and not e.get('resolved')]


def edit(user, staff_id, clock_in, clock_out, reason, approver_id=None, entry_id=None, breaks=None):
    """Yetkili düzeltme (shifts): saatler ISO, gerekçe zorunlu. entry_id yoksa yeni kayıt açılır."""
    import pos
    pos.require_permission(user, approver_id, 'shifts')
    reason = (reason or '').strip()
    if not reason:
        raise OrderError("Gerekçe zorunludur.")
    if clock_out and L.local_minutes(clock_out) <= L.local_minutes(clock_in):
        raise OrderError("Çıkış girişten sonra olmalıdır.")
    conn = database.get_connection()
    try:
        before = None
        if entry_id:
            row = conn.execute("SELECT data FROM time_entries WHERE id=?", (entry_id,)).fetchone()
            before = json.loads(row['data']) if row else None
        day = L.business_day_of(clock_in)
        e = {**(before or {}), 'id': entry_id or 'TE' + uuid.uuid4().hex[:20], 'staffId': staff_id,
             'businessDay': day, 'clockIn': clock_in, 'clockOut': clock_out,
             'breaks': breaks if breaks is not None else (before or {}).get('breaks', []),
             'flags': sorted(set((before or {}).get('flags', [])) | {'edited'}), 'resolved': True,
             'editedBy': approver_id or user['cloud_id'], 'reason': reason,
             'late': L.late_minutes(plan_for(staff_id, day), clock_in, tolerance())}
        if before and before['businessDay'] != day:
            conn.execute("DELETE FROM time_entries WHERE id=?", (before['id'],))
        _save(conn, e)
        database.enqueue_op('timeEdit', {'entryId': e['id'], 'staffId': staff_id, 'clockIn': clock_in,
                                         'clockOut': clock_out, 'breaks': e['breaks'], 'reason': reason,
                                         'approvedBy': approver_id or user['cloud_id']}, user['cloud_id'], conn=conn)
        conn.commit()
    finally:
        conn.close()
    return e


# =====================================================================
# Rapor
# =====================================================================

def report(day_from, day_to, today_=None):
    """Kişi başı: plan, çalışılan, mola, fazla mesai (haftalık 45 sa), geç, gelmedi, unutulan çıkış, ciro/saat."""
    import reports
    today_ = today_ or today()
    pl = plans(day_from, day_to)
    ents = entries(day_from, day_to)
    tol = tolerance()
    rows = {}

    def row(sid):
        if sid not in rows:
            st = database.get_staff(sid)
            rows[sid] = {'staffId': sid, 'name': st['name'] if st else '—', 'planned': 0, 'worked': 0, 'breaks': 0,
                         'overtime': 0, 'lateCount': 0, 'lateMinutes': 0, 'absent': 0, 'forgot': 0, 'leave': 0,
                         'days': 0, 'revenue': 0, '_weeks': {}}
        return rows[sid]

    for (sid, day), p in pl.items():
        r = row(sid)
        if p.get('leave'):
            r['leave'] += 1
        else:
            r['planned'] += L.planned_minutes(p)
    seen = set()
    for e in ents:
        p = pl.get((e['staffId'], e['businessDay']))
        r = row(e['staffId'])
        worked = L.worked_minutes(e, p)
        r['worked'] += worked
        r['breaks'] += L.break_minutes(e, p)
        late = L.late_minutes(p, e['clockIn'], tol)
        if late:
            r['lateCount'] += 1
            r['lateMinutes'] += late
        if 'forgotClockOut' in e.get('flags', []):
            r['forgot'] += 1
        r['days'] += 1
        week = week_start(e['businessDay'])
        r['_weeks'][week] = r['_weeks'].get(week, 0) + worked
        seen.add((e['staffId'], e['businessDay']))
    for (sid, day), p in pl.items():
        if not p.get('leave') and day < today_ and (sid, day) not in seen:
            row(sid)['absent'] += 1
    for s in reports.Report(day_from, day_to, include_legacy=False).staff():
        if s['staffId'] in rows:
            rows[s['staffId']]['revenue'] = s['revenue']
    for r in rows.values():
        r['overtime'] = sum(L.overtime_minutes(m) for m in r.pop('_weeks').values())
        r['revenuePerHour'] = r['revenue'] * 60 // r['worked'] if r['worked'] else 0
    return sorted(rows.values(), key=lambda r: r['name'].lower())


def detail(staff_id, day_from, day_to):
    """Gün gün döküm: plan, giriş, çıkış, mola, çalışılan, geç, işaretler."""
    pl = plans(day_from, day_to)
    by_day = {}
    for e in entries(day_from, day_to, staff_id):
        by_day.setdefault(e['businessDay'], []).append(e)
    days = sorted({d for (s, d) in pl if s == staff_id} | set(by_day))
    out = []
    for d in days:
        p = pl.get((staff_id, d))
        for e in by_day.get(d) or [None]:
            out.append({'day': d, 'plan': p, 'entry': e,
                        'worked': L.worked_minutes(e, p) if e else 0,
                        'breaks': L.break_minutes(e, p) if e else 0,
                        'late': L.late_minutes(p, e['clockIn'], tolerance()) if e else 0})
    return out


def labor_cost(rows, wages):
    """wages: {staffId: kuruş/saat}. Kişi başı maliyet ve toplam (çalışılan saat × ücret)."""
    costs = {r['staffId']: r['worked'] * (wages.get(r['staffId']) or 0) // 60 for r in rows}
    return costs, sum(costs.values())


def week_text(start):
    """Vardiya planının WhatsApp metni."""
    days = week_days(start)
    pl = plans(days[0], days[-1])
    staff = {s: database.get_staff(s) for s in {sid for sid, _ in pl}}
    lines = [f"📅 Vardiya planı {date.fromisoformat(days[0]).strftime('%d.%m')} – "
             f"{date.fromisoformat(days[-1]).strftime('%d.%m')}"]
    for sid in sorted(staff, key=lambda s: (staff[s] or {}).get('name', '')):
        cells = [f"{WEEKDAYS_SHORT[i]} {plan_label(pl.get((sid, d))) or '—'}" for i, d in enumerate(days)]
        lines.append(f"\n*{(staff[sid] or {}).get('name', '?')}*\n" + " · ".join(cells))
    return "\n".join(lines)
