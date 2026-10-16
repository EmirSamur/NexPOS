"""
NexPOS - Giriş Ekranı
Personel kartları + PIN ile giriş (internetsiz de çalışır).
Yönetici/müdür isterse e-posta ve şifreyle de girebilir (panel işlemleri için).
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout, QFrame,
    QGridLayout, QScrollArea, QDialog, QFormLayout
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from styles import COLORS, FONTS, ICONS
from auth_widgets import PinDialog, StaffCard, SyncStatusPill
from cloud.context import ctx
from cloud.permissions import PANEL_ROLES, ROLE_LABELS
from cloud.qt_sync import run_async
import database
import shifts
from shifts_pages import clock_badge, maybe_prompt_clock_in

GRID_COLUMNS = 4


class LoginScreen(QWidget):
    login_success = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(1000, 600)
        self._setup_ui()
        self.refresh_staff()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._create_brand_panel(), 2)

        # ===== SAĞ - Personel kartları =====
        right = QFrame()
        right.setStyleSheet(f"background-color: {COLORS['bg_main']};")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(56, 36, 56, 32)
        rl.setSpacing(8)

        top = QHBoxLayout()
        self.terminal_label = QLabel("NexPOS")
        self.terminal_label.setFont(QFont(FONTS['family'], 16, QFont.Bold))
        self.terminal_label.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
        top.addWidget(self.terminal_label)
        top.addStretch()
        self.status_pill = SyncStatusPill()
        top.addWidget(self.status_pill)
        rl.addLayout(top)

        rl.addSpacing(28)
        welcome = QLabel("Kim çalışıyor?")
        welcome.setFont(QFont(FONTS['family'], FONTS['size_xxl'], QFont.Bold))
        welcome.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        rl.addWidget(welcome)
        subtitle = QLabel("Kartınıza dokunun ve 6 haneli PIN kodunuzu girin.")
        subtitle.setFont(QFont(FONTS['family'], FONTS['size_md']))
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        rl.addWidget(subtitle)
        rl.addSpacing(20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(holder)
        self.grid.setSpacing(18)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(holder)
        rl.addWidget(scroll, 1)

        self.empty_label = QLabel(
            "Bu bilgisayarda henüz personel yok.\n\n"
            "Personel listesi buluttan iner; internet bağlantısını kontrol edin.\n"
            "Personel eklemek için yönetici olarak e-postayla giriş yapın.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"""
            color: {COLORS['text_secondary']}; background: white; font-size: 13px;
            border: 1.5px dashed {COLORS['border']}; border-radius: 16px; padding: 32px;
        """)
        rl.addWidget(self.empty_label)

        bottom = QHBoxLayout()
        bottom.addStretch()
        manager_link = QPushButton("Yönetici girişi (e-posta) →")
        manager_link.setCursor(Qt.PointingHandCursor)
        manager_link.setStyleSheet(f"""
            QPushButton {{ border: none; color: {COLORS['primary']};
                font-size: {FONTS['size_md']}px; background: transparent; font-weight: bold; }}
            QPushButton:hover {{ color: {COLORS['primary_dark']}; text-decoration: underline; }}
        """)
        manager_link.clicked.connect(self._manager_login)
        bottom.addWidget(manager_link)
        rl.addLayout(bottom)

        main_layout.addWidget(right, 3)

    def _create_brand_panel(self):
        left = QFrame()
        left.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0,y1:0,x2:0.3,y2:1,
                    stop:0 #0F172A, stop:0.4 #1E1B4B, stop:1 #4F46E5);
            }
        """)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(48, 60, 48, 40)
        ll.setSpacing(12)
        ll.addStretch(1)

        logo_frame = QHBoxLayout()
        logo_dot = QLabel("N")
        logo_dot.setFixedSize(48, 48)
        logo_dot.setAlignment(Qt.AlignCenter)
        logo_dot.setFont(QFont(FONTS['family'], 22, QFont.Bold))
        logo_dot.setStyleSheet("""
            color: white; border-radius: 14px;
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #818CF8, stop:1 #4F46E5);
        """)
        logo_frame.addWidget(logo_dot)
        logo_frame.addSpacing(12)
        logo = QLabel("NexPOS")
        logo.setFont(QFont(FONTS['family'], 34, QFont.Bold))
        logo.setStyleSheet("color: white; background: transparent; letter-spacing: 3px;")
        logo_frame.addWidget(logo)
        logo_frame.addStretch()
        ll.addLayout(logo_frame)

        tagline = QLabel("Kafenizi akıllıca yönetin.")
        tagline.setFont(QFont(FONTS['family'], FONTS['size_lg']))
        tagline.setStyleSheet("color: rgba(255,255,255,0.6); background: transparent;")
        ll.addWidget(tagline)
        ll.addSpacing(32)

        features = [
            ("PIN ile hızlı giriş", "Kullanıcı değiştirmek saniyeler sürer"),
            ("İnternet olmasa da çalışır", "İşlemler internet gelince gönderilir"),
            ("Rol bazlı yetki", "Yetkisiz işlemde müdür onayı istenir"),
            ("Bulutta yedekli", "Bilgisayar bozulsa da veri kaybolmaz"),
        ]
        for title, desc in features:
            f_frame = QFrame()
            f_frame.setStyleSheet("QFrame { background: rgba(255,255,255,0.06); border-radius: 12px; border: none; }")
            f_ly = QHBoxLayout(f_frame)
            f_ly.setContentsMargins(16, 12, 16, 12)
            f_ly.setSpacing(12)
            check = QLabel(ICONS['check'])
            check.setFont(QFont(FONTS['family'], 16, QFont.Bold))
            check.setStyleSheet("color: #818CF8; background: transparent;")
            check.setFixedWidth(24)
            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            tx = QLabel(title)
            tx.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
            tx.setStyleSheet("color: rgba(255,255,255,0.9); background: transparent;")
            dx = QLabel(desc)
            dx.setFont(QFont(FONTS['family'], FONTS['size_xs']))
            dx.setStyleSheet("color: rgba(255,255,255,0.45); background: transparent;")
            text_col.addWidget(tx)
            text_col.addWidget(dx)
            f_ly.addWidget(check)
            f_ly.addLayout(text_col, 1)
            ll.addWidget(f_frame)

        ll.addStretch(2)
        ver = QLabel("v4.0.0  |  NexPOS")
        ver.setFont(QFont(FONTS['family'], FONTS['size_xs']))
        ver.setStyleSheet("color: rgba(255,255,255,0.25); background: transparent;")
        ll.addWidget(ver)
        return left

    # ------------------------------------------------------------------
    def set_terminal_name(self, letter, name):
        if name:
            self.terminal_label.setText(f"NexPOS · {name} ({letter})")

    def set_sync_status(self, status):
        self.status_pill.update_status(status)
        if status and ({'staff', 'staffPins', 'shiftPlans', 'modules'} & status.changed):
            self.refresh_staff()

    def refresh_staff(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        shifts.auto_close_forgotten()  # iş günü bitmiş, çıkışı unutulmuş mesailer
        staff = database.get_login_staff()
        for i, s in enumerate(staff):
            card = StaffCard(s, ROLE_LABELS.get(s['role'], s['role']), badge=clock_badge(s['id']))
            card.clicked.connect(lambda _, st=s: self._pin_login(st))
            self.grid.addWidget(card, i // GRID_COLUMNS, i % GRID_COLUMNS)
        self.empty_label.setVisible(not staff)

    def _pin_login(self, staff):
        dlg = PinDialog(staff, lambda pin: database.login_with_pin(staff['id'], pin), parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.result_value:
            maybe_prompt_clock_in(self, dlg.result_value)
            ctx.request_sync()
            self.login_success.emit(dlg.result_value)

    # ------------------------------------------------------------------
    def _manager_login(self):
        dlg = ManagerLoginDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.user:
            ctx.request_sync()
            self.login_success.emit(dlg.user)


class ManagerLoginDialog(QDialog):
    """Yönetici/müdür e-posta girişi. Panelde buluta yazan işlemler bu oturumla yapılır."""

    def __init__(self, parent=None, email='', title='Yönetici Girişi', note=None, start_session=True):
        super().__init__(parent)
        self.start_session = start_session
        self.user = None
        self.session = None
        self.setWindowTitle(title)
        self.setFixedWidth(440)
        self.setStyleSheet("QDialog { background: white; }")
        form = QFormLayout(self)
        form.setContentsMargins(32, 28, 32, 28)
        form.setSpacing(14)

        info = QLabel(note or "Menü, personel ve yetki düzenlemek için e-posta ve şifrenizle girin. "
                              "Bu giriş internet bağlantısı gerektirir.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        form.addRow(info)

        self.email = QLineEdit(email)
        self.email.setPlaceholderText("ornek@kafe.com")
        self.email.setFixedHeight(42)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setFixedHeight(42)
        self.password.returnPressed.connect(self._submit)
        form.addRow("E-posta:", self.email)
        form.addRow("Şifre:", self.password)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold; background: transparent;")
        form.addRow(self.error)

        self.btn = QPushButton("Giriş Yap")
        self.btn.setObjectName("primaryBtn")
        self.btn.setFixedHeight(44)
        self.btn.clicked.connect(self._submit)
        form.addRow(self.btn)
        (self.password if email else self.email).setFocus()

    def _submit(self):
        email, password = self.email.text().strip(), self.password.text()
        if not email or not password:
            self.error.setText("E-posta ve şifre gerekli.")
            return
        if not ctx.client:
            self.error.setText("Bulut ayarı yapılmamış (nexpos_config.json).")
            return
        self.btn.setEnabled(False)
        self.btn.setText("Giriş yapılıyor…")
        self.error.setText("")

        def work():
            session = ctx.client.sign_in_with_password(email, password)
            ctx.request_sync()
            return session

        run_async(work, self._on_signed_in, self._on_failed)

    def _on_signed_in(self, session):
        staff = database.get_staff(session.uid)
        if not staff or staff['role'] not in PANEL_ROLES or not staff['active']:
            self._on_failed("Bu hesap yönetim paneline giriş yetkisine sahip değil "
                            "ya da personel listesi henüz bu bilgisayara inmedi.")
            return
        ctx.set_panel_session(session.uid, session)
        self.session = session
        if self.start_session:
            self.user = database.start_session(session.uid, method='email')
        self.accept()

    def _on_failed(self, message):
        self.btn.setEnabled(True)
        self.btn.setText("Giriş Yap")
        self.error.setText(message)
