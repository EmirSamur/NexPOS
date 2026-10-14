"""
Para biçimlendirme. Tutarlar her yerde kuruş cinsinden tam sayıdır (9500 = 95,00 ₺).
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def format_tl(kurus, sign=False):
    """9500 → '95,00 ₺', 125000 → '1.250,00 ₺', sign=True ile '+15,00 ₺'"""
    kurus = int(kurus or 0)
    prefix = '-' if kurus < 0 else ('+' if sign and kurus > 0 else '')
    lira, kr = divmod(abs(kurus), 100)
    return f"{prefix}{lira:,}".replace(',', '.') + f",{kr:02d} ₺"


def parse_tl(text):
    """
    Kullanıcının yazdığı tutarı kuruşa çevirir: '95' → 9500, '95,5' → 9550,
    '1.250,00' → 125000, '12.50' → 1250. Geçersizse ValueError.
    """
    t = (text or '').replace('₺', '').replace(' ', '').strip()
    if not t:
        raise ValueError('Tutar boş.')
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    elif t.count('.') == 1 and len(t.split('.')[1]) in (1, 2):
        pass  # 12.50 → ondalık nokta
    else:
        t = t.replace('.', '')  # 1.250 → binlik ayırıcı
    try:
        value = Decimal(t)
    except InvalidOperation:
        raise ValueError(f'"{text}" geçerli bir tutar değil.')
    if value.as_tuple().exponent < -2:
        raise ValueError('En fazla 2 ondalık basamak girilebilir.')
    return int((value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
