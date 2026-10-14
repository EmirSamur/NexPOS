"""
NexPOS - Yetki kontrolleri
  - request_approval: yetkisiz işlemde yetkili (müdür vb.) PIN onayı
  - require_admin_api: buluta yazan panel işlemleri için yönetici oturumu
"""
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from styles import COLORS, FONTS
from auth_widgets import PinPad
from cloud.context import ctx
from cloud.permissions import PERMISSION_LABELS, ROLE_LABELS
import database

DEFAULT_REASONS = {
    'voidItem': ["Müşteri vazgeçti", "Yanlış girildi", "Ürün bitti", "Diğer"],
    'discount': ["Müdür onayı", "Sürekli müşteri", "Şikâyet telafisi", "Personel indirimi", "Diğer"],
    'comp': ["Bekleme telafisi", "Sürekli müşteri", "Diğer"],
    'refund': ["Ürün beğenilmedi", "Hatalı ürün", "Diğer"],
}


def request_approval(parent, user, permission, action_text):
    """
    Kullanıcının yetkisi varsa (onaylayan, sebep) olarak (user, None) döner.
    Yoksa yetkili onayı penceresini açar; onaylanırsa (onaylayan_personel, sebep),
    vazgeçilirse (None, None) döner. Onay, işlem kuyruğu üzerinden auditLogs'a yazılır.
    """
    if database.user_can(user, permission):
        return user, None
    dlg = ApprovalDialog(user, permission, action_text, parent)
    if dlg.exec() != QDialog.Accepted:
        return None, None
    database.enqueue_op('audit', {
        'action': f'approval_{permission.lower()}',
        'detail': action_text,
        'reason': dlg.reason,
        'approvedBy': dlg.approver['id'],
    }, user['cloud_id'])
    ctx.request_sync()
    return dlg.approver, dlg.reason


class ApprovalDialog(QDialog):
    def __init__(self, user, permission, action_text, parent=None):
        super().__init__(parent)
        self.user = user
        self.permission = permission
        self.approver = None
        self.reason = None
        self.setWindowTitle("Yetkili Onayı")
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(32, 24, 32, 24)
        ly.setSpacing(10)

        head = QLabel("🔒  Bu işlem için yetkili onayı gerekir")
        head.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        head.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        ly.addWidget(head)
        info = QLabel(f"İşlem: <b>{action_text}</b><br>"
                      f"Gereken yetki: {PERMISSION_LABELS.get(permission, permission)}<br>"
                      f"İsteyen: {user.get('ad_soyad', '')}")
        info.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        ly.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Neden:"))
        self.reason_box = QComboBox()
        self.reason_box.setEditable(True)
        self.reason_box.addItems(DEFAULT_REASONS.get(permission, ["Diğer"]))
        row.addWidget(self.reason_box, 1)
        ly.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Yetkili:"))
        self.approver_box = QComboBox()
        candidates = database.staff_with_permission(permission, exclude_id=user.get('cloud_id'))
        for s in candidates:
            self.approver_box.addItem(f"{s['name']} ({ROLE_LABELS.get(s['role'], s['role'])})", s)
        row2.addWidget(self.approver_box, 1)
        ly.addLayout(row2)

        if not candidates:
            empty = QLabel("Bu yetkiye sahip aktif personel yok. Yetki matrisini kontrol edin.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
            ly.addWidget(empty)

        self.pad = PinPad()
        self.pad.submitted.connect(self._on_pin)
        self.pad.setEnabled(bool(candidates))
        ly.addWidget(self.pad, 0, Qt.AlignCenter)

        cancel = QPushButton("Vazgeç")
        cancel.setObjectName("ghostBtn")
        cancel.clicked.connect(self.reject)
        ly.addWidget(cancel)
        self.pad.setFocus()

    def _on_pin(self, pin):
        approver = self.approver_box.currentData()
        if not approver:
            return
        try:
            database.check_pin(approver['id'], pin)
        except database.LoginError as e:
            self.pad.show_error(str(e))
            return
        self.approver = approver
        self.reason = self.reason_box.currentText().strip() or None
        self.accept()


def require_admin_api(parent, user):
    """
    Buluta yazan panel işlemleri için yöneticinin kendi Firebase oturumunu döndürür
    (AdminApi). PIN ile girildiyse bir kez şifre sorulur; oturum kullanıcı değişene
    kadar bellekte tutulur. Vazgeçilirse ya da internet yoksa None döner.
    """
    api = ctx.admin_api(user.get('cloud_id'))
    if api:
        return api
    if not ctx.client:
        QMessageBox.warning(parent, "Bulut Ayarı Yok", "Bu işlem için bulut bağlantısı ayarlanmamış.")
        return None
    if not user.get('email'):
        QMessageBox.warning(parent, "Yetki Yok",
                            "Bu işlem yalnızca e-posta hesabı olan yönetici veya müdür tarafından yapılabilir.")
        return None
    from login_screen import ManagerLoginDialog
    dlg = ManagerLoginDialog(parent, email=user['email'], title="Şifre Onayı",
                             note="Bu değişiklik doğrudan buluta kaydedilir. Devam etmek için "
                                  "şifrenizi girin (internet gerekir).",
                             start_session=False)
    dlg.email.setReadOnly(True)
    if dlg.exec() != QDialog.Accepted or not dlg.session:
        return None
    return ctx.admin_api(user.get('cloud_id'))
