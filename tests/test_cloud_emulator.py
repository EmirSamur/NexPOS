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
