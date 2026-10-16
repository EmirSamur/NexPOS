"""
Uçtan uca test: NexPOS ↔ Firebase emülatörü.

Çalıştırma (firebase/ klasöründen):
    firebase emulators:exec --project demo-nexpos --only auth,firestore,functions \
        "cd .. && NEXPOS_EMULATOR=1 python -m pytest tests/test_cloud_emulator.py"
"""
import os
import re
import subprocess
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('NEXPOS_EMULATOR') != '1',
                                reason='Firebase emülatörü gerekli (NEXPOS_EMULATOR=1)')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_owner(email, password='sahip-sifre-1', name='Deniz Yılmaz', pin='482913'):
    env = {**os.environ,
           'FIRESTORE_EMULATOR_HOST': '127.0.0.1:8080',
           'FIREBASE_AUTH_EMULATOR_HOST': '127.0.0.1:9099',
           'GCLOUD_PROJECT': 'demo-nexpos'}
    out = subprocess.run(
        ['node', os.path.join(ROOT, 'firebase/functions/scripts/createOwner.js'), email, password, name, pin],
        env=env, capture_output=True, text=True, check=True).stdout
    return re.search(r'staffId: (\w+)', out).group(1)


@pytest.fixture
def client():
    from cloud.config import load_config
    from cloud.firebase_client import FirebaseClient
    return FirebaseClient(load_config())


def test_eşleme_giriş_kuyruk_ve_iptal(db, client):
    from cloud import credentials
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    email = f'sahip-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)

    # 1) Eşleme: yönetici giriş yapar, terminal kaydedilir, personel ve PIN'ler iner.
    steps = []
    creds, engine = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1', steps.append)
    assert creds.letter and creds.terminal_id
    assert credentials.load() == creds
    assert len(steps) == 4
    assert owner_id in {s['id'] for s in db.get_login_staff()}

    # 2) Yönetici panelden garson ekler (kendi oturumuyla) → senkronla terminale iner.
    owner_session = client.sign_in_with_password(email, 'sahip-sifre-1')
    api = AdminApi(client, owner_session)
    waiter_id = api.create_staff('Cem Akar', 'waiter', '730591', phone='5359876543')['staffId']
    api.save_permissions({'waiter': {'discount': True}})

    engine = SyncEngine(client, creds)  # yeni açılış gibi: oturum refresh token'dan kurulur
    status = engine.run_once()
    assert status.online and not status.revoked
    assert {'staff', 'staffPins', 'permissions'} <= status.changed
    assert db.get_permission_matrix()['waiter']['discount'] is True

    # 3) İnternetsiz PIN girişi önbellekten çalışır; giriş kaydı kuyruğa düşer.
    user = db.login_with_pin(waiter_id, '730591')
    assert user['gorev'] == 'Garson'
    assert db.user_can(user, 'discount')
    db.enqueue_op('audit', {'action': 'approval_voiditem', 'detail': 'Latte ×1', 'approvedBy': owner_id},
                  waiter_id)
    db.enqueue_op('futureOp', {}, waiter_id)  # sunucu henüz desteklemiyor → kuyrukta bekler
    assert db.outbox_counts() == (3, 0)

    status = engine.run_once()
    assert status.online
    assert db.outbox_counts() == (1, 0)  # yalnızca desteklenmeyen işlem kaldı
    assert db.get_pending_ops()[0]['op'] == 'futureOp'

    # Sunucu giriş zamanını personel kaydına yazdı ve bu da terminale geri indi.
    engine.run_once()
    assert db.get_staff(waiter_id)['last_login_at']

    # 4) PIN sıfırlanınca yeni PIN terminale iner, eskisi geçersiz olur.
    api.set_pin(waiter_id, '902817')
    engine.run_once()
    with pytest.raises(db.LoginError):
        db.check_pin(waiter_id, '730591')
    db.check_pin(waiter_id, '902817')

    # 5) Pasife alınan personel giriş ekranından düşer.
    api.set_active(waiter_id, False)
    engine.run_once()
    assert waiter_id not in {s['id'] for s in db.get_login_staff()}

    # 6) Terminaller listesi ve iptal: bir sonraki senkronda terminal kilitlenir.
    terminals = dict(api.list_terminals())
    assert terminals[creds.terminal_id]['letter'] == creds.letter
    api.revoke_terminal(creds.terminal_id)
    status = SyncEngine(client, creds).run_once()
    assert status.revoked


def test_menu_aktarim_duzenleme_tukendi_toplu_fiyat_fotograf(db, client):
    import json
    import requests
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    # Diğer testlerin (JS emülatör testleri dahil) bıraktığı menü bu testi etkilemesin:
    # Firestore emülatörünü boşalt. Auth hesapları kalır, e-postalar benzersiz.
    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'menu-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Menü Kasa')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)

    # 1) Eski yerel menü buluta aktarılır; yerel satırlar bulut kimliğiyle eşleşir, çift kayıt olmaz.
    cats, prods = db.legacy_import_payload()
    result = api.import_menu(cats, prods)
    db.apply_import_mapping(result['categories'], result['products'])
    status = engine.run_once()
    assert {'categories', 'products'} <= status.changed
    sold = db.get_products_by_category()
    assert len(sold) == len({p['ad'] for p in sold})  # aynı üründen iki tane yok
    latte = next(p for p in db.menu_products() if p['name'] == 'Latte')
    assert latte['price'] == 8500
    kahve = db.menu_item('categories', latte['categoryId'])
    assert kahve['station'] == 'bar' and kahve['stampEligible'] is True

    # 2) Panelden fiyat değişikliği terminale ve eski tablolara iner.
    api.save_product({**{k: latte[k] for k in ('categoryId', 'name')}, 'price': 9500}, latte['id'])
    engine.run_once()
    assert next(p for p in db.get_products_by_category() if p['ad'] == 'Latte')['fiyat'] == 95.0

    # 3) Tükendi: internetsiz yerelde uygulanır, kuyruktan buluta gider (barista yetkisiyle).
    barista = api.create_staff('Burak Öz', 'barista', '573920')['staffId']
    engine.run_once()
    db.set_sold_out(barista, True, product_id=latte['id'])
    assert next(p for p in db.get_products_by_category() if p['ad'] == 'Latte')['tukendi'] == 1
    engine.run_once()
    assert db.outbox_counts() == (0, 0)
    cloud_latte = client.get_doc(f"products/{latte['id']}", api.session)[1]
    assert cloud_latte['soldOut'] is True

    # 4) Toplu fiyat: önizleme yazmaz, uygulama yazar ve terminale iner.
    rule = {'mode': 'percent', 'value': 10, 'rounding': 500}
    preview = api.bulk_prices([latte['categoryId']], rule, False, True)
    assert any(c['id'] == latte['id'] and c['after'] == 10500 for c in preview['products'])
    assert client.get_doc(f"products/{latte['id']}", api.session)[1]['price'] == 9500
    api.bulk_prices([latte['categoryId']], rule, False, False)
    engine.run_once()
    assert db.menu_item('products', latte['id'])['price'] == 10500

    # 5) Fotoğraf yüklenir, herkese açık adresten okunur.
    from PySide6.QtGui import QImage, QColor
    from cloud.images import prepare_upload
    import tempfile
    img = QImage(1600, 1200, QImage.Format_RGB32)
    img.fill(QColor('#8D6E63'))
    path = tempfile.mktemp(suffix='.png')
    img.save(path)
    data = prepare_upload(path)
    assert QImage.fromData(data).width() == 800
    url = api.upload_product_image(data)
    assert requests.get(url, timeout=10).content == data
    api.save_product({'categoryId': latte['categoryId'], 'name': 'Latte', 'price': 10500, 'imageUrl': url}, latte['id'])
    engine.run_once()
    assert db.menu_item('products', latte['id'])['imageUrl'] == url


def test_salon_aktarim_plan_qr_ayarlar(db, client):
    import requests
    from cloud.admin_api import AdminApi
    from cloud.firebase_client import ApiError
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'salon-{uuid.uuid4().hex[:6]}@kafe.test'
    create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Salon Kasa')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)

    # 1) Eski düzen aktarılır; açık adisyonlar masalarında kalır, çift masa oluşmaz.
    result = api.import_floor(db.legacy_floor_payload())
    db.apply_floor_mapping(result['areas'], result['tables'])
    status = engine.run_once()
    assert {'areas', 'tables'} <= status.changed
    areas = db.floor_areas()
    assert [a['name'] for a in areas] == ['Salon', 'Teras', 'Bahçe']
    salon = areas[0]
    states = {t['name']: t for t in db.floor_table_states(salon['id'])}
    assert len(states) == 8 and states['Masa 2']['legacy']['durum'] == 'dolu'
    assert sum(len(db.get_tables_by_region(r['id'])) for r in db.get_all_regions()) == 24

    # 2) Plan kaydı: Masa 1 yuvarlak olup taşınır, Masa 8 silinir, yeni masa ve bar eklenir.
    tables, removed = [], []
    for t in db.floor_tables(salon['id']):
        if t['name'] == 'Masa 8':
            removed.append(t['id'])
            continue
        geo = {k: t[k] for k in ('x', 'y', 'w', 'h', 'rotation')}
        item = {'id': t['id'], 'name': t['name'], 'shape': t['shape'], 'capacity': t['capacity'], **geo}
        if t['name'] == 'Masa 1':
            item.update(shape='round', w=100, h=100, x=600, y=500, capacity=2)
        tables.append(item)
    tables.append({'tempId': 'yeni', 'name': 'Masa 25', 'shape': 'rect', 'capacity': 6,
                   'x': 800, 'y': 600, 'w': 200, 'h': 120, 'rotation': 90})
    bar = [{'id': 'bar1', 'kind': 'bar', 'label': 'Bar', 'x': 820, 'y': 40, 'w': 320, 'h': 70, 'rotation': 0}]
    res = api.save_floor_plan(salon['id'], salon['layoutVersion'], tables, bar, removed)
    engine.run_once()
    states = {t['name']: t for t in db.floor_table_states(salon['id'])}
    assert 'Masa 8' not in states and states['Masa 25']['legacy'] is not None
    assert (states['Masa 1']['shape'], states['Masa 1']['x']) == ('round', 600)
    assert db.menu_item('areas', salon['id'])['fixtures'][0]['label'] == 'Bar'
    assert res['created']['yeni'] == states['Masa 25']['id']

    # Eski sürümle kaydetme reddedilir (iki kişi aynı anda düzenlediyse)
    with pytest.raises(ApiError) as e:
        api.save_floor_plan(salon['id'], salon['layoutVersion'], tables, bar)
    assert e.value.code == 'aborted'

    # 3) QR yenileme yeni anahtarı terminale indirir.
    old = states['Masa 1']['qrToken']
    api.rotate_table_qr([states['Masa 1']['id']])
    engine.run_once()
    assert db.menu_item('tables', states['Masa 1']['id'])['qrToken'] != old

    # 4) Genel ayarlar terminale iner (otomatik kilit dahil).
    api.save_general_settings('Velvet Kafe', 'https://velvet.web.app/masa', 5)
    status = engine.run_once()
    assert 'general' in status.changed
    assert db.general_settings() == {'cafeName': 'Velvet Kafe', 'qrBaseUrl': 'https://velvet.web.app/masa',
                                     'idleLockMinutes': 5}


def test_siparis_internetsiz_akis_sonra_senkron(db, client):
    import requests
    import pos
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'pos-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'POS Kasa')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)

    # Hazırlık: menü + salon + garson + müdür (buluta), terminale iner
    cats, prods = db.legacy_import_payload()
    res = api.import_menu(cats, prods)
    db.apply_import_mapping(res['categories'], res['products'])
    res = api.import_floor(db.legacy_floor_payload())
    db.apply_floor_mapping(res['areas'], res['tables'])
    waiter = api.create_staff('Cem Akar', 'waiter', '730591')['staffId']
    manager = api.create_staff('Mert Kaya', 'manager', '583920', email=f'm-{uuid.uuid4().hex[:6]}@kafe.test',
                               password='mudur-sifre-1')['staffId']
    milk = api.save_option_group({'name': 'Süt', 'options': [{'id': 'normal', 'name': 'Normal', 'priceDelta': 0},
                                                            {'id': 'oat', 'name': 'Yulaf', 'priceDelta': 1500}]})['id']
    latte_id = next(p for p in (api.client.list_docs('products', api.session)) if p[1]['name'] == 'Latte')[0]
    latte_doc = client.get_doc(f'products/{latte_id}', api.session)[1]
    api.save_product({'categoryId': latte_doc['categoryId'], 'name': 'Latte', 'price': 9500,
                      'optionGroupIds': [milk]}, latte_id)
    engine.run_once()
    engine.run_once()
    user = db.login_with_pin(waiter, '730591')

    # Eski açık adisyonlar taşınır (örnek veride 4 masa)
    assert pos.migrate_legacy_open_orders(user) == 4

    # ---- İnternetsiz: hiçbir senkron çağrılmadan baştan sona
    salon = db.floor_areas()[0]
    m1 = next(t for t in db.floor_tables(salon['id']) if t['name'] == 'Masa 1')
    order = pos.open_order(user, {'id': m1['id'], 'name': m1['name']})
    latte = db.menu_item('products', latte_id)
    group = db.menu_item('optionGroups', milk)
    oat = next(o for o in group['options'] if o['id'] == 'oat')
    pos.add_line(user, order['id'], pos.product_line(latte, [(milk, oat)], qty=2))
    tost = next(p for p in db.menu_products() if p['name'] == 'Tost')
    order = pos.add_line(user, order['id'], pos.product_line(tost, note='bol kaşarlı'))
    order, _ = pos.send_pending(user, order['id'])
    order = pos.set_discount(user, order['id'], {'type': 'percent', 'value': 10}, 'Sürekli müşteri', manager)
    order = pos.void_line(user, order['id'], order['items'][1]['lineId'], 'Vazgeçti', manager)
    assert order['total'] == 2 * 11000 - 2200
    order = pos.take_payment(user, order['id'], 'card', order['total'], tip=1000)
    assert order['status'] == 'paid'

    pending_before, _ = db.outbox_counts()
    assert pending_before > 10
    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()

    cloud = client.get_doc(f"orders/{order['id']}", api.session)[1]
    for k in ('subtotal', 'discountAmount', 'total', 'paid', 'status', 'no', 'businessDay'):
        assert cloud[k] == order[k], k
    assert cloud['stamps'] == 2
    assert [l['status'] for l in cloud['items']] == ['active', 'void']
    assert client.get_doc(f"tables/{m1['id']}", api.session)[1]['status'] == 'empty'
    tickets = {d[1]['station']: d[1] for d in client.list_docs('kitchenTickets', api.session)
               if d[1]['orderId'] == order['id']}
    assert tickets['bar']['lines'][0]['options'] == ['Yulaf'] and tickets['kitchen']['lines'][0]['note'] == 'bol kaşarlı'
    pay = client.get_doc(f"payments/{order['payments'][0]['paymentId']}", api.session)[1]
    assert (pay['method'], pay['tip'], pay['amount']) == ('card', 1000, order['total'])

    # Taşınan eski adisyonlar da bulutta açık ve masaları dolu
    moved = [o for o in pos.open_orders() if o['tableName'] == 'Masa 2'][0]
    assert client.get_doc(f"orders/{moved['id']}", api.session)[1]['total'] == 25500
    m2 = next(t for t in db.floor_tables(salon['id']) if t['name'] == 'Masa 2')
    assert client.get_doc(f"tables/{m2['id']}", api.session)[1]['status'] == 'occupied'


def test_kasa_internetsiz_oturum_bolme_iade_sonra_senkron(db, client):
    import requests
    import cash
    import pos
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'kasa-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)
    cats, prods = db.legacy_import_payload()
    res = api.import_menu(cats, prods)
    db.apply_import_mapping(res['categories'], res['products'])
    cashier = api.create_staff('Selin Er', 'cashier', '640218')['staffId']
    saved = api.save_modules({'cashSession': {'required': True}, 'printing': {'enabled': True}})
    assert saved['cashSession']['required'] is True
    engine.run_once()
    assert db.modules()['cashSession']['required'] is True   # modül ayarı terminale indi
    user = db.login_with_pin(cashier, '640218')

    # ---- İnternetsiz: kasa aç, böl, öde, iade, hareket, kapat
    latte = next(p for p in db.menu_products() if p['name'] == 'Latte')
    order = pos.open_order(user)
    with pytest.raises(pos.OrderError, match='Kasa açılmadan'):
        pos.take_payment(user, order['id'], 'cash', 1)
    session = cash.open_session(user, 50000)
    order = pos.add_line(user, order['id'], pos.product_line(latte, qty=3))
    order, _ = pos.send_pending(user, order['id'])
    order, one = pos.split_line(user, order['id'], order['items'][0]['lineId'], 1)
    order = pos.take_payment(user, order['id'], 'cash', pos.lines_payable(order, [one]), line_ids=[one])
    rest = [l['lineId'] for l in order['items'] if not l.get('paidBy')]
    order = pos.take_payment(user, order['id'], 'card', pos.lines_payable(order, rest), line_ids=rest)
    pos.refund(user, order['id'], 'cash', 1000, 'Soğuk geldi', approver_id=owner_id)
    cash.add_movement(user, 'out', 2000, 'Süt', expense=True)
    expected = cash.expected_cash(cash.current_session())
    z = cash.close_session(user, expected)

    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()
    cloud = client.get_doc(f"cashSessions/{session['id']}", api.session)[1]
    assert (cloud['status'], cloud['expectedCash'], cloud['difference']) == ('closed', expected, 0)
    assert cloud['report']['sales']['total'] == z['sales']['total'] == order['total']
    assert cloud['movements'][0]['expense'] is True
    o = client.get_doc(f"orders/{order['id']}", api.session)[1]
    assert (o['status'], o['refunded'], [l.get('paidBy') is not None for l in o['items']]) == ('paid', 1000, [True, True])
    refund = [d for d in client.list_docs('refunds', api.session) if d[1]['orderId'] == order['id']]
    assert refund and refund[0][1]['cashSessionId'] == session['id']


def test_mutfak_ekrani_hazir_kasaya_iner_teslim_buluta_gider(db, client):
    import requests
    import pos
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'kds-{uuid.uuid4().hex[:6]}@kafe.test'
    create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)
    cats, prods = db.legacy_import_payload()
    res = api.import_menu(cats, prods)
    db.apply_import_mapping(res['categories'], res['products'])
    res = api.import_floor(db.legacy_floor_payload())
    db.apply_floor_mapping(res['areas'], res['tables'])
    waiter = api.create_staff('Cem Akar', 'waiter', '730591')['staffId']
    api.save_modules({'kds': {'enabled': True}})
    # Mutfak tableti: kodla eşlenir (giriş yapmadan), kendi cihaz hesabını alır
    code = api.create_kds_pairing_code('Mutfak')['code']
    paired = client.call('pairKds', {'code': code, 'station': 'all'}, None)
    tablet = client.sign_in_with_custom_token(paired['customToken'])
    engine.run_once()
    user = db.login_with_pin(waiter, '730591')

    salon = db.floor_areas()[0]
    m1 = next(t for t in db.floor_tables(salon['id']) if t['name'] == 'Masa 1')
    order = pos.open_order(user, {'id': m1['id'], 'name': m1['name']})
    tost = next(p for p in db.menu_products() if p['name'] == 'Tost')
    pos.add_line(user, order['id'], pos.product_line(tost))
    order, _ = pos.send_pending(user, order['id'])
    engine.run_once()
    ticket_id = order['items'][0]['ticketId']

    # Tablet: Başla → Hazır
    client.call('updateKitchenTicket', {'ticketId': ticket_id, 'status': 'preparing'}, tablet)
    client.call('updateKitchenTicket', {'ticketId': ticket_id, 'status': 'ready'}, tablet)
    status = engine.run_once()
    assert 'kitchenTickets' in status.changed
    ready = db.take_ready_notifications()
    assert [t['id'] for t in ready] == [ticket_id]
    legacy = next(t for t in db.get_tables_by_region(db.get_all_regions()[0]['id']) if t['cloud_id'] == m1['id'])
    assert legacy['ready'] is True

    # Garson teslim etti → bulutta served; tablet artık değiştiremez
    pos.set_ticket_status(user, ticket_id, 'served')
    engine.run_once()
    assert client.get_doc(f'kitchenTickets/{ticket_id}', api.session)[1]['status'] == 'served'
    with pytest.raises(Exception, match='teslim'):
        client.call('updateKitchenTicket', {'ticketId': ticket_id, 'status': 'ready'}, tablet)
    # Tablet personel ve PIN verisini okuyamaz
    with pytest.raises(Exception):
        client.list_docs('staffPins', tablet)


def test_gunluk_ozet_bulutta_yerel_raporla_ayni(db, client):
    import requests
    import pos
    import reports
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'rapor-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)
    cats, prods = db.legacy_import_payload()
    res = api.import_menu(cats, prods)
    db.apply_import_mapping(res['categories'], res['products'])
    waiter = api.create_staff('Cem Akar', 'waiter', '730591')['staffId']
    engine.run_once()
    user = db.login_with_pin(waiter, '730591')
    menu = {p['name']: p for p in db.menu_products()}

    def order(items):
        o = pos.open_order(user)
        for name, qty in items:
            pos.add_line(user, o['id'], pos.product_line(menu[name], qty=qty))
        return pos.send_pending(user, o['id'])[0]

    # İnternetsiz bir gün: iskonto, ikram, iptal, bölünmüş ödeme, adisyon iptali, iade
    o1 = order([('Latte', 2), ('Tost', 1)])
    o1 = pos.set_discount(user, o1['id'], {'type': 'percent', 'value': 15}, 'Öğrenci', owner_id)
    o1 = pos.take_payment(user, o1['id'], 'cash', 5000)
    o1 = pos.take_payment(user, o1['id'], 'card', o1['remaining'], tip=500)
    o2 = order([('Latte', 3)])
    o2, one = pos.split_line(user, o2['id'], o2['items'][0]['lineId'], 1)
    o2 = pos.comp_line(user, o2['id'], one, 'Doğum günü', owner_id)
    o2 = pos.take_payment(user, o2['id'], 'meal', o2['total'])
    o3 = order([('Tost', 2), ('Latte', 1)])
    o3 = pos.void_line(user, o3['id'], o3['items'][0]['lineId'], 'Yanlış', owner_id)
    o3 = pos.take_payment(user, o3['id'], 'card', o3['total'])
    o4 = order([('Tost', 1)])
    pos.cancel_order(user, o4['id'], 'Vazgeçti', owner_id)
    pos.refund(user, o3['id'], 'card', 1000, 'Soğuk', approver_id=owner_id)

    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()
    day = pos.business_day()
    cloud = client.get_doc(f'dailyStats/{day}', api.session)[1]
    local = reports.day_stats(day)
    for key in ('orders', 'dineIn', 'takeaway', 'gross', 'discount', 'discountCount', 'revenue', 'tips', 'byPayment',
                'byStaff', 'byProduct', 'comps', 'voids', 'vat', 'cancelled', 'refunds', 'byHour'):
        assert cloud.get(key) == local.get(key), key
    assert local['revenue'] == o1['total'] + o2['total'] + o3['total']
    # Terminal günlük özeti okuyamaz (yalnızca yönetici/müdür)
    with pytest.raises(Exception):
        client.get_doc(f'dailyStats/{day}', engine._ensure_session())


def test_stok_sablon_internetsiz_satis_bulutla_ayni(db, client):
    import requests
    import pos
    import stock
    import stock_template
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'stok-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)
    cats, prods = db.legacy_import_payload()
    res = api.import_menu(cats, prods)
    db.apply_import_mapping(res['categories'], res['products'])
    api.save_option_group({'name': 'Süt', 'options': [{'id': 'n', 'name': 'Normal', 'priceDelta': 0},
                                                     {'id': 'oat', 'name': 'Yulaf sütü', 'priceDelta': 1500}]})
    waiter = api.create_staff('Cem Akar', 'waiter', '730591')['staffId']
    api.save_modules({'stock': {'enabled': True}})
    engine.run_once()
    # Hazır şablon menüye göre kurulur
    data = stock_template.build(db.menu_products(), db.menu_categories(), db.menu_option_groups(), stock.ingredients())
    assert any(p == 'Latte' for p, _ in data['preview'])
    api.import_stock(data['ingredients'], data['recipes'], data['optionEffects'])
    engine.run_once()
    ings = {i['name']: i for i in stock.ingredients()}
    assert 'Espresso çekirdeği' in ings and db.modules()['stock']['enabled']
    latte = next(p for p in db.menu_products() if p['name'] == 'Latte')
    assert latte['recipe']
    # Uygulamaya bağlı seçenek: yulaf sütü
    group = next(g for g in db.menu_option_groups() if g['name'] == 'Süt')
    oat = next(o for o in group['options'] if o['id'] == 'oat')
    assert oat['recipeEffect']['replace'][0]['to'] == ings['Yulaf sütü']['id']
    user = db.login_with_pin(waiter, '730591')
    stock.set_counts(user, {ings['Espresso çekirdeği']['id']: 2000, ings['Süt (tam yağlı)']['id']: 12000,
                            ings['Yulaf sütü']['id']: 6000}, 'İlk sayım', owner_id)

    # ---- İnternetsiz: paket latte (yulaf) ×2, masa latte ×1 hazırlanmadan iptal
    o = pos.open_order(user)
    pos.add_line(user, o['id'], pos.product_line(latte, [(group['id'], oat)], qty=2))
    pos.add_line(user, o['id'], pos.product_line(latte))
    o, _ = pos.send_pending(user, o['id'])
    pos.void_line(user, o['id'], o['items'][1]['lineId'], 'Yanlış', owner_id, prepared=False)
    local = {i['id']: i['stock'] for i in stock.ingredients()}
    assert local[ings['Yulaf sütü']['id']] == 6000 - 400
    assert local[ings['Espresso çekirdeği']['id']] == 2000 - 36
    assert local[ings['Karton bardak 12oz']['id']] == -2   # sayılmadı, eksiye düşebilir

    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()
    cloud = {d[0]: d[1]['stock'] for d in client.list_docs('ingredients', api.session)}
    assert {k: cloud[k] for k in local} == local
    assert {i['id']: i['stock'] for i in stock.ingredients()} == local   # senkrondan sonra çift sayılmaz


def test_tedarik_siparis_internetsiz_teslim_odeme_bulutla_ayni(db, client):
    import requests
    import stock
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'tedarik-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)
    api.save_modules({'stock': {'enabled': True}})
    sup = api.save_supplier({'name': 'Kahveci'})['id']
    esp = api.save_ingredient({'name': 'Espresso', 'unit': 'g', 'unitCost': 80000, 'critical': 2000, 'target': 5000,
                               'purchaseUnit': {'name': 'paket', 'size': 1000}, 'supplierId': sup})['id']
    engine.run_once()
    owner = db.login_with_pin(owner_id, '482913')
    stock.set_counts(owner, {esp: 1000}, 'İlk sayım', owner_id, initial=True)
    engine.run_once()
    lines = stock.suggest_order(sup)
    assert lines == [{'ingredientId': esp, 'qty': 4000, 'amount': 320000}]
    po = api.save_purchase_order({'supplierId': sup, 'status': 'sent', 'lines': lines})
    engine.run_once()
    assert stock.purchase_orders()[0]['no'] == po['no']

    # ---- İnternetsiz: 3 paket geldi (2.550 ₺), ödenecek; sonra 1.000 ₺ havale
    stock.receive(owner, sup, [{'ingredientId': esp, 'qty': 3000, 'amount': 255000}], {'status': 'unpaid'},
                  po['id'], 'İrsaliye 9', owner_id)
    stock.pay_supplier(owner, sup, 100000, 'transfer', approver_id=owner_id)
    local_ing = stock.ingredient_map()[esp]
    local_sup = next(s for s in stock.suppliers() if s['id'] == sup)
    assert (local_ing['stock'], local_ing['unitCost'], local_sup['balance']) == (4000, 83750, 155000)

    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()
    cloud_ing = client.get_doc(f'ingredients/{esp}', api.session)[1]
    cloud_sup = client.get_doc(f'suppliers/{sup}', api.session)[1]
    cloud_po = client.get_doc(f"purchaseOrders/{po['id']}", api.session)[1]
    assert (cloud_ing['stock'], cloud_ing['unitCost'], cloud_sup['balance']) == (4000, 83750, 155000)
    assert cloud_po['status'] == 'partial' and cloud_po['lines'][0]['received'] == 3000
    # Senkrondan sonra yerel görünüm aynı (çift sayım yok)
    assert stock.ingredient_map()[esp]['stock'] == 4000
    assert next(s for s in stock.suppliers() if s['id'] == sup)['balance'] == 155000


def test_vardiya_plan_internetsiz_mesai_duzeltme_bulutla_ayni(db, client):
    import requests
    import shifts
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'vardiya-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)
    api.save_modules({'staff': {'enabled': True, 'lateToleranceMinutes': 5}})
    waiter = api.create_staff('Elif Demir', 'waiter', '730591')['staffId']
    api.save_shift_plans([{'staffId': waiter, 'date': '2026-10-12', 'start': '09:00', 'end': '17:00', 'breakMinutes': 30},
                          {'staffId': waiter, 'date': '2026-10-13', 'leave': 'annual'}])
    api.publish_shift_week('2026-10-12')
    engine.run_once()
    assert shifts.enabled() and shifts.plan_for(waiter, '2026-10-12')['published']
    user = db.login_with_pin(waiter, '730591')
    owner = db.login_with_pin(owner_id, '482913')

    # ---- İnternetsiz: 09:08 giriş (geç), mola, çıkış unutuldu → gün sonunda plan bitişiyle kapanır, sonra düzeltilir
    e = shifts.clock(user, 'in', '2026-10-12T09:08:00+03:00')
    shifts.clock(user, 'breakStart', '2026-10-12T13:00:00+03:00')
    shifts.clock(user, 'breakEnd', '2026-10-12T13:40:00+03:00')
    assert shifts.auto_close_forgotten('2026-10-13T06:00:00+03:00') == 1
    fixed = shifts.edit(owner, waiter, e['clockIn'], '2026-10-12T18:00:00+03:00', 'Kapanışta kaldı', entry_id=e['id'])
    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()
    cloud = client.get_doc(f"timeEntries/{e['id']}", api.session)[1]
    assert (cloud['clockIn'], cloud['clockOut'], cloud['late'], cloud['resolved']) == \
        (fixed['clockIn'], fixed['clockOut'], 8, True)
    assert sorted(cloud['flags']) == ['edited', 'forgotClockOut'] and cloud['breaks'] == fixed['breaks']
    row = next(r for r in shifts.report('2026-10-12', '2026-10-18', today_='2026-10-16') if r['staffId'] == waiter)
    assert (row['worked'], row['breaks'], row['lateCount'], row['leave']) == (8 * 60 + 52 - 40, 40, 1, 1)
    # Ücret yalnızca yönetici okur; terminal önbelleğine inmez
    api.save_wages({waiter: 15000})
    assert api.get_wages() == {waiter: 15000}
    engine.run_once()
    assert db.cache_rows('staffWages') == []


def test_sadakat_internetsiz_uye_damga_odul_bulutla_ayni(db, client):
    import requests
    import loyalty
    import pos
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'sadakat-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)
    api.save_modules({'loyalty': {'enabled': True}})
    api.save_loyalty_settings({'stampsForReward': 5, 'rewardMaxValue': 9000})
    cat = api.save_category({'name': 'Kahve', 'station': 'bar', 'stampEligible': True})['id']
    latte = api.save_product({'categoryId': cat, 'name': 'Latte', 'price': 9500})['id']
    engine.run_once()
    user = db.login_with_pin(owner_id, '482913')
    assert loyalty.enabled() and loyalty.settings()['stampsForReward'] == 5

    # ---- İnternetsiz: kasada yeni üye, 6 latte → 1 damga kalır, ödül internet gelince
    c = loyalty.create(user, 'Ayşe K.', '0532 111 22 33', True)
    o = pos.open_order(user)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', latte), qty=6))
    o, _ = pos.send_pending(user, o['id'])
    pos.set_customer(user, o['id'], loyalty.get(c['id']))
    o = pos.take_payment(user, o['id'], 'card', 57000)
    card = loyalty.card(c['id'])
    assert (card['stamps'], card['pendingRewards']) == (1, 1)
    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()
    cloud_c = client.get_doc(f"customers/{c['id']}", api.session)[1]
    assert (cloud_c['stamps'], cloud_c['lifetimeStamps'], cloud_c['visitCount'], cloud_c['totalSpent']) == (1, 6, 1, 57000)
    card = loyalty.card(c['id'])
    assert (card['stamps'], card['pendingRewards'], len(card['rewards'])) == (1, 0, 1)

    # ---- Ödül internetsiz kullanılır; iade damgayı geri alır
    o2 = pos.open_order(user)
    pos.add_line(user, o2['id'], pos.product_line(db.menu_item('products', latte), qty=2))
    o2, _ = pos.send_pending(user, o2['id'])
    pos.set_customer(user, o2['id'], loyalty.get(c['id']))
    o2 = pos.use_reward(user, o2['id'], card['rewards'][0]['id'])
    assert o2['total'] == 10000
    o2 = pos.take_payment(user, o2['id'], 'cash', 10000)
    pos.refund(user, o['id'], 'card', 57000, 'Yanlış ürün')
    local = loyalty.card(c['id'])
    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()
    cloud_c = client.get_doc(f"customers/{c['id']}", api.session)[1]
    reward = client.get_doc(f"rewards/{card['rewards'][0]['id']}", api.session)[1]
    assert reward['status'] == 'used' and reward['usedOrderId'] == o2['id']
    assert cloud_c['stamps'] == local['stamps'] and cloud_c['lifetimeStamps'] == local['lifetimeStamps']
    assert loyalty.card(c['id'])['stamps'] == cloud_c['stamps'] and loyalty.card(c['id'])['rewards'] == []


def test_kampanya_panelden_kasada_internetsiz_bulutla_ayni(db, client):
    import requests
    import pos
    import reports
    from cloud.admin_api import AdminApi
    from cloud.pairing import pair_terminal
    from cloud.sync import SyncEngine

    requests.delete('http://127.0.0.1:8080/emulator/v1/projects/demo-nexpos/databases/(default)/documents',
                    timeout=10).raise_for_status()
    email = f'kampanya-{uuid.uuid4().hex[:6]}@kafe.test'
    owner_id = create_owner(email)
    creds, _ = pair_terminal(client, email, 'sahip-sifre-1', 'Kasa 1')
    api = AdminApi(client, client.sign_in_with_password(email, 'sahip-sifre-1'))
    engine = SyncEngine(client, creds)
    api.save_modules({'campaigns': {'enabled': True}})
    kahve = api.save_category({'name': 'Kahve', 'station': 'bar', 'stampEligible': True})['id']
    tatli = api.save_category({'name': 'Tatlı', 'station': 'kitchen'})['id']
    latte = api.save_product({'categoryId': kahve, 'name': 'Latte', 'price': 9500})['id']
    kurabiye = api.save_product({'categoryId': tatli, 'name': 'Kurabiye', 'price': 4500})['id']
    nth = api.save_campaign({'name': '2. kahve %50', 'type': 'nth', 'value': 50, 'nthQty': 2,
                             'appliesTo': {'categoryIds': [kahve]}})['id']
    api.save_campaign({'name': 'Menü', 'type': 'bundle', 'bundle': {'productIds': [latte, kurabiye], 'price': 12000}})
    engine.run_once()
    user = db.login_with_pin(owner_id, '482913')
    assert len(pos.active_campaigns()) == 2

    # ---- İnternetsiz: 3 latte + 1 kurabiye → en avantajlı birleşim kasada hesaplanır
    o = pos.open_order(user)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', latte), qty=3))
    o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', kurabiye)))
    o, _ = pos.send_pending(user, o['id'])
    assert o['campaignAmount'] == 4750 + 2000   # 2. latte %50 + menü (95 + 45 → 120)
    o = pos.take_payment(user, o['id'], 'card', o['total'])
    status = engine.run_once()
    assert status.online and db.outbox_counts() == (0, 0), db.get_failed_ops()
    cloud = client.get_doc(f"orders/{o['id']}", api.session)[1]
    assert (cloud['total'], cloud['campaignAmount'], cloud['status']) == (o['total'], o['campaignAmount'], 'paid')
    stats = client.get_doc(f"dailyStats/{o['businessDay']}", api.session)[1]
    local = reports.contribution(o)
    assert stats['campaign'] == local['campaign'] == 6750
    assert stats['byCampaign'][nth]['amount'] == local['byCampaign'][nth]['amount'] == 4750
