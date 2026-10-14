"""
Yönetim panelinin buluta doğrudan yazdığı işlemler (internet gerektirir).

Bu işlemler terminal hesabıyla değil, panele giren yöneticinin/müdürün kendi
Firebase hesabıyla yapılır; böylece sunucu kimin ne yaptığını bilir ve yetkisini
kontrol eder.
"""
from cloud.firebase_client import ApiError


class AdminApi:
    def __init__(self, client, session):
        self.client = client
        self.session = session

    def _call(self, name, data):
        self.session = self.client.ensure_fresh(self.session)
        return self.client.call(name, data, self.session)

    def create_staff(self, name, role, pin, phone=None, email=None, password=None):
        data = {'action': 'create', 'name': name, 'role': role, 'pin': pin, 'phone': phone}
        if email:
            data['email'] = email
            data['password'] = password
        return self._call('manageStaff', data)

    def update_staff(self, staff_id, name, role, phone=None, email=None, password=None):
        data = {'action': 'update', 'staffId': staff_id, 'name': name, 'role': role, 'phone': phone}
        if email:
            data['email'] = email
        if password:
            data['password'] = password
        return self._call('manageStaff', data)

    def set_pin(self, staff_id, pin):
        return self._call('manageStaff', {'action': 'setPin', 'staffId': staff_id, 'pin': pin})

    def set_active(self, staff_id, active):
        return self._call('manageStaff', {'action': 'setActive', 'staffId': staff_id, 'active': active})

    def save_permissions(self, roles):
        return self._call('savePermissions', {'roles': roles})

    def list_terminals(self):
        self.session = self.client.ensure_fresh(self.session)
        return self.client.list_docs('terminals', self.session)

    def revoke_terminal(self, terminal_id):
        return self._call('revokeTerminal', {'terminalId': terminal_id})


__all__ = ['AdminApi', 'ApiError']
