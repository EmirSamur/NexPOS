"""
NexPOS - Kasa oturumu ve Z/X raporu (6. ekran)

Kasa açılışı, para giriş/çıkışı ve kapanış (Z) internetsiz yapılır; her işlem kuyruğa
(outbox) yazılır ve senkronla buluta gider. Sunucu beklenen nakdi kendi kayıtlarından
yeniden hesaplar; fark çıkarsa kayda geçer.

Oturum açıkken alınan her ödeme ve yapılan her iade oturumun kimliğini taşır
(pos.take_payment / pos.refund). Z raporu bu kayıtlardan hesaplanır.

Para her zaman kuruş cinsinden tam sayıdır.
"""
import json
from datetime import datetime

import database
import pos
from cloud.orders import OrderError, line_total
from pos import PAYMENT_LABELS, now_iso
from reports import vat_amount, vat_by_rate  # raporlarla aynı hesap

METHODS = ('cash', 'card', 'meal')
TAX_RATES = (0, 1, 10, 20)


def _save(conn, session):
    conn.execute("""INSERT INTO cash_sessions (id,data,status,business_day,opened_at,closed_at) VALUES (?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET data=excluded.data, status=excluded.status, closed_at=excluded.closed_at""",
        (session['id'], json.dumps(session, ensure_ascii=False), session['status'], session['businessDay'],
         session['openedAt'], session.get('closedAt')))


def current_session():
    return database.open_cash_session()


def get_session(session_id):
    conn = database.get_connection()
    row = conn.execute("SELECT data FROM cash_sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    return json.loads(row['data']) if row else None


def past_sessions(limit=60):
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM cash_sessions WHERE status='closed' ORDER BY closed_at DESC LIMIT ?",
                        (limit,)).fetchall()
    conn.close()
    return [json.loads(r['data']) for r in rows]


def _staff_name(staff_id):
    row = database.get_staff(staff_id) if staff_id else None
    return row['name'] if row else '—'


# =====================================================================
# İşlemler
# =====================================================================

def open_session(user, opening_cash, approver_id=None):
    pos.require_permission(user, approver_id, 'cash')
    if current_session():
        raise OrderError("Kasa zaten açık.")
    opening_cash = int(opening_cash)
    if not 0 <= opening_cash <= 10_000_000:
        raise OrderError("Açılış nakdi geçersiz.")
    at = now_iso()
    session = {
        'id': pos._new_id('CS'), 'status': 'open', 'businessDay': pos.business_day(),
        'terminalLetter': database.get_sync_state('terminal_letter', 'A') or 'A',
        'openingCash': opening_cash, 'openedBy': user['cloud_id'], 'approvedBy': approver_id or user['cloud_id'],
        'openedAt': at, 'movements': [], 'closedAt': None, 'closedBy': None,
        'countedCash': None, 'expectedCash': None, 'difference': None, 'differenceReason': None, 'report': None,
    }
    conn = database.get_connection()
    try:
        _save(conn, session)
        database.enqueue_op('openCashSession', {'cashSessionId': session['id'], 'businessDay': session['businessDay'],
                                                'openingCash': opening_cash,
                                                'approvedBy': session['approvedBy']}, user['cloud_id'], conn=conn)
        conn.commit()
    finally:
        conn.close()
    return session


def add_movement(user, kind, amount, reason, expense=False, approver_id=None):
    """kind: 'in' (kasaya para girdi) ya da 'out' (çıktı). Nakit gider, Masraflar sayfasına da yazılır."""
    pos.require_permission(user, approver_id, 'cash')
    session = current_session()
    if not session:
        raise OrderError("Kasa açık değil.")
    if kind not in ('in', 'out'):
        raise OrderError("Hareket türü geçersiz.")
    amount = int(amount)
    if not 1 <= amount <= 10_000_000:
        raise OrderError("Tutar geçersiz.")
    reason = (reason or '').strip()[:120]
    if not reason:
        raise OrderError("Gerekçe zorunludur.")
    if kind == 'out' and amount > expected_cash(session):
        raise OrderError("Kasada bu kadar nakit yok.")
    movement = {'movementId': pos._new_id('M'), 'type': kind, 'amount': amount, 'reason': reason,
                'expense': kind == 'out' and bool(expense), 'by': user['cloud_id'],
                'approvedBy': approver_id or user['cloud_id'], 'at': now_iso()}
    session['movements'].append(movement)
    conn = database.get_connection()
    try:
        _save(conn, session)
        if movement['expense']:
            conn.execute("""INSERT INTO expenses (masraf_tipi,tutar,odeme_tipi,masraf_detayi,kullanici_id,masraf_tarihi,
                eklenme_tarihi) VALUES (?,?,?,?,?,?,?)""",
                ('Kasadan ödeme', amount / 100, 'Nakit', reason, user.get('id'), datetime.now().strftime('%Y-%m-%d'),
                 datetime.now().strftime('%Y-%m-%d %H:%M')))
        database.enqueue_op('cashMovement', {'cashSessionId': session['id'], **{k: movement[k] for k in (
            'movementId', 'type', 'amount', 'reason', 'expense', 'approvedBy')}}, user['cloud_id'], conn=conn)
        conn.commit()
    finally:
        conn.close()
    return session


def needs_difference_reason(session, counted):
    return abs(int(counted) - expected_cash(session)) > database.modules()['cashSession']['diffReasonThreshold']


def close_session(user, counted_cash, reason='', approver_id=None):
    """Kasayı kapatır ve Z raporunu döndürür."""
    pos.require_permission(user, approver_id, 'cash')
    session = current_session()
    if not session:
        raise OrderError("Kasa açık değil.")
    counted_cash = int(counted_cash)
    if not 0 <= counted_cash <= 10_000_000:
        raise OrderError("Sayılan nakit geçersiz.")
    reason = (reason or '').strip()[:200]
    if needs_difference_reason(session, counted_cash) and not reason:
        raise OrderError("Kasa farkı için gerekçe zorunludur.")
    at = now_iso()
    session.update(status='closed', closedAt=at, closedBy=user['cloud_id'],
                   approvedBy=approver_id or session.get('approvedBy'))
    report = build_report(session)
    expected = report['cash']['expected']
    session.update(countedCash=counted_cash, expectedCash=expected, difference=counted_cash - expected,
                   differenceReason=reason or None)
    report = build_report(session)  # sayılan nakit ve fark rapora girsin
    session['report'] = report
    conn = database.get_connection()
    try:
        _save(conn, session)
        database.enqueue_op('closeCashSession', {
            'cashSessionId': session['id'], 'countedCash': counted_cash, 'expectedCash': expected,
            'reason': reason, 'approvedBy': approver_id or user['cloud_id'], 'report': _cloud_report(report),
        }, user['cloud_id'], conn=conn)
        conn.commit()
    finally:
        conn.close()
    return report


def _cloud_report(report):
    """Buluta giden özet (raporlar ekranı için); satır ayrıntısı yok."""
    keys = ('sales', 'refunds', 'tips', 'discount', 'campaign', 'rewards', 'comps', 'voids', 'vat', 'orders', 'staff', 'cash')
    return {k: report[k] for k in keys}


# =====================================================================
# Hesaplama
# =====================================================================

def _orders_touched(session):
    """Oturum açıldıktan sonra değişmiş adisyonlar."""
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM pos_orders WHERE updated_at>=? ORDER BY rowid",
                        (session['openedAt'],)).fetchall()
    conn.close()
    return [json.loads(r['data']) for r in rows]


def _in_window(session, iso):
    if not iso or iso < session['openedAt']:
        return False
    return not session.get('closedAt') or iso <= session['closedAt']


def expected_cash(session, orders=None):
    """açılış + nakit tahsilat − nakit iade + giriş − çıkış (sunucudaki expectedCash ile aynı)."""
    orders = _orders_touched(session) if orders is None else orders
    sid = session['id']
    cash_in = sum(p['amount'] for o in orders for p in o['payments']
                  if p.get('cashSessionId') == sid and p['method'] == 'cash')
    cash_out = sum(r['amount'] for o in orders for r in o.get('refunds') or []
                   if r.get('cashSessionId') == sid and r['method'] == 'cash')
    moves = sum(m['amount'] if m['type'] == 'in' else -m['amount'] for m in session['movements'])
    return session['openingCash'] + cash_in - cash_out + moves


def build_report(session):
    """X (ara) ya da Z (kapanış) raporu. Bütün tutarlar kuruş."""
    orders = _orders_touched(session)
    sid = session['id']
    sales = {m: 0 for m in METHODS}
    tips = {m: 0 for m in METHODS}
    refunds = {m: 0 for m in METHODS}
    refund_count = 0
    for o in orders:
        for p in o['payments']:
            if p.get('cashSessionId') == sid:
                sales[p['method']] += p['amount']
                tips[p['method']] += p.get('tip') or 0
        for r in o.get('refunds') or []:
            if r.get('cashSessionId') == sid:
                refunds[r['method']] += r['amount']
                refund_count += 1

    # Bu oturumda kapanan adisyonlar: son ödemesi bu oturuma yazılmış olanlar
    closed = [o for o in orders if o['status'] == 'paid' and o['payments']
              and o['payments'][-1].get('cashSessionId') == sid]
    cancelled = [o for o in orders if o['status'] == 'cancelled' and _in_window(session, o.get('closedAt'))]

    def lines_of(status, source):
        ls = [l for o in source for l in o['items'] if l['status'] == status]
        return {'count': sum(l['qty'] for l in ls),
                'amount': sum(line_total({**l, 'status': 'active'}) for l in ls)}

    comps = lines_of('comp', closed)
    voids = lines_of('void', closed)
    for o in cancelled:  # iptal edilen adisyonun gönderilmiş ürünleri de iptal sayılır
        for l in o['items']:
            if l['status'] == 'active' and l.get('state') == 'sent':
                voids['count'] += l['qty']
                voids['amount'] += line_total(l)

    vat_gross = {}
    staff = {}
    for o in closed:
        for rate, g in vat_by_rate(o).items():
            vat_gross[rate] = vat_gross.get(rate, 0) + g
        staff[o['waiterId']] = staff.get(o['waiterId'], 0) + o['total']
    vat = [{'rate': r, 'gross': g, 'vat': vat_amount(g, r)}
           for r, g in sorted(vat_gross.items())]

    total_sales = sum(sales.values())
    order_total = sum(o['total'] for o in closed)
    movements_in = sum(m['amount'] for m in session['movements'] if m['type'] == 'in')
    movements_out = sum(m['amount'] for m in session['movements'] if m['type'] == 'out')
    expected = expected_cash(session, orders)
    return {
        'kind': 'Z' if session['status'] == 'closed' else 'X',
        'sessionId': sid,
        'cafeName': database.general_settings()['cafeName'],
        'terminalLetter': session.get('terminalLetter', ''),
        'businessDay': session['businessDay'],
        'openedAt': session['openedAt'], 'openedBy': _staff_name(session['openedBy']),
        'closedAt': session.get('closedAt'), 'closedBy': _staff_name(session.get('closedBy')),
        'printedAt': now_iso(),
        'sales': {**sales, 'total': total_sales},
        'tips': {**tips, 'total': sum(tips.values())},
        'refunds': {**refunds, 'total': sum(refunds.values()), 'count': refund_count},
        'discount': {'amount': sum(o['discountAmount'] for o in closed),
                     'count': sum(1 for o in closed if o['discountAmount'])},
        'campaign': {'amount': sum(o.get('campaignAmount') or 0 for o in closed),
                     'count': sum(1 for o in closed if o.get('campaignAmount'))},
        'rewards': {'amount': sum(o.get('rewardAmount') or 0 for o in closed),
                    'count': sum(len(o.get('rewards') or []) for o in closed)},
        'comps': comps,
        'voids': voids,
        'vat': vat,
        'orders': {'count': len(closed), 'total': order_total,
                   'average': order_total // len(closed) if closed else 0, 'cancelled': len(cancelled)},
        'staff': sorted(({'staffId': k, 'name': _staff_name(k), 'total': v} for k, v in staff.items()),
                        key=lambda x: -x['total']),
        'cash': {'opening': session['openingCash'], 'sales': sales['cash'], 'refunds': refunds['cash'],
                 'in': movements_in, 'out': movements_out, 'expected': expected,
                 'counted': session.get('countedCash'), 'difference': session.get('difference'),
                 'differenceReason': session.get('differenceReason')},
        'movements': session['movements'],
    }


def method_label(method):
    return PAYMENT_LABELS.get(method, method)
