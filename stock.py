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
import uuid
from datetime import datetime

import database

UNITS = {'g': ('kg', 1000), 'ml': ('L', 1000), 'adet': ('adet', 1)}
GROUPS = {'bar': 'Bar', 'kitchen': 'Mutfak', 'packaging': 'Ambalaj', 'other': 'Diğer'}


def enabled():
    return database.modules()['stock']['enabled']


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
    """Satırın satışta düşülen miktarı; bölünmüş satırda (splitFrom) ana satırdan adet oranında."""
    chain = [line['lineId']]
    if line.get('splitFrom'):
        chain.append(line['splitFrom'])
    for lid in chain:
        rows = conn.execute("""SELECT ingredient_id, SUM(qty) AS q FROM stock_ledger
            WHERE order_id=? AND line_id=? AND type IN ('sale','void_return') GROUP BY ingredient_id""",
                            (order['id'], lid)).fetchall()
        if rows:
            if lid == line['lineId']:
                return {r['ingredient_id']: -r['q'] for r in rows if r['q']}
            # Ana satırdan bölünmüş parça: güncel reçeteyle hesaplanır (ana satır hâlâ düşülmüş)
            return Recipes().line_consumption(line, order['type'])
    return {}


def record_void_return(conn, order, line, staff_id):
    """Hazırlanmadan iptal edilen satır stoğa döner (yalnızca gerçekten düşülmüş olan kadar)."""
    use = _sold_for_line(conn, order, line)
    if use:
        _move(conn, 'void_return', use, staff_id, order['id'], line['lineId'], sign=+1)


def set_counts(user, counts, reason='Sayım', approver_id=None):
    """counts: {malzeme: sayılan miktar}. Fark kadar 'count' hareketi yazar; yazılan farkları döndürür."""
    current = ingredient_map()
    use = {}
    for ing_id, counted in counts.items():
        if ing_id in current and counted is not None:
            delta = int(counted) - current[ing_id]['stock']
            if delta:
                use[ing_id] = delta
    if not use:
        return {}
    conn = database.get_connection()
    try:
        _move(conn, 'count', use, user['cloud_id'], reason=reason, approver_id=approver_id, sign=+1)
        conn.commit()
    finally:
        conn.close()
    return use


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
