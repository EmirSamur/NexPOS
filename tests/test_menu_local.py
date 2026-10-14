"""Menü önbelleği, eski tablolara yansıtma, tükendi kuyruğu ve para biçimi (internet gerekmez)."""
import json

import pytest

from money import format_tl, parse_tl


def cat(name='Sıcak Kahveler', order=0, **kw):
    return {'name': name, 'color': '#8D6E63', 'station': 'bar', 'order': order, 'deleted': False,
            'updatedAt': '2026-10-14T10:00:00Z', **kw}


def prod(name, category_id, price, **kw):
    return {'name': name, 'categoryId': category_id, 'price': price, 'active': True, 'soldOut': False,
            'deleted': False, 'order': 0, 'updatedAt': '2026-10-14T10:00:00Z', **kw}


def legacy_products(db):
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM products WHERE cloud_id IS NOT NULL ORDER BY ad").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def test_para_bicimi():
    assert format_tl(9500) == '95,00 ₺'
    assert format_tl(125000) == '1.250,00 ₺'
    assert format_tl(1500, sign=True) == '+15,00 ₺'
    assert format_tl(-1500) == '-15,00 ₺'
    assert parse_tl('95') == 9500
    assert parse_tl('95,5') == 9550
    assert parse_tl('1.250,00') == 125000
    assert parse_tl('12.50') == 1250
    assert parse_tl('85,00 ₺') == 8500
    for bad in ('', 'abc', '1,234', '9,999'):
        if bad in ('1,234', '9,999'):
            with pytest.raises(ValueError, match='2 ondalık'):
                parse_tl(bad)
        else:
            with pytest.raises(ValueError):
                parse_tl(bad)


def test_bulut_menusu_eski_tablolara_yansir(db):
    db.upsert_menu('categories', [('c1', cat())])
    db.upsert_menu('products', [('p1', prod('Latte', 'c1', 9500)), ('p2', prod('Mocha', 'c1', 10500, soldOut=True))])
    rows = legacy_products(db)
    assert [(r['ad'], r['fiyat'], r['aktif'], r['tukendi']) for r in rows] == [
        ('Latte', 95.0, 1, 0), ('Mocha', 105.0, 1, 1)]
    # Garson ekranının okuduğu liste: bulut kategorisi var, eski demo menü gizlendi.
    assert [c['ad'] for c in db.get_all_categories()] == ['Sıcak Kahveler']
    assert {p['ad'] for p in db.get_products_by_category()} == {'Latte', 'Mocha'}


def test_kategori_sonra_gelirse_urun_yine_baglanir(db):
    db.upsert_menu('products', [('p1', prod('Latte', 'c1', 9500))])
    assert legacy_products(db) == []
    db.upsert_menu('categories', [('c1', cat())])
    assert [r['ad'] for r in legacy_products(db)] == ['Latte']


def test_fiyat_degisikligi_ve_silme_yansir(db):
    db.upsert_menu('categories', [('c1', cat())])
    db.upsert_menu('products', [('p1', prod('Latte', 'c1', 9500))])
    db.upsert_menu('products', [('p1', prod('Latte', 'c1', 11000))])
    assert legacy_products(db)[0]['fiyat'] == 110.0
    db.upsert_menu('products', [('p1', prod('Latte', 'c1', 11000, deleted=True))])
    row = legacy_products(db)[0]
    assert row['aktif'] == 0 and row['ad'] == 'Latte'  # eski adisyonlar için satır durur
    assert db.menu_products() == []


def test_menu_okuma_sirali_ve_silinenler_haric(db):
    db.upsert_menu('categories', [('c2', cat('Tatlılar', order=2)), ('c1', cat(order=1)),
                                  ('c3', cat('Eski', order=0, deleted=True))])
    assert [c['id'] for c in db.menu_categories()] == ['c1', 'c2']
    assert [c['id'] for c in db.menu_categories(include_deleted=True)] == ['c3', 'c1', 'c2']


def test_tukendi_internetsiz_yerelde_uygulanir_ve_kuyruga_duser(db):
    db.upsert_menu('categories', [('c1', cat())])
    db.upsert_menu('products', [('p1', prod('Latte', 'c1', 9500))])
    db.upsert_menu('optionGroups', [('g1', {'name': 'Süt', 'options': [
        {'id': 'normal', 'name': 'Normal', 'priceDelta': 0}, {'id': 'oat', 'name': 'Yulaf', 'priceDelta': 1500}]})])

    db.set_sold_out('s1', True, product_id='p1')
    db.set_sold_out('s1', True, option_group_id='g1', option_id='oat')

    assert db.menu_item('products', 'p1')['soldOut'] is True
    assert legacy_products(db)[0]['tukendi'] == 1
    oat = [o for o in db.menu_item('optionGroups', 'g1')['options'] if o['id'] == 'oat'][0]
    assert oat['soldOut'] is True
    ops = [(o['op'], json.loads(o['payload'])) for o in db.get_pending_ops()]
    assert ops == [('setSoldOut', {'productId': 'p1', 'soldOut': True}),
                   ('setSoldOut', {'optionGroupId': 'g1', 'optionId': 'oat', 'soldOut': True})]
    with pytest.raises(ValueError):
        db.set_sold_out('s1', True, product_id='yok')


def test_eski_menu_aktarim_listesi_ve_eslesme(db):
    cats, prods = db.legacy_menu_for_import()
    assert len(cats) == 10 and len(prods) == 30  # NexPOS'un örnek menüsü
    latte = [p for p in prods if p['ad'] == 'Latte'][0]
    assert latte['price'] == 8500
    db.apply_import_mapping({str(cats[0]['id']): 'c1'}, {str(latte['id']): 'p1'})
    db.upsert_menu('categories', [('c1', cat())])
    db.upsert_menu('products', [('p1', prod('Latte', 'c1', 8500))])
    lattes = [p for p in db.get_products_by_category() if p['ad'] == 'Latte']
    assert len(lattes) == 1  # çift kayıt oluşmadı
    assert lattes[0]['cloud_id'] == 'p1'
    assert db.legacy_menu_for_import() == ([], [])


def test_markSoldOut_varsayilanlari():
    from cloud.permissions import DEFAULT_PERMISSIONS
    assert DEFAULT_PERMISSIONS['barista']['markSoldOut'] is True
    assert DEFAULT_PERMISSIONS['waiter']['markSoldOut'] is False


def test_aktarimda_icecek_kategorileri_bara_ve_damgaya_duser(db):
    # "İçecek" büyük İ ile başlar; str.lower() 'i̇çecek' üretir ve eşleşmezdi.
    assert db.turkish_lower('Soğuk İçecekler') == 'soğuk içecekler'
    cats, prods = db.legacy_import_payload()
    station = {c['name']: (c['station'], c['stampEligible']) for c in cats}
    assert station['Sıcak Kahveler'] == ('bar', True)
    assert station['Sıcak İçecekler'] == ('bar', True)
    assert station['Soğuk İçecekler'] == ('bar', True)
    assert station['Tatlı ve Pastalar'] == ('kitchen', False)
    assert station['Kahvaltılar'] == ('kitchen', False)
    assert all(isinstance(p['price'], int) for p in prods)
