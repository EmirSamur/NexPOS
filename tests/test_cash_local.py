"""Kasa (6. ekran): bölme, iade, kasa oturumu ve Z raporu — yerel, internet gerekmez."""
import json

import pytest

from tests.test_local import seed
from tests.test_pos_local import ops


@pytest.fixture
def kasa(db):
    import cash
    import pos
    db.set_sync_state('terminal_letter', 'A')
    seed(db, 'w1', 'waiter', pin='730591')
    seed(db, 'c1', 'cashier', pin='640218')
    seed(db, 'm1', 'manager', pin='583920')
    db.upsert_floor('areas', [('a1', {'name': 'Salon', 'order': 0, 'fixtures': [], 'deleted': False})])
    db.upsert_floor('tables', [(f't{i}', {'name': f'Masa {i}', 'areaId': 'a1', 'shape': 'square', 'capacity': 4,
                                          'x': 0, 'y': 0, 'w': 120, 'h': 120, 'rotation': 0, 'deleted': False})
                               for i in (1, 2)])
    db.upsert_menu('categories', [('kahve', {'name': 'Kahve', 'station': 'bar', 'order': 0})])
    db.upsert_menu('products', [('latte', {'name': 'Latte', 'categoryId': 'kahve', 'price': 10000, 'active': True}),
                                ('su', {'name': 'Su', 'categoryId': 'kahve', 'price': 2000, 'active': True,
                                        'taxRate': 1}),
                                ('kurabiye', {'name': 'Kurabiye', 'categoryId': 'kahve', 'price': 3001,
                                              'active': True, 'taxRate': 20})])
    waiter = db.login_with_pin('w1', '730591')
    cashier = db.login_with_pin('c1', '640218')
    db.get_connection().execute("DELETE FROM outbox").connection.commit()
    return cash, pos, waiter, cashier


def _order(db, pos, user, table, products):
    order = pos.open_order(user, {'id': table, 'name': table} if table else None)
    for pid, qty in products:
        pos.add_line(user, order['id'], pos.product_line(db.menu_item('products', pid), qty=qty))
    order, _ = pos.send_pending(user, order['id'])
    return order


def test_urun_satiri_kdv_oranini_menuden_alir(db, kasa):
    cash, pos, waiter, _ = kasa
    order = _order(db, pos, waiter, 't1', [('latte', 1), ('su', 1), ('kurabiye', 1)])
    assert [l['taxRate'] for l in order['items']] == [10, 1, 20]


def test_esit_bolme_kurus_farki_son_odemede_kapanir(db, kasa):
    cash, pos, waiter, cashier = kasa
    order = _order(db, pos, waiter, 't1', [('latte', 1)])
    order = pos.set_discount(waiter, order['id'], {'type': 'amount', 'value': 1})  # 99,99 ₺
    remaining = order['remaining']
    amounts = []
    for left in (3, 2, 1):
        share = pos.equal_share(order['remaining'], left)
        amounts.append(share)
        order = pos.take_payment(cashier, order['id'], 'card', share)
    assert amounts == [3333, 3333, 3333] and sum(amounts) == remaining and order['status'] == 'paid'


def test_urun_secerek_bolme_ve_satir_ayirma(db, kasa):
    cash, pos, waiter, cashier = kasa
    order = _order(db, pos, waiter, 't1', [('latte', 3), ('kurabiye', 1)])
    latte = order['items'][0]['lineId']
    order, one = pos.split_line(cashier, order['id'], latte, 1)
    assert [l['qty'] for l in order['items']] == [2, 1, 1]
    amount = pos.lines_payable(order, [one])
    assert amount == 10000
    order = pos.take_payment(cashier, order['id'], 'cash', amount, line_ids=[one])
    with pytest.raises(pos.OrderError, match='ödenmiş'):
        pos.take_payment(cashier, order['id'], 'card', 10000, line_ids=[one])
    rest = [l['lineId'] for l in order['items'] if not l.get('paidBy')]
    order = pos.take_payment(cashier, order['id'], 'card', pos.lines_payable(order, rest), line_ids=rest)
    assert order['status'] == 'paid'
    assert ops(db)[-3:] == ['splitLine', 'takePayment', 'takePayment']


def test_zorunlu_kasa_acilisi_nakit_almayi_engeller(db, kasa):
    cash, pos, waiter, cashier = kasa
    db.set_setting('modules', {'cashSession': {'required': True}})
    order = _order(db, pos, waiter, None, [('latte', 1)])
    with pytest.raises(pos.OrderError, match='Kasa açılmadan'):
        pos.take_payment(cashier, order['id'], 'cash', 10000)
    pos.take_payment(cashier, order['id'], 'card', 10000)  # kart serbest


def test_kasa_oturumu_ve_z_raporu_adisyonlarla_tutar(db, kasa):
    cash, pos, waiter, cashier = kasa
    with pytest.raises(pos.OrderError, match='cash'):
        cash.open_session(waiter, 50000)  # garsonun kasa yetkisi yok
    session = cash.open_session(cashier, 50000)
    with pytest.raises(pos.OrderError, match='zaten açık'):
        cash.open_session(cashier, 0)

    # 1) Masa 1: latte + su + kurabiye, %10 iskonto, nakit
    o1 = _order(db, pos, waiter, 't1', [('latte', 1), ('su', 1), ('kurabiye', 1)])
    o1 = pos.set_discount(waiter, o1['id'], {'type': 'percent', 'value': 10})
    assert o1['total'] == 15001 - 1500
    o1 = pos.take_payment(cashier, o1['id'], 'cash', o1['total'], received=20000)
    # 2) Paket: 2 latte, biri ikram; kartla, 10 ₺ bahşiş
    o2 = _order(db, pos, waiter, None, [('latte', 2)])
    o2, free = pos.split_line(cashier, o2['id'], o2['items'][0]['lineId'], 1)
    o2 = pos.comp_line(cashier, o2['id'], free, 'Doğum günü')
    o2 = pos.take_payment(cashier, o2['id'], 'card', o2['total'], tip=1000)
    # 3) Masa 2: iptal edilen ürün, sonra yarısı nakit yarısı yemek kartı
    o3 = _order(db, pos, waiter, 't2', [('latte', 1), ('su', 2)])
    o3 = pos.void_line(cashier, o3['id'], o3['items'][1]['lineId'], 'Yanlış sipariş')
    o3 = pos.take_payment(cashier, o3['id'], 'cash', 5000)
    o3 = pos.take_payment(cashier, o3['id'], 'meal', o3['remaining'])
    # 4) İptal edilen adisyon
    o4 = _order(db, pos, waiter, None, [('kurabiye', 1)])
    pos.cancel_order(cashier, o4['id'], 'Müşteri vazgeçti')
    # İade ve kasa hareketleri
    with pytest.raises(pos.OrderError, match='refund'):
        pos.refund(cashier, o1['id'], 'cash', 2000, 'Su bozuk')  # kasiyerin iade yetkisi yok
    pos.refund(cashier, o1['id'], 'cash', 2000, 'Su bozuk', approver_id='m1')
    cash.add_movement(cashier, 'in', 5000, 'Bozuk para')
    cash.add_movement(cashier, 'out', 3000, 'Süt alındı', expense=True)
    with pytest.raises(pos.OrderError, match='Gerekçe'):
        cash.add_movement(cashier, 'out', 100, '')

    x = cash.build_report(cash.current_session())
    assert x['kind'] == 'X'
    assert x['sales'] == {'cash': 13501 + 5000, 'card': 10000, 'meal': 5000, 'total': 33501}
    assert x['sales']['total'] == sum(o['total'] for o in (o1, o2, o3))
    assert x['refunds']['total'] == 2000 and x['refunds']['count'] == 1
    assert x['tips']['total'] == 1000
    assert x['discount'] == {'amount': 1500, 'count': 1}
    assert x['comps'] == {'count': 1, 'amount': 10000}
    assert x['voids'] == {'count': 2 + 1, 'amount': 4000 + 3001}
    assert x['orders'] == {'count': 3, 'total': 33501, 'average': 11167, 'cancelled': 1}
    # KDV: oranlara dağılan matrah toplamı satışa eşit
    assert sum(v['gross'] for v in x['vat']) == 33501
    by_rate = {v['rate']: v for v in x['vat']}
    assert by_rate[20]['vat'] == round(by_rate[20]['gross'] * 20 / 120)
    assert x['staff'][0]['name'] and x['staff'][0]['total'] == 33501
    expected = 50000 + 18501 - 2000 + 5000 - 3000
    assert x['cash']['expected'] == expected == cash.expected_cash(cash.current_session())

    # Masraflar sayfasına nakit gider düştü
    conn = db.get_connection()
    assert conn.execute("SELECT tutar FROM expenses WHERE masraf_detayi='Süt alındı'").fetchone()['tutar'] == 30
    conn.close()

    # Kapanış: fark eşiği (20 ₺) aşılırsa gerekçe zorunlu
    assert cash.needs_difference_reason(cash.current_session(), expected - 2001)
    assert not cash.needs_difference_reason(cash.current_session(), expected - 2000)
    with pytest.raises(pos.OrderError, match='gerekçe'):
        cash.close_session(cashier, expected - 5000)
    z = cash.close_session(cashier, expected - 5000, 'Bozuk para eksik')
    assert z['kind'] == 'Z' and z['cash']['difference'] == -5000 and z['cash']['counted'] == expected - 5000
    assert cash.current_session() is None and cash.past_sessions()[0]['id'] == session['id']

    queued = [o for o in db.get_pending_ops(500) if o['op'] in ('openCashSession', 'cashMovement', 'closeCashSession')]
    assert [o['op'] for o in queued] == ['openCashSession', 'cashMovement', 'cashMovement', 'closeCashSession']
    close = json.loads(queued[-1]['payload'])
    assert close['expectedCash'] == expected and close['report']['sales']['total'] == 33501
    pays = [json.loads(o['payload']) for o in db.get_pending_ops(500) if o['op'] in ('takePayment', 'refundPayment')]
    assert all(p['cashSessionId'] == session['id'] for p in pays)


def test_iade_yalnizca_odenmis_adisyonda_masaya_dokunmaz(db, kasa):
    cash, pos, waiter, cashier = kasa
    order = _order(db, pos, waiter, 't1', [('latte', 1)])
    with pytest.raises(pos.OrderError, match='Yalnızca ödenmiş'):
        pos.refund(cashier, order['id'], 'card', 1000, 'x', approver_id='m1')
    order = pos.take_payment(cashier, order['id'], 'card', 10000)
    pos.open_order(waiter, {'id': 't1', 'name': 'Masa 1'})  # masaya yeni müşteri oturdu
    order = pos.refund(cashier, order['id'], 'card', 10000, 'Müşteri memnun kalmadı', approver_id='m1')
    assert order['refunded'] == 10000 and order['status'] == 'paid'
    conn = db.get_connection()
    assert conn.execute("SELECT durum FROM tables WHERE cloud_id='t1'").fetchone()['durum'] == 'dolu'
    conn.close()
    with pytest.raises(pos.OrderError, match='aşamaz'):
        pos.refund(cashier, order['id'], 'card', 1, 'x', approver_id='m1')
    assert [o['id'] for o in pos.closed_orders()] == [order['id']]


def test_moduller_varsayilanla_tamamlanir(db):
    db.set_setting('modules', {'kds': {'enabled': True, 'warnMinutes': 'x'}, 'tips': False})
    m = db.modules()
    assert m['kds'] == {'enabled': True, 'warnMinutes': 10, 'lateMinutes': 20, 'sound': True}
    assert m['tips'] is False and m['cashSession']['required'] is False


def test_fis_ve_rapor_pdf_olarak_kaydedilir(db, kasa, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841 (yazı tipleri için gerekli)
    import printing
    cash, pos, waiter, cashier = kasa
    cash.open_session(cashier, 10000)
    order = _order(db, pos, waiter, 't1', [('latte', 2), ('su', 1)])
    order = pos.take_payment(cashier, order['id'], 'cash', order['total'])
    bill = printing.bill_html(order)
    assert 'Bilgi fişidir, mali değeri yoktur.' in bill and '2 × Latte' in bill
    kind, path = printing.print_html(bill, f"Adisyon {order['no']}")
    assert kind == 'pdf' and path.endswith('.pdf')
    with open(path, 'rb') as f:
        assert f.read(4) == b'%PDF'
    z = cash.close_session(cashier, 10000 + order['total'])
    html = printing.report_html(z)
    assert 'Z RAPORU' in html and 'Beklenen nakit' in html
    out = printing.save_pdf(html, 'Z', 'A4', str(tmp_path / 'z.pdf'))
    assert (tmp_path / 'z.pdf').stat().st_size > 500 and out.endswith('z.pdf')
    ticket = pos.tickets(('new',))[0]
    assert 'BAR' in printing.ticket_html(ticket)
