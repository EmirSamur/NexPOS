"""
NexPOS - Veritabanı Katmanı
"""
import sqlite3
import os
import sys
import json
import time
import uuid
from datetime import datetime, timedelta

from cloud.permissions import ROLE_LABELS, has_permission, normalize_permissions
from cloud.pins import verify_pin

# PyInstaller exe ile uyumlu DB_PATH
if getattr(sys, 'frozen', False):
    # exe olarak çalışıyor — exe'nin yanındaki klasörü kullan
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Normal Python ile çalışıyor
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, "nexpos.db")


def get_connection():
    # Senkron işçisi ayrı bir thread'de yazdığı için kilit beklemesi uzun tutulur.
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad_soyad TEXT NOT NULL, email TEXT, telefon TEXT,
        sifre TEXT NOT NULL, gorev TEXT NOT NULL DEFAULT 'Garson',
        aktif INTEGER DEFAULT 1, son_giris TEXT, son_cikis TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS regions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad TEXT NOT NULL, sira INTEGER DEFAULT 0)""")

    c.execute("""CREATE TABLE IF NOT EXISTS tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad TEXT NOT NULL, region_id INTEGER NOT NULL, durum TEXT DEFAULT 'bos',
        garson_id INTEGER,
        FOREIGN KEY (region_id) REFERENCES regions(id),
        FOREIGN KEY (garson_id) REFERENCES users(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad TEXT NOT NULL, renk TEXT DEFAULT '#6C5CE7', sira INTEGER DEFAULT 0)""")

    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad TEXT NOT NULL, fiyat REAL NOT NULL DEFAULT 0,
        kategori_id INTEGER, birim TEXT DEFAULT 'Tam', aktif INTEGER DEFAULT 1,
        FOREIGN KEY (kategori_id) REFERENCES categories(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        masa_id INTEGER, garson_id INTEGER, durum TEXT DEFAULT 'hazirlaniyor',
        toplam_tutar REAL DEFAULT 0, tarih TEXT, notlar TEXT,
        FOREIGN KEY (masa_id) REFERENCES tables(id),
        FOREIGN KEY (garson_id) REFERENCES users(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
        adet INTEGER DEFAULT 1, birim_fiyat REAL, toplam REAL, notlar TEXT,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (product_id) REFERENCES products(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        masraf_tipi TEXT, tutar REAL, odeme_tipi TEXT DEFAULT 'Nakit',
        masraf_detayi TEXT, kullanici_id INTEGER, masraf_tarihi TEXT, eklenme_tarihi TEXT,
        FOREIGN KEY (kullanici_id) REFERENCES users(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS waste (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER, zayi_nedeni TEXT, adet INTEGER DEFAULT 1,
        maliyet_tutari REAL DEFAULT 0, sorumlu_id INTEGER,
        zayi_tarihi TEXT, eklenme_tarihi TEXT,
        FOREIGN KEY (product_id) REFERENCES products(id),
        FOREIGN KEY (sorumlu_id) REFERENCES users(id))""")

    # ---- Bulut önbelleği ve işlem kuyruğu (bkz. cloud/ ve MIMARI.md) ----
    c.execute("""CREATE TABLE IF NOT EXISTS staff_cache (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT, role TEXT NOT NULL,
        email TEXT, active INTEGER DEFAULT 1, deleted INTEGER DEFAULT 0,
        pin_version INTEGER DEFAULT 0, permissions TEXT, last_login_at TEXT,
        updated_at TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS pin_cache (
        staff_id TEXT PRIMARY KEY, record TEXT NOT NULL, pin_version INTEGER DEFAULT 0)""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings_cache (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS outbox (
        op_id TEXT PRIMARY KEY, op TEXT NOT NULL, payload TEXT NOT NULL,
        staff_id TEXT NOT NULL, created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER DEFAULT 0, last_error TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS sync_state (
        key TEXT PRIMARY KEY, value TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS login_attempts (
        staff_id TEXT PRIMARY KEY, failures INTEGER DEFAULT 0, locked_until REAL DEFAULT 0)""")

    # Siparişler (4. ekran): adisyonun tam durumu JSON olarak (cloud/orders.py ile aynı yapı).
    # Kapanan adisyonlar raporlar için eski orders/order_items tablolarına da yazılır.
    c.execute("""CREATE TABLE IF NOT EXISTS pos_orders (
        id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL, table_id TEXT,
        business_day TEXT, legacy_order_id INTEGER, updated_at TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pos_orders_status ON pos_orders(status, table_id)")
    # Stok hareket defteri (8. ekran): bu bilgisayarda yapılan her stok hareketinin satırları. Buluta
    # gidene kadar (op_id kuyrukta) yerel stoğa eklenir; gittikten sonra bulut stoğunda zaten vardır.
    c.execute("""CREATE TABLE IF NOT EXISTS stock_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT, movement_id TEXT NOT NULL, op_id TEXT, type TEXT NOT NULL,
        ingredient_id TEXT NOT NULL, qty INTEGER NOT NULL, order_id TEXT, line_id TEXT, at TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock_ledger_line ON stock_ledger(order_id, line_id)")
    # Zayi, sayım ve alış kayıtları (8b): bu bilgisayarda yapılanların raporlanabilir kopyası.
    c.execute("""CREATE TABLE IF NOT EXISTS waste_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, movement_id TEXT, kind TEXT NOT NULL, ref_id TEXT, name TEXT,
        qty INTEGER, unit TEXT, reason TEXT, cost INTEGER, staff_id TEXT, at TEXT, business_day TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS count_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, movement_id TEXT, at TEXT, business_day TEXT, staff_id TEXT,
        reason TEXT, initial INTEGER DEFAULT 0, data TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS purchase_log (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, supplier_id TEXT, purchase_order_id TEXT, total INTEGER,
        payment_status TEXT, method TEXT, note TEXT, data TEXT, at TEXT, business_day TEXT, staff_id TEXT)""")
    # Sadakat defteri (10. ekran): bu bilgisayarda kapanan üye adisyonlarının damga/ödül etkisi. İşlem
    # kuyruktayken (op_id bekliyor) müşterinin kartına eklenir; gidince bulut kaydında zaten vardır.
    c.execute("""CREATE TABLE IF NOT EXISTS loyalty_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT, op_id TEXT NOT NULL, customer_id TEXT NOT NULL, order_id TEXT,
        kind TEXT NOT NULL, stamps INTEGER NOT NULL DEFAULT 0, rewards INTEGER NOT NULL DEFAULT 0,
        used TEXT, at TEXT)""")
    # Mesai kayıtları (9. ekran): bu bilgisayarda başlatılan/düzeltilen mesailer (kuyrukla buluta gider)
    c.execute("""CREATE TABLE IF NOT EXISTS time_entries (
        id TEXT PRIMARY KEY, staff_id TEXT NOT NULL, business_day TEXT NOT NULL, data TEXT NOT NULL,
        open INTEGER DEFAULT 1)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_time_entries ON time_entries(staff_id, business_day)")
    # Kasa oturumları (6. ekran): açılış, hareketler, kapanış ve Z raporu JSON olarak.
    c.execute("""CREATE TABLE IF NOT EXISTS cash_sessions (
        id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL, business_day TEXT,
        opened_at TEXT, closed_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS pos_tickets (
        id TEXT PRIMARY KEY, order_id TEXT NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL,
        station TEXT, created_at TEXT)""")

    # Buluttaki personel, eski siparişlerin bağlı olduğu users tablosunda da bir
    # satırla temsil edilir (garson_id yabancı anahtarı bozulmasın diye).
    user_cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    if 'cloud_id' not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN cloud_id TEXT")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cloud_id ON users(cloud_id)")

    # Bulut koleksiyonlarının önbelleği (menü, salon planı…): dokümanların tamamı cloud_cache'te;
    # eski ekranların okuduğu categories/products/regions/tables tabloları bu önbellekten
    # beslenir (cloud_id ile eşleşir). 2. ekrandaki adı menu_cache idi.
    existing_tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if 'menu_cache' in existing_tables and 'cloud_cache' not in existing_tables:
        c.execute("ALTER TABLE menu_cache RENAME TO cloud_cache")
    c.execute("""CREATE TABLE IF NOT EXISTS cloud_cache (
        collection TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
        PRIMARY KEY (collection, id))""")
    for table, cols in (('categories', (('cloud_id', 'TEXT'), ('silindi', 'INTEGER DEFAULT 0'))),
                        ('products', (('cloud_id', 'TEXT'), ('tukendi', 'INTEGER DEFAULT 0'))),
                        ('regions', (('cloud_id', 'TEXT'), ('silindi', 'INTEGER DEFAULT 0'))),
                        ('tables', (('cloud_id', 'TEXT'), ('silindi', 'INTEGER DEFAULT 0')))):
        existing = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        for name, kind in cols:
            if name not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        c.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_cloud_id ON {table}(cloud_id)")

    conn.commit()

    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        _create_sample_data(conn)
    conn.close()


def _create_sample_data(conn):
    c = conn.cursor()

    # Örnek siparişlerin garsonları. Giriş yapamazlar (şifre yok, pasif); gerçek
    # personel buluttan gelir ve PIN ile giriş yapar.
    users = [
        ("Deniz Yılmaz", "admin@nexpos.com", "5321234567", "", "Yönetici"),
        ("Cem Akar", "cem@nexpos.com", "5359876543", "", "Garson"),
        ("Elif Demir", "elif@nexpos.com", "5447654321", "", "Garson"),
    ]
    c.executemany("INSERT INTO users (ad_soyad,email,telefon,sifre,gorev,aktif) VALUES (?,?,?,?,?,0)", users)

    c.execute("INSERT INTO regions (ad,sira) VALUES ('Salon',1)")
    salon_id = c.lastrowid
    c.execute("INSERT INTO regions (ad,sira) VALUES ('Teras',2)")
    teras_id = c.lastrowid
    c.execute("INSERT INTO regions (ad,sira) VALUES ('Bahçe',3)")
    bahce_id = c.lastrowid

    for i in range(1, 9):
        c.execute("INSERT INTO tables (ad,region_id) VALUES (?,?)", (f"Masa {i}", salon_id))
    for i in range(9, 17):
        c.execute("INSERT INTO tables (ad,region_id) VALUES (?,?)", (f"Masa {i}", teras_id))
    for i in range(17, 25):
        c.execute("INSERT INTO tables (ad,region_id) VALUES (?,?)", (f"Masa {i}", bahce_id))

    cats = [
        ("Sıcak Kahveler", "#8D6E63"), ("Soğuk Kahveler", "#795548"),
        ("Sıcak İçecekler", "#FF7043"), ("Soğuk İçecekler", "#42A5F5"),
        ("Tatlı ve Pastalar", "#EC407A"), ("Kahvaltılar", "#FFA726"),
        ("Atıştırmalıklar", "#66BB6A"), ("Ana Yemekler", "#EF5350"),
        ("Salatalar", "#26A69A"), ("Tostlar & Sandviçler", "#AB47BC"),
    ]
    cat_ids = []
    for cat in cats:
        c.execute("INSERT INTO categories (ad,renk) VALUES (?,?)", cat)
        cat_ids.append(c.lastrowid)

    products = [
        ("Türk Kahvesi", 60, cat_ids[0]), ("Latte", 85, cat_ids[0]),
        ("Americano", 75, cat_ids[0]), ("Cappuccino", 80, cat_ids[0]),
        ("Mocha", 90, cat_ids[0]),
        ("Ice Latte", 90, cat_ids[1]), ("Cold Brew", 95, cat_ids[1]),
        ("Frappe", 85, cat_ids[1]),
        ("Çay", 30, cat_ids[2]), ("Bitki Çayı", 45, cat_ids[2]),
        ("Sahlep", 65, cat_ids[2]), ("Sıcak Çikolata", 70, cat_ids[2]),
        ("Limonata", 70, cat_ids[3]), ("Meyveli Soda", 60, cat_ids[3]),
        ("Smoothie", 90, cat_ids[3]),
        ("San Sebastian", 130, cat_ids[4]), ("Tiramisu", 110, cat_ids[4]),
        ("Brownie", 95, cat_ids[4]), ("Cheesecake", 120, cat_ids[4]),
        ("Serpme Kahvaltı", 450, cat_ids[5]), ("Sahanda Yumurta", 120, cat_ids[5]),
        ("Menemen", 110, cat_ids[5]),
        ("Patates Kızartması", 85, cat_ids[6]), ("Soğan Halkası", 95, cat_ids[6]),
        ("Izgara Tavuk", 195, cat_ids[7]), ("Köfte Tabağı", 185, cat_ids[7]),
        ("Sezar Salata", 140, cat_ids[8]), ("Akdeniz Salata", 130, cat_ids[8]),
        ("Tost", 90, cat_ids[9]), ("Kulüp Sandviç", 140, cat_ids[9]),
    ]
    for p in products:
        c.execute("INSERT INTO products (ad,fiyat,kategori_id) VALUES (?,?,?)", p)

    now = datetime.now()
    orders = [
        (2, 2, "hazirlaniyor", 255.00, (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")),
        (5, 3, "hazirlaniyor", 450.00, (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")),
        (11, 2, "bekliyor", 170.00, (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")),
        (18, 3, "hazirlaniyor", 320.00, (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M")),
    ]
    for o in orders:
        c.execute("INSERT INTO orders (masa_id,garson_id,durum,toplam_tutar,tarih) VALUES (?,?,?,?,?)", o)
        c.execute("UPDATE tables SET durum='dolu', garson_id=? WHERE id=?", (o[1], o[0]))

    conn.commit()


# ---- CRUD ----

def get_all_regions():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM regions WHERE COALESCE(silindi,0)=0 ORDER BY sira, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_region(ad):
    conn = get_connection()
    mx = conn.execute("SELECT COALESCE(MAX(sira),0) FROM regions").fetchone()[0]
    conn.execute("INSERT INTO regions (ad,sira) VALUES (?,?)", (ad, mx + 1))
    conn.commit()
    conn.close()


def delete_region(region_id):
    """Bölgeyi ve altındaki masaları sil. Dolu masa varsa silinemez."""
    conn = get_connection()
    occupied = conn.execute(
        "SELECT COUNT(*) FROM tables WHERE region_id=? AND durum='dolu'",
        (region_id,)
    ).fetchone()[0]
    if occupied > 0:
        conn.close()
        return False  # Silme engellendi
    conn.execute("DELETE FROM tables WHERE region_id=?", (region_id,))
    conn.execute("DELETE FROM regions WHERE id=?", (region_id,))
    conn.commit()
    conn.close()
    return True


def get_tables_by_region(region_id):
    """Bölgenin masaları; açık adisyonun tutarı ve açılış saati pos_orders'tan gelir."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.*, u.ad_soyad as garson_adi
        FROM tables t
        LEFT JOIN users u ON t.garson_id = u.id
        WHERE t.region_id = ? AND COALESCE(t.silindi,0)=0 ORDER BY t.id
    """, (region_id,)).fetchall()
    open_orders = {}
    for r in conn.execute("SELECT table_id, data FROM pos_orders WHERE status='open' AND table_id IS NOT NULL"):
        open_orders[r['table_id']] = json.loads(r['data'])
    # Henüz taşınmamış eski açık adisyonlar (eski kayıt)
    legacy = {r['masa_id']: r for r in conn.execute("""SELECT masa_id, toplam_tutar, tarih FROM orders
        WHERE durum IN ('hazirlaniyor','bekliyor')""")}
    ready = {r['order_id'] for r in conn.execute("SELECT DISTINCT order_id FROM pos_tickets WHERE status='ready'")}
    conn.close()
    result = []
    for r in rows:
        t = dict(r)
        order = open_orders.get(t.get('cloud_id'))
        if order:
            t['toplam_tutar'] = order['total'] / 100
            t['siparis_tarihi'] = _local_minute(order['openedAt'])
            t['order_id'] = order['id']
            t['ready'] = order['id'] in ready   # mutfakta hazır bekleyen ürün var (🔔)
        elif t['id'] in legacy:
            t['toplam_tutar'] = legacy[t['id']]['toplam_tutar']
            t['siparis_tarihi'] = legacy[t['id']]['tarih']
            t['order_id'] = None
        else:
            t['toplam_tutar'] = None
            t['siparis_tarihi'] = None
            t['order_id'] = None
        result.append(t)
    return result


def _local_minute(iso):
    """'2026-10-15T12:05:30+03:00' → '2026-10-15 12:05' (yerel saat)"""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def add_table(ad, region_id):
    conn = get_connection()
    conn.execute("INSERT INTO tables (ad,region_id) VALUES (?,?)", (ad, region_id))
    conn.commit()
    conn.close()


def delete_table(table_id):
    """Masayı sil. Dolu masa silinemez."""
    conn = get_connection()
    durum = conn.execute("SELECT durum FROM tables WHERE id=?", (table_id,)).fetchone()
    if durum and durum['durum'] == 'dolu':
        conn.close()
        return False  # Silme engellendi
    conn.execute("DELETE FROM tables WHERE id=?", (table_id,))
    conn.commit()
    conn.close()
    return True


def get_all_categories():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM categories WHERE COALESCE(silindi,0)=0 ORDER BY sira,id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_category(ad, renk="#6C5CE7"):
    conn = get_connection()
    mx = conn.execute("SELECT COALESCE(MAX(sira),0) FROM categories").fetchone()[0]
    conn.execute("INSERT INTO categories (ad,renk,sira) VALUES (?,?,?)", (ad, renk, mx + 1))
    conn.commit()
    conn.close()


def delete_category(cat_id):
    """Kategoriyi sil. İçinde aktif ürün varsa önce ürünler pasife alınır."""
    conn = get_connection()
    conn.execute("UPDATE products SET aktif=0 WHERE kategori_id=?", (cat_id,))
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()


def get_products_by_category(kategori_id=None):
    conn = get_connection()
    if kategori_id:
        rows = conn.execute("SELECT * FROM products WHERE kategori_id=? AND aktif=1 ORDER BY id",
                            (kategori_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM products WHERE aktif=1 ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_product(ad, fiyat, kategori_id, birim="Tam"):
    conn = get_connection()
    conn.execute("INSERT INTO products (ad,fiyat,kategori_id,birim) VALUES (?,?,?,?)",
                 (ad, fiyat, kategori_id, birim))
    conn.commit()
    conn.close()


def update_product(product_id, ad, fiyat, kategori_id, birim="Tam"):
    """Ürün bilgilerini güncelle"""
    conn = get_connection()
    conn.execute(
        "UPDATE products SET ad=?, fiyat=?, kategori_id=?, birim=? WHERE id=?",
        (ad, fiyat, kategori_id, birim, product_id)
    )
    conn.commit()
    conn.close()


def delete_product(product_id):
    """
    Ürünü soft-delete yap (aktif=0).
    Geçmiş sipariş kayıtları bozulmaz.
    """
    conn = get_connection()
    conn.execute("UPDATE products SET aktif=0 WHERE id=?", (product_id,))
    conn.commit()
    conn.close()


def get_orders(durum=None):
    conn = get_connection()
    q = """SELECT o.*, t.ad as masa_adi, u.ad_soyad as garson_adi
           FROM orders o LEFT JOIN tables t ON o.masa_id=t.id
           LEFT JOIN users u ON o.garson_id=u.id"""
    if durum:
        q += " WHERE o.durum=?"
        rows = conn.execute(q + " ORDER BY o.tarih DESC", (durum,)).fetchall()
    else:
        rows = conn.execute(q + " ORDER BY o.tarih DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_order_items(order_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT oi.*, p.ad as urun_adi
        FROM order_items oi LEFT JOIN products p ON oi.product_id=p.id
        WHERE oi.order_id=? ORDER BY oi.id
    """, (order_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_order(masa_id, garson_id, items, iskonto_pct=0):
    """
    Yeni sipariş oluştur. iskonto_pct: yüzde iskonto (0-100)
    Aynı masa için zaten açık sipariş varsa yeni kalemleri mevcut siparişe ekler.
    """
    conn = get_connection()
    c = conn.cursor()
    tarih = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Aynı masada açık sipariş var mı?
    existing = c.execute(
        "SELECT id, toplam_tutar FROM orders WHERE masa_id=? AND durum IN ('hazirlaniyor','bekliyor') LIMIT 1",
        (masa_id,)
    ).fetchone()

    if existing:
        order_id = existing['id']
        toplam = existing['toplam_tutar'] or 0.0
    else:
        c.execute("INSERT INTO orders (masa_id,garson_id,durum,tarih) VALUES (?,?,?,?)",
                  (masa_id, garson_id, "hazirlaniyor", tarih))
        order_id = c.lastrowid
        toplam = 0.0

    for product_id, adet in items:
        product = c.execute("SELECT fiyat FROM products WHERE id=?", (product_id,)).fetchone()
        if product:
            bf = product[0]
            t = bf * adet
            toplam += t
            c.execute("INSERT INTO order_items (order_id,product_id,adet,birim_fiyat,toplam) VALUES (?,?,?,?,?)",
                      (order_id, product_id, adet, bf, t))

    c.execute("UPDATE orders SET toplam_tutar=? WHERE id=?", (toplam * (1 - iskonto_pct / 100), order_id))
    c.execute("UPDATE tables SET durum='dolu', garson_id=? WHERE id=?", (garson_id, masa_id))
    conn.commit()
    conn.close()
    return order_id


def update_order_status(order_id, new_status):
    conn = get_connection()
    # Önce masa_id'yi al
    order = conn.execute("SELECT masa_id FROM orders WHERE id=?", (order_id,)).fetchone()
    # Siparişi güncelle
    conn.execute("UPDATE orders SET durum=? WHERE id=?", (new_status, order_id))
    # Masa güncelleme — teslimatta da kapalı sayılır
    if new_status in ('tamamlandi', 'iptal', 'teslimatta') and order:
        masa_id = order['masa_id']
        active = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE masa_id=? AND id!=? AND durum NOT IN ('tamamlandi','iptal','teslimatta')",
            (masa_id, order_id)).fetchone()[0]
        if active == 0:
            conn.execute("UPDATE tables SET durum='bos', garson_id=NULL WHERE id=?", (masa_id,))
    conn.commit()
    conn.close()


def get_expenses(start_date=None, end_date=None):
    conn = get_connection()
    q = "SELECT e.*, u.ad_soyad as kullanici_adi FROM expenses e LEFT JOIN users u ON e.kullanici_id=u.id"
    params = []
    if start_date and end_date:
        q += " WHERE e.masraf_tarihi BETWEEN ? AND ?"
        params = [start_date, end_date]
    rows = conn.execute(q + " ORDER BY e.masraf_tarihi DESC", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_expense(masraf_tipi, tutar, odeme_tipi, masraf_detayi, kullanici_id, masraf_tarihi):
    conn = get_connection()
    conn.execute("""INSERT INTO expenses (masraf_tipi,tutar,odeme_tipi,masraf_detayi,kullanici_id,masraf_tarihi,eklenme_tarihi)
        VALUES (?,?,?,?,?,?,?)""",
        (masraf_tipi, tutar, odeme_tipi, masraf_detayi, kullanici_id, masraf_tarihi,
         datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()


def delete_expense(expense_id):
    conn = get_connection()
    conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()


def get_waste(start_date=None, end_date=None):
    conn = get_connection()
    q = """SELECT w.*, p.ad as urun_adi, u.ad_soyad as sorumlu_adi
           FROM waste w LEFT JOIN products p ON w.product_id=p.id
           LEFT JOIN users u ON w.sorumlu_id=u.id"""
    params = []
    if start_date and end_date:
        q += " WHERE w.zayi_tarihi BETWEEN ? AND ?"
        params = [start_date, end_date]
    rows = conn.execute(q + " ORDER BY w.zayi_tarihi DESC", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_waste(product_id, zayi_nedeni, adet, maliyet, sorumlu_id, zayi_tarihi):
    conn = get_connection()
    conn.execute("""INSERT INTO waste (product_id,zayi_nedeni,adet,maliyet_tutari,sorumlu_id,zayi_tarihi,eklenme_tarihi)
        VALUES (?,?,?,?,?,?,?)""",
        (product_id, zayi_nedeni, adet, maliyet, sorumlu_id, zayi_tarihi,
         datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()


def get_dashboard_stats():
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    # Son 30 gün bazlı sorgular — tek günde sipariş yoksa 0 görünmez
    ts = conn.execute(
        "SELECT COALESCE(SUM(toplam_tutar),0) FROM orders WHERE date(tarih) >= date(?,'-30 days') AND durum='tamamlandi'",
        (today,)).fetchone()[0]
    gc = conn.execute(
        "SELECT COUNT(DISTINCT masa_id) FROM orders WHERE date(tarih) >= date(?,'-30 days')",
        (today,)).fetchone()[0]
    oo = conn.execute(
        "SELECT COALESCE(SUM(toplam_tutar),0) FROM orders WHERE durum IN ('hazirlaniyor','bekliyor')").fetchone()[0]
    oo += sum(json.loads(r['data'])['total'] for r in
              conn.execute("SELECT data FROM pos_orders WHERE status='open'")) / 100
    te = conn.execute(
        "SELECT COALESCE(SUM(tutar),0) FROM expenses WHERE date(masraf_tarihi) >= date(?,'-30 days')",
        (today,)).fetchone()[0]
    tt = conn.execute("SELECT COUNT(*) FROM tables WHERE COALESCE(silindi,0)=0").fetchone()[0]
    oc = conn.execute("SELECT COUNT(*) FROM tables WHERE durum IN ('dolu','hesap') AND COALESCE(silindi,0)=0").fetchone()[0]
    conn.close()
    return {'total_sales': ts, 'guest_count': gc, 'open_orders': oo,
            'total_expense': te, 'total_tables': tt, 'occupied_tables': oc}


def get_expense_summary(start_date=None, end_date=None):
    """Masraf tipine göre gruplu özet"""
    conn = get_connection()
    q = """SELECT masraf_tipi, COUNT(*) as islem_sayisi, SUM(tutar) as toplam_tutar,
           odeme_tipi FROM expenses"""
    params = []
    if start_date and end_date:
        q += " WHERE masraf_tarihi BETWEEN ? AND ?"
        params = [start_date, end_date]
    q += " GROUP BY masraf_tipi ORDER BY toplam_tutar DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_expense_payment_summary(start_date=None, end_date=None):
    """Ödeme tipine göre gruplu özet"""
    conn = get_connection()
    q = "SELECT odeme_tipi, SUM(tutar) as toplam FROM expenses"
    params = []
    if start_date and end_date:
        q += " WHERE masraf_tarihi BETWEEN ? AND ?"
        params = [start_date, end_date]
    q += " GROUP BY odeme_tipi"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return {r['odeme_tipi']: r['toplam'] for r in rows}


def get_waste_summary(start_date=None, end_date=None):
    """Ürüne göre gruplu zayi özeti"""
    conn = get_connection()
    q = """SELECT p.ad as urun_adi, SUM(w.adet) as toplam_adet,
           SUM(w.maliyet_tutari) as toplam_maliyet
           FROM waste w LEFT JOIN products p ON w.product_id=p.id"""
    params = []
    if start_date and end_date:
        q += " WHERE w.zayi_tarihi BETWEEN ? AND ?"
        params = [start_date, end_date]
    q += " GROUP BY w.product_id ORDER BY toplam_maliyet DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_waste(waste_id):
    conn = get_connection()
    conn.execute("DELETE FROM waste WHERE id=?", (waste_id,))
    conn.commit()
    conn.close()


def get_popular_products(limit=5):
    """En çok sipariş edilen ürünler"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.ad as urun_adi, p.fiyat,
               SUM(oi.adet) as toplam_adet,
               SUM(oi.toplam) as toplam_tutar,
               COUNT(DISTINCT oi.order_id) as siparis_sayisi
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        JOIN orders o ON oi.order_id = o.id
        WHERE o.durum = 'tamamlandi'
        GROUP BY oi.product_id
        ORDER BY toplam_adet DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def transfer_table(from_table_id, to_table_id, user_id):
    """Masadaki aktif siparişi başka masaya taşı"""
    conn = get_connection()
    # From masasının aktif siparişini bul
    order = conn.execute(
        "SELECT id FROM orders WHERE masa_id=? AND durum IN ('hazirlaniyor','bekliyor') LIMIT 1",
        (from_table_id,)
    ).fetchone()
    if not order:
        conn.close()
        return False
    order_id = order['id']
    # Siparişi yeni masaya taşı
    conn.execute("UPDATE orders SET masa_id=? WHERE id=?", (to_table_id, order_id))
    # Eski masayı boşalt
    conn.execute("UPDATE tables SET durum='bos', garson_id=NULL WHERE id=?", (from_table_id,))
    # Yeni masayı dolu yap
    conn.execute("UPDATE tables SET durum='dolu', garson_id=? WHERE id=?", (user_id, to_table_id))
    conn.commit()
    conn.close()
    return True


def get_shift_summary(user_id):
    """Garsonun bu vardiyasındaki (bugün) sipariş özeti"""
    conn = get_connection()
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    total = conn.execute(
        "SELECT COALESCE(SUM(toplam_tutar),0) FROM orders WHERE garson_id=? AND date(tarih)=? AND durum='tamamlandi'",
        (user_id, today)
    ).fetchone()[0]
    count = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE garson_id=? AND date(tarih)=? AND durum='tamamlandi'",
        (user_id, today)
    ).fetchone()[0]
    conn.close()
    return {'toplam_tutar': total, 'siparis_sayisi': count}


def add_order_note(order_id, note):
    """Siparişe not ekle"""
    conn = get_connection()
    conn.execute("UPDATE orders SET notlar=? WHERE id=?", (note, order_id))
    conn.commit()
    conn.close()


def get_toplam_iskonto():
    """Tamamlanan siparişlerdeki toplam iskonto tutarını hesapla.
    Ham tutar (order_items toplamı) - ödenen tutar (orders.toplam_tutar) farkı."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT o.toplam_tutar,
               COALESCE((SELECT SUM(oi.toplam) FROM order_items oi WHERE oi.order_id = o.id), 0) as ham_tutar
        FROM orders o
        WHERE o.durum = 'tamamlandi'
          AND date(o.tarih) >= date('now', '-30 days')
    """).fetchall()
    conn.close()
    toplam_iskonto = sum(max(0, r['ham_tutar'] - r['toplam_tutar']) for r in rows)
    return toplam_iskonto


# =====================================================================
# Bulut önbelleği: personel, PIN ve ayarlar
# Senkron işçisi (cloud/sync.py) buluttan çektiklerini buraya yazar; ekranlar
# yalnızca buradan okur. Böylece internet yokken de giriş yapılabilir.
# =====================================================================

MAX_PIN_FAILURES = 5
PIN_LOCK_SECONDS = 5 * 60


class LoginError(Exception):
    """PIN girişi başarısız; mesaj doğrudan kullanıcıya gösterilir."""


def upsert_staff(docs):
    """docs: [(staff_id, firestore_alanlari)]"""
    if not docs:
        return
    conn = get_connection()
    for staff_id, d in docs:
        conn.execute("""INSERT INTO staff_cache
            (id,name,phone,role,email,active,deleted,pin_version,permissions,last_login_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, phone=excluded.phone,
              role=excluded.role, email=excluded.email, active=excluded.active,
              deleted=excluded.deleted, pin_version=excluded.pin_version,
              permissions=excluded.permissions, last_login_at=excluded.last_login_at,
              updated_at=excluded.updated_at""",
            (staff_id, d.get('name', ''), d.get('phone'), d.get('role', 'waiter'), d.get('email'),
             1 if d.get('active') else 0, 1 if d.get('deleted') else 0,
             int(d.get('pinVersion') or 0),
             json.dumps(d['permissions']) if isinstance(d.get('permissions'), dict) else None,
             d.get('lastLoginAt'), d.get('updatedAt')))
        _sync_local_user(conn, staff_id)
    conn.commit()
    conn.close()


def upsert_pins(docs):
    if not docs:
        return
    conn = get_connection()
    for staff_id, d in docs:
        conn.execute("""INSERT INTO pin_cache (staff_id, record, pin_version) VALUES (?,?,?)
            ON CONFLICT(staff_id) DO UPDATE SET record=excluded.record, pin_version=excluded.pin_version""",
            (staff_id, json.dumps(d), int(d.get('pinVersion') or 0)))
    conn.commit()
    conn.close()


def _sync_local_user(conn, staff_id):
    """staff_cache satırını users tablosuna yansıtır ve yerel id'yi döndürür."""
    s = conn.execute("SELECT * FROM staff_cache WHERE id=?", (staff_id,)).fetchone()
    if not s:
        return None
    aktif = 1 if s['active'] and not s['deleted'] else 0
    gorev = ROLE_LABELS.get(s['role'], s['role'])
    row = conn.execute("SELECT id FROM users WHERE cloud_id=?", (staff_id,)).fetchone()
    if row:
        conn.execute("UPDATE users SET ad_soyad=?, email=?, telefon=?, gorev=?, aktif=? WHERE id=?",
                     (s['name'], s['email'], s['phone'], gorev, aktif, row['id']))
        return row['id']
    cur = conn.execute(
        "INSERT INTO users (ad_soyad,email,telefon,sifre,gorev,aktif,cloud_id) VALUES (?,?,?,?,?,?,?)",
        (s['name'], s['email'], s['phone'], '', gorev, aktif, staff_id))
    return cur.lastrowid


def set_setting(key, value):
    conn = get_connection()
    conn.execute("""INSERT INTO settings_cache (key,value,updated_at) VALUES (?,?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, json.dumps(value), datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings_cache WHERE key=?", (key,)).fetchone()
    conn.close()
    return json.loads(row['value']) if row else default


def get_sync_state(key, default=None):
    conn = get_connection()
    row = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def set_sync_state(key, value):
    conn = get_connection()
    conn.execute("""INSERT INTO sync_state (key,value) VALUES (?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, value))
    conn.commit()
    conn.close()


def get_permission_matrix():
    data = get_setting('permissions')
    return normalize_permissions(data.get('roles') if isinstance(data, dict) else None)


def _staff_to_user(row, local_id):
    """staff_cache satırını ekranların beklediği kullanıcı sözlüğüne çevirir."""
    return {
        'id': local_id,                     # users.id (eski siparişlerle uyumlu)
        'cloud_id': row['id'],
        'ad_soyad': row['name'],
        'gorev': ROLE_LABELS.get(row['role'], row['role']),
        'role': row['role'],
        'email': row['email'] or '',
        'telefon': row['phone'] or '',
        'permissions': json.loads(row['permissions']) if row['permissions'] else None,
    }


def get_all_staff(include_inactive=True):
    """Yönetim paneli için personel listesi."""
    conn = get_connection()
    q = "SELECT * FROM staff_cache WHERE deleted=0"
    if not include_inactive:
        q += " AND active=1"
    rows = conn.execute(q + " ORDER BY active DESC, name COLLATE NOCASE").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_login_staff():
    """Giriş ekranındaki kartlar: aktif personel."""
    return get_all_staff(include_inactive=False)


def get_staff(staff_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM staff_cache WHERE id=?", (staff_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users():
    """Eski arayüzle uyumluluk: personel listesi users biçiminde."""
    conn = get_connection()
    rows = conn.execute("""SELECT s.*, u.id AS local_id FROM staff_cache s
        LEFT JOIN users u ON u.cloud_id = s.id WHERE s.deleted=0 ORDER BY s.name""").fetchall()
    conn.close()
    return [_staff_to_user(r, r['local_id']) for r in rows]


def check_pin(staff_id, pin):
    """
    PIN'i önbellekteki özetle karşılaştırır (internet gerekmez). Başarılıysa personel
    satırını döndürür, değilse LoginError fırlatır. 5 hatalı denemede kart kilitlenir.
    """
    conn = get_connection()
    try:
        staff = conn.execute(
            "SELECT * FROM staff_cache WHERE id=? AND active=1 AND deleted=0", (staff_id,)).fetchone()
        if not staff:
            raise LoginError("Personel bulunamadı veya pasif durumda.")

        att = conn.execute("SELECT * FROM login_attempts WHERE staff_id=?", (staff_id,)).fetchone()
        now = time.time()
        if att and att['locked_until'] > now:
            kalan = int((att['locked_until'] - now) // 60) + 1
            raise LoginError(f"Çok fazla hatalı deneme yapıldı. {kalan} dakika sonra tekrar deneyin.")

        pin_row = conn.execute("SELECT record FROM pin_cache WHERE staff_id=?", (staff_id,)).fetchone()
        if not pin_row:
            raise LoginError("Bu kişinin PIN'i henüz bu bilgisayara inmedi. "
                             "İnternet bağlantısını kontrol edip biraz sonra tekrar deneyin.")

        if verify_pin(pin, json.loads(pin_row['record'])):
            conn.execute("DELETE FROM login_attempts WHERE staff_id=?", (staff_id,))
            conn.commit()
            return dict(staff)

        failures = (att['failures'] if att else 0) + 1
        if failures >= MAX_PIN_FAILURES:
            conn.execute("""INSERT INTO login_attempts (staff_id,failures,locked_until) VALUES (?,0,?)
                ON CONFLICT(staff_id) DO UPDATE SET failures=0, locked_until=excluded.locked_until""",
                (staff_id, now + PIN_LOCK_SECONDS))
            conn.commit()
            raise LoginError(f"{MAX_PIN_FAILURES} kez hatalı PIN girildi. "
                             f"Bu kart {PIN_LOCK_SECONDS // 60} dakika kilitlendi.")
        conn.execute("""INSERT INTO login_attempts (staff_id,failures,locked_until) VALUES (?,?,0)
            ON CONFLICT(staff_id) DO UPDATE SET failures=excluded.failures""", (staff_id, failures))
        conn.commit()
        raise LoginError(f"PIN hatalı. Kalan deneme: {MAX_PIN_FAILURES - failures}")
    finally:
        conn.close()


def login_with_pin(staff_id, pin):
    """PIN ile giriş: kullanıcı sözlüğünü döndürür, giriş kaydını kuyruğa yazar."""
    check_pin(staff_id, pin)
    return start_session(staff_id, method='pin')


def start_session(staff_id, method):
    conn = get_connection()
    local_id = _sync_local_user(conn, staff_id)
    conn.execute("UPDATE users SET son_giris=? WHERE id=?",
                 (datetime.now().strftime("%d.%m.%Y %H:%M"), local_id))
    row = conn.execute("SELECT * FROM staff_cache WHERE id=?", (staff_id,)).fetchone()
    enqueue_op('staffLogin', {'method': method}, staff_id, conn=conn)
    conn.commit()
    conn.close()
    return _staff_to_user(row, local_id)


def user_can(user, permission):
    if not user:
        return False
    return has_permission(get_permission_matrix(), user.get('role'), permission, user.get('permissions'))


def staff_can(staff_id, permission):
    """Aktif personelin (bulut kimliği) yetkisi var mı? Onaylayan denetimi için."""
    row = get_staff(staff_id) if staff_id else None
    if not row or not row['active'] or row['deleted']:
        return False
    perms = json.loads(row['permissions']) if row['permissions'] else None
    return has_permission(get_permission_matrix(), row['role'], permission, perms)


def staff_with_permission(permission, exclude_id=None):
    """Yetkili onayı penceresinde listelenecek kişiler."""
    matrix = get_permission_matrix()
    result = []
    for s in get_login_staff():
        overrides = json.loads(s['permissions']) if s['permissions'] else None
        if s['id'] != exclude_id and has_permission(matrix, s['role'], permission, overrides):
            result.append(s)
    return result


def reset_cloud_cache():
    """Terminal iptal edildiğinde ya da yeniden eşlenirken önbelleği temizler."""
    conn = get_connection()
    for t in ('staff_cache', 'pin_cache', 'settings_cache', 'sync_state', 'login_attempts', 'cloud_cache'):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()


# =====================================================================
# İşlem kuyruğu (outbox)
# Terminalde yapılan her işlem önce burada saklanır, internet varken sırayla
# buluta gönderilir (cloud/sync.py). Bilgisayar kapansa da kaybolmaz.
# =====================================================================

def enqueue_op(op, payload, staff_id, conn=None):
    """İşlemi kuyruğa ekler. conn verilirse çağıranın transaction'ına katılır."""
    own = conn is None
    if own:
        conn = get_connection()
    op_id = str(uuid.uuid4())
    created = datetime.now().astimezone().isoformat(timespec='seconds')
    conn.execute("INSERT INTO outbox (op_id,op,payload,staff_id,created_at) VALUES (?,?,?,?,?)",
                 (op_id, op, json.dumps(payload, ensure_ascii=False), staff_id, created))
    if own:
        conn.commit()
        conn.close()
    return op_id


def get_pending_ops(limit=50):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM outbox WHERE status='pending' ORDER BY created_at, rowid LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def complete_ops(op_ids):
    if not op_ids:
        return
    conn = get_connection()
    conn.executemany("DELETE FROM outbox WHERE op_id=?", [(i,) for i in op_ids])
    conn.commit()
    conn.close()


def fail_op(op_id, error):
    """Sunucunun reddettiği işlem: kuyrukta 'hatalı' olarak kalır, panelde gösterilir."""
    conn = get_connection()
    conn.execute("UPDATE outbox SET status='failed', attempts=attempts+1, last_error=? WHERE op_id=?",
                 (error, op_id))
    conn.commit()
    conn.close()


def defer_op(op_id, error):
    """Sunucunun henüz tanımadığı işlem: kuyrukta bekler, sonra tekrar denenir."""
    conn = get_connection()
    conn.execute("UPDATE outbox SET attempts=attempts+1, last_error=? WHERE op_id=?", (error, op_id))
    conn.commit()
    conn.close()


def outbox_counts():
    conn = get_connection()
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status").fetchall()
    conn.close()
    counts = {r['status']: r['n'] for r in rows}
    return counts.get('pending', 0), counts.get('failed', 0)


def get_failed_ops():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM outbox WHERE status='failed' ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# =====================================================================
# Menü önbelleği (2. ekran)
# Menü bulutta yaşar; burada tam kopyası (cloud_cache) ve eski ekranların kullandığı
# categories/products tablolarına yansıması tutulur. Düzenleme buluta yapılır
# (cloud/admin_api.py); yalnızca "tükendi" internetsiz, kuyruktan gider.
# =====================================================================

MENU_COLLECTIONS = ('categories', 'optionGroups', 'products')


def upsert_menu(collection, docs):
    """Buluttan gelen dokümanları önbelleğe yazar ve eski tablolara yansıtır."""
    if not docs:
        return
    conn = get_connection()
    for doc_id, d in docs:
        conn.execute("""INSERT INTO cloud_cache (collection,id,data) VALUES (?,?,?)
            ON CONFLICT(collection,id) DO UPDATE SET data=excluded.data""",
            (collection, doc_id, json.dumps(d, ensure_ascii=False)))
    if collection == 'categories':
        for doc_id, d in docs:
            _mirror_category(conn, doc_id, d)
        _mirror_all_products(conn)  # kategori yeni geldiyse bekleyen ürünler bağlansın
    elif collection == 'products':
        for doc_id, d in docs:
            _mirror_product(conn, doc_id, d)
    _hide_legacy_menu_if_cloud(conn)
    conn.commit()
    conn.close()


def _mirror_category(conn, cloud_id, d):
    values = (d.get('name', ''), d.get('color', '#6C5CE7'), int(d.get('order') or 0),
              1 if d.get('deleted') else 0)
    row = conn.execute("SELECT id FROM categories WHERE cloud_id=?", (cloud_id,)).fetchone()
    if row:
        conn.execute("UPDATE categories SET ad=?, renk=?, sira=?, silindi=? WHERE id=?", values + (row['id'],))
    else:
        conn.execute("INSERT INTO categories (ad,renk,sira,silindi,cloud_id) VALUES (?,?,?,?,?)",
                     values + (cloud_id,))


def _mirror_product(conn, cloud_id, d):
    cat = conn.execute("SELECT id FROM categories WHERE cloud_id=?", (d.get('categoryId'),)).fetchone()
    if not cat:
        return  # kategori henüz inmedi; kategori gelince _mirror_all_products bağlar
    aktif = 1 if d.get('active', True) and not d.get('deleted') else 0
    values = (d.get('name', ''), (d.get('price') or 0) / 100.0, cat['id'], aktif, 1 if d.get('soldOut') else 0)
    row = conn.execute("SELECT id FROM products WHERE cloud_id=?", (cloud_id,)).fetchone()
    if row:
        conn.execute("UPDATE products SET ad=?, fiyat=?, kategori_id=?, aktif=?, tukendi=? WHERE id=?",
                     values + (row['id'],))
    else:
        conn.execute("INSERT INTO products (ad,fiyat,kategori_id,aktif,tukendi,cloud_id) VALUES (?,?,?,?,?,?)",
                     values + (cloud_id,))


def _mirror_all_products(conn):
    for r in conn.execute("SELECT id, data FROM cloud_cache WHERE collection='products'").fetchall():
        _mirror_product(conn, r['id'], json.loads(r['data']))


def _hide_legacy_menu_if_cloud(conn):
    """Bulutta menü varsa buluta bağlı olmayan eski yerel menü satış ekranından kalkar."""
    rows = conn.execute("SELECT data FROM cloud_cache WHERE collection='categories'").fetchall()
    if any(not json.loads(r['data']).get('deleted') for r in rows):
        conn.execute("UPDATE products SET aktif=0 WHERE cloud_id IS NULL")
        conn.execute("UPDATE categories SET silindi=1 WHERE cloud_id IS NULL")


def _menu_rows(collection, include_deleted=False):
    conn = get_connection()
    rows = conn.execute("SELECT id, data FROM cloud_cache WHERE collection=?", (collection,)).fetchall()
    conn.close()
    items = []
    for r in rows:
        d = json.loads(r['data'])
        if include_deleted or not d.get('deleted'):
            items.append({**d, 'id': r['id']})
    return sorted(items, key=lambda x: (x.get('order') or 0, x.get('name', '')))


def menu_categories(include_deleted=False):
    return _menu_rows('categories', include_deleted)


def menu_option_groups():
    return _menu_rows('optionGroups')


def menu_products(category_id=None):
    items = _menu_rows('products')
    return [p for p in items if category_id is None or p.get('categoryId') == category_id]


def menu_item(collection, item_id):
    conn = get_connection()
    row = conn.execute("SELECT data FROM cloud_cache WHERE collection=? AND id=?", (collection, item_id)).fetchone()
    conn.close()
    return {**json.loads(row['data']), 'id': item_id} if row else None


def legacy_menu_for_import():
    """Buluta aktarılmamış yerel menü: (kategoriler, ürünler). Fiyatlar kuruşa çevrilir."""
    conn = get_connection()
    cats = conn.execute("""SELECT * FROM categories WHERE cloud_id IS NULL AND COALESCE(silindi,0)=0
        ORDER BY sira,id""").fetchall()
    prods = conn.execute("""SELECT * FROM products WHERE cloud_id IS NULL AND aktif=1 ORDER BY id""").fetchall()
    conn.close()
    cat_ids = {c['id'] for c in cats}
    return ([dict(c) for c in cats],
            [{**dict(p), 'price': int(round((p['fiyat'] or 0) * 100))} for p in prods if p['kategori_id'] in cat_ids])


# Aktarımda isimden istasyon / damga tahmini (sonradan ekrandan değiştirilebilir)
DRINK_WORDS = ('kahve', 'içecek', 'icecek', 'çay', 'coffee', 'drink', 'smoothie', 'limonata')


def turkish_lower(text):
    """Türkçe küçük harf: 'İçecek' → 'içecek' (str.lower() 'i̇çecek' üretir), 'IŞIK' → 'ışık'."""
    return (text or '').replace('İ', 'i').replace('I', 'ı').lower()


_TR_ALPHABET = 'abcçdefgğhıijklmnoöprsştuüvyz'
_TR_ORDER = {ch: i for i, ch in enumerate(_TR_ALPHABET)}


def turkish_sort_key(text):
    """Türkçe alfabe sırası: 'Çift' 'Cem'den sonra, 'Deniz'den önce gelir."""
    return [(_TR_ORDER[ch], '') if ch in _TR_ORDER else (-1, ch) if ch.isdigit() or ch == ' ' else (100, ch)
            for ch in turkish_lower(text)]


def legacy_import_payload():
    """importMenu fonksiyonuna gönderilecek (kategoriler, ürünler) listeleri."""
    cats, prods = legacy_menu_for_import()
    payload_cats = []
    for c in cats:
        drink = any(w in turkish_lower(c['ad']) for w in DRINK_WORDS)
        color = c['renk'] if isinstance(c['renk'], str) and len(c['renk']) == 7 else '#6C5CE7'
        payload_cats.append({'localId': c['id'], 'name': c['ad'], 'color': color,
                             'station': 'bar' if drink else 'kitchen', 'stampEligible': drink})
    payload_prods = [{'localId': p['id'], 'localCategoryId': p['kategori_id'], 'name': p['ad'],
                      'price': p['price']} for p in prods]
    return payload_cats, payload_prods


def apply_import_mapping(category_map, product_map):
    """Aktarımdan sonra yerel satırları bulut kimlikleriyle eşler (çift kayıt oluşmasın)."""
    conn = get_connection()
    for local_id, cloud_id in category_map.items():
        conn.execute("UPDATE categories SET cloud_id=? WHERE id=?", (cloud_id, int(local_id)))
    for local_id, cloud_id in product_map.items():
        conn.execute("UPDATE products SET cloud_id=? WHERE id=?", (cloud_id, int(local_id)))
    conn.commit()
    conn.close()


def set_sold_out(staff_id, sold_out, product_id=None, option_group_id=None, option_id=None):
    """
    Ürünü ya da tek bir seçeneği tükendi işaretler. İnternet gerekmez: yerelde hemen
    uygulanır, işlem kuyruğa yazılır ve senkronla buluta gider.
    """
    conn = get_connection()
    if product_id:
        row = conn.execute("SELECT data FROM cloud_cache WHERE collection='products' AND id=?",
                           (product_id,)).fetchone()
        if not row:
            conn.close()
            raise ValueError("Ürün bulunamadı.")
        d = {**json.loads(row['data']), 'soldOut': sold_out}
        conn.execute("UPDATE cloud_cache SET data=? WHERE collection='products' AND id=?",
                     (json.dumps(d, ensure_ascii=False), product_id))
        conn.execute("UPDATE products SET tukendi=? WHERE cloud_id=?", (1 if sold_out else 0, product_id))
        payload = {'productId': product_id, 'soldOut': sold_out}
    else:
        row = conn.execute("SELECT data FROM cloud_cache WHERE collection='optionGroups' AND id=?",
                           (option_group_id,)).fetchone()
        if not row:
            conn.close()
            raise ValueError("Seçenek grubu bulunamadı.")
        d = json.loads(row['data'])
        d['options'] = [{**o, 'soldOut': sold_out} if o.get('id') == option_id else o
                        for o in d.get('options', [])]
        conn.execute("UPDATE cloud_cache SET data=? WHERE collection='optionGroups' AND id=?",
                     (json.dumps(d, ensure_ascii=False), option_group_id))
        payload = {'optionGroupId': option_group_id, 'optionId': option_id, 'soldOut': sold_out}
    enqueue_op('setSoldOut', payload, staff_id, conn=conn)
    conn.commit()
    conn.close()


# =====================================================================
# Salon planı önbelleği (3. ekran)
# Bölgeler (areas) ve masalar (tables) bulutta; eski regions/tables tablolarına
# yansıtılır. Masanın anlık durumu (durum, garson_id) 4. ekrana kadar yerelde kalır.
# =====================================================================

FLOOR_COLLECTIONS = ('areas', 'tables')


def upsert_floor(collection, docs):
    if not docs:
        return
    conn = get_connection()
    for doc_id, d in docs:
        conn.execute("""INSERT INTO cloud_cache (collection,id,data) VALUES (?,?,?)
            ON CONFLICT(collection,id) DO UPDATE SET data=excluded.data""",
            (collection, doc_id, json.dumps(d, ensure_ascii=False)))
    if collection == 'areas':
        for doc_id, d in docs:
            _mirror_region(conn, doc_id, d)
        _mirror_all_tables(conn)
    else:
        for doc_id, d in docs:
            _mirror_table(conn, doc_id, d)
    _hide_legacy_floor_if_cloud(conn)
    conn.commit()
    conn.close()


def _mirror_region(conn, cloud_id, d):
    values = (d.get('name', ''), int(d.get('order') or 0), 1 if d.get('deleted') else 0)
    row = conn.execute("SELECT id FROM regions WHERE cloud_id=?", (cloud_id,)).fetchone()
    if row:
        conn.execute("UPDATE regions SET ad=?, sira=?, silindi=? WHERE id=?", values + (row['id'],))
    else:
        conn.execute("INSERT INTO regions (ad,sira,silindi,cloud_id) VALUES (?,?,?,?)", values + (cloud_id,))


def _mirror_table(conn, cloud_id, d):
    region = conn.execute("SELECT id FROM regions WHERE cloud_id=?", (d.get('areaId'),)).fetchone()
    if not region:
        return  # bölge henüz inmedi; inince _mirror_all_tables bağlar
    values = (d.get('name', ''), region['id'], 1 if d.get('deleted') else 0)
    row = conn.execute("SELECT id FROM tables WHERE cloud_id=?", (cloud_id,)).fetchone()
    if row:
        # durum ve garson_id yerel kalır (adisyonlar 4. ekrana kadar yerelde)
        conn.execute("UPDATE tables SET ad=?, region_id=?, silindi=? WHERE id=?", values + (row['id'],))
    else:
        conn.execute("INSERT INTO tables (ad,region_id,silindi,cloud_id) VALUES (?,?,?,?)", values + (cloud_id,))


def _mirror_all_tables(conn):
    for r in conn.execute("SELECT id, data FROM cloud_cache WHERE collection='tables'").fetchall():
        _mirror_table(conn, r['id'], json.loads(r['data']))


def _hide_legacy_floor_if_cloud(conn):
    rows = conn.execute("SELECT data FROM cloud_cache WHERE collection='areas'").fetchall()
    if any(not json.loads(r['data']).get('deleted') for r in rows):
        conn.execute("UPDATE regions SET silindi=1 WHERE cloud_id IS NULL")
        conn.execute("UPDATE tables SET silindi=1 WHERE cloud_id IS NULL")


def floor_areas():
    return _menu_rows('areas')


def floor_tables(area_id=None):
    return [t for t in _menu_rows('tables') if area_id is None or t.get('areaId') == area_id]


def floor_table_states(area_id):
    """
    Plan görünümü için masalar: bulut planı (konum, şekil) + yerel durum (dolu/boş,
    tutar, süre). Her öğe eski ekranların beklediği masa sözlüğünü ('legacy') taşır.
    """
    conn = get_connection()
    region = conn.execute("SELECT id FROM regions WHERE cloud_id=?", (area_id,)).fetchone()
    conn.close()
    legacy = {t['cloud_id']: t for t in get_tables_by_region(region['id'])} if region else {}
    return [{**t, 'legacy': legacy.get(t['id'])} for t in floor_tables(area_id)]


def area_has_open_orders(area_id=None, table_ids=None):
    """Silinmek istenen bölge/masalarda açık adisyon var mı? (adisyonlar yerelde)"""
    conn = get_connection()
    q = """SELECT t.ad FROM tables t JOIN orders o ON o.masa_id = t.id
           LEFT JOIN regions r ON r.id = t.region_id
           WHERE o.durum IN ('hazirlaniyor','bekliyor')"""
    params = []
    if area_id:
        q += " AND r.cloud_id=?"
        params.append(area_id)
    if table_ids is not None:
        if not table_ids:
            conn.close()
            return []
        q += f" AND t.cloud_id IN ({','.join('?' * len(table_ids))})"
        params += list(table_ids)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return sorted({r['ad'] for r in rows})


def set_table_reserved(local_table_id, reserved, staff_id=None):
    """Boş masayı elle rezerve işaretler / işareti kaldırır (dolu masaya dokunmaz)."""
    conn = get_connection()
    if reserved:
        cur = conn.execute("UPDATE tables SET durum='rezerve' WHERE id=? AND durum='bos'", (local_table_id,))
    else:
        cur = conn.execute("UPDATE tables SET durum='bos' WHERE id=? AND durum='rezerve'", (local_table_id,))
    changed = cur.rowcount == 1
    row = conn.execute("SELECT cloud_id FROM tables WHERE id=?", (local_table_id,)).fetchone()
    if changed and staff_id and row and row['cloud_id']:
        enqueue_op('setTableReserved', {'tableId': row['cloud_id'], 'reserved': bool(reserved)}, staff_id, conn=conn)
    conn.commit()
    conn.close()
    return changed


def legacy_floor_payload():
    """importFloor'a gönderilecek eski bölge/masa düzeni."""
    conn = get_connection()
    regions = conn.execute("""SELECT * FROM regions WHERE cloud_id IS NULL AND COALESCE(silindi,0)=0
        ORDER BY sira, id""").fetchall()
    payload = []
    for r in regions:
        tables = conn.execute("""SELECT id, ad FROM tables WHERE region_id=? AND cloud_id IS NULL
            AND COALESCE(silindi,0)=0 ORDER BY id""", (r['id'],)).fetchall()
        payload.append({'localId': r['id'], 'name': r['ad'],
                        'tables': [{'localId': t['id'], 'name': t['ad']} for t in tables]})
    conn.close()
    return payload


def apply_floor_mapping(area_map, table_map):
    conn = get_connection()
    for local_id, cloud_id in area_map.items():
        conn.execute("UPDATE regions SET cloud_id=? WHERE id=?", (cloud_id, int(local_id)))
    for local_id, cloud_id in table_map.items():
        conn.execute("UPDATE tables SET cloud_id=? WHERE id=?", (cloud_id, int(local_id)))
    conn.commit()
    conn.close()


def general_settings():
    """settings/general (kafe adı, QR adresi, otomatik kilit); yoksa varsayılanlar."""
    data = get_setting('general') or {}
    return {
        'cafeName': data.get('cafeName') or 'Kafem',
        'qrBaseUrl': data.get('qrBaseUrl') or '',
        'idleLockMinutes': data.get('idleLockMinutes') or 3,
    }


# Modüller (5. ve 6. ekran): settings/modules. Sunucudaki validateModules ile aynı varsayılanlar.
DEFAULT_MODULES = {
    'kds': {'enabled': False, 'warnMinutes': 10, 'lateMinutes': 20, 'sound': True},
    'cashSession': {'required': False, 'diffReasonThreshold': 2000},
    'printing': {'enabled': False, 'kitchenTickets': False},
    'paymentMethods': {'cash': True, 'card': True, 'meal': True},
    'tips': True,
    'stock': {'enabled': False, 'askOnVoid': True},
    'staff': {'enabled': False, 'lateToleranceMinutes': 5},
    'loyalty': {'enabled': False},
    'campaigns': {'enabled': False},
}


def modules():
    """Önbellekteki modül ayarları; eksik alanlar varsayılandan doldurulur."""
    data = get_setting('modules') or {}
    out = {}
    for key, default in DEFAULT_MODULES.items():
        value = data.get(key)
        if isinstance(default, dict):
            value = value if isinstance(value, dict) else {}
            out[key] = {k: (value[k] if type(value.get(k)) is type(v) else v) for k, v in default.items()}
        else:
            out[key] = value if type(value) is type(default) else default
    return out


def open_cash_session():
    """Bu terminalde açık kasa oturumu: {'id', ...data} ya da None."""
    conn = get_connection()
    row = conn.execute("SELECT data FROM cash_sessions WHERE status='open' ORDER BY opened_at DESC LIMIT 1").fetchone()
    conn.close()
    return json.loads(row['data']) if row else None


# Mutfak / bar ekranı (5. ekran): fiş durumu buluttan iner.
TICKET_CLOUD_FIELDS = ('status', 'doneLineIds', 'preparingAt', 'readyAt', 'tableName', 'lines', 'cancelled')


def upsert_cloud_tickets(docs):
    """
    Mutfak ekranının değiştirdiği fişleri yerel fiş panosuna yansıtır. Kasada "teslim
    edildi" (served) olan fiş geri açılmaz. Hazır olan fiş bir kez bildirilmek üzere
    işaretlenir (notifyReady).
    """
    conn = get_connection()
    for ticket_id, data in docs:
        row = conn.execute("SELECT data FROM pos_tickets WHERE id=?", (ticket_id,)).fetchone()
        if not row:
            continue
        local = json.loads(row['data'])
        if local.get('status') == 'served':
            continue
        merged = {**local, **{k: data[k] for k in TICKET_CLOUD_FIELDS if k in data}}
        if merged['status'] == 'ready' and local.get('status') != 'ready' and not merged.get('cancelled'):
            merged['notifyReady'] = True
        conn.execute("UPDATE pos_tickets SET data=?, status=? WHERE id=?",
                     (json.dumps(merged, ensure_ascii=False), merged['status'], ticket_id))
    conn.commit()
    conn.close()


def take_ready_notifications():
    """Bildirilmemiş "hazır" fişler; döndürülenler bildirildi olarak işaretlenir."""
    conn = get_connection()
    rows = conn.execute("SELECT id, data FROM pos_tickets WHERE status='ready'").fetchall()
    out = []
    for r in rows:
        data = json.loads(r['data'])
        if data.pop('notifyReady', False):
            out.append(data)
            conn.execute("UPDATE pos_tickets SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), r['id']))
    conn.commit()
    conn.close()
    return out


def orders_with_ready_tickets():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT order_id FROM pos_tickets WHERE status='ready'").fetchall()
    conn.close()
    return {r['order_id'] for r in rows}


def upsert_cache(collection, docs):
    """Eski tablolara yansıması olmayan bulut koleksiyonları (ör. malzemeler) için önbellek."""
    if not docs:
        return
    conn = get_connection()
    for doc_id, d in docs:
        conn.execute("""INSERT INTO cloud_cache (collection,id,data) VALUES (?,?,?)
            ON CONFLICT(collection,id) DO UPDATE SET data=excluded.data""",
            (collection, doc_id, json.dumps(d, ensure_ascii=False)))
    conn.commit()
    conn.close()


def cache_rows(collection, include_deleted=False):
    return _menu_rows(collection, include_deleted)
