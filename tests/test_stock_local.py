"""Stok ve reçete (8a): reçete hesabı, satışta düşme, iptalde iade, sayım, maliyet/kâr, şablon — yerel."""
import json

import pytest

from tests.test_local import seed

ING = {
    'esp': {'name': 'Espresso çekirdeği', 'unit': 'g', 'unitCost': 80000, 'critical': 500, 'stock': 1000},
    'sut': {'name': 'Süt', 'unit': 'ml', 'unitCost': 3500, 'critical': 5000, 'stock': 10000},
    'yulaf': {'name': 'Yulaf sütü', 'unit': 'ml', 'unitCost': 9500, 'critical': 0, 'stock': 2000},
    'bardak': {'name': 'Bardak', 'unit': 'adet', 'unitCost': 180, 'critical': 50, 'stock': 100},
}


@pytest.fixture
def st(db):
    import pos
    import stock
    db.set_sync_state('terminal_letter', 'A')
    seed(db, 'w1', 'waiter', pin='730591')
    seed(db, 'm1', 'manager', pin='583920')
    db.set_setting('modules', {'stock': {'enabled': True}})
    db.upsert_cache('ingredients', [(k, {**v, 'deleted': False}) for k, v in ING.items()])
    db.upsert_menu('categories', [('kahve', {'name': 'Kahve', 'station': 'bar', 'order': 0}),
                                  ('tatli', {'name': 'Tatlılar', 'station': 'kitchen', 'order': 1})])
    db.upsert_menu('optionGroups', [('sutg', {'name': 'Süt', 'options': [
        {'id': 'normal', 'name': 'Normal', 'priceDelta': 0},
        {'id': 'oat', 'name': 'Yulaf sütü', 'priceDelta': 1500, 'recipeEffect': {'replace': [{'from': 'sut', 'to': 'yulaf'}]}}]}),
        ('boy', {'name': 'Boy', 'options': [{'id': 'b', 'name': 'Büyük', 'priceDelta': 1000, 'recipeEffect': {'scale': 1.5}}]}),
        ('ekstra', {'name': 'Ekstra', 'options': [{'id': 'shot', 'name': 'Ekstra shot', 'priceDelta': 1500,
                                                   'recipeEffect': {'add': [{'ingredientId': 'esp', 'qty': 9}]}}]})])
    db.upsert_menu('products', [
        ('latte', {'name': 'Latte', 'categoryId': 'kahve', 'price': 11000, 'taxRate': 10, 'active': True,
                   'optionGroupIds': ['sutg', 'boy', 'ekstra'],
                   'recipe': [{'ingredientId': 'esp', 'qty': 18}, {'ingredientId': 'sut', 'qty': 200},
                              {'ingredientId': 'bardak', 'qty': 1, 'takeawayOnly': True}]}),
        ('kek', {'name': 'Kek', 'categoryId': 'tatli', 'price': 7000, 'active': True})])
    user = db.login_with_pin('w1', '730591')
    db.get_connection().execute("DELETE FROM outbox").connection.commit()
    return stock, pos, user


OAT = ('sutg', {'id': 'oat', 'name': 'Yulaf sütü', 'priceDelta': 1500})
BIG = ('boy', {'id': 'b', 'name': 'Büyük', 'priceDelta': 1000})
SHOT = ('ekstra', {'id': 'shot', 'name': 'Ekstra shot', 'priceDelta': 1500})


def _stock(stock):
    return {i['id']: i['stock'] for i in stock.ingredients()}


def test_recete_secenek_etkileri(db, st):
    stock, pos, user = st
    r = stock.Recipes()
    assert r.consumption('latte') == {'esp': 18, 'sut': 200}
    assert r.consumption('latte', takeaway=True) == {'esp': 18, 'sut': 200, 'bardak': 1}
    assert r.consumption('latte', [('sutg', 'oat')]) == {'esp': 18, 'yulaf': 200}
    # Büyük: ×1,5 (adetli bardak çarpılmaz); ekstra shot çarpandan sonra eklenir; adet ile çarpılır
    assert r.consumption('latte', [('boy', 'b'), ('ekstra', 'shot')], qty=2, takeaway=True) == \
        {'esp': 2 * (27 + 9), 'sut': 600, 'bardak': 2}
    assert r.consumption('kek') == {}
    assert stock.format_qty(3200, 'ml') == '3,2 L' and stock.format_qty(18, 'g') == '18 g'
    assert stock.format_qty(1500, 'adet') == '1.500 adet'
    assert stock.cost_of(200, ING['sut']) == 700 and stock.cost_of(18, ING['esp']) == 1440


def test_gonderde_duser_kuyruga_gider_senkrondan_sonra_cift_sayilmaz(db, st):
    stock, pos, user = st
    o = pos.open_order(user)  # paket
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), [OAT], qty=2))
    assert _stock(stock)['yulaf'] == 2000  # gönderilmeden düşmez
    o, _ = pos.send_pending(user, o['id'])
    s = _stock(stock)
    assert (s['esp'], s['yulaf'], s['sut'], s['bardak']) == (1000 - 36, 2000 - 400, 10000, 98)
    ops = [op for op in db.get_pending_ops(100) if op['op'] == 'stockMove']
    assert len(ops) == 1
    payload = json.loads(ops[0]['payload'])
    assert payload['type'] == 'sale' and payload['lineId'] == o['items'][0]['lineId']
    assert sorted((l['ingredientId'], l['qty']) for l in payload['lines']) == \
        [('bardak', -2), ('esp', -36), ('yulaf', -400)]
    # Buluta gitti (işlem kuyruktan silindi) ve bulut stoğu indi: aynı miktar
    db.complete_ops([op['op_id'] for op in db.get_pending_ops(100)])
    db.upsert_cache('ingredients', [('yulaf', {**ING['yulaf'], 'stock': 1600, 'deleted': False})])
    assert _stock(stock)['yulaf'] == 1600


def test_iptal_hazirlanmadiysa_stoga_doner(db, st):
    stock, pos, user = st
    o = pos.open_order(user, None)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), qty=3))
    o, _ = pos.send_pending(user, o['id'])
    line = o['items'][0]['lineId']
    assert _stock(stock)['esp'] == 1000 - 54
    # 3 latteden 1'i ayrılıp hazırlanmadan iptal: 1 latte kadar döner
    o, one = pos.split_line(user, o['id'], line, 1)
    o = pos.void_line(user, o['id'], one, 'Yanlış', 'm1', prepared=False)
    assert _stock(stock)['esp'] == 1000 - 36
    assert next(l for l in o['items'] if l['lineId'] == one)['prepared'] is False
    # Hazırlanmış iptal: stok değişmez
    o = pos.void_line(user, o['id'], line, 'Beğenmedi', 'm1', prepared=True)
    assert _stock(stock)['esp'] == 1000 - 36


def test_adisyon_iptali_ve_modul_kapali(db, st):
    stock, pos, user = st
    o = pos.open_order(user, None)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
    o, _ = pos.send_pending(user, o['id'])
    pos.cancel_order(user, o['id'], 'Gitti', 'm1', prepared=False)
    assert _stock(stock) == {k: v['stock'] for k, v in ING.items()}
    # Modül kapalı: hiçbir şey düşmez, iadede de bir şey dönmez
    db.set_setting('modules', {'stock': {'enabled': False}})
    o = pos.open_order(user, None)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
    o, _ = pos.send_pending(user, o['id'])
    assert _stock(stock)['esp'] == 1000
    assert not [op for op in db.get_pending_ops(100) if op['op'] == 'stockMove' and
                json.loads(op['payload']).get('orderId') == o['id']]
    # Modül sonradan açılsa bile düşülmemiş satır için stoğa iade yazılmaz
    db.set_setting('modules', {'stock': {'enabled': True}})
    pos.void_line(user, o['id'], o['items'][0]['lineId'], 'x', 'm1', prepared=False)
    assert _stock(stock)['esp'] == 1000


def test_sayim_ve_kritik(db, st):
    stock, pos, user = st
    changed = stock.set_counts(user, {'sut': 4000, 'esp': 1000, 'yok': 5}, 'İlk sayım', 'm1')
    assert changed == {'sut': -6000}
    assert _stock(stock)['sut'] == 4000
    assert [i['id'] for i in stock.critical()] == ['sut']
    op = [json.loads(o['payload']) for o in db.get_pending_ops(100) if o['op'] == 'stockMove'][-1]
    assert op['type'] == 'count' and op['approvedBy'] == 'm1' and op['reason'] == 'İlk sayım'


def test_maliyet_kar_menu_analizi_ve_gelir_gider(db, st):
    import reports
    stock, pos, user = st
    for _ in range(3):
        o = pos.open_order(user, None)
        pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
        pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'kek')))
        o, _ = pos.send_pending(user, o['id'])
        pos.take_payment(user, o['id'], 'card', o['total'])
    day = pos.business_day()
    r = reports.Report(day, day)
    products = {p['name']: p for p in r.products()}
    latte = products['Latte']
    # Paket latte: 18 g (14,40) + 200 ml (7,00) + bardak (1,80) = 23,20 ₺; KDV hariç 110/1.1 = 100 ₺
    assert latte['cost'] == 3 * 2320 and latte['exVat'] == 30000 and latte['profit'] == 30000 - 6960
    assert latte['margin'] == round((30000 - 6960) * 100 / 30000)
    assert products['Kek']['profit'] is None  # reçetesiz: maliyet bilinmiyor
    costing = stock.product_costing('latte', 11000, 10)
    assert costing['cost'] == 2140 and costing['netPrice'] == 10000 and costing['margin'] == 79
    analysis = r.menu_analysis()
    assert [a['name'] for a in analysis] == ['Latte'] and analysis[0]['class'] == 'star'
    ie = r.income_expense()
    assert ie['cogs'] == 6960 and ie['remaining'] == ie['net'] - ie['expenses'] - ie['waste'] - 6960


def test_hazir_sablon():
    import stock_template
    products = [{'id': 'p1', 'name': 'Latte', 'categoryId': 'k'}, {'id': 'p2', 'name': 'Iced Latte'},
                {'id': 'p3', 'name': 'Türk Kahvesi'}, {'id': 'p4', 'name': 'Susamlı Simit'},
                {'id': 'p5', 'name': 'Su'}, {'id': 'p6', 'name': 'Cheesecake', 'categoryId': 't', 'price': 15000},
                {'id': 'p7', 'name': 'Mocha', 'recipe': [{'ingredientId': 'x', 'qty': 1}]}]
    cats = [{'id': 'k', 'name': 'Kahveler'}, {'id': 't', 'name': 'Tatlılar'}]
    groups = [{'id': 'g', 'name': 'Süt', 'options': [{'id': 'o', 'name': 'Yulaf sütü'}, {'id': 'n', 'name': 'Normal'}]},
              {'id': 'b', 'name': 'Boy', 'options': [{'id': 'l', 'name': 'Büyük'}]}]
    existing = [{'id': 'mevcut-sut', 'name': 'Süt (tam yağlı)'}]
    d = stock_template.build(products, cats, groups, existing)
    recipes = {r['productId']: r['recipe'] for r in d['recipes']}
    assert set(recipes) == {'p1', 'p2', 'p3', 'p5', 'p6'}           # simit eşleşmez, mocha'nın reçetesi var
    assert {'ingredient': 'mevcut-sut', 'qty': 200, 'takeawayOnly': False} in recipes['p1']  # var olan malzeme
    assert any(r['ingredient'] == 'plastik' for r in recipes['p2'])  # soğuk latte: plastik bardak
    assert recipes['p6'][0]['ingredient'] == 'hazir:p6'
    keys = {i['key'] for i in d['ingredients']}
    assert 'sut' not in keys and {'espresso', 'yulaf', 'turk', 'su', 'hazir:p6'} <= keys
    effects = {(e['groupId'], e['optionId']): e['effect'] for e in d['optionEffects']}
    assert effects[('g', 'o')] == {'replace': [{'from': 'mevcut-sut', 'to': 'yulaf'}]}
    assert effects[('b', 'l')] == {'scale': 1.5} and ('g', 'n') not in effects
    assert 'Susamlı Simit' in d['skipped']


# =====================================================================
# 8b
# =====================================================================

@pytest.fixture
def tedarik(db, st):
    stock, pos, user = st
    seed(db, 'c1', 'cashier', pin='640218')
    db.upsert_cache('suppliers', [('kahveci', {'name': 'Kahveci', 'balance': 0, 'deleted': False})])
    db.upsert_cache('ingredients', [('esp', {**ING['esp'], 'supplierId': 'kahveci', 'target': 3000,
                                             'purchaseUnit': {'name': 'paket', 'size': 1000}, 'deleted': False})])
    manager = db.login_with_pin('m1', '583920')
    return stock, pos, user, manager


def test_bolunmus_ana_satirin_iptali_guncel_adet_kadar_doner(db, st):
    stock, pos, user = st
    o = pos.open_order(user, None)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), qty=3))
    o, _ = pos.send_pending(user, o['id'])
    o, one = pos.split_line(user, o['id'], o['items'][0]['lineId'], 1)
    o = pos.void_line(user, o['id'], o['items'][0]['lineId'], 'x', 'm1', prepared=False)  # kalan 2 latte
    assert _stock(stock)['esp'] == 1000 - 18   # yalnızca ayrılan 1 latte düşülü kalır


def test_teslim_alma_agirlikli_maliyet_borc_ve_odeme(db, tedarik):
    import cash
    stock, pos, user, manager = tedarik
    # 1 kg stokta 800 ₺/kg; 2 paket (2 kg) 1.900 ₺ gelir → (800 + 1900) / 3 = 900 ₺/kg
    rid = stock.receive(manager, 'kahveci', [{'ingredientId': 'esp', 'qty': 2000, 'amount': 190000}],
                        {'status': 'unpaid'}, note='Fatura 12')
    esp = stock.ingredient_map()['esp']
    assert esp['stock'] == 3000 and esp['unitCost'] == 90000
    assert next(s for s in stock.suppliers() if s['id'] == 'kahveci')['balance'] == 190000
    op = [json.loads(o['payload']) for o in db.get_pending_ops(100) if o['op'] == 'receivePurchase'][0]
    assert op['receiptId'] == rid and op['payment'] == {'status': 'unpaid'}
    # Kasiyerin stok yetkisi yok
    cashier = db.login_with_pin('c1', '640218')
    with pytest.raises(pos.OrderError, match='stock'):
        stock.receive(cashier, 'kahveci', [{'ingredientId': 'esp', 'qty': 1, 'amount': 1}], {'status': 'unpaid'})
    # Nakit ödeme, kasa açık: kasadan çıkış + Masraflar
    session = cash.open_session(manager, 300000)
    stock.pay_supplier(manager, 'kahveci', 100000, 'cash', 'Kısmi ödeme')
    assert next(s for s in stock.suppliers() if s['id'] == 'kahveci')['balance'] == 90000
    s = cash.current_session()
    assert s['movements'][-1]['amount'] == 100000 and s['movements'][-1]['type'] == 'out'
    assert cash.expected_cash(s) == 200000
    conn = db.get_connection()
    exp = conn.execute("SELECT tutar, odeme_tipi FROM expenses WHERE masraf_tipi='Tedarikçi: Kahveci'").fetchall()
    conn.close()
    assert [(e['tutar'], e['odeme_tipi']) for e in exp] == [(1000, 'Nakit')]   # kasa çıkışı ikinci gider yazmaz
    # Ödendi (kart) teslim: borç artmaz, Masraflar'a yazılır
    stock.receive(manager, 'kahveci', [{'ingredientId': 'sut', 'qty': 12000, 'amount': 42000}],
                  {'status': 'paid', 'method': 'card'})
    assert next(s for s in stock.suppliers() if s['id'] == 'kahveci')['balance'] == 90000
    assert [m['kind'] for m in stock.supplier_statement('kahveci')] == ['receipt', 'payment', 'receipt']
    assert session


def test_siparis_onerisi_ve_metni(db, tedarik):
    stock, pos, user, manager = tedarik
    db.upsert_cache('ingredients', [('esp', {**ING['esp'], 'stock': 400, 'supplierId': 'kahveci', 'target': 3000,
                                             'purchaseUnit': {'name': 'paket', 'size': 1000}, 'deleted': False})])
    lines = stock.suggest_order('kahveci')
    assert lines == [{'ingredientId': 'esp', 'qty': 3000, 'amount': 240000}]   # 2,6 kg → 3 paket
    text = stock.order_text({'no': 7, 'lines': lines, 'note': 'Cuma teslim'}, 'Velvet Kafe')
    assert '3 paket (3 kg) Espresso çekirdeği' in text and 'no 7' in text and 'Cuma teslim' in text


def test_zayi_urun_malzeme_ve_eski_kayit(db, tedarik):
    import reports
    stock, pos, user, manager = tedarik
    cost = stock.waste_product(manager, 'latte', 2, 'Döküldü')
    assert cost == 2 * (1440 + 700) and _stock(stock)['esp'] == 1000 - 36
    assert stock.waste_ingredient(manager, 'sut', 1000, 'Bozuldu') == 3500
    assert stock.waste_product(manager, 'kek', 1, 'Düştü', manual_cost=4000) == 4000   # reçetesiz
    with pytest.raises(pos.OrderError, match='waste'):
        stock.waste_ingredient(user, 'sut', 1, 'x')   # garsonun zayi yetkisi yok
    day = pos.business_day()
    conn = db.get_connection()
    pid = conn.execute("SELECT id FROM products WHERE cloud_id='kek'").fetchone()[0]
    conn.execute("INSERT INTO waste (product_id,zayi_nedeni,adet,maliyet_tutari,zayi_tarihi) VALUES (?,?,1,10,?)",
                 (pid, 'Eski', f"{day} 09:00"))
    conn.commit()
    conn.close()
    entries = stock.waste_entries(day, day)
    assert len(entries) == 4 and any(e['kind'] == 'legacy' for e in entries)
    ie = reports.Report(day, day).income_expense()
    assert ie['waste'] == 4280 + 3500 + 4000 + 1000


def test_sayim_ilk_sayim_ve_tuketim_raporu(db, tedarik):
    import reports
    stock, pos, user, manager = tedarik
    stock.set_counts(manager, {'esp': 2000}, 'İlk sayım', initial=True)        # +1000: kayıp sayılmaz
    o = pos.open_order(user, None)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), qty=10))   # 180 g
    pos.send_pending(user, o['id'])
    stock.waste_ingredient(manager, 'esp', 20, 'Döküldü')
    stock.receive(manager, 'kahveci', [{'ingredientId': 'esp', 'qty': 1000, 'amount': 80000}], {'status': 'unpaid'})
    # Sistemde 2000 − 180 − 20 + 1000 = 2800; sayılan 2750 → 50 g eksik
    stock.set_counts(manager, {'esp': 2750}, 'Haftalık sayım')
    day = pos.business_day()
    row = next(r for r in stock.consumption_report(day, day) if r['ingredientId'] == 'esp')
    assert (row['sale'], row['waste'], row['purchase'], row['countDiff']) == (180, 20, 1000, -50)
    assert (row['theoretical'], row['actual'], row['diffCost']) == (200, 250, -4000)
    hist = stock.count_history()
    assert [h['initial'] for h in hist] == [0, 1] and hist[0]['lines'][0]['diff'] == -50
    st = reports.Report(day, day).stock()
    assert st['countDiff'] == -4000 and st['purchases'] == 80000 and st['wasteCount'] == 1
    # Taslak
    stock.save_count_draft({'esp': 100}, 'Sayım')
    assert stock.load_count_draft()['counts'] == {'esp': 100}
    stock.clear_count_draft()
    assert stock.load_count_draft() is None
