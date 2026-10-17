"""Uygulamadan gelen siparişler (11b): onay → adisyon + fişler (tek transaction), red, gelmedi, masa çağrıları — yerel."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from cloud.orders import OrderError
from tests.test_local import seed


def _iso(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M:%S.000000Z')


@pytest.fixture
def env(db):
    import app_orders
    import pos
    db.set_sync_state('terminal_letter', 'A')
    seed(db, 'w1', 'waiter', pin='730591')
    db.set_setting('modules', {'loyalty': {'enabled': True}, 'app': {'enabled': True, 'tableOrders': True, 'pickup': True}})
    db.upsert_floor('areas', [('a1', {'name': 'Salon', 'order': 0, 'fixtures': [], 'deleted': False})])
    db.upsert_floor('tables', [('t4', {'name': '4', 'areaId': 'a1', 'shape': 'square', 'capacity': 4, 'x': 0, 'y': 0,
                                       'w': 120, 'h': 120, 'rotation': 0, 'deleted': False})])
    db.upsert_menu('categories', [('kahve', {'name': 'Kahve', 'station': 'bar', 'order': 0, 'stampEligible': True}),
                                  ('tatli', {'name': 'Tatlı', 'station': 'kitchen', 'order': 1})])
    db.upsert_menu('products', [('latte', {'name': 'Latte', 'categoryId': 'kahve', 'price': 9500, 'active': True}),
                                ('kek', {'name': 'Kek', 'categoryId': 'tatli', 'price': 7000, 'active': True,
                                         'taxRate': 1})])
    db.upsert_cache('customers', [('c1', {'name': 'Ayşe K.', 'phone': '5321112233', 'stamps': 3, 'tier': 'silver'})])
    db.upsert_cache('appOrders', [
        ('r1', {'kind': 'table', 'tableId': 't4', 'tableName': '4', 'customerId': 'c1', 'customerName': 'Ayşe K.',
                'items': [{'productId': 'latte', 'name': 'Latte', 'qty': 2, 'unitPrice': 9500, 'note': '',
                           'options': [{'groupId': 'size', 'optionId': 'l', 'name': 'Büyük', 'priceDelta': 1500}]},
                          {'productId': 'kek', 'name': 'Kek', 'qty': 1, 'unitPrice': 7000, 'options': [], 'note': ''}],
                'total': 29000, 'note': 'pencere kenarı', 'status': 'pending', 'createdAt': _iso(-1),
                'expiresAt': _iso(1)}),
        ('r2', {'kind': 'pickup', 'customerId': 'c9', 'customerName': 'Mert', 'pickupAt': _iso(15),
                'items': [{'productId': 'latte', 'name': 'Latte', 'qty': 1, 'unitPrice': 9500, 'options': []}],
                'total': 9500, 'status': 'pending', 'createdAt': _iso(-0.5), 'expiresAt': _iso(1.5)}),
        ('r3', {'kind': 'table', 'tableId': 't4', 'customerId': 'c1', 'items': [], 'status': 'pending',
                'createdAt': _iso(-5), 'expiresAt': _iso(-3)}),   # süresi dolmuş
        ('r4', {'kind': 'pickup', 'status': 'rejected', 'items': []}),
    ])
    db.upsert_cache('tableCalls', [('t4_waiter', {'tableId': 't4', 'tableName': '4', 'kind': 'waiter', 'status': 'open',
                                                  'at': '2026-10-17T10:00:00Z'}),
                                   ('t4_bill', {'tableId': 't4', 'kind': 'bill', 'status': 'done', 'at': 'x'})])
    user = db.login_with_pin('w1', '730591')
    db.get_connection().execute("DELETE FROM outbox").connection.commit()
    return app_orders, pos, user


def _ops(db):
    return [(o['op'], json.loads(o['payload'])) for o in db.get_pending_ops(100)]


class Calls:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def __call__(self, name, data):
        self.calls.append((name, data))
        if self.fail:
            raise OrderError(self.fail)
        return {'status': 'ok', 'pickupBlocked': True}


def test_bekleyenler_suresi_dolan_duser_ve_cagrilar(db, env):
    app_orders, _, _ = env
    assert app_orders.enabled()
    assert [r['id'] for r in app_orders.pending()] == ['r1', 'r2']
    assert app_orders.seconds_left(app_orders.pending()[0]) in range(50, 61)
    assert [c['id'] for c in app_orders.open_calls()] == ['t4_waiter']
    assert app_orders.calls_by_table() == {'t4': ['waiter']}
    assert app_orders.place(app_orders.pending()[0]) == 'Masa 4' and app_orders.place(app_orders.pending()[1]) == 'Gel-al'
    assert app_orders.items_text(app_orders.pending()[0]) == '2× Latte (Büyük), 1× Kek'
    t4 = next(t for t in db.get_tables_by_region(db.get_all_regions()[0]['id']) if t['cloud_id'] == 't4')
    assert t4['calls'] == ['waiter']


def test_masa_istegi_onaylaninca_adisyon_fisler_ve_uye(db, env):
    app_orders, pos, user = env
    call = Calls()
    order = app_orders.accept(user, app_orders.pending()[0], call=call)
    assert order['type'] == 'dine_in' and order['tableId'] == 't4' and order['customer']['id'] == 'c1'
    assert order['total'] == 29000
    latte, kek = order['items']
    assert (latte['qty'], latte['options'][0]['name'], latte['note'], latte['state'], latte['station'],
            latte['stampEligible']) == (2, 'Büyük', 'pencere kenarı', 'sent', 'bar', True)
    assert (kek['station'], kek['taxRate'], kek['stampEligible']) == ('kitchen', 1, False)
    name, data = call.calls[0]
    assert name == 'acceptAppOrder' and data['orderId'] == order['id'] and data['orderNo'] == order['no']
    assert sorted(data['ticketIds']) == sorted({latte['ticketId'], kek['ticketId']})
    assert {t['station'] for t in pos.tickets(('new',)) if t['orderId'] == order['id']} == {'bar', 'kitchen'}
    assert [op for op, _ in _ops(db)] == ['openOrder', 'addItems', 'setCustomer', 'sendItems']
    assert [r['id'] for r in app_orders.pending()] == ['r2']   # yerelde hemen düşer

    # Masada açık adisyon varken gelen ikinci istek aynı adisyona eklenir; başka üye varsa dokunulmaz
    db.upsert_cache('appOrders', [('r5', {'kind': 'table', 'tableId': 't4', 'tableName': '4', 'customerId': 'c7',
                                          'items': [{'productId': 'kek', 'name': 'Kek', 'qty': 1, 'unitPrice': 7000}],
                                          'status': 'pending', 'createdAt': _iso(0), 'expiresAt': _iso(2)})])
    again = app_orders.accept(user, next(r for r in app_orders.pending() if r['id'] == 'r5'), call=Calls())
    assert again['id'] == order['id'] and len(again['items']) == 3 and again['customer']['id'] == 'c1'


def test_sunucu_onaylamazsa_hicbir_sey_kaydedilmez(db, env):
    app_orders, pos, user = env
    with pytest.raises(OrderError, match='iptal etti'):
        app_orders.accept(user, app_orders.pending()[1], call=Calls(fail='Müşteri siparişi iptal etti.'))
    assert pos.open_orders() == [] and _ops(db) == [] and pos.tickets(('new',)) == []
    assert db.get_sync_state('order_seq:' + pos.business_day()) in (None, '')   # adisyon numarası da harcanmaz


def test_gel_al_onay_red_gelmedi(db, env):
    app_orders, pos, user = env
    order = app_orders.accept(user, app_orders.pending()[1], call=Calls())
    # Üye önbellekte yoksa istekteki adla bağlanır (damga sunucuda kapanışta işlenir)
    assert order['type'] == 'takeaway' and order['customer'] == {'id': 'c9', 'name': 'Mert', 'tier': None}
    assert [o['id'] for o in pos.open_orders('takeaway')] == [order['id']]
    db.upsert_cache('appOrders', [('r2', {'kind': 'pickup', 'status': 'ready', 'orderId': order['id'],
                                          'orderNo': order['no'], 'pickupAt': _iso(15), 'customerName': 'Mert',
                                          'items': []})])
    assert [r['id'] for r in app_orders.pickups()] == ['r2']
    call = Calls()
    assert app_orders.no_show(user, app_orders.pickups()[0], call=call) == {'status': 'ok', 'pickupBlocked': True}
    assert call.calls[0][0] == 'appOrderNoShow' and app_orders.pickups() == []

    with pytest.raises(OrderError, match='gerekçe'):
        app_orders.reject(user, app_orders.pending()[0], '  ')
    call = Calls()
    app_orders.reject(user, app_orders.pending()[0], 'Ürün bitti', call=call)
    assert call.calls == [('rejectAppOrder', {'id': 'r1', 'reason': 'Ürün bitti', 'staffId': 'w1'})]
    assert app_orders.pending() == []


def test_garson_cagrisi_kuyruktan_kapatilir(db, env):
    app_orders, _, user = env
    app_orders.ack_call(user, app_orders.open_calls()[0])
    assert app_orders.open_calls() == []
    assert _ops(db) == [('ackTableCall', {'callId': 't4_waiter', 'at': '2026-10-17T10:00:00Z'})]


def test_internet_yoksa_onay_hata_verir(db, env):
    app_orders, pos, user = env
    from cloud.context import ctx
    ctx.engine = None
    with pytest.raises(OrderError, match='internet'):
        app_orders.accept(user, app_orders.pending()[0])
    assert pos.open_orders() == []
