"""
Kampanyalar (10. ekran): doğrulama, ne zaman geçerli olduğu ve adisyona uygulanacak indirimler.

Sunucudaki karşılığı firebase/functions/src/campaigns.js'tir; ikisi de
firebase/functions/test/campaign_vectors.json'daki ortak senaryolarla test edilir. Kasa hesabı yapıp sonucu
applyCampaigns ile gönderir. Para kuruştur. Bir ürüne en fazla bir kampanya uygulanır (müşteri için en avantajlısı).
"""
import itertools
import re
from datetime import date

TYPES = ('percent', 'amount', 'nth', 'bundle', 'double_stamps')
TYPE_LABELS = {'percent': 'Yüzde indirim', 'amount': 'Tutar indirim', 'nth': 'X. ürün indirimli',
               'bundle': 'Menü (sabit fiyat)', 'double_stamps': 'Çift damga'}
AUDIENCES = ('all', 'members', 'silver', 'gold')
AUDIENCE_LABELS = {'all': 'Herkes', 'members': 'Üyeler', 'silver': 'Gümüş ve üstü', 'gold': 'Altın üyeler'}
TIME_RE = re.compile(r'([01]\d|2[0-3]):[0-5]\d')
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')


class CampaignError(Exception):
    pass


def _is_int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _ids(v, field, mx):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > mx or any(not isinstance(x, str) or not x or len(x) > 128 for x in v):
        raise CampaignError(f"{field} geçersiz.")
    return list(dict.fromkeys(v))


def validate_campaign(data):
    d = data or {}
    name = d.get('name').strip() if isinstance(d.get('name'), str) else ''
    if not name or len(name) > 60:
        raise CampaignError("Kampanya adı 1-60 karakter olmalıdır.")
    if d.get('type') not in TYPES:
        raise CampaignError("Kampanya türü geçersiz.")
    t = d['type']
    out = {'name': name, 'type': t, 'value': 0, 'nthQty': None, 'bundle': None, 'stampMultiplier': 1,
           'appliesTo': {'categoryIds': [], 'productIds': []}}
    if t in ('percent', 'nth'):
        if not _is_int(d.get('value'), 1, 100):
            raise CampaignError("İndirim yüzdesi 1-100 olmalıdır.")
        out['value'] = d['value']
    if t == 'amount':
        if not _is_int(d.get('value'), 1, 10_000_000):
            raise CampaignError("İndirim tutarı kuruş cinsinden olmalıdır.")
        out['value'] = d['value']
    if t == 'nth':
        if not _is_int(d.get('nthQty'), 2, 10):
            raise CampaignError("Kaçıncı ürün 2-10 olmalıdır.")
        out['nthQty'] = d['nthQty']
    if t == 'bundle':
        b = d.get('bundle') or {}
        pids = _ids(b.get('productIds'), 'Menü ürünleri', 4)
        if len(pids) < 2:
            raise CampaignError("Menüde en az iki farklı ürün olmalıdır.")
        if not _is_int(b.get('price'), 1, 10_000_000):
            raise CampaignError("Menü fiyatı kuruş cinsinden olmalıdır.")
        out['bundle'] = {'productIds': pids, 'price': b['price']}
    if t == 'double_stamps':
        out['stampMultiplier'] = d['stampMultiplier'] if _is_int(d.get('stampMultiplier'), 2, 5) else 2
    if t in ('percent', 'amount', 'nth'):
        a = d.get('appliesTo') or {}
        out['appliesTo'] = {'categoryIds': _ids(a.get('categoryIds'), 'Kategoriler', 50),
                            'productIds': _ids(a.get('productIds'), 'Ürünler', 200)}
    s = d.get('schedule') or {}
    days = s.get('days') if s.get('days') is not None else [1, 2, 3, 4, 5, 6, 7]
    if not isinstance(days, list) or not days or any(not _is_int(x, 1, 7) for x in days):
        raise CampaignError("Günler geçersiz.")
    frm, to = s.get('from') or None, s.get('to') or None
    if (frm and not TIME_RE.fullmatch(frm)) or (to and not TIME_RE.fullmatch(to)) or bool(frm) != bool(to) \
            or (frm and frm == to):
        raise CampaignError("Saat aralığı SS:DD – SS:DD olmalıdır.")
    start, end = s.get('startDate') or None, s.get('endDate') or None
    if (start and not DATE_RE.fullmatch(start)) or (end and not DATE_RE.fullmatch(end)):
        raise CampaignError("Tarih geçersiz.")
    if start and end and end < start:
        raise CampaignError("Bitiş tarihi başlangıçtan önce olamaz.")
    out['schedule'] = {'days': sorted(set(days)), 'from': frm, 'to': to, 'startDate': start, 'endDate': end}
    out['audience'] = d.get('audience') if d.get('audience') is not None else 'all'
    if out['audience'] not in AUDIENCES:
        raise CampaignError("Kampanya kitlesi geçersiz.")
    out['minTotal'] = d.get('minTotal') if d.get('minTotal') is not None else 0
    if not _is_int(out['minTotal'], 0, 10_000_000):
        raise CampaignError("En az adisyon tutarı geçersiz.")
    if 'active' in d and not isinstance(d['active'], bool):
        raise CampaignError("Aktif değeri geçersiz.")
    out['active'] = d.get('active', True)
    out['showInApp'] = d.get('showInApp') is True
    desc = d.get('description').strip() if isinstance(d.get('description'), str) else ''
    if len(desc) > 200:
        raise CampaignError("Açıklama en fazla 200 karakter olabilir.")
    out['description'] = desc
    return out


def _minutes(hm):
    return int(hm[:2]) * 60 + int(hm[3:5])


def is_live(c, at, customer):
    """Kampanya bu an (terminalin yerel saati) ve bu müşteri için geçerli mi?"""
    if not c or c.get('active') is False or c.get('deleted') is True:
        return False
    day = at[:10]
    s = c.get('schedule') or {}
    if s.get('startDate') and day < s['startDate']:
        return False
    if s.get('endDate') and day > s['endDate']:
        return False
    weekday = date.fromisoformat(day).isoweekday()   # 1 = Pazartesi
    now = _minutes(at[11:16])
    days = s.get('days') or []
    if s.get('from') and s.get('to'):
        f, t = _minutes(s['from']), _minutes(s['to'])
        if f < t:
            if now < f or now >= t:
                return False
            day_ok = weekday in days
        elif now >= f:
            day_ok = weekday in days
        elif now < t:
            # Gece yarısını geçen aralık (22:00–02:00): gece kısmı önceki günün kampanyasıdır
            day_ok = ((weekday + 5) % 7) + 1 in days
        else:
            return False
        if not day_ok:
            return False
    elif weekday not in days:
        return False
    aud = c.get('audience') or 'all'
    if aud == 'all':
        return True
    if not customer:
        return False
    if aud == 'members':
        return True
    if aud == 'silver':
        return customer.get('tier') in ('silver', 'gold')
    return customer.get('tier') == 'gold'


def _line_total(l):
    return (l['unitPrice'] + sum(o['priceDelta'] for o in l.get('options') or [])) * l['qty']


def _half_up(x, pct):
    return (x * pct + 50) // 100


def _units(order, category_of):
    """İndirime açık birimler: aktif, ödenmemiş satırların ödül almamış adetleri (pahalıdan ucuza)."""
    units = []
    for l in order['items']:
        if l['status'] != 'active' or l.get('paidBy'):
            continue
        free = sum(1 for r in order.get('rewards') or [] if r['lineId'] == l['lineId'])
        price = _line_total(l) // l['qty']
        for i in range(l['qty'] - free):
            units.append({'key': f"{l['lineId']}#{i}", 'lineId': l['lineId'], 'price': price,
                          'productId': l.get('productId'),
                          'categoryId': category_of.get(l.get('productId')) if l.get('productId') else None})
    return sorted(units, key=lambda u: -u['price'])


def _matches(c, u):
    a = c.get('appliesTo') or {}
    cats, prods = a.get('categoryIds') or [], a.get('productIds') or []
    if not cats and not prods:
        return True
    return u['productId'] in prods or (u['categoryId'] is not None and u['categoryId'] in cats)


def _benefit(c, units):
    take = []
    if c['type'] in ('percent', 'amount'):
        for u in units:
            if not _matches(c, u):
                continue
            off = _half_up(u['price'], c['value']) if c['type'] == 'percent' else min(c['value'], u['price'])
            if off > 0:
                take.append((u['key'], off))
    elif c['type'] == 'nth':
        eligible = [u for u in units if _matches(c, u)]
        n = c['nthQty']
        for i in range(0, len(eligible) - n + 1, n):
            group = eligible[i:i + n]
            off = _half_up(group[-1]['price'], c['value'])
            if off > 0:
                take += [(u['key'], off if j == n - 1 else 0) for j, u in enumerate(group)]
    elif c['type'] == 'bundle':
        pools = [[u for u in units if u['productId'] == pid] for pid in c['bundle']['productIds']]
        for i in range(min(len(p) for p in pools)):
            group = [p[i] for p in pools]
            total = sum(u['price'] for u in group)
            off = total - c['bundle']['price']
            if off <= 0:
                break
            left = off
            for j, u in enumerate(group):
                share = left if j == len(group) - 1 else (off * u['price']) // total
                left -= share
                take.append((u['key'], share))
    return sum(x for _, x in take), take


def _apply_sequence(perm, units):
    """Kampanyaları verilen sırayla kalan birimlere uygular: (toplam indirim, satırlar)."""
    out, total = [], 0
    for c in perm:
        amount, take = _benefit(c, units)
        if amount <= 0:
            continue
        lines, used = {}, set()
        for key, off in take:
            used.add(key)
            if off > 0:
                line_id = key[:key.rindex('#')]
                lines[line_id] = lines.get(line_id, 0) + off
        out.append({'campaignId': c['id'], 'name': c['name'], 'type': c['type'], 'lines': lines})
        total += amount
        units = [u for u in units if u['key'] not in used]
    return total, out


def compute_campaigns(order, campaigns, at, category_of=None):
    """Adisyona uygulanacak kampanyalar (applyCampaigns işleminin campaigns alanı)."""
    excluded = set(order.get('campaignsExcluded') or [])
    live = [c for c in campaigns if c['id'] not in excluded and is_live(c, at, order.get('customer'))]
    subtotal = sum(_line_total(l) for l in order['items'] if l['status'] == 'active')
    eligible = [c for c in live if subtotal >= (c.get('minTotal') or 0)]
    out = []
    stampy = any(l['status'] == 'active' and l.get('stampEligible') for l in order['items'])
    if not order.get('discount'):
        units = _units(order, category_of or {})
        money = sorted([c for c in eligible if c['type'] != 'double_stamps'], key=lambda c: c['id'])
        # Kampanyaları her sırayla dene, müşteriye en çok indirim vereni seç (eşitlikte ilk sıra).
        # Az sayıda kampanya geçerli olur; 6'dan fazlaysa verilen sırayla uygulanır.
        best = None
        for perm in (itertools.permutations(money) if len(money) <= 6 else [money]):
            total, applied = _apply_sequence(perm, units)
            if best is None or total > best[0]:
                best = (total, applied)
        if best:
            out += best[1]
    stamps = sorted([c for c in eligible if c['type'] == 'double_stamps' and order.get('customer') and stampy],
                    key=lambda c: (-(c.get('stampMultiplier') or 2), c['id']))
    if stamps:
        s = stamps[0]
        out.append({'campaignId': s['id'], 'name': s['name'], 'type': 'double_stamps', 'lines': {},
                    'stampMultiplier': s.get('stampMultiplier') or 2})
    return out


def describe(c):
    """Listede kısa açıklama: '%20 · Kahveler', '2. ürün %50', 'Latte + Kurabiye 120 ₺', '2× damga'"""
    from money import format_tl
    t = c['type']
    if t == 'percent':
        return f"%{c['value']} indirim"
    if t == 'amount':
        return f"{format_tl(c['value'])} indirim"
    if t == 'nth':
        return f"{c['nthQty']}. ürün %{c['value']}" if c['value'] < 100 else f"{c['nthQty']} al {c['nthQty'] - 1} öde"
    if t == 'bundle':
        return f"Menü {format_tl(c['bundle']['price'])}"
    return f"{c.get('stampMultiplier') or 2}× damga"


WEEKDAYS = ('Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz')


def schedule_text(c):
    s = c.get('schedule') or {}
    days = s.get('days') or []
    if days == [1, 2, 3, 4, 5, 6, 7]:
        d = "Her gün"
    elif days == [1, 2, 3, 4, 5]:
        d = "Hafta içi"
    elif days == [6, 7]:
        d = "Hafta sonu"
    else:
        d = ", ".join(WEEKDAYS[x - 1] for x in days)
    if s.get('from'):
        d += f" {s['from']}–{s['to']}"
    if s.get('startDate') or s.get('endDate'):
        d += f" · {s.get('startDate') or '…'} → {s.get('endDate') or '…'}"
    return d
