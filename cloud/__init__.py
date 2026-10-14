"""
NexPOS bulut katmanı: Firebase bağlantısı, çevrimdışı işlem kuyruğu ve senkron.

Ekranlar bu pakete doğrudan değil, database.py üzerinden erişir. İstisna olarak
yönetim panelindeki çevrimiçi işlemler (personel, yetki, terminal) admin_api.py'yi kullanır.
"""
