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
