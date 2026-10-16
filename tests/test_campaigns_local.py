"""Kampanyalar (10b): kasada kendiliğinden uygulama, kaldırma, iskontoyla ilişki, fiş/Z, rapor, ekranlar — yerel."""
import json

import pytest

from cloud.orders import OrderError
from tests.test_local import seed

ALL_DAYS = {'days': [1, 2, 3, 4, 5, 6, 7]}


@pytest.fixture
def kmp(db):
    import pos
    db.set_sync_state('terminal_letter', 'A')
    seed(db, 'w1', 'waiter', pin='730591')
    seed(db, 'm1', 'manager', pin='583920')
    db.set_setting('modules', {'campaigns': {'enabled': True}, 'loyalty': {'enabled': True}})
    db.upsert_menu('categories', [('kahve', {'name': 'Kahve', 'station': 'bar', 'order': 0, 'stampEligible': True}),
                                  ('tatli', {'name': 'Tatlı', 'station': 'kitchen', 'order': 1})])
    db.upsert_menu('products', [('latte', {'name': 'Latte', 'categoryId': 'kahve', 'price': 9500, 'active': True}),
                                ('kurabiye', {'name': 'Kurabiye', 'categoryId': 'tatli', 'price': 4500, 'active': True})])
    db.upsert_cache('campaigns', [
        ('hh', {'name': 'Happy Hour', 'type': 'percent', 'value': 20, 'appliesTo': {'categoryIds': ['kahve']},
                'schedule': ALL_DAYS, 'audience': 'all', 'active': True}),
        ('menu', {'name': 'Öğrenci Menüsü', 'type': 'bundle', 'bundle': {'productIds': ['latte', 'kurabiye'], 'price': 11000},
                  'schedule': ALL_DAYS, 'audience': 'all', 'active': True}),
        ('ds', {'name': 'Çift Damga', 'type': 'double_stamps', 'stampMultiplier': 2, 'schedule': ALL_DAYS,
                'audience': 'members', 'active': True}),
        ('old', {'name': 'Eski', 'type': 'percent', 'value': 90, 'schedule': ALL_DAYS, 'active': True, 'deleted': True}),
        ('off', {'name': 'Kapalı', 'type': 'percent', 'value': 90, 'schedule': ALL_DAYS, 'active': False}),
    ])
    db.upsert_cache('customers', [('c1', {'name': 'Ayşe', 'phone': '5321112233', 'stamps': 0, 'lifetimeStamps': 0,
                                          'tier': 'bronze', 'marketingConsent': True})])
    user = db.login_with_pin('w1', '730591')
    db.get_connection().execute("DELETE FROM outbox").connection.commit()
    return pos, user


def _ops(db, name):
    return [json.loads(o['payload']) for o in db.get_pending_ops(200) if o['op'] == name]


def _ids(order):
    return [(c['campaignId'], c['amount']) for c in order['campaigns']]


def test_urun_eklenince_kendiliginden_uygulanir_ve_kuyruga_gider(db, kmp):
    pos, user = kmp
    o = pos.open_order(user)
    o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
    assert _ids(o) == [('hh', 1900)] and o['total'] == 7600
    # Kurabiye eklenince menü (95+45 → 110: 30 ₺) Happy Hour'dan (19 ₺) avantajlı
    o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'kurabiye')))
    assert _ids(o) == [('menu', 3000)] and o['total'] == 11000
    ops = _ops(db, 'applyCampaigns')
    assert len(ops) == 2 and ops[-1]['campaigns'][0]['lines']
    # Ürün değişince sunucu da kampanyayı siler; kasa aynı transaction'da yeniden uygular
    o = pos.update_line(user, o['id'], o['items'][0]['lineId'], note='Az köpük')
    assert _ids(o) == [('menu', 3000)] and len(_ops(db, 'applyCampaigns')) == 3
    # Değişiklik yoksa (ödeme öncesi yenileme) yeni işlem üretilmez
    pos.refresh_campaigns(user, o['id'])
    assert len(_ops(db, 'applyCampaigns')) == 3
    # Silinmiş ve pasif kampanya uygulanmaz; modül kapalıysa hiç uygulanmaz
    db.set_setting('modules', {'campaigns': {'enabled': False}})
    o2 = pos.open_order(user)
    o2 = pos.add_line(user, o2['id'], pos.product_line(db.menu_item('products', 'latte')))
    assert o2['campaigns'] == [] and o2['total'] == 9500


def test_iskonto_kampanyayi_kaldirir_kasiyer_kampanyayi_kaldirabilir(db, kmp):
    pos, user = kmp
    o = pos.open_order(user)
    o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), qty=2))
    o = pos.set_discount(user, o['id'], {'type': 'percent', 'value': 10}, 'Öğrenci', approver_id='m1')
    assert o['campaigns'] == [] and o['discountAmount'] == 1900
    o = pos.set_discount(user, o['id'], None)
    assert _ids(o) == [('hh', 3800)]
    with pytest.raises(OrderError, match='discount'):
        pos.exclude_campaign(user, o['id'], 'hh')
    o = pos.exclude_campaign(user, o['id'], 'hh', approver_id='m1')
    assert o['campaigns'] == [] and o['campaignsExcluded'] == ['hh'] and o['total'] == 19000
    assert _ops(db, 'applyCampaigns')[-1]['approvedBy'] == 'm1'
    o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
    assert o['campaigns'] == []          # kaldırılan kampanya geri gelmez


def test_uye_cift_damga_odul_ve_urun_secerek_odeme(db, kmp):
    import loyalty
    pos, user = kmp
    o = pos.open_order(user)
    o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), qty=3))
    o, _ = pos.send_pending(user, o['id'])
    o = pos.set_customer(user, o['id'], loyalty.get('c1'))
    assert [c['campaignId'] for c in o['campaigns']] == ['hh', 'ds']
    # 3 latteden 1'i ayrı ödenir: kampanya payı satırla birlikte bölünür, toplam değişmez
    total = o['total']
    o, new_id = pos.split_line(user, o['id'], o['items'][0]['lineId'], 1)
    assert o['total'] == total
    share = pos.lines_payable(o, [new_id])
    assert share == 9500 - 1900
    o = pos.take_payment(user, o['id'], 'card', share, line_ids=[new_id])
    o = pos.take_payment(user, o['id'], 'cash', o['remaining'], line_ids=[o['items'][0]['lineId']])
    assert o['status'] == 'paid' and o['paid'] == total
    card = loyalty.card('c1')
    assert card['stamps'] == 6          # 3 latte × 2 (çift damga)
    import printing
    assert 'Kampanya: Happy Hour' in printing.bill_html(o) and 'Çift Damga (2× damga)' in printing.bill_html(o)


def test_fis_z_raporu_ve_sadakat_raporu(db, kmp):
    import cash
    import printing
    import reports
    pos, user = kmp
    manager = db.login_with_pin('m1', '583920')
    cash.open_session(manager, 10000)
    o = pos.open_order(user)
    o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte'), qty=2))
    o, _ = pos.send_pending(user, o['id'])
    import loyalty
    o = pos.set_customer(user, o['id'], loyalty.get('c1'))
    text = printing.bill_html(o)
    assert 'Kampanya: Happy Hour' in text and 'Üye: Ayşe' in text
    o = pos.take_payment(manager, o['id'], 'cash', o['total'])
    rep = cash.build_report(cash.current_session())
    assert rep['campaign'] == {'amount': 3800, 'count': 1} and rep['rewards'] == {'amount': 0, 'count': 0}
    assert 'Kampanya (1 adisyon)' in printing.report_html(rep)
    day = pos.business_day()
    r = reports.Report(day, day)
    s = r.summary()
    assert s['campaign'] == 3800 and s['gross'] - s['campaign'] - s['discount'] == s['revenue']
    lo = r.loyalty()
    assert (lo['members'], lo['active'], lo['memberOrders'], lo['stamps'], lo['memberShare']) == (1, 1, 1, 4, 100)
    hh = next(c for c in lo['campaigns'] if c['campaignId'] == 'hh')
    assert (hh['orders'], hh['discount'], hh['revenue'], hh['windowRevenue']) == (1, 3800, 15200, None)
    # Saatli kampanyada aynı saatlerin önceki 4 haftayla karşılaştırması
    db.upsert_cache('campaigns', [('hh', {'name': 'Happy Hour', 'type': 'percent', 'value': 20,
                                          'appliesTo': {'categoryIds': ['kahve']}, 'active': True,
                                          'schedule': {**ALL_DAYS, 'from': '00:00', 'to': '23:59'}})])
    hh = next(c for c in reports.Report(day, day).loyalty()['campaigns'] if c['campaignId'] == 'hh')
    assert hh['windowRevenue'] == 15200 and hh['windowBefore'] == 0 and hh['windowChange'] is None


def test_ekranlar(db, kmp, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import shiboken6
    import campaign_pages as P
    import reports_screen
    pos, user = kmp
    owner = {'role': 'owner', 'cloud_id': 'm1', 'ad_soyad': 'Mert'}
    widgets = []
    o = pos.open_order(user)
    o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
    box = P.CampaignBox(user)
    widgets.append(box)
    box.set_order(o)
    assert not box.isHidden() and box.ly.count() == 1
    page = P.CampaignsPage(owner)
    widgets.append(page)
    assert page.table.rowCount() == 4 and page.table.item(0, 1).text() == 'Çift Damga'
    assert page.table.item(1, 2).text() == '%20 indirim'
    dlg = P.CampaignDialog(None)
    widgets.append(dlg)
    dlg.name.setText('Hafta sonu tatlı')
    dlg.type.setCurrentIndex(dlg.type.findData('bundle'))
    dlg.bundle_price.setText('110')
    with pytest.raises(Exception, match='iki farklı'):
        dlg.collect()
    for i in range(dlg.targets.count()):
        it = dlg.targets.item(i)
        if it.data(0x0100)[1] in ('latte', 'kurabiye'):
            it.setCheckState(P.Qt.Checked)
    data = dlg.collect()
    assert data['bundle'] == {'productIds': ['latte', 'kurabiye'], 'price': 11000}
    assert data['schedule']['days'] == [1, 2, 3, 4, 5] and data['schedule']['from'] is None
    edit = P.CampaignDialog(next(c for c in db.cache_rows('campaigns') if c['id'] == 'hh'))
    widgets.append(edit)
    assert edit.collect()['appliesTo'] == {'categoryIds': ['kahve'], 'productIds': []}
    notes = P.NotificationsPage(owner)
    widgets.append(notes)
    assert notes.reach.text() == '1 kişi'
    rp = reports_screen.ReportsPage(owner)
    rp._quiet = True
    widgets.append(rp)
    assert rp.tabs.isTabVisible(rp.TAB_LOYALTY)
    rp.tabs.setCurrentIndex(rp.TAB_LOYALTY)
    title, headers, rows = rp.export_data()
    assert headers[0] == 'Kampanya' and 'Üye' in rp.loyalty_summary.text()
    for w in widgets:
        shiboken6.delete(w)


def test_fis_pdf_tek_sayfa_ve_dogru_genislikte(db, kmp, tmp_path):
    """96 dpi dizilen belge 300 dpi PDF'e ölçeklenmeli; yoksa fiş dar dizilip sayfalara bölünüyordu."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import re
    import printing
    pos, user = kmp
    o = pos.open_order(user)
    for _ in range(6):
        pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'latte')))
        o = pos.add_line(user, o['id'], pos.product_line(db.menu_item('products', 'kurabiye')))
    for paper in ('80', '58'):
        path = printing.save_pdf(printing.bill_html(pos.get_order(o['id'])), 'fis', paper, str(tmp_path / f'{paper}.pdf'))
        data = open(path, 'rb').read()
        assert len(re.findall(rb'/Type\s*/Page[^s]', data)) == 1
