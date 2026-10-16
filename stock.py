"""
NexPOS - Stok ve reçete (8. ekran)

- Malzemeler bulutta (ingredients); burada önbelleği ve yerel hareket defteri (stock_ledger) var.
- Yerel stok = buluttaki son stok + henüz buluta gitmemiş yerel hareketler. Hareketler kuyrukla
  (stockMove) gider; sunucu her hareketi bir kez uygular.
- Ürün "Gönder" ile bar/mutfağa gidince reçetesi düşer (pos.send_pending). Gönderildikten sonra
  iptal edilen ürün hazırlanmadıysa stoğa döner; hazırlandıysa zayi sayılır (stok değişmez).

Miktarlar malzemenin temel biriminde tam sayıdır (g, ml, adet). Birim maliyet kuruş cinsinden
kg / L / adet başınadır.
"""
import json
import uuid
from datetime import datetime, timedelta

import database

UNITS = {'g': ('kg', 1000), 'ml': ('L', 1000), 'adet': ('adet', 1)}
GROUPS = {'bar': 'Bar', 'kitchen': 'Mutfak', 'packaging': 'Ambalaj', 'other': 'Diğer'}


def enabled():
    return database.modules()['stock']['enabled']


def _business_day(iso):
    return (datetime.fromisoformat(iso[:19]) - timedelta(hours=5)).strftime('%Y-%m-%d')


def _now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


# =====================================================================
# Gösterim
# =====================================================================

def format_qty(qty, unit):
    """3200 ml → '3,2 L', 840 adet → '840 adet', 18 g → '18 g'"""
    big, factor = UNITS[unit]
    if factor > 1 and abs(qty) >= factor:
        v = f"{qty / factor:,.3f}".rstrip('0').rstrip('.')
        return f"{v.replace(',', 'X').replace('.', ',').replace('X', '.')} {big}"
    return f"{qty:,}".replace(',', '.') + f" {unit}"


def cost_of(qty, ingredient):
    """Miktarın maliyeti (kuruş, yarım yukarı)."""
    factor = UNITS[ingredient['unit']][1]
    return (qty * ingredient.get('unitCost', 0) * 2 + factor) // (2 * factor)


# =====================================================================
# Malzemeler ve yerel stok
# =====================================================================

def _pending_deltas(conn):
    rows = conn.execute("""SELECT ingredient_id, SUM(qty) AS q FROM stock_ledger
        WHERE op_id IN (SELECT op_id FROM outbox WHERE status='pending') GROUP BY ingredient_id""").fetchall()
    return {r['ingredient_id']: r['q'] for r in rows}


def ingredients(include_deleted=False):
    """Malzemeler; 'stock' yerel bekleyen hareketler eklenmiş hâlidir."""
    items = database.cache_rows('ingredients', include_deleted)
    conn = database.get_connection()
    pending = _pending_deltas(conn)
    conn.close()
    for i in items:
        i['stock'] = int(i.get('stock') or 0) + pending.get(i['id'], 0)
        i['value'] = cost_of(max(i['stock'], 0), i)
        i['isCritical'] = bool(i.get('critical')) and i['stock'] <= i['critical']
    return sorted(items, key=lambda i: i['name'].lower())


def ingredient_map():
    return {i['id']: i for i in ingredients()}


def critical():
    return [i for i in ingredients() if i['isCritical']]


# =====================================================================
# Reçete
# =====================================================================

class Recipes:
    """Ürün ve seçenek önbelleğini bir kez okuyup reçete tüketimi ve maliyet hesaplar."""

    def __init__(self):
        self.products = {p['id']: p for p in database.cache_rows('products', include_deleted=True)}
        self.groups = {g['id']: g for g in database.cache_rows('optionGroups', include_deleted=True)}
        self.ingredients = {i['id']: i for i in database.cache_rows('ingredients', include_deleted=True)}

    def effect(self, group_id, option_id):
        g = self.groups.get(group_id) or {}
        opt = next((o for o in g.get('options') or [] if o['id'] == option_id), None)
        return (opt or {}).get('recipeEffect')

    def consumption(self, product_id, options=(), qty=1, takeaway=False):
        """{malzeme: miktar} — options: [(groupId, optionId)]. Sıra: değiştir → çarp → ekle."""
        product = self.products.get(product_id) or {}
        use = {}
        for r in product.get('recipe') or []:
            if r.get('takeawayOnly') and not takeaway:
                continue
            use[r['ingredientId']] = use.get(r['ingredientId'], 0) + r['qty']
        effects = [e for e in (self.effect(g, o) for g, o in options) if e]
        for e in effects:
            for rep in e.get('replace') or []:
                if rep['from'] in use:
                    use[rep['to']] = use.get(rep['to'], 0) + use.pop(rep['from'])
        scale = 1.0
        for e in effects:
            scale *= e.get('scale') or 1
        if scale != 1:
            for ing_id in list(use):
                unit = (self.ingredients.get(ing_id) or {}).get('unit')
                if unit != 'adet':  # bardak, kapak gibi adetler boya göre çoğalmaz
                    use[ing_id] = int(use[ing_id] * scale + 0.5)
        for e in effects:
            for add in e.get('add') or []:
                use[add['ingredientId']] = use.get(add['ingredientId'], 0) + add['qty']
        return {k: v * qty for k, v in use.items() if v}

    def line_consumption(self, line, order_type):
        if not line.get('productId'):
            return {}
        opts = [(o['groupId'], o['optionId']) for o in line.get('options') or []]
        return self.consumption(line['productId'], opts, line['qty'], order_type == 'takeaway')

    def cost(self, use):
        return sum(cost_of(q, self.ingredients[i]) for i, q in use.items() if i in self.ingredients)

    def line_cost(self, line, order_type):
        return self.cost(self.line_consumption(line, order_type))

    def has_recipe(self, product_id):
        return bool((self.products.get(product_id) or {}).get('recipe'))


# =====================================================================
# Hareketler
# =====================================================================

def _move(conn, mtype, use, staff_id, order_id=None, line_id=None, reason='', approver_id=None, sign=-1):
    """use: {malzeme: miktar}; sign −1 düşer, +1 ekler. Hareketi deftere ve kuyruğa yazar."""
    lines = [{'ingredientId': i, 'qty': sign * q} for i, q in use.items() if q]
    if not lines:
        return None
    movement_id = 'SM' + uuid.uuid4().hex[:20]
    payload = {'movementId': movement_id, 'type': mtype, 'lines': lines}
    if order_id:
        payload['orderId'] = order_id
    if line_id:
        payload['lineId'] = line_id
    if reason:
        payload['reason'] = reason
    if approver_id:
        payload['approvedBy'] = approver_id
    op_id = database.enqueue_op('stockMove', payload, staff_id, conn=conn)
    at = _now()
    conn.executemany("""INSERT INTO stock_ledger (movement_id,op_id,type,ingredient_id,qty,order_id,line_id,at)
        VALUES (?,?,?,?,?,?,?,?)""", [(movement_id, op_id, mtype, l['ingredientId'], l['qty'], order_id, line_id, at)
                                      for l in lines])
    return movement_id


def record_sale(conn, order, lines, staff_id):
    """Gönderilen satırların reçetesini düşer (her satır ayrı hareket: iptalde iadesi bulunabilsin)."""
    if not enabled():
        return
    rec = Recipes()
    for line in lines:
        use = rec.line_consumption(line, order['type'])
        if use:
            _move(conn, 'sale', use, staff_id, order['id'], line['lineId'])


def _sold_for_line(conn, order, line):
    """
    İptal edilen satır için stoğa dönecek miktar. Satır (ya da bölündüğü ana satır) satışta gerçekten
    düşülmüşse, satırın ŞU ANKİ adedi kadar reçete döner; satır sonradan bölünmüş olabileceği için
    satıştaki toplam değil güncel adet esas alınır. Hiç düşülmemişse (modül kapalıyken gönderilmiş) boş.
    """
    chain = [line['lineId']] + ([line['splitFrom']] if line.get('splitFrom') else [])
    marks = ','.join('?' * len(chain))
    sold = conn.execute(f"""SELECT 1 FROM stock_ledger WHERE order_id=? AND line_id IN ({marks}) AND type='sale'
        LIMIT 1""", (order['id'], *chain)).fetchone()
    return Recipes().line_consumption(line, order['type']) if sold else {}


def record_void_return(conn, order, line, staff_id):
    """Hazırlanmadan iptal edilen satır stoğa döner (yalnızca gerçekten düşülmüş olan kadar)."""
    use = _sold_for_line(conn, order, line)
    if use:
        _move(conn, 'void_return', use, staff_id, order['id'], line['lineId'], sign=+1)


def set_counts(user, counts, reason='Sayım', approver_id=None, initial=False):
    """
    counts: {malzeme: sayılan miktar}. Stok sayılana eşitlenir: fark kadar 'count' hareketi yazılır ve sayım
    kaydı (count_log) tutulur. initial=True: ilk sayım (fark kayıp sayılmaz). Yazılan farkları döndürür.
    """
    current = ingredient_map()
    use, lines = {}, []
    for ing_id, counted in counts.items():
        if ing_id in current and counted is not None:
            ing = current[ing_id]
            delta = int(counted) - ing['stock']
            lines.append({'ingredientId': ing_id, 'name': ing['name'], 'unit': ing['unit'], 'system': ing['stock'],
                          'counted': int(counted), 'diff': delta, 'cost': cost_of(delta, ing) if delta >= 0
                          else -cost_of(-delta, ing)})
            if delta:
                use[ing_id] = delta
    if not lines:
        return {}
    conn = database.get_connection()
    try:
        movement = _move(conn, 'count', use, user['cloud_id'], reason=reason, approver_id=approver_id, sign=+1) \
            if use else None
        at = _now()
        conn.execute("""INSERT INTO count_log (movement_id,at,business_day,staff_id,reason,initial,data)
            VALUES (?,?,?,?,?,?,?)""", (movement, at, _business_day(at), user['cloud_id'], reason, 1 if initial else 0,
                                        json.dumps(lines, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()
    return use


def count_history(limit=50):
    conn = database.get_connection()
    rows = conn.execute("SELECT * FROM count_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [{**dict(r), 'lines': json.loads(r['data'])} for r in rows]


# Sayım taslağı (yarım bırakılan sayım): bu bilgisayarda saklanır
def save_count_draft(counts, reason):
    database.set_sync_state('count_draft', json.dumps({'counts': counts, 'reason': reason, 'at': _now()}))


def load_count_draft():
    raw = database.get_sync_state('count_draft')
    return json.loads(raw) if raw else None


def clear_count_draft():
    database.set_sync_state('count_draft', '')


# =====================================================================
# Ürün maliyeti (reçete sekmesi ve raporlar)
# =====================================================================

def product_costing(product_id, price, tax_rate, options=(), takeaway=False):
    """{'cost', 'netPrice' (KDV hariç), 'profit', 'margin' (%), 'lines': [(malzeme, miktar, maliyet)]}"""
    rec = Recipes()
    use = rec.consumption(product_id, options, 1, takeaway)
    lines = [(rec.ingredients.get(i), q, cost_of(q, rec.ingredients[i]) if i in rec.ingredients else 0)
             for i, q in use.items()]
    cost = sum(c for _, _, c in lines)
    net = price * 100 // (100 + tax_rate)
    profit = net - cost
    return {'cost': cost, 'netPrice': net, 'profit': profit,
            'margin': round(profit * 100 / net) if net else 0, 'lines': lines}


# =====================================================================
# Tedarik (8b): tedarikçiler, siparişler, teslim alma, ödeme
# =====================================================================

PAY_METHODS = {'cash': 'Nakit', 'card': 'Kredi Kartı', 'transfer': 'Havale / EFT'}
PO_STATUS = {'draft': 'Taslak', 'sent': 'Gönderildi', 'partial': 'Kısmen teslim', 'received': 'Teslim alındı',
             'cancelled': 'İptal'}


def _pending_payloads(conn, op):
    rows = conn.execute("SELECT payload FROM outbox WHERE op=? AND status='pending'", (op,)).fetchall()
    return [json.loads(r['payload']) for r in rows]


def suppliers(include_deleted=False):
    """Tedarikçiler; 'balance' (borç) buluta gitmemiş teslim/ödemeler eklenmiş hâlidir."""
    items = database.cache_rows('suppliers', include_deleted)
    conn = database.get_connection()
    delta = {}
    for p in _pending_payloads(conn, 'receivePurchase'):
        if p['payment']['status'] == 'unpaid':
            delta[p['supplierId']] = delta.get(p['supplierId'], 0) + sum(l['amount'] for l in p['lines'])
    for p in _pending_payloads(conn, 'supplierPayment'):
        delta[p['supplierId']] = delta.get(p['supplierId'], 0) - p['amount']
    conn.close()
    for s in items:
        s['balance'] = int(s.get('balance') or 0) + delta.get(s['id'], 0)
    return sorted(items, key=lambda s: s['name'].lower())


def purchase_orders(statuses=None):
    rows = database.cache_rows('purchaseOrders')
    rows = [r for r in rows if statuses is None or r.get('status') in statuses]
    return sorted(rows, key=lambda r: -(r.get('no') or 0))


def suggest_order(supplier_id):
    """Kritik seviyedeki (bu tedarikçinin) malzemeleri hedef seviyeye tamamlayan satırlar; alış birimine yuvarlanır."""
    lines = []
    for i in ingredients():
        if i.get('supplierId') != supplier_id or not i['isCritical']:
            continue
        target = i.get('target') or max(i.get('critical', 0) * 2, 1)
        need = max(target - i['stock'], 0)
        pack = (i.get('purchaseUnit') or {}).get('size') or 1
        qty = -(-need // pack) * pack if need else pack
        lines.append({'ingredientId': i['id'], 'qty': qty, 'amount': cost_of(qty, i)})
    return lines


def _expense(conn, user, kind, amount, method, detail):
    conn.execute("""INSERT INTO expenses (masraf_tipi,tutar,odeme_tipi,masraf_detayi,kullanici_id,masraf_tarihi,
        eklenme_tarihi) VALUES (?,?,?,?,?,?,?)""",
        (kind, amount / 100, PAY_METHODS[method], detail, user.get('id'), datetime.now().strftime('%Y-%m-%d'),
         datetime.now().strftime('%Y-%m-%d %H:%M')))


def _check_cash(user, method, approver_id):
    """Nakit ödeme açık kasadan çıkar: kasa işlemi yetkisi gerekir."""
    import cash
    import pos
    if method == 'cash' and cash.current_session():
        pos.require_permission(user, approver_id, 'cash')
        return True
    return False


def receive(user, supplier_id, lines, payment, purchase_order_id=None, note='', approver_id=None):
    """
    Teslim alma: lines [{ingredientId, qty (temel birim), amount (kuruş satır toplamı)}],
    payment {'status': 'paid'|'unpaid', 'method': 'cash'|'card'|'transfer'}. Stok hemen artar, birim maliyet
    ağırlıklı ortalamayla güncellenir (sunucu da aynısını yapar). Ödendiyse Masraflar'a yazılır; nakitse açık
    kasadan çıkış olarak düşer. Borç bakiyesi ödenmediyse artar. İnternetsiz çalışır.
    """
    import pos
    from cloud.orders import OrderError
    pos.require_permission(user, approver_id, 'stock')
    lines = [l for l in lines if l.get('qty', 0) > 0]
    if not lines:
        raise OrderError("Teslim alınan malzeme yok.")
    if payment['status'] not in ('paid', 'unpaid') or (payment['status'] == 'paid' and payment.get('method') not in PAY_METHODS):
        raise OrderError("Ödeme bilgisi geçersiz.")
    supplier = database.menu_item('suppliers', supplier_id)
    if not supplier:
        raise OrderError("Tedarikçi bulunamadı.")
    paid_cash = payment['status'] == 'paid' and _check_cash(user, payment['method'], approver_id)
    receipt_id = 'PR' + uuid.uuid4().hex[:20]
    total = sum(l['amount'] for l in lines)
    payload = {'receiptId': receipt_id, 'supplierId': supplier_id, 'lines': lines, 'note': note,
               'payment': {'status': payment['status'], **({'method': payment['method']} if payment['status'] == 'paid' else {})},
               'approvedBy': approver_id or user['cloud_id']}
    if purchase_order_id:
        payload['purchaseOrderId'] = purchase_order_id
    current = {i['id']: i for i in ingredients()}
    conn = database.get_connection()
    try:
        op_id = database.enqueue_op('receivePurchase', payload, user['cloud_id'], conn=conn)
        at = _now()
        for l in lines:
            conn.execute("""INSERT INTO stock_ledger (movement_id,op_id,type,ingredient_id,qty,order_id,line_id,at)
                VALUES (?,?,?,?,?,?,?,?)""", (receipt_id, op_id, 'purchase', l['ingredientId'], l['qty'],
                                              purchase_order_id, None, at))
            ing = current.get(l['ingredientId'])
            if ing:  # birim maliyet hemen güncellensin (sunucudaki weightedUnitCost ile aynı)
                factor = UNITS[ing['unit']][1]
                s = max(ing['stock'], 0)
                ing['unitCost'] = int(((s * ing.get('unitCost', 0)) / factor + l['amount']) * factor / (s + l['qty']) + 0.5)
                ing['stock'] += l['qty']
                row = conn.execute("SELECT data FROM cloud_cache WHERE collection='ingredients' AND id=?",
                                   (ing['id'],)).fetchone()
                if row:
                    data = {**json.loads(row['data']), 'unitCost': ing['unitCost']}
                    conn.execute("UPDATE cloud_cache SET data=? WHERE collection='ingredients' AND id=?",
                                 (json.dumps(data, ensure_ascii=False), ing['id']))
        conn.execute("""INSERT INTO purchase_log (id,kind,supplier_id,purchase_order_id,total,payment_status,method,note,
            data,at,business_day,staff_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (receipt_id, 'receipt', supplier_id, purchase_order_id, total, payment['status'], payment.get('method'),
             note, json.dumps(lines, ensure_ascii=False), at, _business_day(at), user['cloud_id']))
        if payment['status'] == 'paid':
            _expense(conn, user, f"Tedarikçi: {supplier['name']}", total, payment['method'], note or 'Mal alımı')
        conn.commit()
    finally:
        conn.close()
    if paid_cash:
        import cash
        cash.add_movement(user, 'out', total, f"{supplier['name']} ödemesi", expense=False, approver_id=approver_id)
    return receipt_id


def pay_supplier(user, supplier_id, amount, method, note='', approver_id=None):
    """Tedarikçiye ödeme: borç bakiyesi düşer, Masraflar'a yazılır, nakitse açık kasadan çıkar."""
    import pos
    from cloud.orders import OrderError
    pos.require_permission(user, approver_id, 'stock')
    amount = int(amount)
    if amount <= 0 or method not in PAY_METHODS:
        raise OrderError("Ödeme tutarı ya da yöntemi geçersiz.")
    supplier = database.menu_item('suppliers', supplier_id)
    if not supplier:
        raise OrderError("Tedarikçi bulunamadı.")
    paid_cash = _check_cash(user, method, approver_id)
    payment_id = 'SP' + uuid.uuid4().hex[:20]
    conn = database.get_connection()
    try:
        database.enqueue_op('supplierPayment', {'paymentId': payment_id, 'supplierId': supplier_id, 'amount': amount,
                                                'method': method, 'note': note,
                                                'approvedBy': approver_id or user['cloud_id']}, user['cloud_id'], conn=conn)
        at = _now()
        conn.execute("""INSERT INTO purchase_log (id,kind,supplier_id,total,payment_status,method,note,at,business_day,
            staff_id) VALUES (?,?,?,?,?,?,?,?,?,?)""", (payment_id, 'payment', supplier_id, amount, 'paid', method, note,
                                                       at, _business_day(at), user['cloud_id']))
        _expense(conn, user, f"Tedarikçi: {supplier['name']}", amount, method, note or 'Borç ödemesi')
        conn.commit()
    finally:
        conn.close()
    if paid_cash:
        import cash
        cash.add_movement(user, 'out', amount, f"{supplier['name']} ödemesi", expense=False, approver_id=approver_id)
    return payment_id


def supplier_statement(supplier_id):
    """Bu bilgisayarda girilen teslim ve ödemeler (en yeni üstte)."""
    conn = database.get_connection()
    rows = conn.execute("SELECT * FROM purchase_log WHERE supplier_id=? ORDER BY at DESC, rowid DESC", (supplier_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def purchases(day_from, day_to):
    conn = database.get_connection()
    rows = conn.execute("""SELECT * FROM purchase_log WHERE kind='receipt' AND business_day BETWEEN ? AND ?
        ORDER BY at DESC, rowid DESC""", (day_from, day_to)).fetchall()
    conn.close()
    return [{**dict(r), 'lines': json.loads(r['data'] or '[]')} for r in rows]


def order_text(order, cafe_name):
    """Tedarikçiye gönderilecek sipariş metni (WhatsApp / e-posta)."""
    ings = {i['id']: i for i in ingredients(include_deleted=True)}
    out = [f"Merhaba, {cafe_name} sipariş no {order.get('no', '')}:"]
    for l in order['lines']:
        ing = ings.get(l['ingredientId'], {'name': '?', 'unit': 'adet'})
        pu = ing.get('purchaseUnit')
        qty = (f"{l['qty'] // pu['size']} {pu['name']} ({format_qty(l['qty'], ing['unit'])})"
               if pu and l['qty'] % pu['size'] == 0 else format_qty(l['qty'], ing['unit']))
        out.append(f"• {qty} {ing['name']}")
    if order.get('note'):
        out.append(f"Not: {order['note']}")
    out.append("Teşekkürler.")
    return "\n".join(out)


# =====================================================================
# Zayi (8b)
# =====================================================================

WASTE_REASONS = ["Bozuldu", "Düştü / döküldü", "Son kullanma tarihi geçti", "Yanlış hazırlandı", "Diğer"]


def _log_waste(conn, movement_id, kind, ref_id, name, qty, unit, reason, cost, staff_id):
    at = _now()
    conn.execute("""INSERT INTO waste_log (movement_id,kind,ref_id,name,qty,unit,reason,cost,staff_id,at,business_day)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (movement_id, kind, ref_id, name, qty, unit, reason, cost, staff_id, at,
                                             _business_day(at)))


def waste_product(user, product_id, qty, reason, approver_id=None, manual_cost=None, options=()):
    """Ürün zayisi: reçetesi stoktan düşer (modül açıksa), maliyet reçeteden; reçete yoksa manual_cost (kuruş)."""
    import pos
    from cloud.orders import OrderError
    pos.require_permission(user, approver_id, 'waste')
    product = database.menu_item('products', product_id)
    if not product or qty < 1 or not reason:
        raise OrderError("Ürün, adet ve gerekçe gerekli.")
    rec = Recipes()
    use = rec.consumption(product_id, options, qty) if enabled() else {}
    cost = rec.cost(use) if use else int(manual_cost or 0)
    conn = database.get_connection()
    try:
        movement = _move(conn, 'waste', use, user['cloud_id'], reason=reason, approver_id=approver_id) if use else None
        _log_waste(conn, movement, 'product', product_id, product['name'], qty, 'adet', reason, cost, user['cloud_id'])
        conn.commit()
    finally:
        conn.close()
    return cost


def waste_ingredient(user, ingredient_id, qty, reason, approver_id=None):
    import pos
    from cloud.orders import OrderError
    pos.require_permission(user, approver_id, 'waste')
    ing = ingredient_map().get(ingredient_id)
    if not ing or qty < 1 or not reason:
        raise OrderError("Malzeme, miktar ve gerekçe gerekli.")
    cost = cost_of(qty, ing)
    conn = database.get_connection()
    try:
        movement = _move(conn, 'waste', {ingredient_id: qty}, user['cloud_id'], reason=reason, approver_id=approver_id)
        _log_waste(conn, movement, 'ingredient', ingredient_id, ing['name'], qty, ing['unit'], reason, cost,
                   user['cloud_id'])
        conn.commit()
    finally:
        conn.close()
    return cost


def waste_entries(day_from, day_to):
    """Yeni zayi kayıtları + eski NexPOS zayi sayfası kayıtları (eski kayıt)."""
    conn = database.get_connection()
    rows = [dict(r) for r in conn.execute("""SELECT * FROM waste_log WHERE business_day BETWEEN ? AND ?
        ORDER BY at DESC, rowid DESC""", (day_from, day_to))]
    legacy = conn.execute("""SELECT w.*, p.ad AS product_name FROM waste w LEFT JOIN products p ON p.id = w.product_id
        WHERE substr(w.zayi_tarihi,1,10) BETWEEN ? AND ?""", (day_from, day_to)).fetchall()
    conn.close()
    for w in legacy:
        rows.append({'kind': 'legacy', 'name': f"{w['product_name'] or 'Ürün'} (eski kayıt)", 'qty': w['adet'],
                     'unit': 'adet', 'reason': w['zayi_nedeni'] or '', 'cost': int(round((w['maliyet_tutari'] or 0) * 100)),
                     'staff_id': None, 'at': (w['zayi_tarihi'] or '').replace(' ', 'T'), 'business_day': w['zayi_tarihi'][:10]})
    return rows


# =====================================================================
# Tüketim raporu (8b): teorik / gerçek, alış, zayi, sayım farkı
# =====================================================================

def consumption_report(day_from, day_to):
    """
    Malzeme başına dönem içinde: satış tüketimi (satış − iade), zayi, alış ve sayım farkı.
    Teorik tüketim = satış + zayi; gerçek tüketim = teorik − sayım farkı (sayımda eksik çıkan fazladan
    kullanılmıştır). İlk sayım farkı kayıp sayılmaz.
    """
    conn = database.get_connection()
    rows = conn.execute("SELECT type, ingredient_id, qty, movement_id, at FROM stock_ledger").fetchall()
    initial = {r['movement_id'] for r in conn.execute("SELECT movement_id FROM count_log WHERE initial=1")}
    conn.close()
    ings = {i['id']: i for i in ingredients(include_deleted=True)}
    out = {}
    for r in rows:
        if not day_from <= _business_day(r['at']) <= day_to or r['ingredient_id'] not in ings:
            continue
        o = out.setdefault(r['ingredient_id'], {'sale': 0, 'waste': 0, 'purchase': 0, 'countDiff': 0})
        if r['type'] in ('sale', 'void_return'):
            o['sale'] -= r['qty']
        elif r['type'] == 'waste':
            o['waste'] -= r['qty']
        elif r['type'] == 'purchase':
            o['purchase'] += r['qty']
        elif r['type'] == 'count' and r['movement_id'] not in initial:
            o['countDiff'] += r['qty']
    result = []
    for ing_id, o in out.items():
        ing = ings[ing_id]
        theoretical = o['sale'] + o['waste']
        diff_cost = cost_of(abs(o['countDiff']), ing) * (1 if o['countDiff'] >= 0 else -1)
        result.append({'ingredientId': ing_id, 'name': ing['name'], 'unit': ing['unit'], **o,
                       'theoretical': theoretical, 'actual': theoretical - o['countDiff'], 'diffCost': diff_cost,
                       'saleCost': cost_of(max(o['sale'], 0), ing), 'wasteCost': cost_of(max(o['waste'], 0), ing),
                       'purchaseCost': cost_of(o['purchase'], ing)})
    return sorted(result, key=lambda r: (r['diffCost'], r['name']))


def stock_value():
    return sum(i['value'] for i in ingredients())
