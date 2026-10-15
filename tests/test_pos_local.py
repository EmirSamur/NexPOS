"""Sipariş servisi (pos.py): yerel adisyon akışı, kuyruk, eski tablolarla uyum (internet gerekmez)."""
import json
from datetime import datetime

import pytest

from tests.test_local import seed


@pytest.fixture
def setup(db):
    import pos
    db.set_sync_state('terminal_letter', 'A')
    seed(db, 'w1', 'waiter', pin='730591')
    seed(db, 'm1', 'manager', pin='583920')
    user = db.login_with_pin('w1', '730591')
    db.upsert_floor('areas', [('a1', {'name': 'Salon', 'order': 0, 'fixtures': [], 'deleted': False})])
    db.upsert_floor('tables', [(f't{i}', {'name': f'Masa {i}', 'areaId': 'a1', 'shape': 'square', 'capacity': 4,
                                          'x': 0, 'y': 0, 'w': 120, 'h': 120, 'rotation': 0, 'deleted': False})
                               for i in (1, 2, 3)])
    db.upsert_menu('categories', [('kahve', {'name': 'Kahve', 'station': 'bar', 'stampEligible': True, 'order': 0}),
                                  ('tatli', {'name': 'Tatlı', 'station': 'kitchen', 'stampEligible': False, 'order': 1})])
    db.upsert_menu('optionGroups', [('milk', {'name': 'Süt', 'options': [
        {'id': 'normal', 'name': 'Normal', 'priceDelta': 0}, {'id': 'oat', 'name': 'Yulaf', 'priceDelta': 1500}]})])
    db.upsert_menu('products', [('latte', {'name': 'Latte', 'categoryId': 'kahve', 'price': 9500, 'active': True,
                                           'optionGroupIds': ['milk']}),
                                ('kek', {'name': 'Kek', 'categoryId': 'tatli', 'price': 7000, 'active': True})])
    db.get_connection().execute("DELETE FROM outbox").connection.commit()
    return pos, user


def ops(db):
    return [o['op'] for o in db.get_pending_ops(500)]


def legacy_table(db, cloud_id):
    conn = db.get_connection()
    row = dict(conn.execute("SELECT * FROM tables WHERE cloud_id=?", (cloud_id,)).fetchone())
    conn.close()
    return row


def test_tam_akis_masa_ac_ekle_gonder_ode(db, setup):
    pos, user = setup
    latte = db.menu_item('products', 'latte')
    order = pos.open_order(user, {'id': 't1', 'name': 'Masa 1'})
    assert order['no'] == 'A1' and legacy_table(db, 't1')['durum'] == 'dolu'
    with pytest.raises(pos.OrderError, match='zaten açık'):
        pos.open_order(user, {'id': 't1', 'name': 'Masa 1'})

    oat = ('milk', {'id': 'oat', 'name': 'Yulaf', 'priceDelta': 1500})
    pos.add_line(user, order['id'], pos.product_line(latte, [oat]))
    pos.add_line(user, order['id'], pos.product_line(latte, [oat]))   # aynı satır → adet 2
    pos.add_line(user, order['id'], pos.product_line(latte))           # seçeneksiz → ayrı satır
    order = pos.add_line(user, order['id'], pos.product_line(db.menu_item('products', 'kek'), note='az tatlı'))
    assert [(l['name'], l['qty']) for l in order['items']] == [('Latte', 2), ('Latte', 1), ('Kek', 1)]
    assert order['items'][0]['unitPrice'] == 9500 and order['items'][0]['stampEligible'] is True
    assert order['items'][2]['station'] == 'kitchen' and order['items'][2]['stampEligible'] is False
    assert order['total'] == 2 * 11000 + 9500 + 7000

    order, n = pos.send_pending(user, order['id'])
    assert n == 3
    stations = sorted(t['station'] for t in pos.tickets())
    assert stations == ['bar', 'kitchen']
    bar = next(t for t in pos.tickets() if t['station'] == 'bar')
    assert [l['options'] for l in bar['lines']] == [['Yulaf'], []]

    order = pos.request_bill(user, order['id'], True)
    assert legacy_table(db, 't1')['durum'] == 'hesap'
    order = pos.take_payment(user, order['id'], 'cash', order['total'], received=50000)
    assert order['status'] == 'paid' and order['payments'][0]['change'] == 50000 - 38500
    assert legacy_table(db, 't1')['durum'] == 'bos'
    assert ops(db) == ['openOrder', 'addItems', 'updateItem', 'addItems', 'addItems', 'sendItems',
                       'requestBill', 'takePayment']

    # Raporlar için eski tablolara yazıldı (vardiya özeti, popüler ürünler)
    summary = db.get_shift_summary(user['id'])
    assert summary['siparis_sayisi'] == 1 and summary['toplam_tutar'] == 385.0
    assert {p['urun_adi'] for p in db.get_popular_products(5)} >= {'Latte', 'Kek'}


def test_iptal_ikram_iskonto_ve_iptal_icin_onay_gereksinimi(db, setup):
    pos, user = setup
    order = pos.open_order(user, {'id': 't2', 'name': 'Masa 2'})
    order = pos.add_line(user, order['id'], pos.product_line(db.menu_item('products', 'latte')))
    order = pos.add_line(user, order['id'], pos.product_line(db.menu_item('products', 'kek')))
    assert not pos.needs_approval_to_cancel(order)
    order, _ = pos.send_pending(user, order['id'])
    assert pos.needs_approval_to_cancel(order)
    latte_line, kek_line = order['items']
    order = pos.comp_line(user, order['id'], kek_line['lineId'], 'Bekleme telafisi', approver_id='m1')
    order = pos.set_discount(user, order['id'], {'type': 'percent', 'value': 10}, 'Sürekli müşteri', 'm1')
    assert (order['subtotal'], order['discountAmount'], order['total']) == (9500, 950, 8550)
    order = pos.void_line(user, order['id'], latte_line['lineId'], 'Vazgeçti', approver_id='m1')
    assert order['total'] == 0
    payloads = [json.loads(o['payload']) for o in db.get_pending_ops(500) if o['op'] in ('compItem', 'voidItem', 'setDiscount')]
    assert all(p['approvedBy'] == 'm1' for p in payloads)


def test_tasima_birlestirme_ve_masasiz(db, setup):
    pos, user = setup
    a = pos.open_order(user, {'id': 't1', 'name': 'Masa 1'})
    pos.add_line(user, a['id'], pos.product_line(db.menu_item('products', 'latte')))
    b = pos.open_order(user, {'id': 't2', 'name': 'Masa 2'})
    pos.add_line(user, b['id'], pos.product_line(db.menu_item('products', 'kek')))
    with pytest.raises(pos.OrderError, match='dolu'):
        pos.move_order(user, a['id'], {'id': 't2', 'name': 'Masa 2'})
    a = pos.move_order(user, a['id'], {'id': 't3', 'name': 'Masa 3'})
    assert legacy_table(db, 't1')['durum'] == 'bos' and legacy_table(db, 't3')['durum'] == 'dolu'
    merged = pos.merge_into(user, a['id'], b['id'])
    assert len(merged['items']) == 2
    assert pos.get_order(b['id'])['status'] == 'merged'
    assert legacy_table(db, 't2')['durum'] == 'bos'

    take = pos.open_order(user, None)
    assert take['type'] == 'takeaway' and take['no'] == 'A3'
    assert [o['no'] for o in pos.open_orders('takeaway')] == ['A3']


def test_bos_adisyon_iptali_ve_kapanmis_adisyon(db, setup):
    pos, user = setup
    o = pos.open_order(user, {'id': 't1', 'name': 'Masa 1'})
    o = pos.cancel_order(user, o['id'], 'Boş adisyon')
    assert o['status'] == 'cancelled' and legacy_table(db, 't1')['durum'] == 'bos'
    with pytest.raises(pos.OrderError, match='kapanmış'):
        pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'kek')))


def test_gun_donumu_saati(setup):
    pos, _ = setup
    assert pos.business_day(datetime(2026, 10, 16, 4, 59)) == '2026-10-15'
    assert pos.business_day(datetime(2026, 10, 16, 5, 0)) == '2026-10-16'


def test_masa_listesi_acik_adisyondan_beslenir(db, setup):
    pos, user = setup
    o = pos.open_order(user, {'id': 't1', 'name': 'Masa 1'})
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
    region = db.get_all_regions()[0]
    t1 = next(t for t in db.get_tables_by_region(region['id']) if t['cloud_id'] == 't1')
    assert (t1['durum'], t1['toplam_tutar'], t1['order_id']) == ('dolu', 95.0, o['id'])
    assert t1['siparis_tarihi']
    assert db.get_dashboard_stats()['occupied_tables'] == 1


def test_eski_acik_adisyonlar_bir_kez_tasinir(db):
    import pos
    seed(db, 'w1', 'waiter', pin='730591')
    user = db.login_with_pin('w1', '730591')
    payload = db.legacy_floor_payload()
    db.apply_floor_mapping({str(a['localId']): f"area{a['localId']}" for a in payload},
                           {str(t['localId']): f"tbl{t['localId']}" for a in payload for t in a['tables']})
    db.upsert_floor('areas', [(f"area{a['localId']}", {'name': a['name'], 'order': i, 'fixtures': []})
                              for i, a in enumerate(payload)])
    assert pos.migrate_legacy_open_orders(user) == 4
    assert pos.migrate_legacy_open_orders(user) == 0
    moved = {o['tableName']: o for o in pos.open_orders()}
    assert moved['Masa 2']['total'] == 25500 and moved['Masa 2']['items'][0]['state'] == 'sent'
    assert pos.tickets() == []  # eski adisyonlar mutfağa yeniden düşmez
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM orders WHERE durum='tasindi'").fetchone()[0] == 4
    conn.close()
