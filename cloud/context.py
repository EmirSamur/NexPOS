"""
Uygulama genelinde paylaşılan bulut nesneleri (tek örnek).

main.py açılışta doldurur; ekranlar buradan okur. Testlerde ve bulut ayarı
yokken alanlar None kalır, ekranlar bu durumda yalnızca yerel veriyle çalışır.
"""
from cloud.admin_api import AdminApi


class _Context:
    def __init__(self):
        self.config = None
        self.client = None
        self.creds = None
        self.engine = None
        self.worker = None
        self.last_status = None
        # Panele e-posta ile giren yönetici/müdürlerin oturumları (staff_id → Session).
        # Bellekte tutulur, diske yazılmaz; kullanıcı değişince silinir.
        self._panel_sessions = {}

    @property
    def online(self):
        return bool(self.last_status and self.last_status.online)

    def request_sync(self):
        if self.worker:
            self.worker.request_sync()

    def set_panel_session(self, staff_id, session):
        self._panel_sessions[staff_id] = session

    def panel_session(self, staff_id):
        return self._panel_sessions.get(staff_id)

    def clear_panel_sessions(self):
        self._panel_sessions.clear()

    def admin_api(self, staff_id):
        session = self.panel_session(staff_id)
        return AdminApi(self.client, session) if session and self.client else None


ctx = _Context()
