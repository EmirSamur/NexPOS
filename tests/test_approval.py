"""Yetkili onayı penceresi: doğru/yanlış PIN, yetki varsa pencere açılmaz."""
import json

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from tests.test_local import seed


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_yetkisi_olan_icin_pencere_acilmaz(db, app):
    from access import request_approval
    seed(db, 'k1', 'cashier', pin='640218')
    cashier = db.login_with_pin('k1', '640218')
    approver, reason = request_approval(None, cashier, 'discount', 'Masa 1 · %10 iskonto')
    assert approver is cashier and reason is None


def test_yetkili_pin_ile_onaylar_ve_kayit_kuyruga_duser(db, app):
    from access import ApprovalDialog
    seed(db, 'g1', 'waiter', pin='730591')
    seed(db, 'm1', 'manager', pin='583920')
    waiter = db.login_with_pin('g1', '730591')

    dlg = ApprovalDialog(waiter, 'voidItem', 'Sipariş #12 iptali')
    assert dlg.approver_box.count() == 1  # yalnızca müdür listelenir, garsonun kendisi değil
    dlg._on_pin('000001')
    assert dlg.result() != QDialog.Accepted
    assert 'Kalan deneme' in dlg.pad.error_label.text()
    dlg._on_pin('583920')
    assert dlg.result() == QDialog.Accepted
    assert dlg.approver['id'] == 'm1'
    assert dlg.reason == 'Müşteri vazgeçti'


def test_onay_kaydi_audit_olarak_kuyruga_yazilir(db, app, monkeypatch):
    import access
    seed(db, 'g1', 'waiter', pin='730591')
    seed(db, 'm1', 'manager', pin='583920')
    waiter = db.login_with_pin('g1', '730591')

    class FakeDialog:
        def __init__(self, *a):
            self.approver = db.get_staff('m1')
            self.reason = 'Yanlış girildi'

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(access, 'ApprovalDialog', FakeDialog)
    approver, reason = access.request_approval(None, waiter, 'voidItem', 'Sipariş #12 iptali')
    assert approver['id'] == 'm1' and reason == 'Yanlış girildi'
    audit = [o for o in db.get_pending_ops() if o['op'] == 'audit'][0]
    assert audit['staff_id'] == 'g1'
    assert json.loads(audit['payload']) == {
        'action': 'approval_voiditem', 'detail': 'Sipariş #12 iptali',
        'reason': 'Yanlış girildi', 'approvedBy': 'm1'}


def test_yetkili_yoksa_pin_kapali(db, app):
    from access import ApprovalDialog
    seed(db, 'g1', 'waiter', pin='730591')
    waiter = db.login_with_pin('g1', '730591')
    dlg = ApprovalDialog(waiter, 'refund', 'İade')
    assert dlg.approver_box.count() == 0
    assert not dlg.pad.isEnabled()
