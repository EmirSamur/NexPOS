"""
NexPOS - Sipariş servisi (4. ekran)

Ekranlar adisyon işlemlerini buradan yapar. Her işlem tek bir SQLite transaction'ında:
  1. cloud/orders.py ile adisyonun yeni durumu hesaplanır (sunucuyla aynı kurallar),
  2. pos_orders'a yazılır,
  3. eski tablolar (masa durumu, kapanan adisyonlar → orders/order_items) beslenir,
  4. işlem kuyruğa (outbox) eklenir; internet varken senkronla buluta gider.
İnternet yokken de eksiksiz çalışır.
"""
import json
import uuid
from datetime import datetime, timedelta

import database
import stock
from cloud.orders import (  # noqa: F401 (line_total ekranlar için dışa açık)
    OrderError, apply_order_op, compute_totals, line_total, lines_share, merge_orders, table_status_for
)

DAY_START_HOUR = 5  # gün dönümü: 05:00'ten önce kapanan hesap önceki güne yazılır
LEGACY_TABLE_STATUS = {'occupied': 'dolu', 'bill_requested': 'hesap', 'empty': 'bos'}
PAYMENT_LABELS = {'cash': 'Nakit', 'card': 'Kredi Kartı', 'meal': 'Yemek Kartı'}

__all__ = ['OrderError']


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def place_label(doc):
    """Adisyon ya da fiş için yer adı: "Masa 5" / "Bahçe 3" / "Paket". Yalnız rakamsa "Masa" eklenir."""
    if doc.get('type') != 'dine_in':
        return 'Paket'
    name = (doc.get('tableName') or '').strip()
    return f"Masa {name}" if name.isdigit() or not name else name


def business_day(moment=None):
    moment = moment or datetime.now()
    return (moment - timedelta(hours=DAY_START_HOUR)).strftime('%Y-%m-%d')


def _new_id(prefix=''):
    return prefix + uuid.uuid4().hex[:20]


# =====================================================================
# Okuma
# =====================================================================

def get_order(order_id):
    conn = database.get_connection()
    row = conn.execute("SELECT data FROM pos_orders WHERE id=?", (order_id,)).fetchone()
    conn.close()
    return json.loads(row['data']) if row else None


def open_order_for_table(table_cloud_id):
    conn = database.get_connection()
    row = conn.execute("SELECT data FROM pos_orders WHERE status='open' AND table_id=?", (table_cloud_id,)).fetchone()
    conn.close()
    return json.loads(row['data']) if row else None


def open_orders(order_type=None):
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM pos_orders WHERE status='open' ORDER BY rowid").fetchall()
    conn.close()
    orders = [json.loads(r['data']) for r in rows]
    return [o for o in orders if order_type is None or o['type'] == order_type]


def tickets(statuses=('new', 'preparing', 'ready')):
    conn = database.get_connection()
    rows = conn.execute(f"""SELECT data FROM pos_tickets WHERE status IN ({','.join('?' * len(statuses))})
        ORDER BY created_at, rowid""", tuple(statuses)).fetchall()
    conn.close()
    return [json.loads(r['data']) for r in rows]


def top_products_today(limit=12):
    """Bugün en çok satılan ürünler (kapanmış ve açık adisyonlardan): [productId]"""
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM pos_orders WHERE business_day=?", (business_day(),)).fetchall()
    conn.close()
    counts = {}
    for r in rows:
        for line in json.loads(r['data'])['items']:
            if line['status'] == 'active' and line.get('productId'):
                counts[line['productId']] = counts.get(line['productId'], 0) + line['qty']
    return [pid for pid, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]


# =====================================================================
# Yazma: ortak çekirdek
# =====================================================================

def _load(conn, order_id):
    row = conn.execute("SELECT data FROM pos_orders WHERE id=?", (order_id,)).fetchone()
    return json.loads(row['data']) if row else None


def _save(conn, order):
    conn.execute("""INSERT INTO pos_orders (id,data,status,table_id,business_day,updated_at) VALUES (?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET data=excluded.data, status=excluded.status, table_id=excluded.table_id,
        updated_at=excluded.updated_at""",
        (order['id'], json.dumps(order, ensure_ascii=False), order['status'], order.get('tableId'),
         order['businessDay'], now_iso()))


def _local_user_id(conn, staff_cloud_id):
    row = conn.execute("SELECT id FROM users WHERE cloud_id=?", (staff_cloud_id,)).fetchone()
    return row['id'] if row else None


def _sync_legacy_table(conn, table_cloud_id, order):
    """Eski tables.durum alanı (liste görünümü, doluluk sayacı) adisyonla uyumlu tutulur."""
    if not table_cloud_id:
        return
    status = table_status_for(order) if order and order.get('tableId') == table_cloud_id else 'empty'
    if status == 'empty':
        # Masada başka açık adisyon varsa ona dokunma
        other = conn.execute("SELECT 1 FROM pos_orders WHERE status='open' AND table_id=? AND id<>?",
                             (table_cloud_id, order['id'] if order else '')).fetchone()
        if not other:
            conn.execute("UPDATE tables SET durum='bos', garson_id=NULL WHERE cloud_id=?", (table_cloud_id,))
        return
    conn.execute("UPDATE tables SET durum=?, garson_id=? WHERE cloud_id=?",
                 (LEGACY_TABLE_STATUS[status], _local_user_id(conn, order['waiterId']), table_cloud_id))


def _write_legacy_closed(conn, order):
    """Kapanan adisyonu raporların okuduğu eski orders/order_items tablolarına yazar."""
    if order['status'] != 'paid':
        return
    table = conn.execute("SELECT id FROM tables WHERE cloud_id=?", (order.get('tableId'),)).fetchone() \
        if order.get('tableId') else None
    cur = conn.execute(
        "INSERT INTO orders (masa_id,garson_id,durum,toplam_tutar,tarih,notlar) VALUES (?,?,?,?,?,?)",
        (table['id'] if table else None, _local_user_id(conn, order['waiterId']), 'tamamlandi',
         order['total'] / 100, database._local_minute(order['openedAt']), order['no']))
    legacy_id = cur.lastrowid
    for line in order['items']:
        if line['status'] != 'active' or not line.get('productId'):
            continue
        product = conn.execute("SELECT id FROM products WHERE cloud_id=?", (line['productId'],)).fetchone()
        if not product:
            continue
        total = line_total(line)
        conn.execute("INSERT INTO order_items (order_id,product_id,adet,birim_fiyat,toplam,notlar) VALUES (?,?,?,?,?,?)",
                     (legacy_id, product['id'], line['qty'], total / line['qty'] / 100, total / 100, line.get('note')))
    conn.execute("UPDATE pos_orders SET legacy_order_id=? WHERE id=?", (legacy_id, order['id']))


def _commit_op(conn, before, after, op, payload, staff_id, extra_tables=()):
    _save(conn, after)
    tables = {t for t in (before.get('tableId') if before else None, after.get('tableId'), *extra_tables) if t}
    if op == 'refundPayment':
        tables = set()  # iade kapanmış adisyondadır; masanın şimdiki durumuna dokunmaz
    for t in tables:
        _sync_legacy_table(conn, t, after)
    if before and before['status'] == 'open' and after['status'] == 'paid':
        _write_legacy_closed(conn, after)
    database.enqueue_op(op, payload, staff_id, conn=conn)


def _run(op, payload, user, extra=None):
    """Tek bir adisyon işlemini uygular ve kaydeder. extra(conn, before, after) yan işler içindir."""
    conn = database.get_connection()
    try:
        before = _load(conn, payload['orderId'])
        after = apply_order_op(before, op, payload, user['cloud_id'], now_iso())
        if extra:
            extra(conn, before, after)
        _commit_op(conn, before, after, op, payload, user['cloud_id'])
        conn.commit()
        return after
    finally:
        conn.close()


# =====================================================================
# Yazma: işlemler
# =====================================================================

def _next_order_no(conn, day):
    letter = database.get_sync_state('terminal_letter', 'A') or 'A'
    key = f'order_seq:{day}'
    row = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    seq = int(row['value']) + 1 if row else 1
    conn.execute("""INSERT INTO sync_state (key,value) VALUES (?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, str(seq)))
    return f"{letter}{seq}"


def open_order(user, table=None):
    """table: {'id': masa bulut kimliği, 'name': ad} ya da None (masasız sipariş)."""
    conn = database.get_connection()
    try:
        if table and conn.execute("SELECT 1 FROM pos_orders WHERE status='open' AND table_id=?",
                                  (table['id'],)).fetchone():
            raise OrderError("Bu masada zaten açık bir adisyon var.")
        day = business_day()
        payload = {'orderId': _new_id('O'), 'no': _next_order_no(conn, day), 'businessDay': day,
                   'type': 'dine_in' if table else 'takeaway', 'openedAt': now_iso()}
        if table:
            payload.update(tableId=table['id'], tableName=table['name'])
        order = apply_order_op(None, 'openOrder', payload, user['cloud_id'], now_iso())
        _commit_op(conn, None, order, 'openOrder', payload, user['cloud_id'])
        conn.commit()
        return order
    finally:
        conn.close()


def product_line(product, selected_options=(), qty=1, note=''):
    """Menü önbelleğindeki ürün + seçilen seçeneklerden adisyon satırı (fiyat anlık kopyalanır)."""
    category = database.menu_item('categories', product.get('categoryId')) or {}
    stamp = product.get('stampEligible')
    if stamp is None:
        stamp = bool(category.get('stampEligible'))
    return {
        'lineId': _new_id('L'),
        'productId': product['id'],
        'name': product['name'],
        'unitPrice': int(product['price']),
        'options': [{'groupId': g, 'optionId': o['id'], 'name': o['name'], 'priceDelta': int(o.get('priceDelta', 0))}
                    for g, o in selected_options],
        'qty': qty,
        'note': note or '',
        'station': category.get('station') or 'kitchen',
        'taxRate': product.get('taxRate') if product.get('taxRate') in (0, 1, 10, 20) else 10,
        'stampEligible': bool(stamp),
    }


def add_line(user, order_id, line):
    """Aynı ürün + aynı seçenek + aynı not bekleyen bir satırda varsa adedi artar."""
    order = get_order(order_id)
    same = next((l for l in order['items'] if l['state'] == 'pending' and l['status'] == 'active'
                 and l.get('productId') == line['productId'] and l.get('note', '') == line.get('note', '')
                 and [(o['groupId'], o['optionId']) for o in l['options']] ==
                 [(o['groupId'], o['optionId']) for o in line['options']]), None)
    if same and same['qty'] + line['qty'] <= 99:
        return _run('updateItem', {'orderId': order_id, 'lineId': same['lineId'], 'qty': same['qty'] + line['qty']}, user)
    return _run('addItems', {'orderId': order_id, 'items': [line]}, user)


def update_line(user, order_id, line_id, qty=None, note=None):
    payload = {'orderId': order_id, 'lineId': line_id}
    if qty is not None:
        payload['qty'] = qty
    if note is not None:
        payload['note'] = note
    return _run('updateItem', payload, user)


def remove_line(user, order_id, line_id):
    return _run('removeItem', {'orderId': order_id, 'lineId': line_id}, user)


def send_pending(user, order_id):
    """Bekleyen satırları bar ve mutfak fişlerine bölüp gönderir. Gönderilen satır sayısını döndürür."""
    order = get_order(order_id)
    pending = [l for l in order['items'] if l['state'] == 'pending' and l['status'] == 'active']
    if not pending:
        return order, 0
    ticket_ids = {'bar': _new_id('TB'), 'kitchen': _new_id('TK')}
    payload = {'orderId': order_id, 'lineIds': [l['lineId'] for l in pending], 'ticketIds': ticket_ids}

    def write_tickets(conn, before, after):
        at = now_iso()
        for station, tid in ticket_ids.items():
            lines = [{'lineId': l['lineId'], 'name': l['name'], 'qty': l['qty'], 'note': l.get('note', ''),
                      'options': [o['name'] for o in l['options']]} for l in pending if l['station'] == station]
            if not lines:
                continue
            ticket = {'id': tid, 'orderId': order_id, 'orderNo': after['no'], 'tableName': after.get('tableName') or '',
                      'type': after['type'], 'station': station, 'lines': lines, 'status': 'new', 'createdAt': at}
            conn.execute("INSERT INTO pos_tickets (id,order_id,data,status,station,created_at) VALUES (?,?,?,?,?,?)",
                         (tid, order_id, json.dumps(ticket, ensure_ascii=False), 'new', station, at))
        # Stok (8. ekran): gönderilen ürünlerin reçetesi düşer
        sent_ids = {l['lineId'] for l in pending}
        stock.record_sale(conn, after, [l for l in after['items'] if l['lineId'] in sent_ids], user['cloud_id'])

    return _run('sendItems', payload, user, extra=write_tickets), len(pending)


def void_line(user, order_id, line_id, reason, approver_id=None, prepared=True):
    """prepared=False: ürün hazırlanmadı, reçetesi stoğa döner (stok modülü açıksa)."""
    def give_back(conn, before, after):
        if not prepared and stock.enabled():
            line = next(l for l in before['items'] if l['lineId'] == line_id)
            stock.record_void_return(conn, before, line, user['cloud_id'])

    return _run('voidItem', {'orderId': order_id, 'lineId': line_id, 'reason': reason, 'prepared': bool(prepared),
                             'approvedBy': approver_id or user['cloud_id']}, user, extra=give_back)


def ask_prepared(order=None):
    """Gönderilmiş ürün iptalinde "hazırlandı mı?" sorulmalı mı? (stok modülü ve ayarı)"""
    m = database.modules()['stock']
    return m['enabled'] and m['askOnVoid']


def comp_line(user, order_id, line_id, reason, approver_id=None):
    return _run('compItem', {'orderId': order_id, 'lineId': line_id, 'reason': reason,
                             'approvedBy': approver_id or user['cloud_id']}, user)


def set_discount(user, order_id, discount, reason='', approver_id=None):
    """discount: {'type': 'percent'|'amount', 'value': int} ya da None (kaldır)."""
    payload = {'orderId': order_id, 'discount': discount, 'reason': reason or '',
               'approvedBy': approver_id or user['cloud_id']}
    return _run('setDiscount', payload, user)


def request_bill(user, order_id, value):
    return _run('requestBill', {'orderId': order_id, 'value': bool(value)}, user)


def move_order(user, order_id, to_table):
    if open_order_for_table(to_table['id']):
        raise OrderError("Hedef masa dolu; birleştirmeyi kullanın.")
    return _run('moveOrder', {'orderId': order_id, 'toTableId': to_table['id'], 'toTableName': to_table['name']}, user)


def merge_into(user, target_id, source_id):
    conn = database.get_connection()
    try:
        target, source = _load(conn, target_id), _load(conn, source_id)
        at = now_iso()
        new_target, new_source = merge_orders(target, source, at)
        payload = {'orderId': target_id, 'sourceOrderId': source_id}
        _save(conn, new_source)
        _sync_legacy_table(conn, source.get('tableId'), new_source)
        _commit_op(conn, target, new_target, 'mergeOrders', payload, user['cloud_id'])
        conn.commit()
        return new_target
    finally:
        conn.close()


def _cash_session_id(method):
    """Açık kasa oturumu varsa her ödeme/iade ona yazılır. Zorunlu kasa modülünde nakit için şarttır."""
    row = database.open_cash_session()
    if row:
        return row['id']
    if method == 'cash' and database.modules()['cashSession']['required']:
        raise OrderError("Kasa açılmadan nakit işlem yapılamaz. Önce Kasa ekranından kasayı açın.")
    return None


def take_payment(user, order_id, method, amount, tip=0, received=None, line_ids=None):
    """line_ids verilirse "ürün seçerek böl": tutar, seçilen satırların payı olmalıdır (bkz. lines_payable)."""
    payload = {'orderId': order_id, 'paymentId': _new_id('P'), 'method': method, 'amount': int(amount),
               'tip': int(tip or 0)}
    if method == 'cash':
        payload['received'] = int(received if received is not None else amount)
    if line_ids:
        payload['lineIds'] = list(line_ids)
    session_id = _cash_session_id(method)
    if session_id:
        payload['cashSessionId'] = session_id
    return _run('takePayment', payload, user)


def lines_payable(order, line_ids):
    """Seçilen satırlar için alınacak tutar: kalan bütün satırlar seçildiyse kalan tutarın tamamı."""
    unpaid = [l['lineId'] for l in order['items'] if l['status'] == 'active' and not l.get('paidBy')]
    if line_ids and all(lid in line_ids for lid in unpaid):
        return compute_totals(order)['remaining']
    return lines_share(order, line_ids)


def equal_share(remaining, people_left):
    """Eşit bölmede bu kişinin payı: kalan / kalan kişi (aşağı); son kişi kalanın tamamını öder."""
    people_left = max(1, int(people_left))
    return remaining if people_left == 1 else remaining // people_left


def split_line(user, order_id, line_id, qty):
    """Satırdan qty adedi ayrı bir satıra ayırır (3 latteden 1'i). Yeni satırı döndürür."""
    new_id = _new_id('L')
    order = _run('splitLine', {'orderId': order_id, 'lineId': line_id, 'qty': int(qty), 'newLineId': new_id}, user)
    return order, new_id


def require_permission(user, approver_id, permission):
    """Sunucu aynı denetimi yapar; yerelde de yapılır ki kuyruktaki işlem sonradan reddedilmesin."""
    if not database.staff_can(approver_id or user['cloud_id'], permission):
        raise OrderError(f"Bu işlem için yetki yok ({permission}). Yetkili onayı gerekir.")


def refund(user, order_id, method, amount, reason, approver_id=None):
    """Ödenmiş adisyonda (kısmi) iade. refund yetkisi gerekir (ekran onay ister)."""
    require_permission(user, approver_id, 'refund')
    payload = {'orderId': order_id, 'refundId': _new_id('R'), 'method': method, 'amount': int(amount),
               'reason': reason, 'approvedBy': approver_id or user['cloud_id']}
    session_id = _cash_session_id(method)
    if session_id:
        payload['cashSessionId'] = session_id
    return _run('refundPayment', payload, user)


def closed_orders(day=None):
    """Bir iş gününün ödenmiş adisyonları (en yeni önce) — iade ve raporlar için."""
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM pos_orders WHERE status='paid' AND business_day=? ORDER BY updated_at DESC",
                        (day or business_day(),)).fetchall()
    conn.close()
    return [json.loads(r['data']) for r in rows]


def cancel_order(user, order_id, reason, approver_id=None, prepared=True):
    def give_back(conn, before, after):
        if not prepared and stock.enabled():
            for line in before['items']:
                if line['status'] == 'active' and line['state'] == 'sent':
                    stock.record_void_return(conn, before, line, user['cloud_id'])

    return _run('cancelOrder', {'orderId': order_id, 'reason': reason, 'prepared': bool(prepared),
                                'approvedBy': approver_id or user['cloud_id']}, user, extra=give_back)


def set_ticket_status(user, ticket_id, status):
    conn = database.get_connection()
    try:
        row = conn.execute("SELECT data FROM pos_tickets WHERE id=?", (ticket_id,)).fetchone()
        if not row:
            raise OrderError("Fiş bulunamadı.")
        ticket = {**json.loads(row['data']), 'status': status, f'{status}At': now_iso()}
        conn.execute("UPDATE pos_tickets SET data=?, status=? WHERE id=?",
                     (json.dumps(ticket, ensure_ascii=False), status, ticket_id))
        database.enqueue_op('updateTicket', {'ticketId': ticket_id, 'status': status}, user['cloud_id'], conn=conn)
        conn.commit()
        return ticket
    finally:
        conn.close()


def mark_ticket_printed(ticket_id):
    """Kâğıda basılan fiş tekrar basılmasın (yalnızca yerel)."""
    conn = database.get_connection()
    row = conn.execute("SELECT data FROM pos_tickets WHERE id=?", (ticket_id,)).fetchone()
    if row:
        conn.execute("UPDATE pos_tickets SET data=? WHERE id=?",
                     (json.dumps({**json.loads(row['data']), 'printed': True}, ensure_ascii=False), ticket_id))
        conn.commit()
    conn.close()


def needs_approval_to_cancel(order):
    return any(l['status'] == 'active' and l['state'] == 'sent' for l in order['items'])


# =====================================================================
# Eski açık adisyonların taşınması (bir kez)
# =====================================================================

def migrate_legacy_open_orders(user):
    """
    Eski NexPOS'ta açık kalmış adisyonları yeni yapıya taşır. Yalnızca masası buluta
    aktarılmış (cloud_id'li) olanlar taşınır; satırı olmayan eski adisyon tek bir
    "Eski adisyon" satırıyla taşınır. Taşınan sayıyı döndürür.
    """
    conn = database.get_connection()
    rows = conn.execute("""SELECT o.*, t.cloud_id AS table_cloud_id, t.ad AS table_name FROM orders o
        JOIN tables t ON t.id = o.masa_id
        WHERE o.durum IN ('hazirlaniyor','bekliyor') AND t.cloud_id IS NOT NULL""").fetchall()
    conn.close()
    moved = 0
    for r in rows:
        if open_order_for_table(r['table_cloud_id']):
            continue
        order = open_order(user, {'id': r['table_cloud_id'], 'name': r['table_name']})
        conn = database.get_connection()
        items = conn.execute("""SELECT oi.*, p.cloud_id AS product_cloud_id, p.ad AS product_name,
            c.cloud_id AS category_cloud_id FROM order_items oi
            LEFT JOIN products p ON p.id = oi.product_id LEFT JOIN categories c ON c.id = p.kategori_id
            WHERE oi.order_id=?""", (r['id'],)).fetchall()
        conn.close()
        lines = []
        for it in items:
            category = database.menu_item('categories', it['category_cloud_id']) if it['category_cloud_id'] else {}
            lines.append({'lineId': _new_id('L'), 'productId': it['product_cloud_id'],
                          'name': it['product_name'] or 'Ürün', 'unitPrice': int(round((it['birim_fiyat'] or 0) * 100)),
                          'qty': max(1, min(99, it['adet'] or 1)), 'station': (category or {}).get('station') or 'kitchen',
                          'options': [], 'note': it['notlar'] or ''})
        if not lines and r['toplam_tutar']:
            lines.append({'lineId': _new_id('L'), 'productId': None, 'name': 'Eski adisyon (aktarıldı)',
                          'unitPrice': int(round(r['toplam_tutar'] * 100)), 'qty': 1, 'station': 'kitchen',
                          'options': [], 'note': ''})
        if lines:
            _run('addItems', {'orderId': order['id'], 'items': lines}, user)
            sent, _ = send_pending(user, order['id'])
            # Eski sistemde zaten hazırlanmış ürünler: fişler panoya "yeni" düşmesin
            for tid in {l['ticketId'] for l in sent['items'] if l.get('ticketId')}:
                if any(t['id'] == tid for t in tickets(('new',))):
                    set_ticket_status(user, tid, 'served')
        conn = database.get_connection()
        conn.execute("UPDATE orders SET durum='tasindi' WHERE id=?", (r['id'],))
        conn.commit()
        conn.close()
        moved += 1
    return moved
