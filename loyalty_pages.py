"""
NexPOS - Müşteri ve sadakat ekranları (10. ekran)

Kasa:
- CustomerBar: adisyon panelinde müşteri kartı (damga, seviye, ödül), Müşteri ekle / Ödül kullan
- CustomerPickerDialog: QR okut (internet), telefon/ad ile ara, kasada yeni üye (internetsiz)
Panel (Pazarlama):
- CustomersPage: üye listesi, filtreler, düzenle, damga düzelt, geçmiş/dışa aktar, KVKK silme
- LoyaltySettingsPanel: damga sayısı, ödül üst sınırı ve süresi, doğum günü, seviyeler
- MarketingPage: sekmeler (Müşteriler · Kampanyalar · Bildirimler · Sadakat Ayarları)
"""
import json
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QButtonGroup, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget
)

import database
import loyalty
import loyalty_logic as L
import pos
from admin_access_pages import _button, cloud_action
from cloud.context import ctx
from cloud.orders import OrderError
from cloud.qt_sync import run_async
from money import format_tl, parse_tl
from styles import COLORS
from widgets import ToastNotification

MONTHS = ('Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim',
          'Kasım', 'Aralık')
REWARD_TYPES = {'free_drink': 'Bedava içecek', 'birthday': 'Doğum günü', 'manual': 'Hediye', 'campaign': 'Kampanya'}


def _muted(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
    return lb


def birthday_label(md):
    if not md:
        return ''
    m, d = md.split('-')
    return f"{int(d)} {MONTHS[int(m) - 1]}"


class BirthdayEdit(QWidget):
    """Doğum günü: gün + ay (yıl tutulmaz). Boş bırakılabilir."""

    def __init__(self, value=None, parent=None):
        super().__init__(parent)
        ly = QHBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        self.day = QComboBox()
        self.day.addItem("—", 0)
        for d in range(1, 32):
            self.day.addItem(str(d), d)
        self.month = QComboBox()
        self.month.addItem("—", 0)
        for i, m in enumerate(MONTHS, start=1):
            self.month.addItem(m, i)
        ly.addWidget(self.day)
        ly.addWidget(self.month)
        ly.addStretch()
        if value:
            m, d = value.split('-')
            self.day.setCurrentIndex(int(d))
            self.month.setCurrentIndex(int(m))

    def value(self):
        d, m = self.day.currentData(), self.month.currentData()
        if not d and not m:
            return None
        if not d or not m:
            raise ValueError("Doğum gününde gün ve ay birlikte seçilmelidir.")
        try:
            date(2024, m, d)
        except ValueError:
            raise ValueError("Doğum günü geçersiz.")
        return f"{m:02d}-{d:02d}"


class ConsentChoice(QWidget):
    """KVKK: kampanya bildirimi izni müşteriye sorulur; ikisinden biri seçilmeden kayıt yapılmaz."""

    def __init__(self, value=None, parent=None):
        super().__init__(parent)
        ly = QHBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        self.yes, self.no = QRadioButton("Evet"), QRadioButton("Hayır")
        group = QButtonGroup(self)
        for b in (self.yes, self.no):
            group.addButton(b)
            ly.addWidget(b)
        ly.addStretch()
        if value is True:
            self.yes.setChecked(True)
        elif value is False:
            self.no.setChecked(True)

    def value(self):
        return True if self.yes.isChecked() else False if self.no.isChecked() else None


# =====================================================================
# Kasa
# =====================================================================

class CustomerPickerDialog(QDialog):
    """QR okut (internet) · telefon ya da adla ara · yeni üye (internetsiz)."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.customer = None
        self.setWindowTitle("Müşteri")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumWidth(520)
        ly = QVBoxLayout(self)
        ly.setContentsMargins(22, 18, 22, 18)
        ly.setSpacing(10)
        ly.addWidget(QLabel("<b>Uygulama QR'ı</b>"))
        self.qr = QLineEdit()
        self.qr.setPlaceholderText("QR'ı okutun (okuyucu yazıp Enter'a basar) — internet gerekir")
        self.qr.returnPressed.connect(self._qr)
        ly.addWidget(self.qr)
        ly.addWidget(QLabel("<b>Telefon ya da ad</b>"))
        self.query = QLineEdit()
        self.query.setPlaceholderText("0532 … ya da numaranın son 4 hanesi, ya da ad")
        self.query.textChanged.connect(self._search)
        self.query.returnPressed.connect(self._pick_first)
        ly.addWidget(self.query)
        self.results = QListWidget()
        self.results.setMinimumHeight(150)
        self.results.itemDoubleClicked.connect(lambda it: self._choose(it.data(Qt.UserRole)))
        ly.addWidget(self.results)
        row = QHBoxLayout()
        pick = _button("Seç")
        pick.clicked.connect(self._pick_selected)
        self.new_btn = _button("+ Yeni üye", primary=False)
        self.new_btn.clicked.connect(self._toggle_new)
        row.addWidget(self.new_btn)
        row.addStretch()
        row.addWidget(pick)
        ly.addLayout(row)

        self.new_box = QFrame()
        self.new_box.setObjectName("newBox")
        self.new_box.setStyleSheet(f"QFrame#newBox {{ border: 1px solid {COLORS['border']}; border-radius: 10px; }}")
        form = QFormLayout(self.new_box)
        form.setContentsMargins(14, 12, 14, 12)
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("0532 123 45 67")
        self.birth = BirthdayEdit()
        self.consent = ConsentChoice()
        form.addRow("Ad soyad:", self.name)
        form.addRow("Telefon:", self.phone)
        form.addRow("Doğum günü:", self.birth)
        form.addRow("Kampanya bildirimi istiyor mu?", self.consent)
        form.addRow(_muted("Müşteriye sorun (KVKK). Uygulamaya aynı numarayla girince kartı aynen gelir."))
        create = _button("Üye yap ve seç")
        create.clicked.connect(self._create)
        form.addRow(create)
        self.new_box.setVisible(False)
        ly.addWidget(self.new_box)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
        ly.addWidget(self.error)
        self.query.setFocus()

    def _search(self, text):
        self.results.clear()
        for c in loyalty.search(text):
            card = loyalty.card(c['id'])
            it = QListWidgetItem(f"{c['name']}  ·  {L.mask_phone(c.get('phone'))}  ·  "
                                 f"{card['stamps']}/{card['stampsForReward']} damga"
                                 + (f"  ·  🎁 {len(card['rewards'])}" if card['rewards'] else ""))
            it.setData(Qt.UserRole, c['id'])
            self.results.addItem(it)
        digits = ''.join(ch for ch in text if ch.isdigit())
        if not self.results.count() and L.normalize_phone(text):
            self.error.setText("Bu numarayla üye yok. Yeni üye yapabilirsiniz.")
            self.phone.setText(text)
        else:
            self.error.setText("" if self.results.count() or len(digits) < 3 else "Eşleşen üye yok.")

    def _pick_first(self):
        if self.results.count():
            self._choose(self.results.item(0).data(Qt.UserRole))

    def _pick_selected(self):
        it = self.results.currentItem() or (self.results.item(0) if self.results.count() == 1 else None)
        if it:
            self._choose(it.data(Qt.UserRole))

    def _choose(self, customer_id):
        self.customer = loyalty.get(customer_id)
        if self.customer:
            self.accept()

    def _toggle_new(self):
        self.new_box.setVisible(not self.new_box.isVisible())
        if self.new_box.isVisible():
            self.name.setFocus()

    def _create(self):
        try:
            birth = self.birth.value()
            self.customer = loyalty.create(self.user, self.name.text(), self.phone.text(), self.consent.value(), birth)
        except (OrderError, ValueError) as e:
            self.error.setText(str(e))
            return
        ctx.request_sync()
        self.accept()

    def _qr(self):
        token = self.qr.text().strip()
        self.qr.clear()
        self.error.setText("QR doğrulanıyor…")

        def done(c):
            self.customer = c
            self.accept()

        run_async(lambda: loyalty.resolve_qr(token), done, lambda m: self.error.setText(str(m)))


class CustomerBar(QFrame):
    """Adisyon panelinde üye kartı. changed(order) yeni adisyon durumunu bildirir."""
    changed = Signal(object)

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.order = None
        self.setObjectName("customerBar")
        self.setStyleSheet(f"QFrame#customerBar {{ background: {COLORS['primary_bg']}; border-radius: 10px; }}")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(10, 8, 10, 8)
        ly.setSpacing(6)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"background: transparent; color: {COLORS['text_dark']};")
        ly.addWidget(self.label)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.add_btn = self._small("👤 Müşteri ekle", self._pick)
        self.reward_btn = self._small("🎁 Ödül kullan", self._use_reward)
        self.remove_btn = self._small("✕ Müşteriyi kaldır", self._remove)
        for b in (self.add_btn, self.reward_btn, self.remove_btn):
            row.addWidget(b)
        row.addStretch()
        ly.addLayout(row)
        self.rewards_box = QVBoxLayout()
        self.rewards_box.setSpacing(2)
        ly.addLayout(self.rewards_box)

    def _small(self, text, fn):
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(32)
        b.setStyleSheet(f"QPushButton {{ background: white; border: 1px solid {COLORS['border']}; border-radius: 8px;"
                        f" padding: 0 10px; font-weight: bold; }} QPushButton:disabled {{ color: {COLORS['text_muted']}; }}")
        b.clicked.connect(fn)
        return b

    def set_order(self, order):
        self.order = order
        on = loyalty.enabled()
        self.setVisible(on)
        if not on:
            return
        while self.rewards_box.count():
            w = self.rewards_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        c = (order or {}).get('customer')
        closed = bool(order) and order['status'] != 'open'
        card = loyalty.card(c['id']) if c else None
        if c and card:
            self.label.setText("👤 " + loyalty.summary(card))
        elif c:
            self.label.setText(f"👤 {c['name']}")
        else:
            self.label.setText("Müşteri yok. Üyeyse damga için ekleyin.")
        self.add_btn.setText("👤 Değiştir" if c else "👤 Müşteri ekle")
        self.add_btn.setEnabled(bool(order) and not closed)
        self.remove_btn.setVisible(bool(c))
        self.remove_btn.setEnabled(not closed)
        self.reward_btn.setVisible(bool(card and card['rewards']))
        self.reward_btn.setEnabled(not closed)
        names = {l['lineId']: l['name'] for l in (order or {}).get('items', [])}
        for r in (order or {}).get('rewards') or []:
            line = QHBoxLayout()
            w = QWidget()
            w.setLayout(line)
            line.setContentsMargins(0, 0, 0, 0)
            t = QLabel(f"🎁 Ödül: {names.get(r['lineId'], '')}  {format_tl(-r['amount'])}")
            t.setStyleSheet(f"background: transparent; color: {COLORS['success_dark']}; font-weight: bold;")
            line.addWidget(t, 1)
            x = QPushButton("✕")
            x.setFixedSize(28, 24)
            x.setToolTip("Ödülü sonraya sakla")
            x.setEnabled(not closed)
            x.clicked.connect(lambda _=False, rid=r['rewardId']: self._run(pos.remove_reward, self.user, self.order['id'], rid))
            line.addWidget(x)
            self.rewards_box.addWidget(w)

    def _run(self, fn, *args):
        try:
            order = fn(*args)
        except OrderError as e:
            QMessageBox.warning(self, "Müşteri", str(e))
            return
        ctx.request_sync()
        self.changed.emit(order)

    def _pick(self):
        if not self.order:
            return
        dlg = CustomerPickerDialog(self.user, self.window())
        if dlg.exec() == QDialog.Accepted and dlg.customer:
            self._run(pos.set_customer, self.user, self.order['id'], dlg.customer)

    def _remove(self):
        self._run(pos.set_customer, self.user, self.order['id'], None)

    def _use_reward(self):
        card = loyalty.card(self.order['customer']['id'])
        if card and card['rewards']:
            self._run(pos.use_reward, self.user, self.order['id'], card['rewards'][0]['id'])


# =====================================================================
# Panel: Müşteriler
# =====================================================================

COLUMNS = ["Ad", "Telefon", "Seviye", "Damga", "Ziyaret", "Harcama", "Son ziyaret", "Doğum günü", "Bildirim"]


class _Num(QTableWidgetItem):
    def __init__(self, text, key):
        super().__init__(text)
        self.key = key
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.key < getattr(other, 'key', 0)


class CustomersPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.rows = []
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 12, 28, 20)
        ly.setSpacing(10)
        head = QHBoxLayout()
        self.title = QLabel()
        head.addWidget(self.title, 1)
        for text, fn, primary in (("+ Müşteri", lambda: self._edit(None), True), ("Düzenle", self._edit_selected, False),
                                  ("Damga düzelt", self._adjust, False), ("Geçmiş / dışa aktar", self._detail, False),
                                  ("Kaydı sil (KVKK)", self._delete, False)):
            b = _button(text, primary=primary)
            b.clicked.connect(fn)
            head.addWidget(b, 0, Qt.AlignVCenter)
            if text.startswith("Kaydı sil"):
                b.setVisible(user.get('role') == 'owner')
        ly.addLayout(head)
        self.module_note = _muted("")
        ly.addWidget(self.module_note)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Ad ya da telefon ara…")
        self.search.setMinimumHeight(36)
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        self.filter = QComboBox()
        self.filter.setMinimumHeight(36)
        for k, v in loyalty.FILTERS:
            self.filter.addItem(v, k)
        self.filter.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.filter)
        ly.addLayout(bar)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _: self._detail())
        ly.addWidget(self.table, 1)
        ly.addWidget(_muted("Damga ve harcama ödeme kapanınca işlenir. Üye ekleme/düzenleme ve geçmiş internet ister; "
                            "damga düzeltme internetsiz yapılır ve kuyrukla gider."))
        self.refresh()

    def refresh(self, *_):
        on = loyalty.enabled()
        self.module_note.setText("" if on else "⚠ Sadakat modülü kapalı: kasada müşteri sorulmuyor. "
                                 "Ayarlar → Modüller'den açabilirsiniz.")
        s = loyalty.settings()
        self.rows = loyalty.filtered(self.filter.currentData() or 'all', self.search.text())
        total = len(loyalty.customers())
        self.title.setText(f"<b style='font-size:18px'>Müşteriler</b><br><span style='color:#64748b'>"
                           f"{total} üye · gösterilen {len(self.rows)}</span>")
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for r, c in enumerate(self.rows):
            card = loyalty.card(c['id'])
            days = loyalty.days_since(c.get('lastVisitAt'))
            last = "—" if days is None else "bugün" if days == 0 else f"{days} gün önce"
            name = QTableWidgetItem(c['name'])
            name.setData(Qt.UserRole, c['id'])
            cells = [name, QTableWidgetItem(L.format_phone(c.get('phone'))), QTableWidgetItem(card['tierName']),
                     _Num(f"{card['stamps']}/{s['stampsForReward']}" + (f" 🎁{len(card['rewards'])}" if card['rewards'] else ""),
                          card['lifetimeStamps']),
                     _Num(str(c.get('visitCount') or 0), c.get('visitCount') or 0),
                     _Num(format_tl(c.get('totalSpent') or 0), c.get('totalSpent') or 0),
                     _Num(last, -(days if days is not None else 99999)),
                     QTableWidgetItem(birthday_label(c.get('birthDate'))),
                     QTableWidgetItem("✓" if c.get('marketingConsent') else "✗")]
            for col, item in enumerate(cells):
                self.table.setItem(r, col, item)
        self.table.setSortingEnabled(True)

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return loyalty.get(self.table.item(rows[0].row(), 0).data(Qt.UserRole))

    def _need(self):
        c = self.selected()
        if not c:
            QMessageBox.information(self, "Müşteri", "Önce listeden bir müşteri seçin.")
        return c

    def _edit_selected(self):
        c = self._need()
        if c:
            self._edit(c)

    def _edit(self, customer):
        dlg = CustomerEditDialog(customer, self)
        if dlg.exec() != QDialog.Accepted:
            return
        data, cid = dlg.data, (customer or {}).get('id')
        cloud_action(self, lambda api: api.save_customer(data, cid), "Müşteri kaydedildi.", lambda _: self.refresh())

    def _adjust(self):
        c = self._need()
        if not c:
            return
        dlg = AdjustDialog(c, self)
        if dlg.exec() != QDialog.Accepted:
            return
        from pos_screen import authorize
        approver, _ = authorize(self, self.user, 'loyalty', f"{c['name']} · damga düzeltme", need_reason=False)
        if not approver:
            return
        try:
            loyalty.adjust(self.user, c['id'], dlg.stamps.value(), dlg.reason.text(), dlg.grant.isChecked(), approver)
        except OrderError as e:
            QMessageBox.warning(self, "Damga düzeltme", str(e))
            return
        ctx.request_sync()
        ToastNotification(self.window(), "Düzeltme kaydedildi; internet gelince işlenir.", "success")
        self.refresh()

    def _detail(self):
        c = self._need()
        if c:
            cloud_action(self, lambda api: api.export_customer(c['id']), "Müşteri geçmişi getirildi.",
                         lambda data: CustomerDetailDialog(data, self).exec())

    def _delete(self):
        c = self._need()
        if not c:
            return
        r = QMessageBox.question(self, "Kaydı sil (KVKK)",
                                 f"{c['name']} kaydındaki kişisel bilgiler (ad, telefon, doğum günü) silinecek; "
                                 "geçmiş satışlar anonim kalacak, kullanılmamış ödülleri iptal olacak. Emin misiniz?",
                                 QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            cloud_action(self, lambda api: api.delete_customer(c['id']), "Müşteri kaydı silindi.", lambda _: self.refresh())


class CustomerEditDialog(QDialog):
    def __init__(self, customer, parent=None):
        super().__init__(parent)
        self.data = None
        self.setWindowTitle("Müşteri" if customer else "Yeni müşteri")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        form.setContentsMargins(22, 18, 22, 18)
        c = customer or {}
        self.name = QLineEdit(c.get('name', ''))
        self.name.setMaxLength(60)
        self.phone = QLineEdit(L.format_phone(c.get('phone')))
        self.birth = BirthdayEdit(c.get('birthDate'))
        self.consent = ConsentChoice(c.get('marketingConsent') if customer else None)
        form.addRow("Ad soyad:", self.name)
        form.addRow("Telefon:", self.phone)
        form.addRow("Doğum günü:", self.birth)
        form.addRow("Kampanya bildirimi:", self.consent)
        # Gel-al siparişine üst üste gelmeyen müşteriye gel-al kapanır (11b); buradan açılır
        self.unblock = QCheckBox(f"Gel-al kapalı ({c.get('noShows', 0)} kez gelmedi) — yeniden aç")
        self.unblock.setVisible(c.get('pickupBlocked') is True)
        form.addRow(self.unblock)
        self.error = QLabel()
        self.error.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
        form.addRow(self.error)
        ok = _button("Kaydet")
        ok.clicked.connect(self._ok)
        form.addRow(ok)

    def _ok(self):
        try:
            birth = self.birth.value()
        except ValueError as e:
            self.error.setText(str(e))
            return
        phone = L.normalize_phone(self.phone.text())
        if not self.name.text().strip() or not phone:
            self.error.setText("Ad ve geçerli bir telefon numarası gerekli.")
            return
        if self.consent.value() is None:
            self.error.setText("Bildirim izni müşteriye sorulmalıdır.")
            return
        self.data = {'name': self.name.text().strip(), 'phone': phone, 'birthDate': birth,
                     'marketingConsent': self.consent.value()}
        if self.unblock.isVisible() and self.unblock.isChecked():
            self.data['pickupBlocked'] = False
        self.accept()


class AdjustDialog(QDialog):
    def __init__(self, customer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Damga düzeltme")
        self.setStyleSheet("QDialog { background: white; }")
        form = QFormLayout(self)
        form.setContentsMargins(22, 18, 22, 18)
        card = loyalty.card(customer['id'])
        form.addRow(QLabel(f"<b>{customer['name']}</b> · şu an {card['stamps']}/{card['stampsForReward']} damga"))
        self.stamps = QSpinBox()
        self.stamps.setRange(-100, 100)
        self.stamps.setPrefix("+ ")
        self.stamps.valueChanged.connect(lambda v: self.stamps.setPrefix("+ " if v >= 0 else ""))
        self.grant = QCheckBox("Ayrıca bir bedava içecek ödülü ver")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Ör. kart kayboldu, damga unutuldu")
        self.reason.setMaxLength(120)
        form.addRow("Damga:", self.stamps)
        form.addRow(self.grant)
        form.addRow("Gerekçe:", self.reason)
        form.addRow(_muted("Yetki (loyalty) ister; düzeltme kayda geçer."))
        ok = _button("Kaydet")
        ok.clicked.connect(self._ok)
        form.addRow(ok)

    def _ok(self):
        if not self.reason.text().strip() or (not self.stamps.value() and not self.grant.isChecked()):
            QMessageBox.warning(self, "Damga düzeltme", "Damga ya da ödül ve gerekçe girin.")
            return
        self.accept()


class CustomerDetailDialog(QDialog):
    """Ziyaret geçmişi, damga/ödül hareketleri; KVKK için JSON olarak kaydedilir."""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        c = data['customer']
        self.setWindowTitle(f"Müşteri · {c.get('name')}")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumSize(720, 560)
        ly = QVBoxLayout(self)
        view = QTextBrowser()
        view.setHtml(self.html())
        ly.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch()
        save = _button("Verileri kaydet (JSON)", primary=False)
        save.clicked.connect(self._save)
        close = _button("Kapat", primary=False)
        close.clicked.connect(self.accept)
        row.addWidget(save)
        row.addWidget(close)
        ly.addLayout(row)

    def html(self):
        import html
        d = self.data
        c = d['customer']
        s = loyalty.settings()
        top = {}
        for o in d['orders']:
            for it in o.get('items', []):
                top[it['name']] = top.get(it['name'], 0) + it['qty']
        fav = ", ".join(f"{n} ({q})" for n, q in sorted(top.items(), key=lambda kv: -kv[1])[:5]) or "—"
        rows = "".join(f"<tr><td>{o['businessDay']}</td><td>{html.escape(o['no'])}</td>"
                       f"<td align='right'>{format_tl(o['total'])}</td></tr>" for o in d['orders'][:50])
        events = "".join(f"<tr><td>{(e.get('at') or '')[:16].replace('T', ' ')}</td><td>"
                         f"{ {'stamp': 'Damga', 'revoke': 'İade', 'adjust': 'Düzeltme'}.get(e['type'], e['type'])}</td>"
                         f"<td align='right'>{e.get('amount', 0):+d}</td><td>{html.escape(e.get('reason') or '')}</td></tr>"
                         for e in d['events'][:50])
        rewards = "".join(f"<tr><td>{REWARD_TYPES.get(r.get('type'), r.get('type'))}</td><td>{r.get('status')}</td>"
                          f"<td>{r.get('expiresAt', '')}</td></tr>" for r in d['rewards'])
        return (f"<h2>{html.escape(c.get('name') or '')}</h2>"
                f"<p>{L.format_phone(c.get('phone'))} · {L.tier_name(c.get('tier'), s)} · "
                f"{c.get('stamps', 0)}/{s['stampsForReward']} damga · ömür boyu {c.get('lifetimeStamps', 0)}<br>"
                f"{c.get('visitCount', 0)} ziyaret · {format_tl(c.get('totalSpent') or 0)} harcama · "
                f"doğum günü {birthday_label(c.get('birthDate')) or '—'} · bildirim "
                f"{'izni var' if c.get('marketingConsent') else 'izni yok'}</p>"
                f"<p><b>En çok aldıkları:</b> {html.escape(fav)}</p>"
                f"<h3>Ziyaretler</h3><table width='100%' cellpadding='3'>{rows}</table>"
                f"<h3>Damga hareketleri</h3><table width='100%' cellpadding='3'>{events}</table>"
                f"<h3>Ödüller</h3><table width='100%' cellpadding='3'>{rewards}</table>")

    def _save(self, path=None):
        name = self.data['customer'].get('name') or 'musteri'
        path = path or QFileDialog.getSaveFileName(self, "Kaydet", f"{name}.json", "JSON (*.json)")[0]
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        return path


# =====================================================================
# Panel: Sadakat ayarları
# =====================================================================

class LoyaltySettingsPanel(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setMaximumWidth(900)
        outer.addWidget(inner, 1)
        outer.addStretch()
        ly = QVBoxLayout(inner)
        ly.setContentsMargins(28, 12, 28, 20)
        ly.setSpacing(10)
        ly.addWidget(QLabel("<b style='font-size:18px'>Sadakat ayarları</b>"))
        form = QFormLayout()
        self.stamps = QSpinBox()
        self.stamps.setRange(2, 50)
        self.stamps.setSuffix(" damga = 1 bedava içecek")
        self.max_value = QLineEdit()
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setSuffix(" gün geçerli")
        self.birthday = QCheckBox("Doğum günü haftasında gelen üyeye bir bedava içecek")
        form.addRow("Kart:", self.stamps)
        form.addRow("Bedava ürün en fazla (₺):", self.max_value)
        form.addRow("Ödül:", self.days)
        form.addRow(self.birthday)
        ly.addLayout(form)
        ly.addWidget(QLabel("<b>Seviyeler</b> (ömür boyu damgaya göre)"))
        grid = QGridLayout()
        self.tiers = []
        for i, h in enumerate(("Ad", "Eşik (damga)", "Ayrıcalık (kasada ve uygulamada yazı olarak görünür)")):
            grid.addWidget(QLabel(f"<b>{h}</b>"), 0, i)
        for i in range(3):
            name, th, perks = QLineEdit(), QSpinBox(), QLineEdit()
            name.setMaxLength(20)
            th.setRange(0 if i == 0 else 1, 100000)
            th.setEnabled(i > 0)
            perks.setMaxLength(200)
            for col, w in enumerate((name, th, perks)):
                grid.addWidget(w, i + 1, col)
            self.tiers.append((name, th, perks))
        ly.addLayout(grid)
        ly.addWidget(_muted("Seviyeye özel indirim, kampanyalarda \"kime: Altın üyeler\" seçilerek yapılır. "
                            "Damga kazandıran ürünler Menü'de kategori ya da ürün ayarındaki \"damga kazandırır\" seçeneğiyle belirlenir."))
        self.note = _muted("")
        ly.addWidget(self.note)
        row = QHBoxLayout()
        row.addStretch()
        self.save_btn = _button("Kaydet")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        ly.addLayout(row)
        ly.addStretch()
        self.refresh()

    def refresh(self):
        s = loyalty.settings()
        self.stamps.setValue(s['stampsForReward'])
        self.max_value.setText(format_tl(s['rewardMaxValue']).replace(' ₺', ''))
        self.days.setValue(s['rewardValidDays'])
        self.birthday.setChecked(s['birthdayReward'])
        for (name, th, perks), t in zip(self.tiers, s['tiers']):
            name.setText(t['name'])
            th.setValue(t['minStamps'])
            perks.setText(t.get('perks', ''))
        owner = self.user.get('role') == 'owner'
        for w in (self.stamps, self.max_value, self.days, self.birthday, self.save_btn,
                  *[x for t in self.tiers for x in t]):
            w.setEnabled(owner and w not in (self.tiers[0][1],))
        self.note.setText("Ayarlar buluta kaydedilir (internet gerekir)." if owner
                          else "Sadakat ayarlarını yalnızca Yönetici değiştirebilir.")

    def data(self):
        return {'stampsForReward': self.stamps.value(), 'rewardMaxValue': parse_tl(self.max_value.text()),
                'rewardValidDays': self.days.value(), 'birthdayReward': self.birthday.isChecked(),
                'tiers': [{'name': n.text().strip(), 'minStamps': t.value(), 'perks': p.text().strip()}
                          for n, t, p in self.tiers]}

    def _save(self):
        try:
            data = self.data()
            L.validate_loyalty_settings(data)
        except (ValueError, L.LoyaltyError) as e:
            self.note.setText(f"⚠ {e}")
            return

        def saved(result):
            database.set_setting('loyalty', result)
            self.refresh()
        cloud_action(self, lambda api: api.save_loyalty_settings(data), "Sadakat ayarları kaydedildi.", saved)


KVKK_TEMPLATE = """{cafe} — Kişisel Verilerin Korunması Aydınlatma Metni

Veri sorumlusu: {cafe}{address}

İşlenen veriler: ad, telefon numarası, isteğe bağlı doğum günü (gün/ay), siparişlerin ve sadakat damgalarının kaydı.

Amaç: sadakat programının yürütülmesi (damga ve ödüller), siparişlerinin alınması ve hazırlanması, izin verdiysen
kampanya bildirimleri.

Hukuki sebep: üyelik sözleşmesinin kurulması ve ifası; kampanya bildirimleri için açık rızan.

Aktarım: verilerin üçüncü kişilerle paylaşılmaz. Sistem bulut altyapısında (Google Firebase) saklanır.

Saklama süresi: üyeliğin süresince; hesabını sildiğinde kişisel bilgilerin silinir, geçmiş satışlar anonim kalır.

Hakların: KVKK 11. madde uyarınca verilerine erişme, düzeltme, silme ve itiraz hakkın vardır. Uygulamadaki
Profil → Hesabımı sil ile ya da kasada bize başvurarak kullanabilirsin.{phone}
"""


class AppSettingsPanel(QWidget):
    """Pazarlama → Mobil Uygulama: müşteri uygulamasında görünen kafe bilgisi ve aydınlatma metni (Yönetici)."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setMaximumWidth(900)
        outer.addWidget(inner, 1)
        outer.addStretch()
        ly = QVBoxLayout(inner)
        ly.setContentsMargins(28, 12, 28, 20)
        ly.setSpacing(10)
        ly.addWidget(QLabel("<b style='font-size:18px'>Mobil uygulama</b><br><span style='color:#64748b'>"
                            "Müşteri uygulamasında görünen kafe bilgisi. Uygulamanın adı, logosu ve renkleri kafeye "
                            "özel derlemede ayarlanır (KURULUM.md).</span>"))
        form = QFormLayout()
        self.cafe = QLineEdit()
        self.address = QLineEdit()
        self.phone = QLineEdit()
        self.instagram = QLineEdit()
        self.instagram.setPlaceholderText("@kafeadi")
        self.hours = QLineEdit()
        self.hours.setPlaceholderText("Her gün 08:00 – 24:00")
        for w, n in ((self.cafe, 60), (self.address, 200), (self.phone, 30), (self.instagram, 60), (self.hours, 200)):
            w.setMaxLength(n)
        form.addRow("Kafe adı:", self.cafe)
        form.addRow("Adres:", self.address)
        form.addRow("Telefon:", self.phone)
        form.addRow("Instagram:", self.instagram)
        form.addRow("Çalışma saatleri:", self.hours)
        ly.addLayout(form)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Aydınlatma metni (KVKK)</b> — uygulamada üye olurken onaylanır"), 1)
        tpl = _button("Hazır metni doldur", primary=False)
        tpl.clicked.connect(self._template)
        head.addWidget(tpl)
        ly.addLayout(head)
        from PySide6.QtWidgets import QPlainTextEdit
        self.kvkk = QPlainTextEdit()
        self.kvkk.setMinimumHeight(220)
        ly.addWidget(self.kvkk, 1)
        ly.addWidget(_muted("Hazır metin genel bir taslaktır; kafenin bilgileriyle kontrol edip gerekirse bir hukukçuya "
                            "danışın."))
        self.note = _muted("")
        ly.addWidget(self.note)
        row = QHBoxLayout()
        row.addStretch()
        self.save_btn = _button("Kaydet")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        ly.addLayout(row)
        self.refresh()

    def refresh(self):
        d = database.get_setting('app') or {}
        self.cafe.setText(d.get('cafeName') or database.general_settings()['cafeName'])
        self.address.setText(d.get('address', ''))
        self.phone.setText(d.get('phone', ''))
        self.instagram.setText(d.get('instagram', ''))
        self.hours.setText(d.get('hours', ''))
        self.kvkk.setPlainText(d.get('kvkkText', ''))
        owner = self.user.get('role') == 'owner'
        for w in (self.cafe, self.address, self.phone, self.instagram, self.hours, self.kvkk, self.save_btn):
            w.setEnabled(owner)
        self.note.setText("Kaydedince birkaç saniyede uygulamaya yansır (internet gerekir)." if owner
                          else "Bu bilgileri yalnızca Yönetici değiştirebilir.")

    def _template(self):
        cafe = self.cafe.text().strip() or 'Kafe'
        self.kvkk.setPlainText(KVKK_TEMPLATE.format(
            cafe=cafe, address=f", {self.address.text().strip()}" if self.address.text().strip() else '',
            phone=f"\nİletişim: {self.phone.text().strip()}" if self.phone.text().strip() else ''))

    def data(self):
        return {'cafeName': self.cafe.text().strip(), 'address': self.address.text().strip(),
                'phone': self.phone.text().strip(), 'instagram': self.instagram.text().strip(),
                'hours': self.hours.text().strip(), 'kvkkText': self.kvkk.toPlainText().strip()}

    def _save(self):
        data = self.data()
        if len(data['kvkkText']) > 20000:
            self.note.setText("⚠ Aydınlatma metni en fazla 20.000 karakter olabilir.")
            return

        def saved(result):
            database.set_setting('app', result)
            self.refresh()
        cloud_action(self, lambda api: api.save_app_settings(data), "Uygulama bilgileri kaydedildi.", saved)


class MarketingPage(QWidget):
    """Pazarlama: Müşteriler · Kampanyalar · Bildirimler · Sadakat Ayarları · Mobil Uygulama · Kahve Önerisi."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{ padding: 10px 18px; font-weight: bold; color: {COLORS['text_secondary']};
                background: transparent; border-bottom: 3px solid transparent; }}
            QTabBar::tab:selected {{ color: {COLORS['primary']}; border-bottom-color: {COLORS['primary']}; }}
        """)
        from campaign_pages import CampaignsPage, NotificationsPage
        self.customers = CustomersPage(user)
        self.campaigns = CampaignsPage(user)
        self.notifications = NotificationsPage(user)
        self.settings = LoyaltySettingsPanel(user)
        self.tabs.addTab(self.customers, "Müşteriler")
        self.tabs.addTab(self.campaigns, "Kampanyalar")
        self.tabs.addTab(self.notifications, "Bildirimler")
        self.tabs.addTab(self.settings, "Sadakat Ayarları")
        self.app_settings = AppSettingsPanel(user)
        self.tabs.addTab(self.app_settings, "Mobil Uygulama")
        from quiz_pages import QuizPanel
        self.quiz = QuizPanel(user)
        self.tabs.addTab(self.quiz, "Kahve Önerisi")
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        ly.addWidget(self.tabs)

    def refresh(self):
        w = self.tabs.currentWidget()
        if hasattr(w, 'refresh'):
            w.refresh()
