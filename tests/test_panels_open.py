"""Ekranlar açılıyor mu: yönetici paneli (bütün sayfalar, bütün modüller açık) ve garson/kasa paneli.

Sayfaların tek tek testleri var; bu test paneli bir bütün olarak kurar (eksik bir sayfa yöntemi gibi hatalar
yalnızca burada yakalanır)."""
from tests.test_local import seed

ALL_MODULES = {'kds': {'enabled': True}, 'stock': {'enabled': True}, 'staff': {'enabled': True},
               'loyalty': {'enabled': True}, 'campaigns': {'enabled': True},
               'app': {'enabled': True, 'tableOrders': True, 'pickup': True}}


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_yonetici_paneli_butun_sayfalar(db):
    seed(db, 'o1', 'owner', pin='482913')
    db.set_setting('modules', ALL_MODULES)
    user = db.login_with_pin('o1', '482913')
    _app()
    from admin_panel import AdminPanel
    panel = AdminPanel(user)
    visible = [i for i in range(panel.pages.count()) if panel._can_see(i)]
    assert len(visible) == panel.pages.count() == 14
    for i in visible:
        panel._show_page(i)
        assert panel.pages.currentIndex() == i


def test_garson_ve_kasa_paneli(db):
    from user_panel import UserPanel
    _app()
    db.set_setting('modules', ALL_MODULES)
    for sid, role, pin in (('w1', 'waiter', '730591'), ('c1', 'cashier', '640218'), ('o1', 'owner', '482913')):
        seed(db, sid, role, pin=pin)
        panel = UserPanel(db.login_with_pin(sid, pin))
        for idx in range(panel.pages.count()):
            panel.pages.setCurrentIndex(idx)
        panel.on_app_orders_changed()
