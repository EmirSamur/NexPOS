"""Vardiya ve mesai (9. ekran): giriş/çıkış/mola, geç kalma, unutulan çıkış, düzeltme, rapor — yerel."""
import json

import pytest

from cloud.orders import OrderError
from tests.test_local import seed

TZ = '+03:00'


def at(day, hhmm):
    return f"{day}T{hhmm}:00{TZ}"


@pytest.fixture
def sh(db):
    import shifts
    seed(db, 'w1', 'waiter', pin='730591')
    seed(db, 'w2', 'waiter', pin='730592')
    seed(db, 'm1', 'manager', pin='583920')
    db.set_setting('modules', {'staff': {'enabled': True, 'lateToleranceMinutes': 5}})
    db.upsert_cache('shiftPlans', [
        ('w1_2026-10-12', {'staffId': 'w1', 'date': '2026-10-12', 'start': '09:00', 'end': '17:00',
                           'breakMinutes': 30, 'published': True}),
        ('w1_2026-10-13', {'staffId': 'w1', 'date': '2026-10-13', 'start': '16:00', 'end': '01:00',
                           'breakMinutes': 0, 'published': True}),
        ('w1_2026-10-14', {'staffId': 'w1', 'date': '2026-10-14', 'leave': 'annual', 'published': True}),
        ('w2_2026-10-12', {'staffId': 'w2', 'date': '2026-10-12', 'start': '08:00', 'end': '16:00',
                           'breakMinutes': 0, 'published': False}),
        ('w2_2026-10-13', {'staffId': 'w2', 'date': '2026-10-13', 'start': '08:00', 'end': '16:00',
                           'deleted': True}),
    ])
    w1 = db.login_with_pin('w1', '730591')
    w2 = db.login_with_pin('w2', '730592')
    db.get_connection().execute("DELETE FROM outbox").connection.commit()
    return shifts, w1, w2


def _ops(db, name):
    return [json.loads(o['payload']) for o in db.get_pending_ops(100) if o['op'] == name]


def test_modul_varsayilan_kapali(db):
    import shifts
    assert not shifts.enabled() and shifts.tolerance() == 5


def test_plan_okuma_ve_etiketler(db, sh):
    shifts, w1, w2 = sh
    assert shifts.week_start('2026-10-15') == '2026-10-12'
    assert shifts.week_days('2026-10-12')[-1] == '2026-10-18'
    p = shifts.plans('2026-10-12', '2026-10-18')
    assert ('w2', '2026-10-13') not in p and len(p) == 4
    assert set(shifts.plans('2026-10-12', '2026-10-18', published_only=True)) == \
        {('w1', '2026-10-12'), ('w1', '2026-10-13'), ('w1', '2026-10-14')}
    assert shifts.plan_label(p[('w1', '2026-10-12')]) == '09:00–17:00'
    assert shifts.plan_label(p[('w1', '2026-10-14')]) == 'Yıllık izin'
    assert shifts.plan_label(None) == ''


def test_giris_mola_cikis_internetsiz_ve_kuyruk(db, sh):
    shifts, w1, w2 = sh
    assert shifts.status('w1') == ('off', None)
    e = shifts.clock(w1, 'in', at('2026-10-12', '09:07'))
    assert e['late'] == 7 and e['businessDay'] == '2026-10-12'
    with pytest.raises(OrderError):
        shifts.clock(w1, 'in', at('2026-10-12', '09:10'))
    with pytest.raises(OrderError):
        shifts.clock(w1, 'breakEnd', at('2026-10-12', '12:00'))
    shifts.clock(w1, 'breakStart', at('2026-10-12', '12:00'))
    assert shifts.status('w1')[0] == 'break'
    shifts.clock(w1, 'breakEnd', at('2026-10-12', '12:20'))
    assert shifts.status('w1')[0] == 'working'
    e = shifts.clock(w1, 'out', at('2026-10-12', '17:07'))
    assert shifts.status('w1') == ('off', None)
    import shifts_logic as L
    assert L.break_minutes(e, shifts.plan_for('w1', '2026-10-12')) == 20
    assert L.worked_minutes(e, shifts.plan_for('w1', '2026-10-12')) == 8 * 60 - 20
    ops = _ops(db, 'timeClock')
    assert [o['action'] for o in ops] == ['in', 'breakStart', 'breakEnd', 'out']
    assert {o['entryId'] for o in ops} == {e['id']}
    with pytest.raises(OrderError):
        shifts.clock(w1, 'out')
    # tolerans içinde geç sayılmaz
    e2 = shifts.clock(w2, 'in', at('2026-10-12', '08:05'))
    assert e2['late'] == 0


def test_cikis_unutulursa_gun_sonunda_plan_bitisiyle_kapanir(db, sh):
    shifts, w1, w2 = sh
    shifts.clock(w1, 'in', at('2026-10-13', '16:00'))     # gece 01:00'e kadar planlı
    shifts.clock(w1, 'breakStart', at('2026-10-13', '20:00'))  # mola açık kaldı
    shifts.clock(w2, 'in', at('2026-10-12', '08:00'))
    # aynı iş günü içinde (gece 02:00) kapatılmaz
    assert shifts.auto_close_forgotten(at('2026-10-14', '02:00')) == 1   # yalnızca w2 (12'si)
    assert shifts.auto_close_forgotten(at('2026-10-14', '06:00')) == 1
    e = shifts.entries('2026-10-13', '2026-10-13', 'w1')[0]
    assert e['clockOut'][:16] == '2026-10-14T01:00' and e['breaks'][-1]['end'] == e['clockOut']
    assert 'forgotClockOut' in e['flags']
    e2 = shifts.entries('2026-10-12', '2026-10-12', 'w2')[0]
    assert e2['clockOut'][:16] == '2026-10-12T16:00'
    assert {x['id'] for x in shifts.to_fix()} == {e['id'], e2['id']}
    assert all(o.get('auto') for o in _ops(db, 'timeClock') if o['action'] == 'out')
    assert shifts.auto_close_forgotten(at('2026-10-15', '06:00')) == 0
    # Kapatılmamış dünkü mesai, ertesi gün girişte önce kendiliğinden kapanır
    shifts.clock(w1, 'in', at('2026-10-15', '09:00'))
    e3 = shifts.clock(w1, 'in', at('2026-10-16', '09:00'))
    assert e3['businessDay'] == '2026-10-16' and 'forgotClockOut' in shifts.entries('2026-10-15', '2026-10-15')[0]['flags']


def test_plansiz_unutulan_cikis_son_islem_saatiyle(db, sh):
    shifts, w1, w2 = sh
    shifts.clock(w1, 'in', at('2026-10-16', '10:00'))
    order = {'id': 'o1', 'items': [{'addedBy': 'w1', 'addedAt': at('2026-10-16', '14:30')}],
             'payments': [{'by': 'w1', 'at': at('2026-10-16', '15:10')}, {'by': 'x', 'at': at('2026-10-16', '23:00')}]}
    conn = db.get_connection()
    conn.execute("INSERT INTO pos_orders (id,data,status,business_day) VALUES (?,?,?,?)",
                 ('o1', json.dumps(order), 'paid', '2026-10-16'))
    conn.commit()
    conn.close()
    shifts.auto_close_forgotten(at('2026-10-17', '07:00'))
    assert shifts.entries('2026-10-16', '2026-10-16', 'w1')[0]['clockOut'][:16] == '2026-10-16T15:10'


def test_duzeltme_yetki_ve_gerekce(db, sh):
    shifts, w1, w2 = sh
    shifts.clock(w1, 'in', at('2026-10-12', '09:00'))
    shifts.auto_close_forgotten(at('2026-10-13', '06:00'))
    e = shifts.to_fix()[0]
    with pytest.raises(OrderError):
        shifts.edit(w1, 'w1', e['clockIn'], at('2026-10-12', '18:00'), 'unuttum', entry_id=e['id'])
    with pytest.raises(OrderError):
        shifts.edit(w1, 'w1', e['clockIn'], at('2026-10-12', '18:00'), '  ', approver_id='m1', entry_id=e['id'])
    with pytest.raises(OrderError):
        shifts.edit(w1, 'w1', e['clockIn'], at('2026-10-12', '08:00'), 'ters', approver_id='m1', entry_id=e['id'])
    e = shifts.edit(w1, 'w1', e['clockIn'], at('2026-10-12', '18:00'), 'Kapanışta kaldı', approver_id='m1',
                    entry_id=e['id'])
    assert e['resolved'] and 'edited' in e['flags'] and e['editedBy'] == 'm1'
    assert shifts.to_fix() == []
    op = _ops(db, 'timeEdit')[0]
    assert op['approvedBy'] == 'm1' and op['reason'] == 'Kapanışta kaldı' and op['clockOut'][:16] == '2026-10-12T18:00'
    # Kayıt hiç yoksa yeni açılır (gelmiş ama giriş yapmamış)
    m1 = db.login_with_pin('m1', '583920')
    n = shifts.edit(m1, 'w2', at('2026-10-12', '08:30'), at('2026-10-12', '16:00'), 'Giriş yapmayı unuttu')
    assert n['late'] == 30 and shifts.entries('2026-10-12', '2026-10-12', 'w2')[0]['id'] == n['id']


def test_rapor_plan_calisilan_fazla_mesai_gelmedi(db, sh, monkeypatch):
    shifts, w1, w2 = sh
    import reports
    monkeypatch.setattr(reports.Report, 'staff',
                        lambda self: [{'staffId': 'w1', 'revenue': 400000}, {'staffId': 'zz', 'revenue': 1}])
    shifts.clock(w1, 'in', at('2026-10-12', '09:20'))
    shifts.clock(w1, 'out', at('2026-10-12', '17:00'))      # 460 brüt − 30 plan molası = 430
    shifts.clock(w1, 'in', at('2026-10-13', '15:55'))
    shifts.clock(w1, 'out', at('2026-10-14', '01:05'))      # 550
    rows = {r['staffId']: r for r in shifts.report('2026-10-12', '2026-10-18', today_='2026-10-16')}
    r = rows['w1']
    assert r['planned'] == 450 + 540 and r['worked'] == 430 + 550 and r['breaks'] == 30
    assert (r['lateCount'], r['lateMinutes'], r['leave'], r['absent'], r['days']) == (1, 20, 1, 0, 2)
    assert r['overtime'] == 0 and r['revenue'] == 400000 and r['revenuePerHour'] == 400000 * 60 // 980
    assert rows['w2']['absent'] == 1 and rows['w2']['worked'] == 0
    costs, total = shifts.labor_cost(list(rows.values()), {'w1': 12000})
    assert costs['w1'] == 980 * 12000 // 60 and total == costs['w1']
    d = shifts.detail('w1', '2026-10-12', '2026-10-18')
    assert [x['day'] for x in d] == ['2026-10-12', '2026-10-13', '2026-10-14']
    assert d[0]['late'] == 20 and d[2]['entry'] is None and d[2]['plan']['leave'] == 'annual'


def test_haftalik_45_saati_asan_fazla_mesai(db, sh):
    shifts, w1, w2 = sh
    for i in range(6):                                      # 6 gün × 9 saat (plansız) = 54 sa
        day = f'2026-10-{12 + i:02d}'
        shifts.clock(w2, 'in', at(day, '08:00'))
        shifts.clock(w2, 'out', at(day, '17:00'))
    r = [x for x in shifts.report('2026-10-12', '2026-10-18', today_='2026-10-19') if x['staffId'] == 'w2'][0]
    assert r['worked'] == 54 * 60 and r['overtime'] == 9 * 60


def test_whatsapp_metni(db, sh):
    shifts, w1, w2 = sh
    text = shifts.week_text('2026-10-12')
    assert text.startswith('📅 Vardiya planı 12.10 – 18.10')
    assert '*Kişi w1*' in text and 'Pzt 09:00–17:00' in text and 'Sal 16:00–01:00' in text and 'Paz —' in text


def test_ekranlar_plan_mesai_vardiyam(db, sh, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import shiboken6
    import shifts_pages as P
    from auth_widgets import StaffCard
    from modules_page import ModulesPanel
    shifts, w1, w2 = sh
    owner = {'role': 'owner', 'cloud_id': 'm1', 'ad_soyad': 'Kişi m1'}
    widgets = []
    # Modüller: personel bölümü kaydedilen veriye girer
    mp = ModulesPanel(owner)
    widgets.append(mp)
    assert mp.data()['staff'] == {'enabled': True, 'lateToleranceMinutes': 5}
    # Plan: hücre, şablon boyama, 45 saat uyarısı, günlük kişi, kopyalama, kaydedilecek hücreler
    page = P.PlanPage(owner)
    widgets.append(page)
    page.week = '2026-10-12'
    page.refresh()
    ids = [s['id'] for s in page.staff]
    r1 = ids.index('w1')
    assert page.table.item(r1, 1).text() == '09–17' and page.table.item(r1, 2).text() == '16–01'
    assert page.table.item(r1, 3).text() == 'Yıllık izin'
    assert page.daily_counts()[:3] == [2, 1, 0]
    assert not page.save_btn.isEnabled()
    page.tpl_buttons[1].setChecked(True)                    # Akşam 16–24
    for col in range(1, 8):
        page._cell_clicked(ids.index('w2'), col)
    assert page.table.item(ids.index('w2'), 4).text() == '16–24'
    assert page.week_totals()['w2'] == 7 * 450
    assert '⚠' in page.table.item(ids.index('w2'), 8).text()
    page.tpl_buttons[4].setChecked(True)                    # Temizle
    page._cell_clicked(ids.index('w2'), 7)                  # kayıtlı değildi: değişiklik sayılmaz
    page._cell_clicked(r1, 1)                               # kayıtlıydı: silinecek
    page.tpl_buttons[4].setChecked(False)
    assert page.paint is None
    cells = page.pending_cells()
    assert len(cells) == 7 and cells[0] == {'staffId': 'w1', 'date': '2026-10-12', 'clear': True}
    assert cells[1] == {'staffId': 'w2', 'date': '2026-10-12', 'start': '16:00', 'end': '00:00', 'breakMinutes': 30}
    assert page.save_btn.isEnabled() and not page.publish_btn.isEnabled()
    page._revert()
    page.week = '2026-10-19'
    page.refresh()
    assert page.copy_last_week() == 4 and page.cell('w1', '2026-10-20')['end'] == '01:00'
    assert page.export_pdf(str(tmp_path / 'plan.pdf')) and open(tmp_path / 'plan.pdf', 'rb').read(4) == b'%PDF'
    page.changes = {}
    # Mesai: rapor, düzeltilecekler, ücretsiz işçilik sütunu gizli; CSV
    shifts.clock(w1, 'in', at('2026-10-12', '09:00'))
    ts = P.TimesheetPage(owner)
    widgets.append(ts)
    ts.range = ('2026-10-12', '2026-10-18')
    ts.refresh()
    assert ts.fix_table.rowCount() == 1 and ts.table.isColumnHidden(len(P.COLUMNS) - 1)
    ts.wages = {'w1': 15000}
    ts.refresh()
    assert not ts.table.isColumnHidden(len(P.COLUMNS) - 1) and 'İşçilik' in ts.labor.text()
    assert open(ts.export_csv(str(tmp_path / 'mesai.csv')), encoding='utf-8-sig').read().startswith('Personel;Plan')
    d = P.DetailDialog(ts, 'w1', 'Kişi w1', '2026-10-12', '2026-10-18')
    widgets.append(d)
    assert d.table.rowCount() == 3 and 'çıkış unutuldu' in d.table.item(0, 7).text()
    dlg = P.EditEntryDialog('w1', shifts.to_fix()[0])
    widgets.append(dlg)
    dlg.cout.setTime(dlg.cout.time().fromString('01:30', 'HH:mm'))
    dlg.reason_edit.setText('Kapanış')
    dlg._ok()
    assert dlg.clock_out[:16] == '2026-10-13T01:30' and dlg.clock_in[:16] == '2026-10-12T09:00'
    # Vardiyam ve giriş kartı
    sd = P.ShiftDialog(w2)
    widgets.append(sd)
    assert not sd.buttons['in'].isHidden() and sd.buttons['out'].isHidden()
    sd._clock('in')
    assert sd.buttons['in'].isHidden() and not sd.buttons['breakStart'].isHidden()
    assert P.clock_badge('w2').startswith('🟢 Mesaide')
    card = StaffCard(db.get_staff('w2'), 'Garson', badge=P.clock_badge('w2'))
    widgets.append(card)
    assert card.height() == 180
    db.set_setting('modules', {'staff': {'enabled': False}})
    assert P.clock_badge('w2') == ''
    for w in widgets:
        shiboken6.delete(w)
