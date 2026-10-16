"""
NexPOS - Raporlar (7. ekran)

Bütün rapor rakamları yerel adisyonlardan (pos_orders) hesaplanır; internetsiz çalışır.

Temel birim bir adisyonun **katkısı**dır (contribution): ödenmiş adisyonun cirosu, iskontosu,
ödeme yöntemleri, saati, ürünleri, personeli, ikram/iptali ve KDV dağılımı. Bir dönemin raporu,
o dönemdeki katkıların toplamıdır. Sunucu da aynı katkıyı (firebase/functions/src/stats.js)
dailyStats/{iş günü} dokümanına ekler; iki hesap testlerde karşılaştırılır.

Kurallar:
  - Adisyon, açıldığı iş gününe yazılır (gün 05:00'te döner); saat dağılımı kapanış saatine göre.
  - İade, yapıldığı iş gününe yazılır.
  - İskonto satırlara orantılı dağıtılır (kuruş farkı son satırda) — KDV ve ürün cirosu bu paydan.
  - İkram ve iptal satışa dahil değildir; liste fiyatıyla ayrıca gösterilir.

Para her zaman kuruştur.
"""
import json
from datetime import date, datetime, timedelta

import database
from cloud.orders import compute_totals, line_total

DAY_START_HOUR = 5
METHODS = ('cash', 'card', 'meal')
WEEKDAYS = ('Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar')


# =====================================================================
# Yardımcılar
# =====================================================================

def business_day_of(iso):
    """'2026-10-16T02:30:00+03:00' → '2026-10-15' (yerel saat, 05:00 dönümü)."""
    local = datetime.fromisoformat(iso[:19])
    return (local - timedelta(hours=DAY_START_HOUR)).strftime('%Y-%m-%d')


def business_minutes(iso):
    """İş günü başından (05:00) bu yana geçen dakika: aynı saate kadar karşılaştırma için."""
    local = datetime.fromisoformat(iso[:19])
    return ((local.hour - DAY_START_HOUR) % 24) * 60 + local.minute


def _list_value(line):
    """İkram/iptal edilen satırın liste fiyatı (status'a bakmadan)."""
    return line_total({**line, 'status': 'active'})


def product_key(line):
    return line.get('productId') or f"n:{line['name']}"


def line_nets(order):
    """Aktif satırlar ve iskonto düşülmüş payları: [(satır, net)]. Toplam = adisyon toplamı."""
    lines = [l for l in order['items'] if l['status'] == 'active' and line_total(l) > 0]
    t = compute_totals(order)
    left = t['discountAmount']
    out = []
    for i, l in enumerate(lines):
        lt = line_total(l)
        share = left if i == len(lines) - 1 else (t['discountAmount'] * lt) // t['subtotal']
        left -= share
        out.append((l, lt - share))
    return out


def vat_by_rate(order):
    """KDV dahil tutarın oranlara dağılımı: {oran: tutar}."""
    gross = {}
    for l, net in line_nets(order):
        rate = l.get('taxRate', 10)
        gross[rate] = gross.get(rate, 0) + net
    return gross


def vat_amount(gross, rate):
    """KDV dahil tutardaki KDV (yarım yukarı yuvarlanır)."""
    return (gross * rate * 2 + (100 + rate)) // ((100 + rate) * 2)


def merge(a, b):
    """Katkıları toplar: sayılar eklenir, sözlükler iç içe birleşir, metin (ad) korunur."""
    for k, v in b.items():
        if isinstance(v, dict):
            merge(a.setdefault(k, {}), v)
        elif isinstance(v, str):
            a.setdefault(k, v)
        else:
            a[k] = a.get(k, 0) + v
    return a


# =====================================================================
# Katkı (sunucudaki stats.js ile aynı)
# =====================================================================

def contribution(order):
    """Bir adisyonun güne katkısı. Açık ya da birleştirilmiş adisyon katkı vermez."""
    if order['status'] == 'cancelled':
        lost = [l for l in order['items'] if l['status'] == 'void' or (l['status'] == 'active' and l['state'] == 'sent')]
        return {'cancelled': 1,
                'voids': {'count': sum(l['qty'] for l in lost), 'amount': sum(_list_value(l) for l in lost)}}
    if order['status'] != 'paid':
        return {}
    t = compute_totals(order)
    hour = (order.get('closedAt') or order['openedAt'])[11:13]
    c = {
        'orders': 1,
        'dineIn': 1 if order['type'] == 'dine_in' else 0,
        'takeaway': 0 if order['type'] == 'dine_in' else 1,
        'gross': t['subtotal'],
        'discount': t['discountAmount'],
        'discountCount': 1 if t['discountAmount'] else 0,
        'revenue': t['total'],
        'tips': sum(p.get('tip') or 0 for p in order['payments']),
        'byPayment': {},
        'byHour': {hour: {'revenue': t['total'], 'orders': 1}},
        'byStaff': {order['waiterId']: {'revenue': t['total'], 'orders': 1}},
        'byProduct': {},
        'comps': {'count': 0, 'amount': 0},
        'voids': {'count': 0, 'amount': 0},
        'vat': {},
    }
    for p in order['payments']:
        c['byPayment'][p['method']] = c['byPayment'].get(p['method'], 0) + p['amount']
    for l, net in line_nets(order):
        merge(c['byProduct'], {product_key(l): {'name': l['name'], 'qty': l['qty'], 'revenue': net}})
        rate = str(l.get('taxRate', 10))
        c['vat'][rate] = c['vat'].get(rate, 0) + net
    for l in order['items']:
        if l['status'] in ('comp', 'void'):
            kind = 'comps' if l['status'] == 'comp' else 'voids'
            c[kind]['count'] += l['qty']
            c[kind]['amount'] += _list_value(l)
            merge(c['byProduct'], {product_key(l): {'name': l['name'], kind: l['qty']}})
    return c


def refund_contribution(refund):
    return {'refunds': {'count': 1, 'amount': refund['amount'], refund['method']: refund['amount']}}


# =====================================================================
# Veri
# =====================================================================

def _orders(day_from, day_to):
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM pos_orders WHERE business_day BETWEEN ? AND ? ORDER BY rowid",
                        (day_from, day_to)).fetchall()
    conn.close()
    return [json.loads(r['data']) for r in rows]


def _refunds(day_from, day_to):
    """İadeler yapıldıkları güne yazılır; eski bir adisyonun iadesi de bulunsun diye geniş taranır."""
    start = (date.fromisoformat(day_from) - timedelta(days=120)).isoformat()
    conn = database.get_connection()
    rows = conn.execute("SELECT data FROM pos_orders WHERE status='paid' AND business_day>=? AND data LIKE '%refundId%'",
                        (start,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        order = json.loads(r['data'])
        for ref in order.get('refunds') or []:
            if day_from <= business_day_of(ref['at']) <= day_to:
                out.append({**ref, 'orderId': order['id'], 'orderNo': order['no'], 'tableName': order.get('tableName'),
                            'type': order['type']})
    return out


def day_stats(day):
    """Bir iş gününün özeti: buluttaki dailyStats/{gün} ile aynı yapı."""
    s = {}
    for o in _orders(day, day):
        merge(s, contribution(o))
    for r in _refunds(day, day):
        merge(s, refund_contribution(r))
    return s


def _legacy(day_from, day_to):
    """Yeni sisteme geçmeden önceki NexPOS satışları (yalnızca toplam ve ürün adedi vardır)."""
    start = f"{day_from} {DAY_START_HOUR:02d}:00"
    end = f"{(date.fromisoformat(day_to) + timedelta(days=1)).isoformat()} {DAY_START_HOUR:02d}:00"
    conn = database.get_connection()
    rows = conn.execute("""SELECT o.id, o.toplam_tutar FROM orders o WHERE o.durum='tamamlandi'
        AND o.tarih >= ? AND o.tarih < ? AND o.id NOT IN
        (SELECT legacy_order_id FROM pos_orders WHERE legacy_order_id IS NOT NULL)""", (start, end)).fetchall()
    ids = [r['id'] for r in rows]
    products = {}
    if ids:
        for r in conn.execute(f"""SELECT p.ad, SUM(oi.adet) AS qty, SUM(oi.toplam) AS total FROM order_items oi
                JOIN products p ON p.id = oi.product_id WHERE oi.order_id IN ({','.join('?' * len(ids))})
                GROUP BY p.ad""", ids):
            products[r['ad']] = {'qty': r['qty'] or 0, 'revenue': int(round((r['total'] or 0) * 100))}
    conn.close()
    return {'orders': len(rows), 'revenue': int(round(sum(r['toplam_tutar'] or 0 for r in rows) * 100)),
            'products': products}


# =====================================================================
# Dönem
# =====================================================================

def today():
    return (datetime.now() - timedelta(hours=DAY_START_HOUR)).date()


PERIODS = (('today', 'Bugün'), ('yesterday', 'Dün'), ('week', 'Bu hafta'), ('last_week', 'Geçen hafta'),
           ('month', 'Bu ay'), ('last_month', 'Geçen ay'))


def period(name, ref=None):
    """Hazır dönem → (ilk gün, son gün) ISO."""
    d = ref or today()
    if name == 'today':
        a = b = d
    elif name == 'yesterday':
        a = b = d - timedelta(days=1)
    elif name == 'week':
        a, b = d - timedelta(days=d.weekday()), d
    elif name == 'last_week':
        b = d - timedelta(days=d.weekday() + 1)
        a = b - timedelta(days=6)
    elif name == 'month':
        a, b = d.replace(day=1), d
    elif name == 'last_month':
        b = d.replace(day=1) - timedelta(days=1)
        a = b.replace(day=1)
    else:
        raise ValueError(name)
    return a.isoformat(), b.isoformat()


def previous_period(day_from, day_to):
    """Aynı uzunlukta bir önceki dönem."""
    a, b = date.fromisoformat(day_from), date.fromisoformat(day_to)
    n = (b - a).days + 1
    return (a - timedelta(days=n)).isoformat(), (a - timedelta(days=1)).isoformat()


def change(current, previous):
    """Yüzde değişim (önceki 0 ise None)."""
    if not previous:
        return None
    return round((current - previous) * 100 / previous)


# =====================================================================
# Rapor
# =====================================================================

class Report:
    """Bir dönemin bütün sekmeleri. Veriler bir kez okunur."""

    def __init__(self, day_from, day_to, include_legacy=True):
        self.day_from, self.day_to = day_from, day_to
        self.orders = _orders(day_from, day_to)
        self.refunds = _refunds(day_from, day_to)
        self.stats = {}
        for o in self.orders:
            merge(self.stats, contribution(o))
        for r in self.refunds:
            merge(self.stats, refund_contribution(r))
        self.legacy = _legacy(day_from, day_to) if include_legacy else {'orders': 0, 'revenue': 0, 'products': {}}
        self.paid = [o for o in self.orders if o['status'] == 'paid']

    # ---------------------------------------------------------------- satış
    def summary(self):
        s = self.stats
        refunds = s.get('refunds', {})
        vat = [{'rate': int(r), 'gross': g, 'vat': vat_amount(g, int(r)), 'net': g - vat_amount(g, int(r))}
               for r, g in sorted(s.get('vat', {}).items(), key=lambda kv: int(kv[0]))]
        orders = s.get('orders', 0)
        revenue = s.get('revenue', 0)
        return {
            'gross': s.get('gross', 0), 'discount': s.get('discount', 0), 'discountCount': s.get('discountCount', 0),
            'revenue': revenue,
            'refunds': refunds.get('amount', 0), 'refundCount': refunds.get('count', 0),
            'net': revenue - refunds.get('amount', 0),
            'comps': s.get('comps', {'count': 0, 'amount': 0}), 'voids': s.get('voids', {'count': 0, 'amount': 0}),
            'tips': s.get('tips', 0),
            'byPayment': {m: s.get('byPayment', {}).get(m, 0) for m in METHODS},
            'vat': vat,
            'orders': orders, 'average': revenue // orders if orders else 0,
            'dineIn': s.get('dineIn', 0), 'takeaway': s.get('takeaway', 0), 'cancelled': s.get('cancelled', 0),
            'legacy': {'orders': self.legacy['orders'], 'revenue': self.legacy['revenue']},
        }

    # ---------------------------------------------------------------- ürün
    def products(self):
        """Ürün tablosu (ciroya göre); eski kayıtlar ayrı satır olarak eklenir."""
        rows = []
        total = self.stats.get('revenue', 0) or 1
        costs = self.costing()['products']
        for key, p in self.stats.get('byProduct', {}).items():
            c = costs.get(key, {'cost': 0, 'exVat': 0})
            profit = c['exVat'] - c['cost']
            rows.append({'key': key, 'name': p['name'], 'qty': p.get('qty', 0), 'revenue': p.get('revenue', 0),
                         'share': p.get('revenue', 0) * 100 / total, 'comps': p.get('comps', 0),
                         'voids': p.get('voids', 0), 'legacy': False, 'cost': c['cost'], 'exVat': c['exVat'],
                         'profit': profit if c['cost'] else None,
                         'margin': round(profit * 100 / c['exVat']) if c['cost'] and c['exVat'] else None})
        for name, p in self.legacy['products'].items():
            rows.append({'key': f'legacy:{name}', 'name': f"{name} (eski kayıt)", 'qty': p['qty'],
                         'revenue': p['revenue'], 'share': None, 'comps': 0, 'voids': 0, 'legacy': True,
                         'cost': 0, 'exVat': 0, 'profit': None, 'margin': None})
        return sorted(rows, key=lambda r: (-r['revenue'], r['name']))

    # ---------------------------------------------------------------- maliyet ve kâr (8. ekran)
    def costing(self):
        """Ürün başına maliyet ve KDV hariç ciro; ikram ve hazırlanmış iptal maliyeti (güncel birim maliyetle)."""
        if hasattr(self, '_costing'):
            return self._costing
        import stock
        rec = stock.Recipes()
        per, comps, waste = {}, 0, 0
        for o in self.orders:
            if o['status'] == 'paid':
                for l, net in line_nets(o):
                    r = per.setdefault(product_key(l), {'cost': 0, 'exVat': 0})
                    r['cost'] += rec.line_cost(l, o['type'])
                    r['exVat'] += net - vat_amount(net, l.get('taxRate', 10))
            for l in o['items']:
                if o['status'] == 'paid' and l['status'] == 'comp':
                    comps += rec.line_cost(l, o['type'])
                prepared_void = l['status'] == 'void' and l.get('prepared', True)
                cancelled_sent = (o['status'] == 'cancelled' and o.get('prepared', True)
                                  and l['status'] == 'active' and l.get('state') == 'sent')
                if prepared_void or cancelled_sent:
                    waste += rec.line_cost(l, o['type'])
        has_recipes = any(p.get('recipe') for p in rec.products.values())
        self._costing = {'products': per, 'comps': comps, 'waste': waste, 'hasRecipes': has_recipes,
                         'sold': sum(v['cost'] for v in per.values())}
        return self._costing

    def menu_analysis(self):
        """Menü analizi: adet (popülerlik) ve birim kâr (KDV hariç fiyat − maliyet) ortalamalarına göre dört grup."""
        rows = [p for p in self.products() if not p['legacy'] and p['qty'] and p.get('cost')]
        if not rows:
            return []
        total_qty = sum(r['qty'] for r in rows)
        avg_qty = total_qty / len(rows)
        avg_profit = sum(r['profit'] for r in rows) / total_qty
        out = []
        for r in rows:
            popular = r['qty'] >= 0.7 * avg_qty
            profitable = r['profit'] / r['qty'] >= avg_profit
            kind = {(True, True): 'star', (True, False): 'plowhorse', (False, True): 'puzzle',
                    (False, False): 'dog'}[(popular, profitable)]
            out.append({**r, 'unitProfit': r['profit'] // r['qty'], 'class': kind})
        order = {'star': 0, 'plowhorse': 1, 'puzzle': 2, 'dog': 3}
        return sorted(out, key=lambda r: (order[r['class']], -r['profit']))

    def categories(self):
        cats = {}
        for key, p in self.stats.get('byProduct', {}).items():
            product = database.menu_item('products', key) if not key.startswith('n:') else None
            cat = database.menu_item('categories', product.get('categoryId')) if product else None
            name = cat['name'] if cat else 'Diğer'
            c = cats.setdefault(name, {'name': name, 'qty': 0, 'revenue': 0})
            c['qty'] += p.get('qty', 0)
            c['revenue'] += p.get('revenue', 0)
        return sorted(cats.values(), key=lambda c: -c['revenue'])

    def options(self):
        """Seçenek kullanımı: kaç kez seçildi, ne kadar ek gelir getirdi (liste fiyatıyla)."""
        out = {}
        for o in self.paid:
            for l in o['items']:
                if l['status'] != 'active':
                    continue
                for opt in l.get('options') or []:
                    r = out.setdefault(opt['name'], {'name': opt['name'], 'count': 0, 'extra': 0})
                    r['count'] += l['qty']
                    r['extra'] += opt['priceDelta'] * l['qty']
        return sorted(out.values(), key=lambda r: (-r['count'], r['name']))

    def unsold(self):
        sold = set(self.stats.get('byProduct', {}))
        return sorted((p['name'] for p in database.menu_products()
                       if not p.get('deleted') and p.get('active', True) and p['id'] not in sold),
                      key=str.lower)

    # ---------------------------------------------------------------- zaman
    def heatmap(self):
        """{(haftanın günü 0-6, saat 'HH'): ciro} — kapanış saatine göre."""
        grid = {}
        for o in self.paid:
            wd = date.fromisoformat(o['businessDay']).weekday()
            hour = (o.get('closedAt') or o['openedAt'])[11:13]
            grid[(wd, hour)] = grid.get((wd, hour), 0) + o['total']
        return grid

    def weekdays(self):
        """Haftanın günlerine göre ortalama günlük ciro (dönemde o günden kaç tane varsa)."""
        a, b = date.fromisoformat(self.day_from), date.fromisoformat(self.day_to)
        counts = [0] * 7
        d = a
        while d <= b:
            counts[d.weekday()] += 1
            d += timedelta(days=1)
        totals = [0] * 7
        for o in self.paid:
            totals[date.fromisoformat(o['businessDay']).weekday()] += o['total']
        return [{'day': WEEKDAYS[i], 'average': totals[i] // counts[i] if counts[i] else 0, 'days': counts[i]}
                for i in range(7)]

    # ---------------------------------------------------------------- personel
    def staff(self):
        rows = {}

        def row(staff_id):
            if staff_id not in rows:
                st = database.get_staff(staff_id)
                rows[staff_id] = {'staffId': staff_id, 'name': st['name'] if st else '—', 'orders': 0, 'revenue': 0,
                                  'tips': 0, 'discount': 0, 'comps': 0, 'voids': 0, 'approved': 0}
            return rows[staff_id]

        for o in self.paid:
            r = row(o['waiterId'])
            r['orders'] += 1
            r['revenue'] += o['total']
            r['tips'] += sum(p.get('tip') or 0 for p in o['payments'])
            d = o.get('discount')
            if d:
                row(d['by'])['discount'] += 1
                if d.get('approvedBy') and d['approvedBy'] != d['by']:
                    row(d['approvedBy'])['approved'] += 1
            for l in o['items']:
                if l['status'] in ('comp', 'void'):
                    row(l['by'])['comps' if l['status'] == 'comp' else 'voids'] += l['qty']
                    if l.get('approvedBy') and l['approvedBy'] != l['by']:
                        row(l['approvedBy'])['approved'] += 1
        for r in rows.values():
            r['average'] = r['revenue'] // r['orders'] if r['orders'] else 0
        return sorted(rows.values(), key=lambda r: (-r['revenue'], r['name']))

    # ---------------------------------------------------------------- kayıp / denetim
    def losses(self):
        """İptal, ikram, iskonto, iade, adisyon iptali ve kasa farkı: tek tek, en yeni üstte."""
        events = []

        def name(staff_id):
            st = database.get_staff(staff_id) if staff_id else None
            return st['name'] if st else '—'

        def where(o):
            return o.get('tableName') or 'Paket'

        for o in self.orders:
            for l in o['items']:
                if l['status'] in ('comp', 'void'):
                    events.append({'kind': 'İkram' if l['status'] == 'comp' else 'İptal',
                                   'at': l.get('actionAt') or o.get('closedAt') or o['openedAt'],
                                   'order': o['no'], 'where': where(o), 'what': f"{l['qty']}× {l['name']}",
                                   'amount': _list_value(l), 'by': name(l.get('by')),
                                   'approvedBy': name(l.get('approvedBy')), 'reason': l.get('reason', '')})
            d = o.get('discount')
            if d and o['status'] == 'paid':
                label = f"%{d['value']}" if d['type'] == 'percent' else 'tutar'
                events.append({'kind': 'İskonto', 'at': d.get('at') or o.get('closedAt'), 'order': o['no'],
                               'where': where(o), 'what': label, 'amount': o['discountAmount'],
                               'by': name(d.get('by')), 'approvedBy': name(d.get('approvedBy')),
                               'reason': d.get('reason', '')})
            if o['status'] == 'cancelled':
                lost = [l for l in o['items'] if l['status'] == 'active' and l['state'] == 'sent']
                events.append({'kind': 'Adisyon iptali', 'at': o.get('closedAt'), 'order': o['no'], 'where': where(o),
                               'what': f"{sum(l['qty'] for l in lost)} ürün",
                               'amount': sum(line_total(l) for l in lost), 'by': name(o.get('cancelledBy')),
                               'approvedBy': name(o.get('approvedBy')), 'reason': o.get('cancelReason', '')})
        for r in self.refunds:
            events.append({'kind': 'İade', 'at': r['at'], 'order': r['orderNo'], 'where': r.get('tableName') or 'Paket',
                           'what': r['method'], 'amount': r['amount'], 'by': name(r.get('by')),
                           'approvedBy': name(r.get('approvedBy')), 'reason': r.get('reason', '')})
        conn = database.get_connection()
        rows = conn.execute("SELECT data FROM cash_sessions WHERE status='closed' AND business_day BETWEEN ? AND ?",
                            (self.day_from, self.day_to)).fetchall()
        conn.close()
        for r in rows:
            s = json.loads(r['data'])
            if s.get('difference'):
                events.append({'kind': 'Kasa farkı', 'at': s['closedAt'], 'order': '', 'where': 'Kasa',
                               'what': 'sayılan − beklenen', 'amount': s['difference'], 'by': name(s.get('closedBy')),
                               'approvedBy': name(s.get('approvedBy')), 'reason': s.get('differenceReason') or ''})
        return sorted(events, key=lambda e: e['at'] or '', reverse=True)

    # ---------------------------------------------------------------- gelir-gider
    def income_expense(self):
        conn = database.get_connection()
        exp = conn.execute("""SELECT odeme_tipi, COALESCE(SUM(tutar),0) AS t FROM expenses
            WHERE masraf_tarihi BETWEEN ? AND ? GROUP BY odeme_tipi""", (self.day_from, self.day_to)).fetchall()
        waste = conn.execute("""SELECT COALESCE(SUM(maliyet_tutari),0) FROM waste
            WHERE substr(zayi_tarihi,1,10) BETWEEN ? AND ?""", (self.day_from, self.day_to)).fetchone()[0]
        conn.close()
        expenses = {r['odeme_tipi'] or 'Diğer': int(round(r['t'] * 100)) for r in exp}
        net = self.summary()['net'] + self.legacy['revenue']
        total_exp = sum(expenses.values())
        waste = int(round((waste or 0) * 100))
        c = self.costing()
        cogs = c['sold'] + c['comps']
        return {'net': net, 'expenses': total_exp, 'expensesByType': expenses, 'waste': waste,
                'cogs': cogs, 'compCost': c['comps'], 'voidWaste': c['waste'], 'hasRecipes': c['hasRecipes'],
                'remaining': net - total_exp - waste - cogs - c['waste']}

    # ---------------------------------------------------------------- mutfak
    def kitchen(self):
        """İstasyon ve ürün başına ortalama hazırlama süresi (gönderme → hazır), geciken fiş oranı."""
        late_min = database.modules()['kds']['lateMinutes']
        conn = database.get_connection()
        rows = conn.execute("SELECT data FROM pos_tickets").fetchall()
        conn.close()
        stations, products = {}, {}
        for r in rows:
            t = json.loads(r['data'])
            if not t.get('readyAt') or t.get('cancelled') or not self.day_from <= business_day_of(t['createdAt']) <= self.day_to:
                continue
            secs = (datetime.fromisoformat(t['readyAt'].replace('Z', '+00:00'))
                    - datetime.fromisoformat(t['createdAt'])).total_seconds()
            if secs < 0:
                continue
            s = stations.setdefault(t['station'], {'station': t['station'], 'tickets': 0, 'seconds': 0, 'late': 0})
            s['tickets'] += 1
            s['seconds'] += secs
            s['late'] += secs >= late_min * 60
            for l in t['lines']:
                if not l.get('voided'):
                    p = products.setdefault(l['name'], {'name': l['name'], 'tickets': 0, 'seconds': 0})
                    p['tickets'] += 1
                    p['seconds'] += secs
        for x in (*stations.values(), *products.values()):
            x['average'] = int(x['seconds'] / x['tickets']) if x['tickets'] else 0
        for s in stations.values():
            s['lateRate'] = round(s['late'] * 100 / s['tickets']) if s['tickets'] else 0
        return {'stations': sorted(stations.values(), key=lambda s: s['station']),
                'products': sorted(products.values(), key=lambda p: -p['average'])}


def compare(day_from, day_to):
    """(bu dönem özeti, önceki dönem özeti, {alan: % değişim})"""
    cur = Report(day_from, day_to).summary()
    prev = Report(*previous_period(day_from, day_to)).summary()
    keys = ('gross', 'discount', 'revenue', 'refunds', 'net', 'tips', 'orders', 'average')
    return cur, prev, {k: change(cur[k], prev[k]) for k in keys}


# =====================================================================
# Ana sayfa (bugün)
# =====================================================================

def dashboard(now=None):
    """
    Bugünün özeti ve geçen haftanın aynı günü, aynı saatine kadarki karşılaştırma.
    now: test için sabit an (ISO).
    """
    import cash  # cash da bu modülü kullanır; döngüsel içe aktarma olmasın
    now_iso = now or datetime.now().astimezone().isoformat(timespec='seconds')
    day = business_day_of(now_iso)
    last = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    cutoff = business_minutes(now_iso)

    def until_now(orders):
        return [o for o in orders if o['status'] in ('paid', 'cancelled')
                and business_minutes(o.get('closedAt') or o['openedAt']) <= cutoff]

    today_orders = _orders(day, day)
    s_today, s_last = {}, {}
    for o in today_orders:
        merge(s_today, contribution(o))
    for o in until_now(_orders(last, last)):
        merge(s_last, contribution(o))

    def hourly(stats):
        return {h: v['revenue'] for h, v in stats.get('byHour', {}).items()}

    def pct(key):
        return change(s_today.get(key, 0), s_last.get(key, 0))

    orders = s_today.get('orders', 0)
    last_orders = s_last.get('orders', 0)
    open_orders = [o for o in today_orders if o['status'] == 'open']
    conn = database.get_connection()
    for r in conn.execute("SELECT data FROM pos_orders WHERE status='open' AND business_day<>?", (day,)):
        open_orders.append(json.loads(r['data']))
    yesterday_diff = conn.execute("""SELECT data FROM cash_sessions WHERE status='closed' AND business_day<?
        ORDER BY closed_at DESC LIMIT 1""", (day,)).fetchone()
    conn.close()
    session = database.open_cash_session()
    top = sorted(s_today.get('byProduct', {}).values(), key=lambda p: (-p.get('qty', 0), p['name']))
    pending, failed = database.outbox_counts()
    alerts = []
    voids, comps = s_today.get('voids', {}), s_today.get('comps', {})
    if voids.get('count') or comps.get('count') or s_today.get('discount'):
        alerts.append({'target': 'losses', 'voids': voids, 'comps': comps, 'discount': s_today.get('discount', 0)})
    if yesterday_diff:
        last_session = json.loads(yesterday_diff['data'])
        if last_session.get('difference'):
            alerts.append({'target': 'cash', 'difference': last_session['difference'],
                           'reason': last_session.get('differenceReason') or '', 'day': last_session['businessDay']})
    if failed:
        alerts.append({'target': 'terminals', 'failed': failed})
    if database.modules()['stock']['enabled']:
        import stock
        low = stock.critical()
        if low:
            alerts.append({'target': 'stock', 'items': [i['name'] for i in low]})
    kitchen = None
    if database.modules()['kds']['enabled']:
        kitchen = Report(day, day, include_legacy=False).kitchen()
    tables = database.floor_tables()
    return {
        'day': day, 'compareDay': last, 'cutoff': cutoff, 'hour': now_iso[11:13],
        'revenue': s_today.get('revenue', 0), 'revenueChange': pct('revenue'),
        'orders': orders, 'ordersChange': pct('orders'),
        'average': s_today.get('revenue', 0) // orders if orders else 0,
        'averageChange': change(s_today.get('revenue', 0) // orders if orders else 0,
                                s_last.get('revenue', 0) // last_orders if last_orders else 0),
        'hourly': hourly(s_today), 'hourlyLast': hourly(s_last),
        'top': [{'name': p['name'], 'qty': p.get('qty', 0)} for p in top if p.get('qty')][:5],
        'openTables': len({o['tableId'] for o in open_orders if o.get('tableId')}),
        'totalTables': len([t for t in tables if not t.get('deleted')]),
        'openAmount': sum(o['total'] - o['paid'] for o in open_orders),
        'cashSession': session, 'expectedCash': cash.expected_cash(session) if session else None,
        'alerts': alerts, 'kitchen': kitchen,
        'pending': pending,
    }


def my_shift(staff_id, day=None):
    """Garsonun "Vardiyam" penceresi: bugünkü kendi satırı."""
    day = day or today().isoformat()
    for r in Report(day, day, include_legacy=False).staff():
        if r['staffId'] == staff_id:
            return r
    return {'staffId': staff_id, 'orders': 0, 'revenue': 0, 'average': 0, 'tips': 0, 'discount': 0, 'comps': 0,
            'voids': 0, 'approved': 0}
