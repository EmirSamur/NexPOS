"""
NexPOS - Giriş bileşenleri
PIN tuş takımı, PIN penceresi, personel kartı ve senkron durum etiketi.
"""
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from styles import COLORS, FONTS
from widgets import add_shadow

PIN_LENGTH = 6

# Rol → kart rengi
ROLE_COLORS = {
    'owner': '#4F46E5',
    'manager': '#7C3AED',
    'cashier': '#0EA5E9',
    'waiter': '#10B981',
    'courier': '#F59E0B',
    'barista': '#8D6E63',
    'kitchen': '#EF4444',
}


def initials(name):
    parts = [p for p in (name or '').split() if p]
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


class PinPad(QWidget):
    """6 haneli PIN girişi: nokta göstergesi + dokunmatik tuş takımı + klavye."""
    submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pin = ''
        self.setFocusPolicy(Qt.StrongFocus)

        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(14)

        dots_row = QHBoxLayout()
        dots_row.setSpacing(12)
        dots_row.addStretch()
        self._dots = []
        for _ in range(PIN_LENGTH):
            d = QFrame()
            d.setFixedSize(18, 18)
            self._dots.append(d)
            dots_row.addWidget(d)
        dots_row.addStretch()
        ly.addLayout(dots_row)

        self.error_label = QLabel('')
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setMinimumHeight(34)
        self.error_label.setStyleSheet(f"color: {COLORS['danger']}; font-size: 12px; font-weight: bold; background: transparent;")
        ly.addWidget(self.error_label)

        grid = QGridLayout()
        grid.setSpacing(10)
        keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '⌫', '0', '✓']
        for i, k in enumerate(keys):
            b = QPushButton(k)
            b.setFixedSize(84, 64)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFont(QFont(FONTS['family'], 20, QFont.Bold))
            if k == '✓':
                b.setStyleSheet(f"""
                    QPushButton {{ background: {COLORS['primary']}; color: white; border: none; border-radius: 14px; }}
                    QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
                """)
                b.clicked.connect(self._submit)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{ background: {COLORS['bg_input']}; color: {COLORS['text_dark']};
                        border: 1px solid {COLORS['border_light']}; border-radius: 14px; }}
                    QPushButton:hover {{ background: {COLORS['primary_bg']}; }}
                    QPushButton:pressed {{ background: {COLORS['border']}; }}
                """)
                if k == '⌫':
                    b.clicked.connect(self._backspace)
                else:
                    b.clicked.connect(lambda _, d=k: self._press(d))
            grid.addWidget(b, i // 3, i % 3)
        ly.addLayout(grid)
        self._render()

    # Klavye: rakamlar, Backspace, Enter
    def keyPressEvent(self, e):
        if e.text().isdigit():
            self._press(e.text())
        elif e.key() == Qt.Key_Backspace:
            self._backspace()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._submit()
        else:
            super().keyPressEvent(e)

    def _press(self, digit):
        if len(self._pin) < PIN_LENGTH:
            self._pin += digit
            self.error_label.setText('')
            self._render()
            if len(self._pin) == PIN_LENGTH:
                self._submit()

    def _backspace(self):
        self._pin = self._pin[:-1]
        self._render()

    def _submit(self):
        if len(self._pin) == PIN_LENGTH:
            self.submitted.emit(self._pin)

    def _render(self):
        for i, d in enumerate(self._dots):
            filled = i < len(self._pin)
            d.setStyleSheet(f"""
                background: {COLORS['primary'] if filled else 'transparent'};
                border: 2px solid {COLORS['primary'] if filled else COLORS['border']};
                border-radius: 9px;
            """)

    def clear(self):
        self._pin = ''
        self._render()

    def show_error(self, message):
        self.clear()
        self.error_label.setText(message)


class PinDialog(QDialog):
    """
    Bir personelin PIN'ini sorar. verify(pin) başarılıysa sonucunu döndürmeli,
    değilse mesajı kullanıcıya gösterilecek bir hata fırlatmalıdır.
    """

    def __init__(self, staff, verify, title=None, subtitle=None, parent=None):
        super().__init__(parent)
        self.verify = verify
        self.result_value = None
        self.setWindowTitle(title or 'PIN Girişi')
        self.setModal(True)
        self.setStyleSheet("QDialog { background: white; }")

        ly = QVBoxLayout(self)
        ly.setContentsMargins(32, 28, 32, 28)
        ly.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(Avatar(staff['name'], staff['role'], 48))
        head.addSpacing(8)
        txt = QVBoxLayout()
        txt.setSpacing(0)
        n = QLabel(staff['name'])
        n.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        n.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        s = QLabel(subtitle or 'PIN kodunuzu girin')
        s.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        txt.addWidget(n)
        txt.addWidget(s)
        head.addLayout(txt)
        head.addStretch()
        ly.addLayout(head)
        ly.addSpacing(8)

        self.pad = PinPad()
        self.pad.submitted.connect(self._on_submit)
        ly.addWidget(self.pad, 0, Qt.AlignCenter)

        cancel = QPushButton('Vazgeç')
        cancel.setObjectName('ghostBtn')
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        ly.addWidget(cancel)
        self.pad.setFocus()

    def _on_submit(self, pin):
        try:
            self.result_value = self.verify(pin)
        except Exception as e:  # LoginError vb. — mesajı göster, pencere açık kalsın
            self.pad.show_error(str(e))
            return
        self.accept()


class Avatar(QLabel):
    def __init__(self, name, role, size=56, parent=None):
        super().__init__(initials(name), parent)
        color = ROLE_COLORS.get(role, COLORS['primary'])
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setFont(QFont(FONTS['family'], max(10, size // 3), QFont.Bold))
        self.setStyleSheet(f"background: {color}; color: white; border-radius: {size // 2}px;")


class StaffCard(QPushButton):
    """Giriş ekranındaki personel kartı."""

    def __init__(self, staff, role_label, parent=None, badge=''):
        super().__init__(parent)
        self.staff = staff
        self.setFixedSize(150, 180 if badge else 160)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{ background: white; border: 1.5px solid {COLORS['border_light']}; border-radius: 16px; }}
            QPushButton:hover {{ border: 2px solid {COLORS['primary']}; background: {COLORS['primary_bg']}; }}
        """)
        add_shadow(self, blur=14, offset_y=3, color=QColor(0, 0, 0, 18))
        ly = QVBoxLayout(self)
        ly.setContentsMargins(10, 16, 10, 12)
        ly.setSpacing(6)
        ly.addWidget(Avatar(staff['name'], staff['role'], 58), 0, Qt.AlignHCenter)
        name = QLabel(staff['name'].split()[0] if staff['name'] else '?')
        name.setAlignment(Qt.AlignCenter)
        name.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        name.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent; border: none;")
        role = QLabel(role_label)
        role.setAlignment(Qt.AlignCenter)
        role.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; background: transparent; border: none;")
        labels = [name, role]
        if badge:  # mesai durumu (9. ekran): 🟢 Mesaide 08:58 / ☕ Molada / İzinli
            state = QLabel(badge)
            state.setAlignment(Qt.AlignCenter)
            state.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px; font-weight: bold; "
                                f"background: {COLORS['bg_input']}; border: none; border-radius: 8px; padding: 2px 4px;")
            labels.append(state)
        for w in labels:
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            ly.addWidget(w)


class SyncStatusPill(QLabel):
    """🟢 Çevrimiçi / 🟠 Çevrimdışı · 12 işlem bekliyor / 🔴 2 işlem hatalı"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.ArrowCursor)
        self.update_status(None)

    def update_status(self, status):
        if status is None:
            text, color, bg = '● Bağlanıyor…', COLORS['text_secondary'], COLORS['bg_input']
            tip = 'Bulut bağlantısı kontrol ediliyor.'
        elif status.revoked:
            text, color, bg = '● Terminal iptal edildi', COLORS['danger'], COLORS['bg_danger']
            tip = 'Bu bilgisayar yönetim panelinden iptal edildi.'
        elif status.failed:
            text, color, bg = f'● {status.failed} işlem hatalı', COLORS['danger'], COLORS['bg_danger']
            tip = 'Sunucunun reddettiği işlemler var. Yönetim paneli → Terminaller sayfasına bakın.'
        elif not status.online:
            extra = f' · {status.pending} işlem bekliyor' if status.pending else ''
            text, color, bg = f'● Çevrimdışı{extra}', COLORS['warning_dark'], COLORS['bg_warning']
            tip = ('İnternet bağlantısı yok. Sipariş ve ödeme almaya devam edebilirsiniz; '
                   'işlemler internet gelince otomatik gönderilir.')
            if status.last_sync:
                tip += f'\nSon senkron: {status.last_sync}'
        else:
            extra = f' · {status.pending} işlem gönderiliyor' if status.pending else ''
            text, color, bg = f'● Çevrimiçi{extra}', COLORS['success_dark'], COLORS['bg_success']
            tip = f'Son senkron: {status.last_sync}'
        self.setText(f'  {text}  ')
        self.setToolTip(tip)
        self.setStyleSheet(f"""
            QLabel {{ background: {bg}; color: {color}; border-radius: 12px;
                padding: 5px 8px; font-size: 12px; font-weight: bold; }}
        """)
