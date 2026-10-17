"""Müşteri ve sadakat (10. ekran): kasada üyelik, tanıma, ödül, kapanış defteri, iade, düzeltme — yerel."""
import json

import pytest

from cloud.orders import OrderError
from tests.test_local import seed


@pytest.fixture
def sad(db):
    import loyalty
    import pos
    db.set_sync_state('terminal_letter', 'A')
    seed(db, 'w1', 'waiter', pin='730591')
    seed(db, 'm1', 'manager', pin='583920')
    db.set_setting('modules', {'loyalty': {'enabled': True}})
    db.upsert_menu('categories', [('kahve', {'name': 'Kahve', 'station': 'bar', 'order': 0, 'stampEligible': True}),
                                  ('tatli', {'name': 'Tatlı', 'station': 'kitchen', 'order': 1})])
    db.upsert_menu('products', [('latte', {'name': 'Latte', 'categoryId': 'kahve', 'price': 9500, 'active': True}),
                                ('mocha', {'name': 'Mocha', 'categoryId': 'kahve', 'price': 11000, 'active': True}),
                                ('kek', {'name': 'Kek', 'categoryId': 'tatli', 'price': 7000, 'active': True})])
    db.upsert_cache('customers', [
        ('c1', {'name': 'Ayşe K.', 'phone': '5321112233', 'stamps': 8, 'lifetimeStamps': 48, 'tier': 'bronze',
                'birthDate': '10-17', 'marketingConsent': True, 'lastVisitAt': '2026-10-10T12:00:00+03:00'}),
        ('c2', {'name': 'Mehmet T.', 'phone': '5051234512', 'stamps': 2, 'lifetimeStamps': 160, 'tier': 'gold',
                'marketingConsent': False, 'lastVisitAt': '2026-08-01T12:00:00+03:00'}),
        ('cdup', {'aliasOf': 'c1', 'deleted': True}),
        ('cdel', {'name': 'Silinmiş müşteri', 'phone': None, 'deleted': True}),
    ])
    db.upsert_cache('rewards', [
        ('r1', {'customerId': 'c1', 'status': 'active', 'type': 'free_drink', 'expiresAt': '2099-01-01'}),
        ('r2', {'customerId': 'c1', 'status': 'active', 'type': 'birthday', 'expiresAt': '2000-01-01'}),
        ('r3', {'customerId': 'c1', 'status': 'used', 'type': 'free_drink', 'expiresAt': '2099-01-01'}),
    ])
    user = db.login_with_pin('w1', '730591')
    db.get_connection().execute("DELETE FROM outbox").connection.commit()
    return loyalty, pos, user


def _ops(db, name):
    return [json.loads(o['payload']) for o in db.get_pending_ops(100) if o['op'] == name]


def test_modul_varsayilan_kapali(db):
    import loyalty
    assert not loyalty.enabled() and loyalty.settings()['stampsForReward'] == 10


def test_uyeler_arama_ve_kasada_yeni_uye(db, sad):
    loyalty, pos, user = sad
    assert [c['id'] for c in loyalty.customers()] == ['c1', 'c2']
    assert loyalty.find_by_phone('0532 111 22 33')['id'] == 'c1'
    assert [c['id'] for c in loyalty.search('2233')] == ['c1']
    assert [c['id'] for c in loyalty.search('mehm')] == ['c2']
    assert loyalty.get('cdup')['id'] == 'c1' and loyalty.get('cdel') is None
    with pytest.raises(OrderError, match='zaten kayıtlı: Ayşe'):
        loyalty.create(user, 'Ayşe', '+90 532 111 2233', True)
    with pytest.raises(OrderError, match='Telefon'):
        loyalty.create(user, 'X', '123', False)
    with pytest.raises(OrderError, match='izni'):
        loyalty.create(user, 'X', '05441234567', None)
    c = loyalty.create(user, 'Zeynep A.', '0544 123 45 67', False, '03-08')
    assert loyalty.find_by_phone('5441234567')['id'] == c['id']
    op = _ops(db, 'customerCreate')[0]
    assert op == {'customerId': c['id'], 'name': 'Zeynep A.', 'phone': '5441234567', 'marketingConsent': False,
                  'birthDate': '03-08'}


def test_kart_odul_secimi_ve_kapanis_defteri(db, sad):
    loyalty, pos, user = sad
    card = loyalty.card('c1')
    assert (card['stamps'], card['tierName'], [r['id'] for r in card['rewards']]) == (8, 'Bronz', ['r1'])
    assert card['maskedPhone'] == '0532 *** ** 33'
    assert '●●●●●●●●○○ 8/10' in loyalty.summary(card)
    o = pos.open_order(user)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), qty=2))
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'mocha')))
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'kek')))
    o, _ = pos.send_pending(user, o['id'])
    with pytest.raises(OrderError, match='müşteri'):
        pos.use_reward(user, o['id'], 'r1')
    o = pos.set_customer(user, o['id'], loyalty.get('c1'))
    # En pahalı uygun içecek (mocha 110 ₺) ama üst sınır 90 ₺
    o = pos.use_reward(user, o['id'], 'r1')
    mocha = next(l for l in o['items'] if l['productId'] == 'mocha')
    assert o['rewards'][0]['lineId'] == mocha['lineId'] and o['rewardAmount'] == 9000
    assert loyalty.card('c1')['rewards'] == []          # açık adisyonda seçildi, başkası kullanamaz
    o = pos.take_payment(user, o['id'], 'card', o['total'])
    assert o['status'] == 'paid'
    card = loyalty.card('c1')
    # 2 latte damga verir (ödüllü mocha vermez): 8 + 2 → kart doldu, ödül internet gelince
    assert (card['stamps'], card['pendingRewards'], card['rewards']) == (0, 1, [])
    assert 'internet gelince' in loyalty.summary(card)
    # İşlem buluta gidince defter sayılmaz (bulut kaydı güncellenmiş olur)
    db.complete_ops([o['op_id'] for o in db.get_pending_ops(100)])
    assert loyalty.card('c1')['stamps'] == 8 and [r['id'] for r in loyalty.card('c1')['rewards']] == ['r1']


def test_iade_damgayi_geri_alir_ve_musteri_degisince_odul_duser(db, sad):
    loyalty, pos, user = sad
    o = pos.open_order(user)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), qty=4))
    o, _ = pos.send_pending(user, o['id'])
    o = pos.set_customer(user, o['id'], loyalty.get('c2'))
    o = pos.take_payment(user, o['id'], 'card', o['total'])
    assert loyalty.card('c2')['stamps'] == 6
    manager = db.login_with_pin('m1', '583920')
    pos.refund(manager, o['id'], 'card', o['total'] // 2, 'Soğuktu')
    assert loyalty.card('c2')['stamps'] == 4
    pos.refund(manager, o['id'], 'card', o['total'] // 2, 'Hepsi')
    assert loyalty.card('c2')['stamps'] == 2
    # Ödül seçilmiş adisyonda müşteri değişirse ödül düşer
    o2 = pos.open_order(user)
    pos.add_line(user, o2['id'], pos.product_line(db.menu_item('products', 'latte')))
    o2, _ = pos.send_pending(user, o2['id'])
    pos.set_customer(user, o2['id'], loyalty.get('c1'))
    o2 = pos.use_reward(user, o2['id'], 'r1')
    o2 = pos.set_customer(user, o2['id'], loyalty.get('c2'))
    assert o2['rewards'] == [] and o2['customer']['id'] == 'c2'


def test_elle_duzeltme_yetki_ve_filtreler(db, sad):
    loyalty, pos, user = sad
    with pytest.raises(OrderError, match='loyalty'):
        loyalty.adjust(user, 'c1', 2, 'Kart kayboldu')
    with pytest.raises(OrderError, match='Gerekçe'):
        loyalty.adjust(user, 'c1', 2, ' ', approver_id='m1')
    loyalty.adjust(user, 'c1', 3, 'Kart kayboldu', grant_reward=True, approver_id='m1')
    card = loyalty.card('c1')
    assert (card['stamps'], card['pendingRewards']) == (1, 2)   # 8+3 → 1 ödül + verilen 1
    assert _ops(db, 'loyaltyAdjust')[0]['approvedBy'] == 'm1'
    assert [c['id'] for c in loyalty.filtered('inactive30', today='2026-10-16')] == ['c2']
    assert [c['id'] for c in loyalty.filtered('birthday', today='2026-10-16')] == ['c1']
    assert [c['id'] for c in loyalty.filtered('consent')] == ['c1']
    assert [c['id'] for c in loyalty.filtered('gold')] == ['c2']
    assert loyalty.days_since('2026-10-10T12:00:00+03:00', '2026-10-16') == 6


def test_ekranlar_kasa_cubugu_secici_panel(db, sad, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import shiboken6
    import loyalty_pages as P
    from modules_page import ModulesPanel
    loyalty, pos, user = sad
    widgets = []
    owner = {'role': 'owner', 'cloud_id': 'm1', 'ad_soyad': 'Mert'}
    mp = ModulesPanel(owner)
    widgets.append(mp)
    assert mp.data()['loyalty'] == {'enabled': True} and mp.data()['campaigns'] == {'enabled': False}
    # Kasa çubuğu: müşteri yok → ekle; ödül kullan
    o = pos.open_order(user)
    pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
    o, _ = pos.send_pending(user, o['id'])
    bar = P.CustomerBar(user)
    widgets.append(bar)
    bar.set_order(o)
    assert 'Müşteri yok' in bar.label.text() and bar.reward_btn.isHidden()
    got = []
    bar.changed.connect(got.append)
    bar._run(pos.set_customer, user, o['id'], loyalty.get('c1'))
    bar.set_order(got[-1])
    assert 'Ayşe K.' in bar.label.text() and not bar.reward_btn.isHidden()
    bar._use_reward()
    bar.set_order(got[-1])
    assert got[-1]['rewardAmount'] == 9000 and bar.rewards_box.count() == 1
    # Seçici: arama, yeni üye (izin sorulmadan olmaz)
    dlg = P.CustomerPickerDialog(user)
    widgets.append(dlg)
    dlg.query.setText('2233')
    assert dlg.results.count() == 1
    dlg.query.setText('0544 765 43 21')
    assert dlg.phone.text() == '0544 765 43 21' and 'Yeni üye' in dlg.error.text()
    dlg.name.setText('Can B.')
    dlg._create()
    assert 'izni' in dlg.error.text()
    dlg.consent.no.setChecked(True)
    dlg._create()
    assert dlg.customer['name'] == 'Can B.' and loyalty.find_by_phone('05447654321')
    # Panel: liste, filtre, ayarlar, detay
    page = P.MarketingPage(owner)
    widgets.append(page)
    cp = page.customers
    assert cp.table.rowCount() == 3
    cp.filter.setCurrentIndex([k for k, _ in loyalty.FILTERS].index('gold'))
    assert cp.table.rowCount() == 1 and cp.table.item(0, 0).text() == 'Mehmet T.'
    st = page.settings
    assert st.stamps.value() == 10 and st.data()['rewardMaxValue'] == 9000
    assert st.data()['tiers'][1] == {'name': 'Gümüş', 'minStamps': 50, 'perks': ''}
    detail = P.CustomerDetailDialog({'customer': {'name': 'Ayşe', 'phone': '5321112233', 'stamps': 3, 'tier': 'silver'},
                                     'orders': [{'businessDay': '2026-10-16', 'no': 'A1', 'total': 19000,
                                                 'items': [{'name': 'Latte', 'qty': 2}]}],
                                     'events': [{'type': 'stamp', 'amount': 2, 'at': '2026-10-16T12:00:00'}],
                                     'rewards': [{'type': 'birthday', 'status': 'active', 'expiresAt': '2026-12-15'}]})
    widgets.append(detail)
    html = detail.html()
    assert 'Latte (2)' in html and 'Doğum günü' in html and 'Gümüş' in html
    path = detail._save(str(tmp_path / 'ayse.json'))
    assert json.load(open(path, encoding='utf-8'))['customer']['phone'] == '5321112233'
    for w in widgets:
        shiboken6.delete(w)


def test_mobil_uygulama_ayarlari_ve_modul(db, sad):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import shiboken6
    import loyalty_pages as P
    from modules_page import ModulesPanel
    owner = {'role': 'owner', 'cloud_id': 'm1'}
    db.set_setting('general', {'cafeName': 'Velvet Kafe'})
    db.set_setting('app', {'address': 'Moda Cad. 12', 'hours': 'Her gün 08–24'})
    panel = P.AppSettingsPanel(owner)
    assert panel.cafe.text() == 'Velvet Kafe' and panel.hours.text() == 'Her gün 08–24'
    panel.phone.setText('0216 000 00 00')
    panel._template()
    text = panel.kvkk.toPlainText()
    assert text.startswith('Velvet Kafe — Kişisel') and 'Moda Cad. 12' in text and '0216 000 00 00' in text
    assert panel.data()['kvkkText'] == text.strip()
    manager = P.AppSettingsPanel({'role': 'manager', 'cloud_id': 'm1'})
    assert not manager.save_btn.isEnabled()
    mp = ModulesPanel(owner)
    assert mp.data()['app'] == {'enabled': False, 'tableOrders': False, 'pickup': False}
    assert not mp.table_orders.isEnabled()   # 11b'de açılır
    for w in (panel, manager, mp):
        shiboken6.delete(w)
