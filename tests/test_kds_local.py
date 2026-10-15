"""Mutfak ekranı (5. ekran): buluttan inen fiş durumu, hazır bildirimi ve masadaki 🔔 — yerel."""
from tests.test_pos_local import setup  # noqa: F401 (fixture)


def _send(db, pos, user):
    order = pos.open_order(user, {'id': 't1', 'name': 'Masa 1'})
    pos.add_line(user, order['id'], pos.product_line(db.menu_item('products', 'latte')))
    pos.add_line(user, order['id'], pos.product_line(db.menu_item('products', 'kek')))
    order, _ = pos.send_pending(user, order['id'])
    return order, {t['station']: t for t in pos.tickets()}


def _legacy_table(db):
    region = db.get_all_regions()[0]
    return next(t for t in db.get_tables_by_region(region['id']) if t['cloud_id'] == 't1')


def test_mutfakta_hazir_denen_fis_bir_kez_bildirilir_ve_masada_zil_gorunur(db, setup):
    pos, user = setup
    order, tickets = _send(db, pos, user)
    kitchen = tickets['kitchen']
    db.upsert_cloud_tickets([(kitchen['id'], {'status': 'preparing', 'doneLineIds': [kitchen['lines'][0]['lineId']]})])
    assert db.take_ready_notifications() == []
    db.upsert_cloud_tickets([(kitchen['id'], {'status': 'ready', 'readyAt': 'x'})])
    ready = db.take_ready_notifications()
    assert [t['id'] for t in ready] == [kitchen['id']] and pos.place_label(ready[0]) == 'Masa 1'
    assert db.take_ready_notifications() == []          # ikinci kez bildirilmez
    assert _legacy_table(db)['ready'] is True            # plan / masa kartında 🔔

    # Garson teslim etti: zil kalkar; mutfaktan gelen eski durum teslimi geri açmaz
    pos.set_ticket_status(user, kitchen['id'], 'served')
    assert _legacy_table(db)['ready'] is False
    db.upsert_cloud_tickets([(kitchen['id'], {'status': 'ready'})])
    assert [t['status'] for t in pos.tickets(('served',))] == ['served']


def test_iptal_edilen_fis_bildirilmez_bilinmeyen_fis_atlanir(db, setup):
    pos, user = setup
    order, tickets = _send(db, pos, user)
    bar = tickets['bar']
    db.upsert_cloud_tickets([(bar['id'], {'status': 'ready', 'cancelled': True}),
                             ('baska-terminalin-fisi', {'status': 'ready'})])
    assert db.take_ready_notifications() == []
    assert next(t for t in pos.tickets() if t['id'] == bar['id'])['cancelled'] is True


def test_masa_adi_etiketi():
    import pos
    assert pos.place_label({'type': 'dine_in', 'tableName': '5'}) == 'Masa 5'
    assert pos.place_label({'type': 'dine_in', 'tableName': 'Bahçe 3'}) == 'Bahçe 3'
    assert pos.place_label({'type': 'takeaway', 'tableName': ''}) == 'Paket'
