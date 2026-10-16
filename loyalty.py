"""
NexPOS - Müşteri ve sadakat (10. ekran)

- Üyeler ve ödüller bulutta (customers, rewards); bu bilgisayar önbellekte tutar, kasada telefonla
  tanıma internetsiz çalışır. Uygulama QR'ı ile tanıma internet ister (resolveLoyaltyToken).
- Kasada yeni üye kuyrukla (customerCreate) gider; damga ve ödül, adisyon ödenip kapanınca sunucuda işlenir.
  O ana kadar kart, bu bilgisayardaki sadakat defterinden (loyalty_ledger) tahmin edilir.
- Hesaplar loyalty_logic.py'dedir (sunucudaki src/loyalty.js ile ortak senaryolar).
"""
import json
import uuid
from datetime import date, datetime, timedelta

import database
import loyalty_logic as L
from cloud.orders import OrderError, line_deduction, line_total, stamp_count


def enabled():
    return database.modules()['loyalty']['enabled']


def settings():
    return L.normalize_loyalty(database.get_setting('loyalty'))


def _today():
    import pos
    return pos.business_day()


# =====================================================================
# Üyeler
# =====================================================================

def _live(c):
    return not c.get('deleted') and not c.get('aliasOf')


def customers():
    """Önbellekteki üyeler (silinmiş ve birleştirilmiş kayıtlar hariç), ada göre."""
    rows = [c for c in database.cache_rows('customers', include_deleted=True) if _live(c)]
    return sorted(rows, key=lambda c: database.turkish_sort_key(c.get('name', '')))


def get(customer_id):
    c = next((x for x in database.cache_rows('customers', include_deleted=True) if x['id'] == customer_id), None)
    if c and c.get('aliasOf'):
        return get(c['aliasOf'])
    return c if c and not c.get('deleted') else None


def find_by_phone(text):
    phone = L.normalize_phone(text)
    return next((c for c in customers() if c.get('phone') == phone), None) if phone else None


def search(text, limit=20):
    """Ad ya da telefonun bir kısmıyla arama (kasada)."""
    q = (text or '').strip()
    if not q:
        return []
    exact = find_by_phone(q)
    if exact:
        return [exact]
    digits = ''.join(ch for ch in q if ch.isdigit())
    low = database.turkish_lower(q)
    out = []
    for c in customers():
        if (digits and len(digits) >= 3 and digits.lstrip('0') in (c.get('phone') or '')) or \
                (not digits and low in database.turkish_lower(c.get('name', ''))):
            out.append(c)
    return out[:limit]


def create(user, name, phone, marketing_consent, birth_date=None):
    """Kasada yeni üye (internetsiz). Telefon zaten kayıtlıysa o üye kullanılmalıdır."""
    name = (name or '').strip()
    if not 1 <= len(name) <= 60:
        raise OrderError("Ad 1-60 karakter olmalıdır.")
    p = L.normalize_phone(phone)
    if not p:
        raise OrderError("Telefon numarası geçersiz.")
    if not isinstance(marketing_consent, bool):
        raise OrderError("Bildirim izni sorulmalıdır.")
    existing = find_by_phone(p)
    if existing:
        raise OrderError(f"Bu numara zaten kayıtlı: {existing['name']}.")
    cid = 'C' + uuid.uuid4().hex[:20]
    at = datetime.now().astimezone().isoformat(timespec='seconds')
    payload = {'customerId': cid, 'name': name, 'phone': p, 'marketingConsent': marketing_consent,
               'birthDate': birth_date or None}
    database.enqueue_op('customerCreate', payload, user['cloud_id'])
    doc = {'name': name, 'phone': p, 'birthDate': birth_date or None, 'marketingConsent': marketing_consent,
           'consentAt': at if marketing_consent else None, 'stamps': 0, 'lifetimeStamps': 0, 'tier': 'bronze',
           'totalSpent': 0, 'visitCount': 0, 'lastVisitAt': None, 'source': 'pos', 'deleted': False, 'createdAt': at}
    database.upsert_cache('customers', [(cid, doc)])
    return {**doc, 'id': cid}


# =====================================================================
# Kart (bulut + bu bilgisayarda bekleyen işlemler)
# =====================================================================

def _pending(customer_id):
    conn = database.get_connection()
    rows = conn.execute("""SELECT * FROM loyalty_ledger WHERE customer_id=?
        AND op_id IN (SELECT op_id FROM outbox WHERE status='pending') ORDER BY id""", (customer_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _reserved_rewards():
    """Açık adisyonlarda kullanılmak üzere seçilmiş ödüller ve kuyruktaki kapanışlarda kullanılanlar."""
    import pos
    out = {r['rewardId'] for o in pos.open_orders() for r in o.get('rewards') or []}
    conn = database.get_connection()
    for row in conn.execute("""SELECT used FROM loyalty_ledger
            WHERE op_id IN (SELECT op_id FROM outbox WHERE status='pending')"""):
        out |= set(json.loads(row['used'] or '[]'))
    conn.close()
    return out


def rewards(customer_id, day=None, exclude_reserved=True):
    """Kullanılabilir ödüller (süresi geçmemiş, başka adisyonda seçilmemiş), en eski önce."""
    day = day or _today()
    reserved = _reserved_rewards() if exclude_reserved else set()
    rows = [r for r in database.cache_rows('rewards', include_deleted=True)
            if L.reward_usable(r, customer_id, day) and r['id'] not in reserved]
    return sorted(rows, key=lambda r: (r.get('expiresAt') or '', r['id']))


def card(customer_id):
    """Kasada gösterilen kart: damga (bekleyenler dahil), seviye, ödüller."""
    c = get(customer_id)
    if not c:
        return None
    s = settings()
    state = {'stamps': c.get('stamps') or 0, 'lifetimeStamps': c.get('lifetimeStamps') or 0}
    coming = 0
    for e in _pending(c['id']):
        if e['stamps'] >= 0:
            st = L.apply_stamps(state, e['stamps'], s)
        else:
            st = L.revoke_stamps(state, -e['stamps'], s)
        coming += st['newRewards'] + e['rewards']
        state = {'stamps': st['stamps'], 'lifetimeStamps': st['lifetimeStamps']}
    tier = L.tier_for(state['lifetimeStamps'], s)
    return {**c, 'stamps': state['stamps'], 'lifetimeStamps': state['lifetimeStamps'], 'tier': tier,
            'tierName': L.tier_name(tier, s), 'stampsForReward': s['stampsForReward'],
            'rewards': rewards(c['id']), 'pendingRewards': coming, 'maskedPhone': L.mask_phone(c.get('phone')),
            'birthdayWeek': L.is_birthday_week(c.get('birthDate'), _today())}


def stamp_dots(stamps, total):
    return '●' * stamps + '○' * max(total - stamps, 0)


def summary(card_):
    """'Ayşe K. · ●●●●●●●○○○ 7/10 · Gümüş · 🎁 1 ödül hazır'"""
    parts = [card_['name'], f"{stamp_dots(card_['stamps'], card_['stampsForReward'])} "
                            f"{card_['stamps']}/{card_['stampsForReward']}", card_['tierName']]
    if card_['rewards']:
        parts.append(f"🎁 {len(card_['rewards'])} ödül hazır")
    if card_['pendingRewards']:
        parts.append(f"🎁 {card_['pendingRewards']} ödül internet gelince")
    if card_.get('birthdayWeek'):
        parts.append("🎂 doğum günü haftası")
    return " · ".join(parts)


# =====================================================================
# Adisyon: ödül seçimi ve kapanış defteri
# =====================================================================

def reward_target(order, max_value):
    """Ödülün uygulanacağı satır ve tutar: en pahalı uygun içecek (damga kazandıran, ödenmemiş,
    adedi kadar ödül). (lineId, tutar) ya da None."""
    best = None
    for l in order['items']:
        if l['status'] != 'active' or l.get('paidBy') or not l.get('stampEligible'):
            continue
        used = sum(1 for r in order.get('rewards') or [] if r['lineId'] == l['lineId'])
        if used >= l['qty']:
            continue
        unit = line_total(l) // l['qty']
        room = line_total(l) - line_deduction(order, l['lineId'])
        amount = min(unit, max_value, room)
        if amount > 0 and (best is None or (amount, unit) > (best[1], best[2])):
            best = (l['lineId'], amount, unit)
    return best[:2] if best else None


def record_close(conn, order, op_id):
    """Adisyon üyeyle kapandı: kazanılan damga ve kullanılan ödüller deftere (internet gelene kadar)."""
    if not order.get('customer'):
        return
    conn.execute("INSERT INTO loyalty_ledger (op_id,customer_id,order_id,kind,stamps,used,at) VALUES (?,?,?,?,?,?,?)",
                 (op_id, order['customer']['id'], order['id'], 'close', stamp_count(order),
                  json.dumps([r['rewardId'] for r in order.get('rewards') or []]), order.get('closedAt')))


def record_refund(conn, order, op_id):
    """İadede geri alınacak damga (sunucuyla aynı oran)."""
    if not order.get('customer'):
        return
    from cloud.orders import compute_totals
    t = compute_totals(order)
    earned = stamp_count(order)
    done = -(conn.execute("SELECT COALESCE(SUM(stamps),0) s FROM loyalty_ledger WHERE order_id=? AND kind='revoke'",
                          (order['id'],)).fetchone()['s'])
    n = L.refund_revoke(earned, t['paid'], t['refunded'], done)
    if n:
        conn.execute("INSERT INTO loyalty_ledger (op_id,customer_id,order_id,kind,stamps,at) VALUES (?,?,?,?,?,?)",
                     (op_id, order['customer']['id'], order['id'], 'revoke', -n, order['refunds'][-1]['at']))


def adjust(user, customer_id, stamps, reason, grant_reward=False, approver_id=None):
    """Elle damga düzeltme / ödül verme (loyalty yetkisi, gerekçe zorunlu). İnternetsiz, kuyruktan gider."""
    import pos
    pos.require_permission(user, approver_id, 'loyalty')
    reason = (reason or '').strip()
    if not reason:
        raise OrderError("Gerekçe zorunludur.")
    if not isinstance(stamps, int) or not -100 <= stamps <= 100 or (not stamps and not grant_reward):
        raise OrderError("Damga −100 ile 100 arası olmalıdır.")
    c = get(customer_id)
    if not c:
        raise OrderError("Müşteri bulunamadı.")
    adjust_id = 'ADJ' + uuid.uuid4().hex[:20]
    payload = {'adjustId': adjust_id, 'customerId': c['id'], 'stamps': stamps, 'grantReward': bool(grant_reward),
               'reason': reason, 'approvedBy': approver_id or user['cloud_id']}
    conn = database.get_connection()
    try:
        op_id = database.enqueue_op('loyaltyAdjust', payload, user['cloud_id'], conn=conn)
        conn.execute("INSERT INTO loyalty_ledger (op_id,customer_id,kind,stamps,rewards,at) VALUES (?,?,?,?,?,?)",
                     (op_id, c['id'], 'adjust', stamps, 1 if grant_reward else 0,
                      datetime.now().astimezone().isoformat(timespec='seconds')))
        conn.commit()
    finally:
        conn.close()
    return adjust_id


# =====================================================================
# Panel: liste ve filtreler
# =====================================================================

FILTERS = (('all', 'Hepsi'), ('inactive30', '30 gündür gelmeyen'), ('birthday', 'Bu hafta doğum günü'),
           ('consent', 'Bildirim izni olan'), ('silver', 'Gümüş ve üstü'), ('gold', 'Altın'))


def filtered(kind='all', text='', today=None):
    today = today or _today()
    rows = search(text, limit=100000) if text.strip() else customers()
    limit = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    if kind == 'inactive30':
        rows = [c for c in rows if (c.get('lastVisitAt') or c.get('createdAt') or '')[:10] < limit]
    elif kind == 'birthday':
        rows = [c for c in rows if L.is_birthday_week(c.get('birthDate'), today)]
    elif kind == 'consent':
        rows = [c for c in rows if c.get('marketingConsent')]
    elif kind == 'silver':
        rows = [c for c in rows if c.get('tier') in ('silver', 'gold')]
    elif kind == 'gold':
        rows = [c for c in rows if c.get('tier') == 'gold']
    return rows


def days_since(iso, today=None):
    if not iso:
        return None
    today = date.fromisoformat(today or _today())
    try:
        return (today - date.fromisoformat(iso[:10])).days
    except ValueError:
        return None


def resolve_qr(token):
    """Uygulamadaki QR → üye kaydı. İnternet ister (QR sunucuda doğrulanır, tek kullanımlık)."""
    from cloud.context import ctx
    token = (token or '').strip()
    if not token:
        raise OrderError("QR okutulmadı.")
    if not ctx.engine:
        raise OrderError("QR ile tanıma internet ister; telefon numarasıyla arayın.")
    result = ctx.engine.client.call('resolveLoyaltyToken', {'token': token}, ctx.engine._ensure_session())
    return get(result['customerId']) or {'id': result['customerId'], 'name': result['name'],
                                         'tier': result.get('tier'), 'stamps': result.get('stamps', 0)}
