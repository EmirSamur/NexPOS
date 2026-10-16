"""
NexPOS - Ayarlar → Modüller (5., 6., 8., 9. ve 10. ekran)

Mutfak ekranı (KDS), zorunlu kasa açılışı, bilgi fişi yazdırma, ödeme yöntemleri ve bahşiş
modül olarak açılıp kapanır. Ayar bulutta (settings/modules) tutulur ve bütün cihazlara iner;
yalnızca Yönetici (owner) değiştirebilir. Modül kapatmak veri silmez.
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox, QFrame, QPushButton
)
from PySide6.QtCore import Qt

import database
from admin_access_pages import cloud_action
from styles import COLORS, ICONS


def _section(title, description):
    box = QFrame()
    box.setObjectName("moduleBox")
    box.setStyleSheet(f"QFrame#moduleBox {{ border: 1px solid {COLORS['border_light']}; border-radius: 10px; background: white; }}")
    ly = QVBoxLayout(box)
    ly.setContentsMargins(16, 12, 16, 12)
    ly.setSpacing(6)
    check = QCheckBox(title)
    check.setStyleSheet("font-size: 14px; font-weight: bold; background: transparent;")
    ly.addWidget(check)
    desc = QLabel(description)
    desc.setWordWrap(True)
    desc.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; margin-left: 24px;")
    ly.addWidget(desc)
    return box, ly, check


def _row(*widgets):
    row = QHBoxLayout()
    row.setContentsMargins(24, 0, 0, 0)
    for w in widgets:
        if isinstance(w, str):
            lbl = QLabel(w)
            lbl.setStyleSheet("background: transparent;")
            row.addWidget(lbl)
        else:
            row.addWidget(w)
    row.addStretch()
    return row


class ModulesPanel(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        ly = QVBoxLayout(self)
        ly.setContentsMargins(24, 20, 24, 20)
        ly.setSpacing(10)

        box, bl, self.kds = _section("Mutfak / Bar Ekranı (KDS)",
                                     "Fişler mutfak ve bardaki tablet ekranına düşer. Tablet, Terminaller sayfasından eşlenir.")
        self.warn = QSpinBox()
        self.warn.setRange(1, 120)
        self.warn.setSuffix(" dk")
        self.late = QSpinBox()
        self.late.setRange(2, 240)
        self.late.setSuffix(" dk")
        self.sound = QCheckBox("Yeni fişte ses")
        bl.addLayout(_row("Sarı:", self.warn, "  Kırmızı:", self.late, "   ", self.sound))
        ly.addWidget(box)

        box, bl, self.cash_required = _section("Zorunlu kasa açılışı",
                                               "Nakit ödeme almak için önce Kasa ekranından kasa açılmalıdır.")
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 100000)
        self.threshold.setSuffix(" ₺")
        bl.addLayout(_row("Kapanışta bu tutarı aşan kasa farkı için gerekçe iste:", self.threshold))
        ly.addWidget(box)

        box, bl, self.printing = _section("Bilgi fişi yazdırma",
                                          "Adisyon (ön fiş) hesap istendiğinde basılır. Yazıcı, bu bilgisayara özel olarak "
                                          "Yazıcı Ayarları sekmesinden seçilir; yazıcı yoksa PDF kaydedilir.")
        self.kitchen_print = QCheckBox("Mutfak/bar fişini de bas (Gönder'e basınca)")
        bl.addLayout(_row(self.kitchen_print))
        ly.addWidget(box)

        box, bl, self.stock = _section("Stok ve reçete",
                                       "Ürün bar/mutfağa gönderilince reçetesindeki malzemeler stoktan düşer; "
                                       "maliyet ve kâr raporlanır. Menü: Stok → Malzemeler.")
        self.ask_void = QCheckBox("Gönderilmiş ürün iptalinde \"Hazırlandı mı?\" diye sor (hayır: stoğa döner)")
        bl.addLayout(_row(self.ask_void))
        ly.addWidget(box)

        box, bl, self.staff = _section("Personel ve mesai",
                                       "Personel mesaiye başlar/bitirir, mola verir; vardiya planı ve mesai raporu "
                                       "Personel menüsündedir. Mesaiye başlamadan da sipariş alınabilir.")
        self.tolerance = QSpinBox()
        self.tolerance.setRange(0, 60)
        self.tolerance.setSuffix(" dk")
        bl.addLayout(_row("Geç kalma toleransı:", self.tolerance))
        ly.addWidget(box)

        box, bl, self.loyalty = _section("Sadakat (damga kartı)",
                                         "Kasada üye telefonla ya da uygulama QR'ı ile tanınır; içeceklerde damga, kart "
                                         "dolunca bedava içecek. Ayarlar: Pazarlama → Sadakat Ayarları.")
        ly.addWidget(box)
        box, bl, self.campaigns = _section("Kampanyalar",
                                           "Happy Hour, 2. ürün indirimi, menü fiyatı, çift damga; kasada kendiliğinden "
                                           "uygulanır. Pazarlama → Kampanyalar.")
        ly.addWidget(box)

        box, bl, self.tips = _section("Bahşiş", "Kartla ödemede bahşiş alanı gösterilir.")
        self.methods = {k: QCheckBox(v) for k, v in (('cash', 'Nakit'), ('card', 'Kredi Kartı'), ('meal', 'Yemek Kartı'))}
        lbl = QLabel("Ödeme yöntemleri:")
        bl.addLayout(_row(lbl, *self.methods.values()))
        ly.addWidget(box)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        ly.addWidget(self.note)
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.save_btn = QPushButton(f"{ICONS['save']} Modülleri Kaydet")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary']}; color: white; font-weight: bold;
                border-radius: 8px; padding: 10px 22px; font-size: 13px; border: none; }}
            QPushButton:disabled {{ background: {COLORS['border']}; }}
        """)
        self.save_btn.clicked.connect(self._save)
        bottom.addWidget(self.save_btn)
        ly.addLayout(bottom)
        ly.addStretch()
        self.kds.toggled.connect(self._enable)
        self.cash_required.toggled.connect(self._enable)
        self.printing.toggled.connect(self._enable)
        self.stock.toggled.connect(self._enable)
        self.staff.toggled.connect(self._enable)
        self.refresh()

    def _enable(self, *_):
        owner = self.user.get('role') == 'owner'
        for w in (self.warn, self.late, self.sound):
            w.setEnabled(owner and self.kds.isChecked())
        self.kitchen_print.setEnabled(owner and self.printing.isChecked())
        self.ask_void.setEnabled(owner and self.stock.isChecked())
        self.tolerance.setEnabled(owner and self.staff.isChecked())

    def refresh(self):
        m = database.modules()
        self.kds.setChecked(m['kds']['enabled'])
        self.warn.setValue(m['kds']['warnMinutes'])
        self.late.setValue(m['kds']['lateMinutes'])
        self.sound.setChecked(m['kds']['sound'])
        self.cash_required.setChecked(m['cashSession']['required'])
        self.threshold.setValue(m['cashSession']['diffReasonThreshold'] // 100)
        self.printing.setChecked(m['printing']['enabled'])
        self.kitchen_print.setChecked(m['printing']['kitchenTickets'])
        self.tips.setChecked(m['tips'])
        self.stock.setChecked(m['stock']['enabled'])
        self.ask_void.setChecked(m['stock']['askOnVoid'])
        self.staff.setChecked(m['staff']['enabled'])
        self.tolerance.setValue(m['staff']['lateToleranceMinutes'])
        self.loyalty.setChecked(m['loyalty']['enabled'])
        self.campaigns.setChecked(m['campaigns']['enabled'])
        for k, c in self.methods.items():
            c.setChecked(m['paymentMethods'][k])
        owner = self.user.get('role') == 'owner'
        for w in (self.kds, self.cash_required, self.threshold, self.printing, self.tips, self.stock, self.staff, self.loyalty, self.campaigns, self.save_btn,
                  *self.methods.values()):
            w.setEnabled(owner)
        self._enable()
        self.note.setText("Modül ayarları buluta kaydedilir (internet gerekir) ve birkaç saniyede bütün cihazlara iner. "
                          "Bir modülü kapatmak geçmiş kayıtları silmez." if owner else
                          "Modülleri yalnızca Yönetici (işletme sahibi) değiştirebilir.")

    def data(self):
        return {
            'kds': {'enabled': self.kds.isChecked(), 'warnMinutes': self.warn.value(),
                    'lateMinutes': self.late.value(), 'sound': self.sound.isChecked()},
            'cashSession': {'required': self.cash_required.isChecked(),
                            'diffReasonThreshold': self.threshold.value() * 100},
            'printing': {'enabled': self.printing.isChecked(), 'kitchenTickets': self.kitchen_print.isChecked()},
            'paymentMethods': {k: c.isChecked() for k, c in self.methods.items()},
            'tips': self.tips.isChecked(),
            'stock': {'enabled': self.stock.isChecked(), 'askOnVoid': self.ask_void.isChecked()},
            'staff': {'enabled': self.staff.isChecked(), 'lateToleranceMinutes': self.tolerance.value()},
            'loyalty': {'enabled': self.loyalty.isChecked()},
            'campaigns': {'enabled': self.campaigns.isChecked()},
        }

    def validate(self):
        d = self.data()
        if d['kds']['lateMinutes'] <= d['kds']['warnMinutes']:
            return "Kırmızı eşik sarı eşikten büyük olmalıdır."
        if not any(d['paymentMethods'].values()):
            return "En az bir ödeme yöntemi açık olmalıdır."
        return None

    def _save(self):
        error = self.validate()
        if error:
            self.note.setText(f"⚠ {error}")
            return
        data = self.data()

        def saved(result):
            database.set_setting('modules', result)
            self.refresh()

        cloud_action(self, lambda api: api.save_modules(data), "Modüller kaydedildi.", saved)

