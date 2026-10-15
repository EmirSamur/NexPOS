"""Raporlar (7. ekran): yerel hesaplar — Z raporuyla tutarlılık, dönemler, personel, denetim, ana sayfa."""
import json
from datetime import date, datetime, timedelta

import pytest

from tests.test_cash_local import _order, kasa  # noqa: F401 (fixture)


@pytest.fixture
def gun(db, kasa):  # noqa: F811
    """Bir kasa oturumunda geçen dolu bir gün."""
    import reports
    cash, pos, waiter, cashier = kasa
    db.upsert_menu('optionGroups', [('sut', {'name': 'Süt', 'options': [{'id': 'oat', 'name': 'Yulaf', 'priceDelta': 1500}]})])
    session = cash.open_session(cashier, 50000)
    # 1) Masa: latte (yulaf) + su + kurabiye, %10 iskonto (müdür onayı), nakit
    o1 = pos.open_order(waiter, {'id': 't1', 'name': 'Masa 1'})
    pos.add_line(waiter, o1['id'], pos.product_line(db.menu_item('products', 'latte'),
                                                   [('sut', {'id': 'oat', 'name': 'Yulaf', 'priceDelta': 1500})]))
    pos.add_line(waiter, o1['id'], pos.product_line(db.menu_item('products', 'su')))
    pos.add_line(waiter, o1['id'], pos.product_line(db.menu_item('products', 'kurabiye')))
    o1, _ = pos.send_pending(waiter, o1['id'])
    o1 = pos.set_discount(waiter, o1['id'], {'type': 'percent', 'value': 10}, 'Sürekli müşteri', approver_id='m1')
    o1 = pos.take_payment(cashier, o1['id'], 'cash', o1['total'])
    # 2) Paket: 2 latte, biri ikram; kart + bahşiş
    o2 = _order(db, pos, waiter, None, [('latte', 2)])
    o2, free = pos.split_line(cashier, o2['id'], o2['items'][0]['lineId'], 1)
    o2 = pos.comp_line(cashier, o2['id'], free, 'Doğum günü', approver_id='m1')
    o2 = pos.take_payment(cashier, o2['id'], 'card', o2['total'], tip=1000)
    # 3) Masa 2: bir ürün iptal; yemek kartı
    o3 = _order(db, pos, waiter, 't2', [('latte', 1), ('su', 2)])
    o3 = pos.void_line(waiter, o3['id'], o3['items'][1]['lineId'], 'Yanlış sipariş', approver_id='m1')
    o3 = pos.take_payment(cashier, o3['id'], 'meal', o3['total'])
    # 4) İptal edilen adisyon, 5) açık adisyon (rapora girmez)
    o4 = _order(db, pos, waiter, None, [('kurabiye', 1)])
    pos.cancel_order(cashier, o4['id'], 'Müşteri vazgeçti', approver_id='m1')
    o5 = _order(db, pos, waiter, None, [('latte', 1)])
    # İade
    pos.refund(cashier, o1['id'], 'cash', 2000, 'Su bozuk', approver_id='m1')
    day = pos.business_day()
    return reports, cash, pos, day, session, (o1, o2, o3, o4, o5)


def test_satis_ozeti_z_raporuyla_kurusu_kurusuna_tutar(db, gun):
    reports, cash, pos, day, session, (o1, o2, o3, o4, o5) = gun
    z = cash.build_report(cash.current_session())
    s = reports.Report(day, day).summary()
    assert s['revenue'] == z['sales']['total'] == o1['total'] + o2['total'] + o3['total']
    assert s['byPayment'] == {m: z['sales'][m] for m in ('cash', 'card', 'meal')}
    assert s['refunds'] == z['refunds']['total'] == 2000 and s['net'] == s['revenue'] - 2000
    assert s['discount'] == z['discount']['amount'] and s['discountCount'] == 1
    assert s['gross'] - s['discount'] == s['revenue']
    assert s['comps'] == z['comps'] and s['voids'] == z['voids']
    assert s['tips'] == z['tips']['total'] == 1000
    assert [(v['rate'], v['gross'], v['vat']) for v in s['vat']] == [(v['rate'], v['gross'], v['vat']) for v in z['vat']]
    assert sum(v['gross'] for v in s['vat']) == s['revenue']
    assert all(v['net'] + v['vat'] == v['gross'] for v in s['vat'])
    assert (s['orders'], s['dineIn'], s['takeaway'], s['cancelled']) == (3, 2, 1, 1)
    assert s['average'] == s['revenue'] // 3
    # Bulut özetiyle aynı yapı
    assert reports.day_stats(day)['revenue'] == s['revenue']


def test_urunler_secenekler_kategoriler_satilmayanlar(db, gun):
    reports, cash, pos, day, *_ = gun
    r = reports.Report(day, day)
    products = {p['name']: p for p in r.products()}
    assert sum(p['revenue'] for p in products.values()) == r.summary()['revenue']
    assert products['Latte']['qty'] == 3 and products['Latte']['comps'] == 1
    assert products['Su']['voids'] == 2  # 2 adetlik satır iptal
    assert r.options() == [{'name': 'Yulaf', 'count': 1, 'extra': 1500}]
    assert [c['name'] for c in r.categories()] == ['Kahve']
    assert r.unsold() == []


def test_personel_ve_onaylayan(db, gun):
    reports, cash, pos, day, *_ = gun
    staff = {r['staffId']: r for r in reports.Report(day, day).staff()}
    w = staff['w1']
    assert w['orders'] == 3 and w['discount'] == 1 and w['voids'] == 2 and w['tips'] == 1000
    m = staff['m1']
    assert m['approved'] == 3  # iskonto, iptal ve ikram onayı (adisyon iptali ayrıca denetimde)
    assert reports.my_shift('w1', day)['revenue'] == w['revenue']
    assert reports.my_shift('yok', day)['orders'] == 0


def test_kayip_ve_denetim_listesi(db, gun):
    reports, cash, pos, day, *_ = gun
    events = reports.Report(day, day).losses()
    kinds = sorted(e['kind'] for e in events)
    assert kinds == ['Adisyon iptali', 'İade', 'İkram', 'İptal', 'İskonto']
    void = next(e for e in events if e['kind'] == 'İptal')
    assert void['reason'] == 'Yanlış sipariş' and void['what'] == '2× Su' and void['at']
    assert next(e for e in events if e['kind'] == 'İade')['amount'] == 2000
    # Kasa farkı da listeye girer
    cash.close_session(_cashier(db), cash.expected_cash(cash.current_session()) - 3000, 'Bozuk para')
    assert any(e['kind'] == 'Kasa farkı' and e['amount'] == -3000 for e in reports.Report(day, day).losses())


def _cashier(db):
    return db.login_with_pin('c1', '640218')


def test_is_gunu_donumu_ve_iadenin_gunu(db, gun):
    reports, cash, pos, day, session, (o1, *_) = gun
    assert reports.business_day_of('2026-10-16T02:30:00+03:00') == '2026-10-15'
    assert reports.business_day_of('2026-10-16T05:00:00+03:00') == '2026-10-16'
    assert reports.business_minutes('2026-10-16T05:30:00+03:00') == 30
    assert reports.business_minutes('2026-10-16T01:00:00+03:00') == 20 * 60
    # Ertesi gün yapılan iade o güne yazılır
    order = pos.get_order(o1['id'])
    order['refunds'][0]['at'] = (datetime.fromisoformat(order['refunds'][0]['at']) + timedelta(days=1)).isoformat()
    conn = db.get_connection()
    conn.execute("UPDATE pos_orders SET data=? WHERE id=?", (json.dumps(order), o1['id']))
    conn.commit()
    conn.close()
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    assert reports.Report(day, day).summary()['refunds'] == 0
    assert reports.Report(nxt, nxt).summary()['refunds'] == 2000


def test_donemler_ve_onceki_donem():
    import reports
    ref = date(2026, 10, 15)  # Perşembe
    assert reports.period('today', ref) == ('2026-10-15', '2026-10-15')
    assert reports.period('week', ref) == ('2026-10-12', '2026-10-15')
    assert reports.period('last_week', ref) == ('2026-10-05', '2026-10-11')
    assert reports.period('last_month', ref) == ('2026-09-01', '2026-09-30')
    assert reports.previous_period('2026-10-12', '2026-10-15') == ('2026-10-08', '2026-10-11')
    assert reports.change(110, 100) == 10 and reports.change(5, 0) is None


def test_eski_kayitlar_gelir_gider_ve_mutfak(db, gun):
    reports, cash, pos, day, *_ = gun
    conn = db.get_connection()
    conn.execute("INSERT INTO orders (masa_id,durum,toplam_tutar,tarih) VALUES (NULL,'tamamlandi',150.5,?)",
                 (f"{day} 12:00",))
    legacy_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    pid = conn.execute("SELECT id FROM products WHERE cloud_id='latte'").fetchone()[0]
    conn.execute("INSERT INTO order_items (order_id,product_id,adet,birim_fiyat,toplam) VALUES (?,?,2,75.25,150.5)",
                 (legacy_id, pid))
    conn.execute("INSERT INTO waste (product_id,zayi_nedeni,adet,maliyet_tutari,zayi_tarihi) VALUES (?,?,1,12.5,?)",
                 (pid, 'Düştü', f"{day} 10:00"))
    conn.commit()
    conn.close()
    r = reports.Report(day, day)
    s = r.summary()
    assert s['legacy'] == {'orders': 1, 'revenue': 15050}
    assert s['revenue'] < s['revenue'] + 15050  # eski kayıt ayrı satır, satış özetine karışmaz
    assert any(p['legacy'] and p['qty'] == 2 for p in r.products())
    ie = r.income_expense()
    # Kasadan 0 gider yapıldı; zayi 12,50
    assert ie['waste'] == 1250 and ie['net'] == s['net'] + 15050 and ie['remaining'] == ie['net'] - ie['expenses'] - 1250
    assert reports.Report(day, day, include_legacy=False).summary()['legacy']['orders'] == 0

    # Mutfak: fiş 12 dk'da hazır
    t = pos.tickets(('new',))[0]
    ready = (datetime.fromisoformat(t['createdAt']) + timedelta(minutes=12)).isoformat()
    db.upsert_cloud_tickets([(t['id'], {'status': 'ready', 'readyAt': ready})])
    k = r.kitchen()
    st = next(x for x in k['stations'] if x['station'] == t['station'])
    assert st['average'] == 720 and st['lateRate'] == 0


def test_ana_sayfa_gecen_haftanin_ayni_saatine_gore(db, gun):
    reports, cash, pos, day, session, orders = gun
    o1, o2, o3, o4, o5 = orders
    # Geçen haftaya iki adisyon kopyala: biri şu ana kadar, biri günün ilerisinde kapanmış
    now = datetime.now().astimezone()
    last_day = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    conn = db.get_connection()
    for i, (src, minutes) in enumerate(((o1, -60), (o2, +600))):
        copy = json.loads(json.dumps(src))
        copy['id'] = f'gecen{i}'
        copy['businessDay'] = last_day
        closed = now - timedelta(days=7) + timedelta(minutes=minutes)
        copy['closedAt'] = closed.isoformat(timespec='seconds')
        copy['refunds'] = []
        conn.execute("INSERT INTO pos_orders (id,data,status,business_day,updated_at) VALUES (?,?,?,?,?)",
                     (copy['id'], json.dumps(copy), 'paid', last_day, copy['closedAt']))
    conn.commit()
    conn.close()
    d = reports.dashboard(now.isoformat(timespec='seconds'))
    today_rev = o1['total'] + o2['total'] + o3['total']
    assert d['revenue'] == today_rev and d['orders'] == 3
    # Saat 10 saat sonra kapanan geçen hafta adisyonu karşılaştırmaya girmez (gün içi saat sınırı
    # iş günü dönümünü aşıyorsa ikisi de girer; testin anlamlı olması için kontrol)
    in_window = reports.business_minutes((now + timedelta(minutes=600)).isoformat()) <= reports.business_minutes(now.isoformat())
    expected_last = o1['total'] + (o2['total'] if in_window else 0)
    assert d['revenueChange'] == reports.change(today_rev, expected_last)
    assert d['top'][0] == {'name': 'Latte', 'qty': 3}
    assert d['openAmount'] == o5['total'] and d['expectedCash'] == cash.expected_cash(session)
    kinds = {a['target'] for a in d['alerts']}
    assert 'losses' in kinds
    assert sum(d['hourly'].values()) == today_rev


def test_katki_hesabi_sunucuyla_ayni():
    """Ortak adisyon senaryolarındaki her adisyonun katkısı Python ve JS'de aynı (dailyStats ↔ raporlar)."""
    import os
    import shutil
    import subprocess

    import reports
    from tests.test_orders_logic import CASES, run
    if not shutil.which('node'):
        pytest.skip('node yok')
    orders, refunds = [], []
    for case in CASES:
        if case.get('expectError'):
            continue
        for o in run(case['steps']).values():
            orders.append(o)
            refunds += o.get('refunds') or []
    stats_js = os.path.join(os.path.dirname(__file__), '..', 'firebase', 'functions', 'src', 'stats.js')
    script = (f"const s=require({json.dumps(os.path.abspath(stats_js))});"
              "const d=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "console.log(JSON.stringify({c:d.orders.map(s.contribution),r:d.refunds.map(s.refundContribution),"
              "day:s.businessDayOf('2026-10-16T02:30:00+03:00')}))")
    out = subprocess.run(['node', '-e', script], input=json.dumps({'orders': orders, 'refunds': refunds}),
                         capture_output=True, text=True, check=True).stdout
    js = json.loads(out)
    assert len(orders) > 15 and any(o['status'] == 'paid' for o in orders) and refunds
    assert js['c'] == [json.loads(json.dumps(reports.contribution(o))) for o in orders]
    assert js['r'] == [reports.refund_contribution(r) for r in refunds]
    assert js['day'] == reports.business_day_of('2026-10-16T02:30:00+03:00')


def test_ekranlar_aciliyor_ve_disa_aktariyor(db, gun, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import reports_screen
    reports, cash, pos, day, *_ = gun
    user = {'role': 'owner', 'cloud_id': 'm1'}
    dash = reports_screen.DashboardPage(user)
    assert dash.t_orders.value.text() == '3'
    page = reports_screen.ReportsPage(user)
    page._quiet = True
    assert page.period() == (day, day)
    assert page.product_table.rowCount() == 3 and page.loss_table.rowCount() == 5
    for tab in range(page.tabs.count()):
        page.tabs.setCurrentIndex(tab)
        title, headers, rows = page.export_data()
        assert headers and title
    page.tabs.setCurrentIndex(page.TAB_SUMMARY)
    path = page.export_csv(str(tmp_path / 'ozet.csv'))
    text = open(path, encoding='utf-8-sig').read()
    assert 'Net satış' in text and ';' in text
    page.tabs.setCurrentIndex(page.TAB_PRODUCTS)
    pdf = page.export_pdf(str(tmp_path / 'urunler.pdf'))
    assert open(pdf, 'rb').read(4) == b'%PDF'
    # Garson Kayıp ve Denetim sekmesini görmez
    waiter_page = reports_screen.ReportsPage({'role': 'waiter', 'cloud_id': 'w1'})
    assert not waiter_page.tabs.isTabVisible(waiter_page.TAB_LOSSES)
    # Qt nesneleri uygulamadan önce silinsin (süreç kapanırken takılmasın)
    import shiboken6
    dash.timer.stop()
    for w in (dash, page, waiter_page):
        shiboken6.delete(w)
