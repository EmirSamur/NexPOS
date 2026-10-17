"""
Kahve önerisi (11c): "Bana öner" soruları ve kural tabanlı eşleştirme.

Sunucudaki karşılığı firebase/functions/src/quiz.js, uygulamadaki mobile/lib/quiz.dart'tır; üçü de
firebase/functions/test/quiz_vectors.json'daki ortak senaryolarla test edilir. Panel bunu soruları
düzenlerken "Dene" önizlemesi için kullanır (uygulamadaki hesabın aynısı).
"""
import json
import os
import re

DIMS = ('strength', 'sweetness', 'acidity', 'body')
DIM_LABELS = {'strength': 'Sertlik', 'sweetness': 'Tatlılık', 'acidity': 'Asidite', 'body': 'Gövde'}
_FUNCTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'firebase', 'functions')


def _load(rel):
    with open(os.path.join(_FUNCTIONS, rel), encoding='utf-8') as f:
        return json.load(f)


def default_quiz():
    return _load('test/quiz_vectors.json')['quiz']


def flavor_templates():
    """Yaygın içecekler için hazır tat profilleri: [{'name', 'flavor'}]"""
    return _load('src/flavor_templates.json')['templates']


def _tr_lower(text):
    return text.replace('I', 'ı').replace('İ', 'i').lower()


def profile_from(quiz, answers):
    target = {'strength': 3, 'sweetness': 3, 'acidity': 3, 'body': 3}
    notes, filt = [], {}
    for q in quiz['questions']:
        a = next((x for x in q['answers'] if x['id'] == (answers or {}).get(q['id'])), None)
        if not a:
            continue
        for k, v in (a.get('weights') or {}).items():
            target[k] = min(5, max(1, target[k] + v))
        for n in a.get('notes') or []:
            if n not in notes:
                notes.append(n)
        filt.update(a.get('filter') or {})
    return {'target': target, 'notes': notes, 'filter': filt}


def recommend(products, quiz, answers, ctx=None):
    """products: [{'id', 'flavor', 'soldOut', 'caffeineMg'}] → en fazla 3 {'productId', 'score', 'reasons'}"""
    ctx = ctx or {}
    prof = profile_from(quiz, answers)
    target, notes, filt = prof['target'], prof['notes'], prof['filter']
    usable = [p for p in products if p.get('flavor') and p.get('soldOut') is not True]

    def passes(p, keys):
        return all(k not in filt or p['flavor'].get(k) == filt[k] for k in keys)
    pool = [p for p in usable if passes(p, ('milk', 'temperature'))]
    if not pool and 'temperature' in filt:
        pool = [p for p in usable if passes(p, ('milk',))]
    if not pool:
        pool = usable
    tried = set(ctx.get('triedIds') or [])
    scored = []
    for p in pool:
        f = p['flavor']
        distance = sum(abs(target[k] - f[k]) for k in DIMS)
        score = 1 - distance / 16
        reasons = []
        pnotes = [_tr_lower(n) for n in f.get('notes') or []]
        if any(n in pnotes for n in notes):
            score += 0.15
            reasons.append('notes')
        hour = ctx.get('hour')
        if (12 if hour is None else hour) >= 17 and p.get('caffeineMg') == 0:
            score += 0.1
            reasons.append('decaf')
        if ctx.get('hotDay') and f.get('temperature') == 'iced':
            score += 0.1
            reasons.append('iced')
        if ctx.get('triedIds') and p['id'] not in tried:
            score += 0.05
            reasons.append('new')
        # JS Math.round ile aynı: yarım yukarı
        scored.append({'productId': p['id'], 'score': int(min(1, max(0, score)) * 100 + 0.5), 'reasons': reasons})
    scored.sort(key=lambda x: (-x['score'], x['productId']))
    return scored[:3]


def answer_effect(a):
    """Panelde cevabın etkisi: "Sertlik +2 · çikolata · sütlü"."""
    parts = [f"{DIM_LABELS[k]} {v:+d}" for k, v in (a.get('weights') or {}).items()]
    parts += a.get('notes') or []
    f = a.get('filter') or {}
    if 'milk' in f:
        parts.append('sütlü' if f['milk'] else 'sütsüz')
    if 'temperature' in f:
        parts.append('sıcak' if f['temperature'] == 'hot' else 'soğuk')
    return " · ".join(parts) or "etkisiz"


_TR = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')


def slug(text, taken):
    """Cevap/soru kimliği: "Buz gibi 🧊" → "buz-gibi" (benzersiz)"""
    base = re.sub(r'[^a-z0-9]+', '-', text.translate(_TR).lower()).strip('-')[:20] or 'x'
    s, i = base, 2
    while s in taken:
        s = f"{base[:18]}{i}"
        i += 1
    return s
