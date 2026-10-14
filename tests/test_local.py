"""Yerel önbellek, PIN girişi, yetki ve işlem kuyruğu testleri (internet gerekmez)."""
import hashlib
import json

import pytest

from cloud.permissions import DEFAULT_PERMISSIONS, can_manage_role, has_permission, normalize_permissions
from cloud.pins import is_valid_pin, verify_pin

SALT = '00112233445566778899aabbccddeeff'
# firebase/functions/test/lib.test.js içindeki sabit vektörle aynı.
NODE_HASH = '7a1c930a8cc57f037ca762cbfd3f09a10469299fafcca9ff5e0a25a46b23414d'


def pin_record(pin, version=1):
    h = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(SALT), n=16384, r=8, p=1, dklen=32).hex()
    return {'algo': 'scrypt', 'salt': SALT, 'hash': h, 'n': 16384, 'r': 8, 'p': 1, 'pinVersion': version}


def seed(db, staff_id='s1', role='waiter', pin='482913', active=True):
    db.upsert_staff([(staff_id, {'name': f'Kişi {staff_id}', 'role': role, 'active': active,
                                 'pinVersion': 1, 'updatedAt': '2026-10-14T10:00:00Z'})])
    db.upsert_pins([(staff_id, pin_record(pin))])


def test_pin_hash_node_ile_ayni():
    assert verify_pin('482913', {'algo': 'scrypt', 'salt': SALT, 'hash': NODE_HASH})
    assert not verify_pin('482914', {'algo': 'scrypt', 'salt': SALT, 'hash': NODE_HASH})
    assert not verify_pin('482913', None)
    assert not verify_pin('482913', {'algo': 'scrypt', 'salt': 'zz', 'hash': NODE_HASH})


def test_is_valid_pin():
    assert is_valid_pin('482913')
    for bad in ['123456', '111111', '654321', '12345', 'abcdef', 482913]:
        assert not is_valid_pin(bad)


def test_yetki_matrisi():
    m = normalize_permissions({'waiter': {'discount': True, 'x': True}, 'owner': {'settings': False}})
    assert m['waiter']['discount'] is True
    assert 'x' not in m['waiter']
    assert m['owner']['settings'] is True
    assert has_permission(DEFAULT_PERMISSIONS, 'waiter', 'discount') is False
    assert has_permission(DEFAULT_PERMISSIONS, 'waiter', 'discount', {'discount': True}) is True
    assert has_permission(DEFAULT_PERMISSIONS, 'owner', 'settings', {'settings': False}) is True
    assert can_manage_role('manager', 'waiter') and not can_manage_role('manager', 'manager')


def test_pin_ile_giris_ve_yerel_kullanici(db):
    seed(db)
    user = db.login_with_pin('s1', '482913')
    assert user['cloud_id'] == 's1'
    assert user['gorev'] == 'Garson'
    assert isinstance(user['id'], int)
    # Eski siparişlerin bağlı olduğu users tablosunda satır oluştu.
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM users WHERE cloud_id='s1'").fetchone()
    conn.close()
    assert row['aktif'] == 1 and row['son_giris']
    # Giriş kaydı kuyruğa yazıldı.
    ops = db.get_pending_ops()
    assert [o['op'] for o in ops] == ['staffLogin']
    assert json.loads(ops[0]['payload']) == {'method': 'pin'}


def test_hatali_pin_kilitleme(db):
    seed(db)
    for kalan in (4, 3, 2, 1):
        with pytest.raises(db.LoginError, match=f'Kalan deneme: {kalan}'):
            db.check_pin('s1', '000001')
    with pytest.raises(db.LoginError, match='kilitlendi'):
        db.check_pin('s1', '000001')
    # Doğru PIN de kilit süresince reddedilir.
    with pytest.raises(db.LoginError, match='dakika sonra'):
        db.check_pin('s1', '482913')


def test_dogru_pin_sayaci_sifirlar(db):
    seed(db)
    for _ in range(3):
        with pytest.raises(db.LoginError):
            db.check_pin('s1', '000001')
    db.check_pin('s1', '482913')
    with pytest.raises(db.LoginError, match='Kalan deneme: 4'):
        db.check_pin('s1', '000001')


def test_pasif_personel_giremez_ve_listede_gorunmez(db):
    seed(db, active=False)
    assert db.get_login_staff() == []
    with pytest.raises(db.LoginError, match='pasif'):
        db.check_pin('s1', '482913')


def test_pin_inmemisse_anlasilir_mesaj(db):
    db.upsert_staff([('s2', {'name': 'Yeni', 'role': 'waiter', 'active': True, 'pinVersion': 1})])
    with pytest.raises(db.LoginError, match='henüz bu bilgisayara inmedi'):
        db.check_pin('s2', '482913')


def test_user_can_matristen_okur(db):
    seed(db)
    user = db.login_with_pin('s1', '482913')
    assert not db.user_can(user, 'discount')
    db.set_setting('permissions', {'roles': {'waiter': {'discount': True}}})
    assert db.user_can(user, 'discount')


def test_yetkili_listesi(db):
    seed(db, 's1', 'waiter')
    seed(db, 's2', 'manager', pin='583920')
    seed(db, 's3', 'cashier', pin='640218')
    assert [s['id'] for s in db.staff_with_permission('voidItem')] == ['s2']
    assert {s['id'] for s in db.staff_with_permission('discount')} == {'s2', 's3'}
    assert [s['id'] for s in db.staff_with_permission('discount', exclude_id='s3')] == ['s2']


def test_kuyruk_durumlari(db):
    a = db.enqueue_op('audit', {'action': 'x'}, 's1')
    b = db.enqueue_op('audit', {'action': 'y'}, 's1')
    c = db.enqueue_op('addItems', {}, 's1')
    assert db.outbox_counts() == (3, 0)
    db.complete_ops([a])
    db.fail_op(b, 'reddedildi')
    db.defer_op(c, 'desteklenmiyor')
    assert db.outbox_counts() == (1, 1)
    assert db.get_failed_ops()[0]['last_error'] == 'reddedildi'
    assert db.get_pending_ops()[0]['op_id'] == c
