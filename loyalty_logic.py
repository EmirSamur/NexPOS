"""
Sadakat (10. ekran): damga, ödül, seviye ve doğum günü kuralları.

Sunucudaki karşılığı firebase/functions/src/loyalty.js'tir; ikisi de
firebase/functions/test/loyalty_vectors.json'daki ortak senaryolarla test edilir.
Telefon numarası 10 hane olarak tutulur (5321234567).
"""
import copy
import re
from datetime import date, timedelta

DEFAULT_LOYALTY = {
    'stampsForReward': 10,
    'rewardMaxValue': 9000,          # kuruş: bedava ürün en fazla 90 ₺
    'rewardValidDays': 60,
    'birthdayReward': True,
    'tiers': [
        {'id': 'bronze', 'name': 'Bronz', 'minStamps': 0, 'perks': ''},
        {'id': 'silver', 'name': 'Gümüş', 'minStamps': 50, 'perks': ''},
        {'id': 'gold', 'name': 'Altın', 'minStamps': 150, 'perks': ''},
    ],
}


class LoyaltyError(Exception):
    pass


def _int_in(v, fallback, lo, hi, message):
    x = fallback if v is None else v
    if not isinstance(x, int) or isinstance(x, bool) or not lo <= x <= hi:
        raise LoyaltyError(message)
    return x


def validate_loyalty_settings(data):
    d = data or {}
    D = DEFAULT_LOYALTY
    tiers_in = d.get('tiers') if d.get('tiers') is not None else D['tiers']
    if not isinstance(tiers_in, list) or len(tiers_in) != 3:
        raise LoyaltyError("Üç seviye olmalıdır.")
    tiers = []
    for i, t in enumerate(tiers_in):
        t = t if isinstance(t, dict) else {}
        name = t.get('name').strip() if isinstance(t.get('name'), str) else ''
        if not name or len(name) > 20:
            raise LoyaltyError("Seviye adı 1-20 karakter olmalıdır.")
        perks = t.get('perks').strip() if isinstance(t.get('perks'), str) else ''
        if len(perks) > 200:
            raise LoyaltyError("Ayrıcalık metni en fazla 200 karakter olabilir.")
        tiers.append({'id': D['tiers'][i]['id'], 'name': name, 'perks': perks,
                      'minStamps': 0 if i == 0 else _int_in(t.get('minStamps'), D['tiers'][i]['minStamps'], 1, 100000,
                                                            "Seviye eşiği geçersiz.")})
    if not tiers[1]['minStamps'] < tiers[2]['minStamps']:
        raise LoyaltyError("Seviye eşikleri artan sırada olmalıdır.")
    if 'birthdayReward' in d and not isinstance(d['birthdayReward'], bool):
        raise LoyaltyError("Doğum günü ayarı geçersiz.")
    return {
        'stampsForReward': _int_in(d.get('stampsForReward'), D['stampsForReward'], 2, 50,
                                   "Ödül için damga sayısı 2-50 olmalıdır."),
        'rewardMaxValue': _int_in(d.get('rewardMaxValue'), D['rewardMaxValue'], 100, 1_000_000, "Ödül üst sınırı geçersiz."),
        'rewardValidDays': _int_in(d.get('rewardValidDays'), D['rewardValidDays'], 1, 365, "Ödül süresi 1-365 gün olmalıdır."),
        'birthdayReward': d.get('birthdayReward', D['birthdayReward']),
        'tiers': tiers,
    }


def normalize_loyalty(stored):
    try:
        return validate_loyalty_settings(stored)
    except LoyaltyError:
        return copy.deepcopy(DEFAULT_LOYALTY)


def normalize_phone(text):
    """'0532 123 45 67', '+90 532…', '5321234567' → '5321234567'; geçersizse None"""
    if not isinstance(text, str):
        return None
    digits = re.sub(r'\D', '', text)
    if len(digits) == 12 and digits.startswith('90'):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    return digits if re.fullmatch(r'[2-5]\d{9}', digits) else None


def mask_phone(phone):
    """'5321234567' → '0532 *** ** 67'"""
    return f"0{phone[:3]} *** ** {phone[8:]}" if phone else ''


def format_phone(phone):
    """'5321234567' → '0532 123 45 67'"""
    return f"0{phone[:3]} {phone[3:6]} {phone[6:8]} {phone[8:]}" if phone else ''


def tier_for(lifetime, settings):
    tid = settings['tiers'][0]['id']
    for t in settings['tiers']:
        if lifetime >= t['minStamps']:
            tid = t['id']
    return tid


def tier_name(tier_id, settings):
    return next((t['name'] for t in settings['tiers'] if t['id'] == tier_id), '')


def apply_stamps(state, earned, settings):
    """Damga ekler: kart dolunca ödül çıkar, artan damga yeni karta geçer."""
    total = (state.get('stamps') or 0) + earned
    lifetime = (state.get('lifetimeStamps') or 0) + earned
    n = settings['stampsForReward']
    return {'stamps': total % n, 'lifetimeStamps': lifetime, 'newRewards': total // n,
            'tier': tier_for(lifetime, settings)}


def revoke_stamps(state, n, settings):
    """Damga geri alır (iade, elle düzeltme). Verilmiş ödül geri alınmaz; damga 0'ın altına inmez."""
    lifetime = max((state.get('lifetimeStamps') or 0) - n, 0)
    return {'stamps': max((state.get('stamps') or 0) - n, 0), 'lifetimeStamps': lifetime, 'newRewards': 0,
            'tier': tier_for(lifetime, settings)}


def refund_revoke(earned, paid, refunded_total, already_revoked):
    """İadede geri alınacak damga: ödenenin iade edilen oranı kadar (aşağı), daha önce alınanlar düşülür."""
    if not earned or not paid:
        return 0
    return max(earned * min(refunded_total, paid) // paid - (already_revoked or 0), 0)


def add_days(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def is_birthday_week(birth_date, day):
    """Doğum gününün 3 gün öncesi ile 3 gün sonrası (yıl dönümü dahil)."""
    if not isinstance(birth_date, str) or not re.fullmatch(r'\d{2}-\d{2}', birth_date):
        return False
    d = date.fromisoformat(day)
    for y in (d.year - 1, d.year, d.year + 1):
        md = birth_date
        leap = (y % 4 == 0 and y % 100 != 0) or y % 400 == 0
        if md == '02-29' and not leap:
            md = '02-28'
        try:
            b = date.fromisoformat(f"{y}-{md}")
        except ValueError:
            return False
        if abs((d - b).days) <= 3:
            return True
    return False


def reward_usable(reward, customer_id, day):
    return bool(reward) and reward.get('status') == 'active' and reward.get('customerId') == customer_id \
        and isinstance(reward.get('expiresAt'), str) and reward['expiresAt'] >= day
