"""
NexPOS - Hazır stok şablonu (8. ekran)

Yaygın kafe ürünleri için malzeme listesi, reçeteler ve seçenek etkileri. Menüdeki ürün ve seçenek
adlarıyla eşleşir; eşleşmeyen ürün atlanır. Reçetesi olan ürüne ve adı zaten var olan malzemeye
dokunulmaz. Hazır alınan tatlılar için "<ürün> (hazır)" adlı adetli bir malzeme açılır.

Miktarlar ve fiyatlar başlangıç içindir; kafeye göre düzenlenir.
"""
# anahtar: (ad, birim, grup, alış birimi (ad, miktar) ya da None, kritik, birim maliyet kuruş / kg-L-adet)
INGREDIENTS = {
    'espresso': ("Espresso çekirdeği", 'g', 'bar', ("paket", 1000), 1000, 80000),
    'filtre': ("Filtre kahve", 'g', 'bar', ("paket", 1000), 500, 60000),
    'turk': ("Türk kahvesi", 'g', 'bar', ("paket", 250), 500, 50000),
    'sut': ("Süt (tam yağlı)", 'ml', 'bar', ("koli", 12000), 10000, 3500),
    'yulaf': ("Yulaf sütü", 'ml', 'bar', ("koli", 6000), 3000, 9500),
    'laktozsuz': ("Laktozsuz süt", 'ml', 'bar', ("koli", 12000), 3000, 4500),
    'cay': ("Siyah çay", 'g', 'bar', ("paket", 1000), 500, 30000),
    'cikolata': ("Sıcak çikolata tozu", 'g', 'bar', ("paket", 1000), 500, 40000),
    'sahlep': ("Sahlep tozu", 'g', 'bar', ("paket", 1000), 300, 60000),
    'cikolata_sos': ("Çikolata sosu", 'ml', 'bar', ("şişe", 1000), 500, 30000),
    'vanilya': ("Vanilya şurubu", 'ml', 'bar', ("şişe", 700), 350, 50000),
    'karamel': ("Karamel şurubu", 'ml', 'bar', ("şişe", 700), 350, 50000),
    'bardak': ("Karton bardak 12oz", 'adet', 'packaging', ("koli", 1000), 200, 180),
    'kapak': ("Bardak kapağı", 'adet', 'packaging', ("koli", 1000), 200, 80),
    'plastik': ("Plastik bardak 16oz", 'adet', 'packaging', ("koli", 1000), 200, 250),
    'su': ("Su 0,5 L", 'adet', 'other', ("koli", 24), 24, 500),
    'ekmek': ("Tost ekmeği (dilim)", 'adet', 'kitchen', ("paket", 20), 40, 300),
    'kasar': ("Kaşar peyniri", 'g', 'kitchen', ("paket", 1000), 1000, 40000),
    'tereyag': ("Tereyağı", 'g', 'kitchen', ("paket", 1000), 500, 45000),
    'yumurta': ("Yumurta", 'adet', 'kitchen', ("koli", 30), 30, 400),
    'domates': ("Domates", 'g', 'kitchen', None, 2000, 3000),
}

TO_GO = [('bardak', 1, True), ('kapak', 1, True)]  # sıcak içecek paket bardağı

# (ad içinde geçen, reçete [(malzeme, miktar, yalnızca paket)]) — ilk eşleşen kullanılır; özel olan önce
RECIPES = [
    ('ice latte', [('espresso', 18, False), ('sut', 180, False), ('plastik', 1, False)]),
    ('iced latte', [('espresso', 18, False), ('sut', 180, False), ('plastik', 1, False)]),
    ('soğuk latte', [('espresso', 18, False), ('sut', 180, False), ('plastik', 1, False)]),
    ('buzlu latte', [('espresso', 18, False), ('sut', 180, False), ('plastik', 1, False)]),
    ('cold brew', [('filtre', 25, False), ('plastik', 1, False)]),
    ('frappe', [('espresso', 18, False), ('sut', 150, False), ('plastik', 1, False)]),
    ('türk kahve', [('turk', 7, False)]),
    ('filtre kahve', [('filtre', 15, False), *TO_GO]),
    ('flat white', [('espresso', 18, False), ('sut', 120, False), *TO_GO]),
    ('macchiato', [('espresso', 18, False), ('sut', 30, False), *TO_GO]),
    ('mocha', [('espresso', 18, False), ('sut', 180, False), ('cikolata_sos', 30, False), *TO_GO]),
    ('cappuccino', [('espresso', 18, False), ('sut', 150, False), *TO_GO]),
    ('latte', [('espresso', 18, False), ('sut', 200, False), *TO_GO]),
    ('americano', [('espresso', 18, False), *TO_GO]),
    ('espresso', [('espresso', 18, False)]),
    ('sıcak çikolata', [('cikolata', 30, False), ('sut', 200, False), *TO_GO]),
    ('sahlep', [('sahlep', 20, False), ('sut', 200, False), *TO_GO]),
    ('bitki çay', []),
    ('çay', [('cay', 3, False)]),
    ('demlik', [('cay', 6, False)]),
    ('tost', [('ekmek', 2, False), ('kasar', 60, False), ('tereyag', 10, False)]),
    ('menemen', [('yumurta', 3, False), ('domates', 150, False), ('tereyag', 15, False)]),
    ('omlet', [('yumurta', 3, False), ('tereyag', 10, False)]),
    ('su', [('su', 1, False)]),
]

# (seçenek adında geçen, etki) — malzemeler anahtarla
OPTION_EFFECTS = [
    ('yulaf', {'replace': [('sut', 'yulaf')]}),
    ('laktozsuz', {'replace': [('sut', 'laktozsuz')]}),
    ('büyük', {'scale': 1.5}),
    ('küçük', {'scale': 0.75}),
    ('ekstra shot', {'add': [('espresso', 9)]}),
    ('ekstra espresso', {'add': [('espresso', 9)]}),
    ('vanilya', {'add': [('vanilya', 15)]}),
    ('karamel', {'add': [('karamel', 15)]}),
]

READY_CATEGORY_WORDS = ('tatlı', 'pasta', 'kek')


def _lower(s):
    return (s or '').replace('I', 'ı').replace('İ', 'i').lower()


def _match(name, table):
    # ı/i farkı yok sayılır: Türkçe küçük harfte "Iced" → "ıced" olur, İngilizce ad yine eşleşsin
    n = _lower(name).replace('ı', 'i')
    for word, value in table:
        word = word.replace('ı', 'i')
        # Kısa adlar (su) yalnızca ilk kelime olarak eşleşir: "Su", "Su 0,5 L" — "Susamlı" değil
        if (word in n) if len(word) > 3 else (n.split() or [''])[0] == word:
            return value
    return None


def build(products, categories, groups, existing):
    """
    products/categories/groups: menü önbelleği; existing: mevcut malzemeler.
    Döner: {'ingredients', 'recipes', 'optionEffects', 'preview': [(ürün, [malzeme adları])],
            'options': [(grup · seçenek, açıklama)], 'skipped': [ürün adı]}
    """
    by_name = {_lower(i['name']): i['id'] for i in existing}
    used, new_ingredients, ready = {}, [], {}

    def ref(key):
        """Şablon anahtarı → mevcut malzemenin kimliği ya da yeni malzemenin anahtarı."""
        name = INGREDIENTS[key][0]
        if _lower(name) in by_name:
            return by_name[_lower(name)]
        if key not in used:
            used[key] = True
            name, unit, group, pu, crit, cost = INGREDIENTS[key]
            new_ingredients.append({'key': key, 'name': name, 'unit': unit, 'group': group,
                                    'purchaseUnit': {'name': pu[0], 'size': pu[1]} if pu else None,
                                    'critical': crit, 'unitCost': cost})
        return key

    cat_names = {c['id']: _lower(c.get('name')) for c in categories}
    recipes, preview, skipped = [], [], []
    for p in products:
        if p.get('deleted') or p.get('recipe'):
            continue
        recipe = _match(p['name'], RECIPES)
        if recipe is None and any(w in cat_names.get(p.get('categoryId'), '') for w in READY_CATEGORY_WORDS):
            key = f"hazir:{p['id']}"
            name = f"{p['name']} (hazır)"
            if _lower(name) in by_name:
                ready_ref = by_name[_lower(name)]
            else:
                ready_ref = key
                new_ingredients.append({'key': key, 'name': name, 'unit': 'adet', 'group': 'kitchen',
                                        'purchaseUnit': None, 'critical': 5,
                                        'unitCost': round(p.get('price', 0) * 0.35)})
            ready[p['id']] = name
            recipes.append({'productId': p['id'], 'recipe': [{'ingredient': ready_ref, 'qty': 1, 'takeawayOnly': False}]})
            preview.append((p['name'], [name]))
            continue
        if not recipe:
            skipped.append(p['name'])
            continue
        recipes.append({'productId': p['id'], 'recipe': [{'ingredient': ref(k), 'qty': q, 'takeawayOnly': t}
                                                         for k, q, t in recipe]})
        preview.append((p['name'], [f"{INGREDIENTS[k][0]} {q}{INGREDIENTS[k][1] if INGREDIENTS[k][1] != 'adet' else ' adet'}"
                                    + (" (paket)" if t else "") for k, q, t in recipe]))

    effects, option_preview = [], []
    for g in groups:
        for o in g.get('options') or []:
            if o.get('recipeEffect'):
                continue
            e = _match(o['name'], OPTION_EFFECTS)
            if not e:
                continue
            effect, text = {}, []
            if 'replace' in e:
                effect['replace'] = [{'from': ref(a), 'to': ref(b)} for a, b in e['replace']]
                text.append(", ".join(f"{INGREDIENTS[a][0]} → {INGREDIENTS[b][0]}" for a, b in e['replace']))
            if 'add' in e:
                effect['add'] = [{'ingredient': ref(k), 'qty': q} for k, q in e['add']]
                text.append(", ".join(f"+{q} {INGREDIENTS[k][1]} {INGREDIENTS[k][0]}" for k, q in e['add']))
            if 'scale' in e:
                effect['scale'] = e['scale']
                text.append(f"reçete ×{str(e['scale']).replace('.', ',')}")
            effects.append({'groupId': g['id'], 'optionId': o['id'], 'effect': effect})
            option_preview.append((f"{g['name']} · {o['name']}", "; ".join(text)))
    return {'ingredients': new_ingredients, 'recipes': recipes, 'optionEffects': effects,
            'preview': preview, 'options': option_preview, 'skipped': skipped}
