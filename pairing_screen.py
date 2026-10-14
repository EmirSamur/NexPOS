"""
NexPOS - Terminal Eşleme Ekranı
İlk kurulumda bir kez gösterilir: bu bilgisayarı kafenin bulut hesabına bağlar.
"""
from PySide6.QtWidgets import (
    QFrame, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget, QProgressBar
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from styles import COLORS, FONTS
from widgets import add_shadow
from cloud.context import ctx
from cloud.pairing import pair_terminal
from cloud.qt_sync import run_async

STEPS = 4


class PairingScreen(QWidget):
    paired = Signal(object, object)  # (TerminalCredentials, SyncEngine)

    def __init__(self, parent=None, message=None):
        super().__init__(parent)
        self._step = 0
        self.setObjectName("pairingRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#pairingRoot { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, "
                           "stop:0 #0F172A, stop:1 #4F46E5); }")
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setFixedWidth(520)
        card.setObjectName("pairCard")
        card.setStyleSheet("QFrame#pairCard { background: white; border-radius: 20px; }")
        add_shadow(card, blur=40, offset_y=10, color=QColor(0, 0, 0, 80))
        outer.addWidget(card)

        ly = QVBoxLayout(card)
        ly.setContentsMargins(40, 36, 40, 32)
        ly.setSpacing(10)

        title = QLabel("☕  Bu bilgisayarı kafeye bağla")
        title.setFont(QFont(FONTS['family'], FONTS['size_xl'], QFont.Bold))
        title.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        ly.addWidget(title)
        sub = QLabel(message or
                     "Bu işlem yalnızca bir kez yapılır. Yönetici hesabınızla giriş yapın; "
                     "bu bilgisayar bir kasa terminali olarak kaydedilir. Sonrasında NexPOS "
                     "internet olmadan da açılır.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {COLORS['danger'] if message else COLORS['text_secondary']}; background: transparent;")
        ly.addWidget(sub)
        ly.addSpacing(10)

        form = QFormLayout()
        form.setSpacing(12)
        self.email = QLineEdit()
        self.email.setPlaceholderText("yonetici@kafe.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.name = QLineEdit("Kasa 1")
        self.name.setMaxLength(40)
        for w in (self.email, self.password, self.name):
            w.setFixedHeight(42)
        self.name.returnPressed.connect(self._start)
        form.addRow("Yönetici e-posta:", self.email)
        form.addRow("Şifre:", self.password)
        form.addRow("Terminal adı:", self.name)
        ly.addLayout(form)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold; background: transparent;")
        ly.addWidget(self.error)

        self.progress = QProgressBar()
        self.progress.setRange(0, STEPS)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        ly.addWidget(self.progress)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        ly.addWidget(self.progress_label)

        row = QHBoxLayout()
        row.addStretch()
        self.btn = QPushButton("Bağla ve verileri indir")
        self.btn.setObjectName("primaryBtn")
        self.btn.setFixedHeight(46)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self._start)
        row.addWidget(self.btn)
        ly.addLayout(row)

        if not ctx.client:
            self._disable("Bulut ayarı bulunamadı. Uygulama klasörüne nexpos_config.json dosyasını "
                          "ekleyin (KURULUM.md).")

    def _disable(self, message):
        self.error.setText(message)
        self.btn.setEnabled(False)

    def _start(self):
        email, password, name = self.email.text().strip(), self.password.text(), self.name.text().strip()
        if not email or not password or not name:
            self.error.setText("Tüm alanları doldurun.")
            return
        self.error.setText("")
        self.btn.setEnabled(False)
        self._step = 0
        self.progress.setValue(0)
        self.progress.setVisible(True)
        run_async(lambda progress: pair_terminal(ctx.client, email, password, name, progress),
                  self._on_done, self._on_failed, on_progress=self._on_progress)

    def _on_progress(self, text):
        self.progress_label.setText(f"{text} ({self._step + 1}/{STEPS})")
        self.progress.setValue(self._step)
        self._step += 1

    def _on_done(self, result):
        self.progress.setValue(STEPS)
        self.password.clear()
        creds, engine = result
        self.paired.emit(creds, engine)

    def _on_failed(self, message):
        self.progress.setVisible(False)
        self.progress_label.setText("")
        self.btn.setEnabled(True)
        if 'yetkiniz yok' in message.lower():
            message += " Terminali yalnızca Yönetici rolündeki hesap bağlayabilir."
        self.error.setText(message)
