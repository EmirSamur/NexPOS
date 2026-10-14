"""Salon planı: önbellek, eski tablolara yansıtma, rezerve, QR çıktısı, editör davranışı."""
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def area(name='Salon', order=0, **kw):
    return {'name': name, 'order': order, 'fixtures': [], 'layoutVersion': 1, 'deleted': False,
            'updatedAt': '2026-10-14T10:00:00Z', **kw}


def table(name, area_id, **kw):
    return {'name': name, 'areaId': area_id, 'shape': 'square', 'capacity': 4, 'x': 60, 'y': 60, 'w': 120,
            'h': 120, 'rotation': 0, 'qrToken': 'tok' + name[-1], 'deleted': False,
            'updatedAt': '2026-10-14T10:00:00Z', **kw}


def legacy_tables(db):
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM tables WHERE COALESCE(silindi,0)=0 ORDER BY ad").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def test_eski_menu_cache_tablosu_yeniden_adlandirilir(db):
    conn = db.get_connection()
    conn.execute("ALTER TABLE cloud_cache RENAME TO menu_cache")
    conn.execute("INSERT INTO menu_cache VALUES ('products','p1','{\"name\":\"Latte\"}')")
    conn.commit()
    conn.close()
    db.init_database()
    assert db.menu_item('products', 'p1')['name'] == 'Latte'


def test_bulut_plani_eski_tablolara_yansir_ve_eski_duzeni_gizler(db):
    db.upsert_floor('areas', [('a1', area())])
    db.upsert_floor('tables', [('t1', table('M1', 'a1')), ('t2', table('M2', 'a1'))])
    assert [r['ad'] for r in db.get_all_regions()] == ['Salon']
    rid = db.get_all_regions()[0]['id']
    assert [t['ad'] for t in db.get_tables_by_region(rid)] == ['M1', 'M2']
    assert {t['ad'] for t in legacy_tables(db)} == {'M1', 'M2'}  # 24 demo masa gizlendi


def test_masa_bolgeden_once_gelse_de_baglanir(db):
    db.upsert_floor('tables', [('t1', table('M1', 'a1'))])
    db.upsert_floor('areas', [('a1', area())])
    assert [t['ad'] for t in legacy_tables(db)] == ['M1']


def test_yerel_durum_plan_guncellemesinde_korunur(db):
    db.upsert_floor('areas', [('a1', area())])
    db.upsert_floor('tables', [('t1', table('M1', 'a1'))])
    local_id = legacy_tables(db)[0]['id']
    assert db.set_table_reserved(local_id, True)
    db.upsert_floor('tables', [('t1', table('Masa 1', 'a1', x=300))])
    row = legacy_tables(db)[0]
    assert (row['ad'], row['durum']) == ('Masa 1', 'rezerve')
    state = db.floor_table_states('a1')[0]
    assert state['x'] == 300 and state['legacy']['durum'] == 'rezerve'


def test_rezerve_yalnizca_bos_masada(db):
    db.upsert_floor('areas', [('a1', area())])
    db.upsert_floor('tables', [('t1', table('M1', 'a1'))])
    local_id = legacy_tables(db)[0]['id']
    conn = db.get_connection()
    conn.execute("UPDATE tables SET durum='dolu' WHERE id=?", (local_id,))
    conn.commit()
    conn.close()
    assert db.set_table_reserved(local_id, True) is False
    assert legacy_tables(db)[0]['durum'] == 'dolu'


def test_aktarim_listesi_esleme_ve_acik_adisyonlar(db):
    payload = db.legacy_floor_payload()
    assert [a['name'] for a in payload] == ['Salon', 'Teras', 'Bahçe']
    assert sum(len(a['tables']) for a in payload) == 24
    # Örnek veride Masa 2, 5, 11 ve 18'de açık adisyon var.
    area_map = {str(a['localId']): f"area{a['localId']}" for a in payload}
    table_map = {str(t['localId']): f"tbl{t['localId']}" for a in payload for t in a['tables']}
    db.apply_floor_mapping(area_map, table_map)
    db.upsert_floor('areas', [(cid, area(name=a['name'], order=i)) for i, (a, cid) in
                              enumerate(zip(payload, area_map.values()))])
    db.upsert_floor('tables', [(f"tbl{t['localId']}", table(t['name'], f"area{a['localId']}"))
                               for a in payload for t in a['tables']])
    assert len(legacy_tables(db)) == 24  # çift kayıt yok
    assert db.legacy_floor_payload() == []
    assert db.area_has_open_orders(area_id='area1') == ['Masa 2', 'Masa 5']
    assert db.area_has_open_orders(table_ids=['tbl11', 'tbl12']) == ['Masa 11']
    assert db.area_has_open_orders(table_ids=[]) == []
    salon = db.floor_table_states('area1')
    assert next(t for t in salon if t['name'] == 'Masa 2')['legacy']['durum'] == 'dolu'


def test_genel_ayarlar_varsayilan(db):
    assert db.general_settings() == {'cafeName': 'Kafem', 'qrBaseUrl': '', 'idleLockMinutes': 3}
    db.set_setting('general', {'cafeName': 'Velvet', 'qrBaseUrl': 'https://v.web.app/masa', 'idleLockMinutes': 5})
    assert db.general_settings()['cafeName'] == 'Velvet'


def test_qr_adresi_ve_pdf(tmp_path, app):
    from qr_print import default_base_url, table_qr_url, write_qr_pdf
    assert default_base_url('kafe-1') == 'https://kafe-1.web.app/masa'
    assert table_qr_url('https://v.web.app/masa/', 'abc', 'x_y-z') == 'https://v.web.app/masa/abc?t=x_y-z'
    path = str(tmp_path / 'qr.pdf')
    tables = [{'id': f't{i}', 'name': f'Masa {i}', 'qrToken': f'tok{i}'} for i in range(7)]
    assert write_qr_pdf(path, 'Velvet Kafe', 'https://v.web.app/masa', tables) == 2
    data = open(path, 'rb').read()
    assert data.startswith(b'%PDF') and data.count(b'/Type /Page\n') + data.count(b'/Type /Page ') >= 1


def test_plan_ogesi_izgara_ve_tuval_siniri(app):
    from floor_editor import FloorScene, PlanItem
    scene = FloorScene(editable=True)
    item = PlanItem({'name': 'M1', 'shape': 'rect', 'capacity': 6, 'x': 60, 'y': 60, 'w': 200, 'h': 120,
                     'rotation': 0}, True, True)
    scene.addItem(item)
    item.setPos(1187, 33)
    assert (item.info['x'], item.info['y']) == (1000, 40)  # 1200-200 sınırı, 20'lik ızgara
    item.rotate()
    assert item.size() == (120, 200) and item.info['rotation'] == 90
    item.snap_enabled = False
    item.setPos(13, 7)
    assert (item.info['x'], item.info['y']) == (13, 7)


def test_editor_ayni_adli_masayi_kaydetmez(db, app):
    from floor_editor import FloorPlanPage
    db.upsert_floor('areas', [('a1', area())])
    db.upsert_floor('tables', [('t1', table('Masa 1', 'a1'))])
    page = FloorPlanPage({'role': 'owner', 'cloud_id': 'o1', 'permissions': None})
    page._add_table('round')
    tables, _ = page._collect()
    assert sorted(t['name'] for t in tables) == ['Masa 1', 'Masa 2']
    new = next(t for t in tables if t['name'] == 'Masa 2')
    assert 'tempId' in new and 'id' not in new and new['capacity'] == 2
    for it in page._items(tables=True):
        it.info['name'] = 'masa 1'
    with pytest.raises(ValueError, match='birden fazla'):
        page._collect()


def test_editor_yalnizca_sildigi_masayi_bildirir(db, app):
    from floor_editor import FloorPlanPage
    db.upsert_floor('areas', [('a1', area())])
    db.upsert_floor('tables', [('t1', table('Masa 1', 'a1')), ('t2', table('Masa 2', 'a1', x=300))])
    page = FloorPlanPage({'role': 'owner', 'cloud_id': 'o1', 'permissions': None})
    from cloud.context import ctx
    from cloud.sync import SyncStatus
    ctx.last_status = SyncStatus(online=True)
    try:
        page._apply_online()
        victim = next(i for i in page._items(tables=True) if i.info['name'] == 'Masa 2')
        page.scene.clearSelection()
        victim.setSelected(True)
        page._delete_selected()
        assert page._removed_ids == ['t2']
        tables, _ = page._collect()
        assert [t['name'] for t in tables] == ['Masa 1']
    finally:
        ctx.last_status = None
