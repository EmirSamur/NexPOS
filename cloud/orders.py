"""
Sipariş mantığı (4. ekran): bir adisyonun durumuna işlem uygulayan saf fonksiyonlar.

Sunucudaki karşılığı firebase/functions/src/orders.js içindedir. İkisi de
firebase/functions/test/order_vectors.json'daki ortak senaryolarla test edilir; bir kural
değişirse iki dosya ve senaryolar birlikte güncellenmelidir.

Para her zaman kuruş cinsinden tam sayıdır.
"""
import copy

STATIONS = ('bar', 'kitchen')
TAX_RATES = (0, 1, 10, 20)
PAYMENT_METHODS = ('cash', 'card', 'meal')
ORDER_TYPES = ('dine_in', 'takeaway')
CAMPAIGN_TYPES = ('percent', 'amount', 'nth', 'bundle', 'double_stamps')
ITEM_OPS = ('addItems', 'updateItem', 'removeItem', 'voidItem', 'compItem')
MAX_MONEY = 10_000_000


class OrderError(Exception):
    """İşlem adisyon kurallarına aykırı; mesaj kullanıcıya gösterilir."""


def _is_int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _str(v, field, max_len, optional=False):
    if v in (None, '') and optional:
        return ''
    if not isinstance(v, str) or not v.strip() or len(v) > max_len:
        raise OrderError(f"{field} geçersiz.")
    return v.strip()


def line_total(line):
    if line['status'] != 'active':
        return 0
    unit = line['unitPrice'] + sum(o['priceDelta'] for o in line.get('options') or [])
    return unit * line['qty']


def line_deduction(order, line_id):
    """Satırdan düşülen kampanya ve ödül tutarı (10. ekran)."""
    total = sum((c.get('lines') or {}).get(line_id, 0) for c in order.get('campaigns') or [])
    return total + sum(r['amount'] for r in order.get('rewards') or [] if r['lineId'] == line_id)


def compute_totals(order):
    """Önce satırlardan kampanya ve ödül düşülür; elle iskonto kalan tutara BİR KEZ uygulanır
    (eski NexPOS'ta tekrar uygulanıyordu)."""
    subtotal = sum(line_total(l) for l in order['items'])
    campaign_amount = sum(c['amount'] for c in order.get('campaigns') or [])
    reward_amount = sum(r['amount'] for r in order.get('rewards') or [])
    base = subtotal - campaign_amount - reward_amount
    discount_amount = 0
    d = order.get('discount')
    if d and d['type'] == 'percent':
        discount_amount = (base * d['value'] + 50) // 100  # yarım yukarı
    if d and d['type'] == 'amount':
        discount_amount = min(d['value'], base)
    total = base - discount_amount
    paid = sum(p['amount'] for p in order['payments'])
    refunded = sum(r['amount'] for r in order.get('refunds') or [])
    return {'subtotal': subtotal, 'campaignAmount': campaign_amount, 'rewardAmount': reward_amount,
            'discountAmount': discount_amount, 'total': total, 'paid': paid,
            'refunded': refunded, 'remaining': max(total - paid, 0)}


def lines_share(order, line_ids):
    """Seçilen satırların ödenecek payı: satır toplamı − kampanya/ödül − iskontonun orantılı payı
    (aşağı yuvarlanır; kuruş farkı son ödemede kapanır)."""
    t = compute_totals(order)
    gross = sum(line_total(l) - (line_deduction(order, l['lineId']) if l['status'] == 'active' else 0)
                for l in order['items'] if l['lineId'] in line_ids)
    base = t['subtotal'] - t['campaignAmount'] - t['rewardAmount']
    if not t['discountAmount'] or not base:
        return gross
    return gross - (t['discountAmount'] * gross) // base


def with_totals(order):
    return {**order, **compute_totals(order)}


def table_status_for(order):
    if not order or order['status'] != 'open' or order['type'] != 'dine_in':
        return 'empty'
    return 'bill_requested' if order.get('billRequested') else 'occupied'


def stamp_count(order):
    """Sadakat damgası: damga kazandıran aktif ürünler − ödülle bedava alınanlar; çift damga ile katlanır."""
    active = {l['lineId']: l for l in order['items'] if l['status'] == 'active' and l.get('stampEligible')}
    units = sum(l['qty'] for l in active.values()) - sum(1 for r in order.get('rewards') or [] if r['lineId'] in active)
    mult = max([1] + [c.get('stampMultiplier') or 1 for c in order.get('campaigns') or []])
    return max(units, 0) * mult


def _reset_deductions(o):
    """Ürünler değişince kampanyalar silinir (terminal ödemeden önce tekrar uygular); ödüller,
    satırı hâlâ duruyorsa kalır."""
    o['campaigns'] = []
    used, keep = {}, []
    for r in o.get('rewards') or []:
        line = next((l for l in o['items'] if l['lineId'] == r['lineId']), None)
        if not line or line['status'] != 'active':
            continue
        used[r['lineId']] = used.get(r['lineId'], 0) + 1
        if used[r['lineId']] <= line['qty']:
            keep.append(r)
    o['rewards'] = keep


def _check_not_below_paid(o):
    t = compute_totals(o)
    if t['total'] < t['paid']:
        raise OrderError("Toplam alınmış ödemenin altına inemez.")


def _find_line(order, line_id):
    for line in order['items']:
        if line['lineId'] == line_id:
            return line
    raise OrderError("Adisyon satırı bulunamadı.")


def _validate_item(item, existing_ids):
    item = item or {}
    line_id = _str(item.get('lineId'), 'Satır kimliği', 64)
    if line_id in existing_ids:
        raise OrderError("Bu satır zaten eklenmiş.")
    existing_ids.add(line_id)
    if not _is_int(item.get('unitPrice'), 0, MAX_MONEY):
        raise OrderError("Birim fiyat kuruş cinsinden tam sayı olmalıdır.")
    if not _is_int(item.get('qty'), 1, 99):
        raise OrderError("Adet 1-99 arası olmalıdır.")
    if item.get('station') not in STATIONS:
        raise OrderError("İstasyon bar ya da mutfak olmalıdır.")
    tax_rate = item.get('taxRate')
    tax_rate = 10 if tax_rate is None else tax_rate
    if isinstance(tax_rate, bool) or tax_rate not in TAX_RATES:
        raise OrderError("KDV oranı geçersiz.")
    options = item.get('options') or []
    if not isinstance(options, list) or len(options) > 20:
        raise OrderError("Seçenekler geçersiz.")
    clean_options = []
    for o in options:
        if not _is_int((o or {}).get('priceDelta'), -MAX_MONEY, MAX_MONEY):
            raise OrderError("Seçenek fiyat farkı geçersiz.")
        clean_options.append({'groupId': _str(o.get('groupId'), 'Seçenek grubu', 128),
                              'optionId': _str(o.get('optionId'), 'Seçenek', 64),
                              'name': _str(o.get('name'), 'Seçenek adı', 60), 'priceDelta': o['priceDelta']})
    return {
        'lineId': line_id,
        'productId': None if item.get('productId') is None else _str(item['productId'], 'Ürün', 128),
        'name': _str(item.get('name'), 'Ürün adı', 80),
        'unitPrice': item['unitPrice'],
        'options': clean_options,
        'qty': item['qty'],
        'note': _str(item.get('note'), 'Not', 120, optional=True),
        'station': item['station'],
        'taxRate': tax_rate,
        'stampEligible': item.get('stampEligible') is True,
        'state': 'pending',
        'status': 'active',
    }


def apply_order_op(order, op, payload, staff_id, at):
    """order: mevcut durum (openOrder için None). Yeni durumu döndürür; girdiyi değiştirmez."""
    p = payload or {}
    if op == 'openOrder':
        if order:
            raise OrderError("Bu adisyon zaten açılmış.")
        if p.get('type') not in ORDER_TYPES:
            raise OrderError("Sipariş türü geçersiz.")
        if p['type'] == 'dine_in' and (not isinstance(p.get('tableId'), str) or not p['tableId']):
            raise OrderError("Masa belirtilmedi.")
        return with_totals({
            'id': _str(p.get('orderId'), 'Adisyon', 64),
            'no': _str(p.get('no'), 'Adisyon numarası', 12),
            'businessDay': _str(p.get('businessDay'), 'İş günü', 10),
            'type': p['type'],
            'tableId': p['tableId'] if p['type'] == 'dine_in' else None,
            'tableName': _str(p.get('tableName'), 'Masa adı', 40, optional=True),
            'status': 'open',
            'billRequested': False,
            'waiterId': staff_id,
            'openedAt': p.get('openedAt') or at,
            'closedAt': None,
            'items': [],
            'discount': None,
            'payments': [],
            'mergedInto': None,
            'cancelReason': None,
            'customer': None,
            'campaigns': [],
            'campaignsExcluded': [],
            'rewards': [],
        })

    if not order:
        raise OrderError("Adisyon bulunamadı.")
    if op == 'refundPayment':
        return _refund(order, p, staff_id, at)
    if order['status'] != 'open':
        raise OrderError("Adisyon kapanmış.")
    o = copy.deepcopy(order)

    if op == 'addItems':
        items = p.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise OrderError("Eklenecek ürün yok.")
        ids = {l['lineId'] for l in o['items']}
        for item in items:
            o['items'].append({**_validate_item(item, ids), 'addedBy': staff_id, 'addedAt': at})
    elif op == 'updateItem':
        line = _find_line(o, p.get('lineId'))
        if line['state'] != 'pending' or line['status'] != 'active':
            raise OrderError("Gönderilmiş satır değiştirilemez.")
        if 'qty' in p:
            if not _is_int(p['qty'], 1, 99):
                raise OrderError("Adet 1-99 arası olmalıdır.")
            line['qty'] = p['qty']
        if 'note' in p:
            line['note'] = _str(p['note'], 'Not', 120, optional=True)
    elif op == 'removeItem':
        line = _find_line(o, p.get('lineId'))
        if line['state'] != 'pending':
            raise OrderError("Gönderilmiş satır silinemez; iptal edilmelidir.")
        o['items'] = [l for l in o['items'] if l['lineId'] != p['lineId']]
    elif op == 'sendItems':
        line_ids = p.get('lineIds')
        if not isinstance(line_ids, list) or not line_ids:
            raise OrderError("Gönderilecek satır yok.")
        tickets = p.get('ticketIds') or {}
        for lid in line_ids:
            line = _find_line(o, lid)
            if line['state'] != 'pending' or line['status'] != 'active':
                raise OrderError("Satır zaten gönderilmiş.")
            if not isinstance(tickets.get(line['station']), str):
                raise OrderError("Fiş kimliği eksik.")
            line['state'] = 'sent'
            line['sentAt'] = at
            line['ticketId'] = tickets[line['station']]
    elif op in ('voidItem', 'compItem'):
        line = _find_line(o, p.get('lineId'))
        if line['status'] != 'active':
            raise OrderError("Satır zaten iptal ya da ikram edilmiş.")
        if line.get('paidBy'):
            raise OrderError("Ödenmiş satır iptal edilemez; iade yapılmalıdır.")
        if op == 'voidItem' and line['state'] != 'sent':
            raise OrderError("Gönderilmemiş satır iptal edilmez, silinir.")
        line['status'] = 'void' if op == 'voidItem' else 'comp'
        line['reason'] = _str(p.get('reason'), 'Gerekçe', 120)
        line['by'] = staff_id
        line['approvedBy'] = p.get('approvedBy') or staff_id
        line['actionAt'] = at
        # İptal edilen ürün hazırlanmış mıydı? (8. ekran: hazırlandıysa zayi, değilse stoğa döner)
        if op == 'voidItem':
            line['prepared'] = p.get('prepared') is not False
    elif op == 'setDiscount':
        if any(x.get('lineIds') for x in o['payments']):
            raise OrderError("Ürün seçerek ödeme alınmış adisyonda iskonto değiştirilemez.")
        if 'discount' in p and p['discount'] is None:
            o['discount'] = None
        else:
            d = p.get('discount') or {}
            if d.get('type') == 'percent' and not _is_int(d.get('value'), 1, 100):
                raise OrderError("İskonto yüzdesi 1-100 arası tam sayı olmalıdır.")
            if d.get('type') == 'amount' and not _is_int(d.get('value'), 1, MAX_MONEY):
                raise OrderError("İskonto tutarı kuruş cinsinden olmalıdır.")
            if d.get('type') not in ('percent', 'amount'):
                raise OrderError("İskonto türü geçersiz.")
            o['discount'] = {'type': d['type'], 'value': d['value'],
                             'reason': _str(p.get('reason'), 'Gerekçe', 120, optional=True),
                             'by': staff_id, 'approvedBy': p.get('approvedBy') or staff_id, 'at': at}
    elif op == 'requestBill':
        if not isinstance(p.get('value'), bool):
            raise OrderError("Hesap isteği true/false olmalıdır.")
        o['billRequested'] = p['value']
    elif op == 'moveOrder':
        if o['type'] != 'dine_in':
            raise OrderError("Masasız sipariş taşınamaz.")
        to = p.get('toTableId')
        if not isinstance(to, str) or not to or to == o['tableId']:
            raise OrderError("Hedef masa geçersiz.")
        o['tableId'] = to
        o['tableName'] = _str(p.get('toTableName'), 'Masa adı', 40, optional=True)
    elif op == 'splitLine':
        line = _find_line(o, p.get('lineId'))
        if line['status'] != 'active' or line.get('paidBy'):
            raise OrderError("Bu satır bölünemez.")
        if not _is_int(p.get('qty'), 1, line['qty'] - 1):
            raise OrderError("Ayrılacak adet satırdaki adetten az olmalıdır.")
        new_id = _str(p.get('newLineId'), 'Satır kimliği', 64)
        if any(l['lineId'] == new_id for l in o['items']):
            raise OrderError("Bu satır zaten eklenmiş.")
        before_qty = line['qty']
        line['qty'] -= p['qty']
        o['items'].insert(o['items'].index(line) + 1,
                          {**copy.deepcopy(line), 'lineId': new_id, 'qty': p['qty'], 'splitFrom': line['lineId']})
        # Kampanya indirimi adet oranında, satırın kalan adedinden fazla ödül yeni satıra geçer (toplam değişmez)
        for c in o.get('campaigns') or []:
            amount = (c.get('lines') or {}).get(line['lineId'])
            if not amount:
                continue
            moved = amount * p['qty'] // before_qty
            if moved:
                c['lines'][new_id] = moved
                c['lines'][line['lineId']] = amount - moved
        kept = 0
        for r in o.get('rewards') or []:
            if r['lineId'] != line['lineId']:
                continue
            kept += 1
            if kept > line['qty']:
                r['lineId'] = new_id
    elif op == 'takePayment':
        t = compute_totals(o)
        if any(l['status'] == 'active' and l['state'] == 'pending' for l in o['items']):
            raise OrderError("Gönderilmemiş ürün varken ödeme alınamaz.")
        payment_id = _str(p.get('paymentId'), 'Ödeme', 64)
        if any(x['paymentId'] == payment_id for x in o['payments']):
            raise OrderError("Bu ödeme zaten alınmış.")
        if p.get('method') not in PAYMENT_METHODS:
            raise OrderError("Ödeme yöntemi geçersiz.")
        amount = p.get('amount')
        if not _is_int(amount, 0 if t['total'] == 0 else 1, t['remaining']):
            raise OrderError("Ödeme tutarı kalan tutardan fazla olamaz.")
        if t['total'] > 0 and amount == 0:
            raise OrderError("Ödeme tutarı geçersiz.")
        line_ids = None
        if p.get('lineIds') is not None:
            # Ürün seçerek bölme
            if not isinstance(p['lineIds'], list) or not p['lineIds']:
                raise OrderError("Ödenecek satır seçilmedi.")
            if any(not x.get('lineIds') for x in o['payments']):
                raise OrderError("Tutar olarak ödeme alınmış adisyonda ürün seçerek bölünemez.")
            unpaid = [l['lineId'] for l in o['items'] if l['status'] == 'active' and not l.get('paidBy')]
            for lid in p['lineIds']:
                if lid not in unpaid:
                    raise OrderError("Seçilen satır ödenmiş ya da geçersiz.")
            covers_all = all(lid in p['lineIds'] for lid in unpaid)
            expected = t['remaining'] if covers_all else lines_share(o, p['lineIds'])
            if amount != expected:
                raise OrderError("Tutar seçilen ürünlerin payıyla uyuşmuyor.")
            line_ids = list(p['lineIds'])
        tip = p.get('tip', 0) if p.get('tip') is not None else 0
        if not _is_int(tip, 0, MAX_MONEY):
            raise OrderError("Bahşiş geçersiz.")
        received = None
        if p['method'] == 'cash':
            received = p.get('received') if p.get('received') is not None else amount
            if not _is_int(received, amount, MAX_MONEY):
                raise OrderError("Alınan nakit tutardan az olamaz.")
        o['payments'].append({'paymentId': payment_id, 'method': p['method'], 'amount': amount, 'tip': tip,
                              'received': received, 'change': 0 if received is None else received - amount,
                              'by': staff_id, 'at': at, 'lineIds': line_ids,
                              'cashSessionId': p['cashSessionId'] if isinstance(p.get('cashSessionId'), str) else None})
        if line_ids:
            for l in o['items']:
                if l['lineId'] in line_ids:
                    l['paidBy'] = payment_id
        if compute_totals(o)['remaining'] == 0:
            o['status'] = 'paid'
            o['closedAt'] = at
    elif op == 'cancelOrder':
        if o['payments']:
            raise OrderError("Ödeme alınmış adisyon iptal edilemez.")
        o['status'] = 'cancelled'
        o['cancelReason'] = _str(p.get('reason'), 'Gerekçe', 120)
        o['closedAt'] = at
        o['cancelledBy'] = staff_id
        o['prepared'] = p.get('prepared') is not False
        o['approvedBy'] = p.get('approvedBy') or staff_id
    elif op == 'setCustomer':
        c = p.get('customer', 0)
        if c is not None and not isinstance(c, dict):
            raise OrderError("Müşteri geçersiz.")
        new = None if c is None else {'id': _str(c.get('id'), 'Müşteri', 64), 'name': _str(c.get('name'), 'Müşteri adı', 60),
                                      'tier': _str(c.get('tier'), 'Seviye', 20, optional=True) or None}
        if ((o.get('customer') or {}).get('id')) != ((new or {}).get('id')):
            o['rewards'] = []
            o['campaigns'] = []
        o['customer'] = new
    elif op == 'useReward':
        if not o.get('customer'):
            raise OrderError("Önce müşteri seçilmelidir.")
        if any(x.get('lineIds') for x in o['payments']):
            raise OrderError("Ürün seçerek ödeme alınmış adisyonda ödül kullanılamaz.")
        reward_id = _str(p.get('rewardId'), 'Ödül', 64)
        rewards = o.get('rewards') or []
        if any(r['rewardId'] == reward_id for r in rewards):
            raise OrderError("Bu ödül zaten kullanılmış.")
        line = _find_line(o, p.get('lineId'))
        if line['status'] != 'active' or line.get('paidBy') or not line.get('stampEligible'):
            raise OrderError("Ödül bu ürüne uygulanamaz.")
        if sum(1 for r in rewards if r['lineId'] == line['lineId']) >= line['qty']:
            raise OrderError("Bu satırdaki bütün ürünlere ödül uygulanmış.")
        unit = line_total(line) // line['qty']
        if not _is_int(p.get('amount'), 1, unit) or line_deduction(o, line['lineId']) + p['amount'] > line_total(line):
            raise OrderError("Ödül tutarı ürün fiyatını aşamaz.")
        o['rewards'] = rewards + [{'rewardId': reward_id, 'lineId': line['lineId'], 'amount': p['amount'],
                                   'customerId': o['customer']['id']}]
        _check_not_below_paid(o)
    elif op == 'removeReward':
        if not any(r['rewardId'] == p.get('rewardId') for r in o.get('rewards') or []):
            raise OrderError("Ödül bulunamadı.")
        o['rewards'] = [r for r in o['rewards'] if r['rewardId'] != p['rewardId']]
    elif op == 'applyCampaigns':
        if any(x.get('lineIds') for x in o['payments']):
            raise OrderError("Ürün seçerek ödeme alınmış adisyonda kampanya değiştirilemez.")
        if not isinstance(p.get('campaigns'), list) or len(p['campaigns']) > 20:
            raise OrderError("Kampanyalar geçersiz.")
        excluded = p.get('excluded') if p.get('excluded') is not None else []
        if not isinstance(excluded, list) or len(excluded) > 50 or \
                any(not isinstance(x, str) or len(x) > 128 for x in excluded):
            raise OrderError("Kaldırılan kampanyalar geçersiz.")
        open_lines = {l['lineId']: l for l in o['items'] if l['status'] == 'active' and not l.get('paidBy')}
        seen, campaigns = set(), []
        for c in p['campaigns']:
            c = c if isinstance(c, dict) else {}
            cid = _str(c.get('campaignId'), 'Kampanya', 128)
            if cid in seen or cid in excluded:
                raise OrderError("Kampanya tekrar ediyor.")
            seen.add(cid)
            if c.get('type') not in CAMPAIGN_TYPES:
                raise OrderError("Kampanya türü geçersiz.")
            entries = list((c.get('lines') or {}).items())
            if len(entries) > 50:
                raise OrderError("Kampanya satırları geçersiz.")
            lines = {}
            for line_id, amount in entries:
                if line_id not in open_lines:
                    raise OrderError("Kampanya satırı bulunamadı.")
                if not _is_int(amount, 1, MAX_MONEY):
                    raise OrderError("Kampanya tutarı geçersiz.")
                lines[line_id] = amount
            mult = 1
            if c['type'] == 'double_stamps':
                mult = c['stampMultiplier'] if _is_int(c.get('stampMultiplier'), 2, 5) else 2
            elif not entries:
                raise OrderError("Kampanya satırı yok.")
            campaigns.append({'campaignId': cid, 'name': _str(c.get('name'), 'Kampanya adı', 60), 'type': c['type'],
                              'lines': lines, 'amount': sum(lines.values()), 'stampMultiplier': mult})
        o['campaigns'] = campaigns
        o['campaignsExcluded'] = list(excluded)
        for l in open_lines.values():
            if line_deduction(o, l['lineId']) > line_total(l):
                raise OrderError("Kampanya ürün fiyatını aşamaz.")
        if o.get('discount') and any(c['amount'] > 0 for c in campaigns):
            raise OrderError("Elle iskonto yapılmış adisyonda kampanya uygulanmaz.")
        _check_not_below_paid(o)
    else:
        raise OrderError(f"Bilinmeyen adisyon işlemi: {op}")
    if op in ITEM_OPS:
        _reset_deductions(o)
    if op == 'setDiscount' and o.get('discount'):
        o['campaigns'] = []
    return with_totals(o)


def _refund(order, p, staff_id, at):
    """Kapanmış (ödenmiş) adisyonda iade. Adisyon "paid" kalır; iadeler ayrı listede tutulur."""
    if order['status'] != 'paid':
        raise OrderError("Yalnızca ödenmiş adisyon iade edilebilir.")
    o = copy.deepcopy(order)
    o['refunds'] = o.get('refunds') or []
    t = compute_totals(o)
    refund_id = _str(p.get('refundId'), 'İade', 64)
    if any(r['refundId'] == refund_id for r in o['refunds']):
        raise OrderError("Bu iade zaten yapılmış.")
    if p.get('method') not in PAYMENT_METHODS:
        raise OrderError("İade yöntemi geçersiz.")
    if not _is_int(p.get('amount'), 1, t['paid'] - t['refunded']):
        raise OrderError("İade tutarı ödenen tutarı aşamaz.")
    o['refunds'].append({'refundId': refund_id, 'method': p['method'], 'amount': p['amount'],
                         'reason': _str(p.get('reason'), 'Gerekçe', 120), 'by': staff_id,
                         'approvedBy': p.get('approvedBy') or staff_id, 'at': at,
                         'cashSessionId': p['cashSessionId'] if isinstance(p.get('cashSessionId'), str) else None})
    return with_totals(o)


def merge_orders(target, source, at):
    """Kaynaktaki satırlar hedefe taşınır, kaynak kapanır. (hedef, kaynak) döndürür."""
    if not target or not source:
        raise OrderError("Adisyon bulunamadı.")
    if target['status'] != 'open' or source['status'] != 'open':
        raise OrderError("Kapanmış adisyon birleştirilemez.")
    if target['id'] == source['id']:
        raise OrderError("Adisyon kendisiyle birleştirilemez.")
    if source['payments']:
        raise OrderError("Ödeme alınmış adisyon birleştirilemez.")
    if any(x.get('lineIds') for x in target['payments']):
        raise OrderError("Ürün seçerek ödeme alınmış adisyona birleştirme yapılamaz.")
    t, s = copy.deepcopy(target), copy.deepcopy(source)
    ids = {l['lineId'] for l in t['items']}
    for line in s['items']:
        if line['lineId'] in ids:
            raise OrderError("Satır kimlikleri çakışıyor.")
        t['items'].append({**line, 'mergedFrom': s['id']})
    _reset_deductions(t)
    s['items'] = []
    s['status'] = 'merged'
    s['mergedInto'] = t['id']
    s['closedAt'] = at
    return with_totals(t), with_totals(s)
