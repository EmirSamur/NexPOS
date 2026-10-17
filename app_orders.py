"""
NexPOS - Uygulamadan gelen siparişler (11b)

Müşteri uygulamasından (masadaki QR ya da gel-al) gelen istekler buluttan (appOrders) iner. Kasada
"Onayla" denince istek bu bilgisayarda NORMAL adisyona çevrilir: masanın açık adisyonuna eklenir (yoksa açılır)
ya da masasız (paket) adisyon açılır, satırlar bar/mutfak fişlerine gönderilir, üye ise adisyona bağlanır.
Hepsi tek SQLite transaction'ındadır; sunucu onayı (acceptAppOrder) gelmezse hiçbir şey kaydedilmez
(müşteri iptal etmiş ya da süre dolmuş olabilir).

Masadan "Garson çağır / Hesap iste" çağrıları tableCalls'tan iner; "Tamam" kuyruktan (internetsiz de) kapatılır.
"""
import json
from datetime import datetime, timezone

import database
import loyalty
import pos
from pos import OrderError

REJECT_REASONS = ["Ürün bitti", "Şu an çok yoğunuz", "Kapanmak üzereyiz", "Masa bulunamadı"]
CALL_LABELS = {'waiter': "Garson çağırıyor", 'bill': "Hesap istiyor"}
CALL_ICONS = {'waiter': "🙋", 'bill': "🧾"}
STATUS_LABELS = {'pending': "Onay bekliyor", 'accepted': "Onaylandı", 'preparing': "Hazırlanıyor",
                 'ready': "Hazır", 'completed': "Teslim edildi", 'rejected': "Reddedildi", 'expired': "Süresi doldu",
                 'cancelled': "İptal", 'no_show': "Gelinmedi"}


def enabled():
    m = database.modules()['app']
    return m['enabled'] and (m['tableOrders'] or m['pickup'])


def _ms(value):
    if not value:
        return 0
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp() * 1000
    except ValueError:
        return 0


def _now_ms():
    return datetime.now(timezone.utc).timestamp() * 1000


def seconds_left(req, now_ms=None):
    """Onay için kalan saniye (süre dolduysa 0)."""
    return max(int((_ms(req.get('expiresAt')) - (now_ms or _now_ms())) / 1000), 0)


def pending(now_ms=None):
    """Onay bekleyen istekler (süresi dolanlar düşer), eskiden yeniye."""
    now_ms = now_ms or _now_ms()
    rows = [r for r in database.cache_rows('appOrders', include_deleted=True)
            if r.get('status') == 'pending' and _ms(r.get('expiresAt')) > now_ms]
    return sorted(rows, key=lambda r: r.get('createdAt') or '')


def pickups():
    """Onaylanmış, teslim edilmemiş gel-al siparişleri (geliş saatine göre)."""
    rows = [r for r in database.cache_rows('appOrders', include_deleted=True)
            if r.get('kind') == 'pickup' and r.get('status') in ('accepted', 'preparing', 'ready')]
    return sorted(rows, key=lambda r: r.get('pickupAt') or '')


def open_calls():
    rows = [r for r in database.cache_rows('tableCalls', include_deleted=True) if r.get('status') == 'open']
    return sorted(rows, key=lambda r: r.get('at') or '')


def calls_by_table():
    """{masa bulut kimliği: ['waiter', 'bill']} — masa kartında 🙋 / 🧾 için."""
    out = {}
    for c in open_calls():
        out.setdefault(c.get('tableId'), []).append(c.get('kind'))
    return out


def place(req):
    if req.get('kind') == 'table':
        name = req.get('tableName') or ''
        return f"Masa {name}" if name.isdigit() or not name else name
    return "Gel-al"


def local_time(iso):
    ms = _ms(iso)
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().strftime('%H:%M') if ms else ''


def items_text(req):
    parts = []
    for i in req.get('items') or []:
        opts = ", ".join(o['name'] for o in i.get('options') or [])
        parts.append(f"{i['qty']}× {i['name']}" + (f" ({opts})" if opts else ""))
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Sunucu çağrıları
# ---------------------------------------------------------------------------

def _cloud_call(name, data):
    from cloud.context import ctx
    from cloud.firebase_client import ApiError, OfflineError
    if not ctx.engine:
        raise OrderError("Uygulama siparişleri internet ister.")
    try:
        return ctx.engine.client.call(name, data, ctx.engine._ensure_session())
    except OfflineError:
        raise OrderError("İnternet yok; sipariş onaylanamadı. Bağlantı gelince tekrar deneyin.")
    except ApiError as e:
        raise OrderError(e.message or "Sunucu isteği reddetti.")


def _mark(collection, doc_id, fields):
    """Yerel önbellekte durumu hemen günceller (sonraki senkron sunucudakiyle değiştirir)."""
    doc = next((r for r in database.cache_rows(collection, include_deleted=True) if r['id'] == doc_id), None)
    if doc:
        doc = {k: v for k, v in doc.items() if k != 'id'}
        database.upsert_cache(collection, [(doc_id, {**doc, **fields})])


def _lines(req):
    """İstekteki ürünler → adisyon satırları. Fiyat müşterinin gördüğü (sunucunun menüden hesapladığı) fiyattır;
    istasyon, KDV ve damga menü önbelleğinden gelir."""
    lines = []
    for i, item in enumerate(req.get('items') or []):
        product = database.menu_item('products', item.get('productId')) or {}
        category = database.menu_item('categories', product.get('categoryId')) or {}
        stamp = product.get('stampEligible')
        if stamp is None:
            stamp = bool(category.get('stampEligible'))
        note = item.get('note') or ''
        if i == 0 and req.get('note'):
            note = f"{note} · {req['note']}" if note else req['note']
        lines.append({
            'lineId': pos._new_id('L'),
            'productId': item.get('productId'),
            'name': item['name'][:80],
            'unitPrice': int(item['unitPrice']),
            'options': [{'groupId': o['groupId'], 'optionId': o['optionId'], 'name': o['name'],
                         'priceDelta': int(o.get('priceDelta', 0))} for o in item.get('options') or []],
            'qty': int(item['qty']),
            'note': note[:120],
            'station': category.get('station') or 'kitchen',
            'taxRate': product.get('taxRate') if product.get('taxRate') in (0, 1, 10, 20) else 10,
            'stampEligible': bool(stamp),
        })
    return lines


def accept(user, req, call=None):
    """İsteği adisyona çevirir; sunucu onaylarsa kaydeder. Adisyonu döndürür."""
    call = call or _cloud_call
    conn = database.get_connection()
    try:
        if req.get('kind') == 'table':
            row = conn.execute("SELECT data FROM pos_orders WHERE status='open' AND table_id=?",
                               (req.get('tableId'),)).fetchone()
            order = json.loads(row['data']) if row else pos._open(conn, user, {'id': req['tableId'],
                                                                              'name': req.get('tableName') or ''})
        else:
            order = pos._open(conn, user, None)
        lines = _lines(req)
        order = pos._apply(conn, 'addItems', {'orderId': order['id'], 'items': lines}, user)
        # Üye: adisyona bağlanır (damga kapanışta kartına işlenir); masada başka üye varsa dokunulmaz
        if req.get('customerId') and not order.get('customer') and database.modules()['loyalty']['enabled']:
            c = loyalty.get(req['customerId']) or {'id': req['customerId'], 'name': req.get('customerName') or 'Üye',
                                                    'tier': req.get('customerTier')}
            order = pos._apply(conn, 'setCustomer', {'orderId': order['id'], 'customer': {
                'id': c['id'], 'name': (c.get('name') or 'Üye')[:60], 'tier': c.get('tier') or None}}, user)
        ids = {l['lineId'] for l in lines}
        order, used = pos._send_lines(conn, user, order, [l for l in order['items'] if l['lineId'] in ids])
        call('acceptAppOrder', {'id': req['id'], 'orderId': order['id'], 'orderNo': order['no'],
                                'ticketIds': list(used.values()), 'staffId': user['cloud_id']})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _mark('appOrders', req['id'], {'status': 'accepted', 'orderId': order['id'], 'orderNo': order['no']})
    return order


def reject(user, req, reason, call=None):
    reason = (reason or '').strip()
    if not reason:
        raise OrderError("Reddetme gerekçesi yazın.")
    (call or _cloud_call)('rejectAppOrder', {'id': req['id'], 'reason': reason[:120], 'staffId': user['cloud_id']})
    _mark('appOrders', req['id'], {'status': 'rejected', 'reason': reason})


def no_show(user, req, call=None):
    """Gel-al siparişine gelinmedi. Sonuç: {'pickupBlocked': bool}. Adisyonu iptal etmek ekrana kalır (yetkiyle)."""
    result = (call or _cloud_call)('appOrderNoShow', {'id': req['id'], 'staffId': user['cloud_id']})
    _mark('appOrders', req['id'], {'status': 'no_show'})
    return result or {}


def ack_call(user, call_doc):
    """Garson çağrıyı gördü: kuyruktan kapatılır (internetsiz de)."""
    database.enqueue_op('ackTableCall', {'callId': call_doc['id'], 'at': call_doc.get('at')}, user['cloud_id'])
    _mark('tableCalls', call_doc['id'], {'status': 'done'})
