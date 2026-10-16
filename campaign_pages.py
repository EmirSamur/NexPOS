"""
NexPOS - Kampanya ve bildirim ekranları (10. ekran)

- CampaignBox: adisyon panelinde uygulanan kampanyalar (🏷 satırları); kasiyer kaldırabilir (iskonto yetkisi)
- CampaignsPage / CampaignDialog: kampanya listesi ve düzenleme (Pazarlama → Kampanyalar; internet ister)
- NotificationsPage: bildirim taslağı, kitle, erişim tahmini, geçmiş (gerçek gönderim 11. ekranda)
"""
from datetime import date

from PySide6.QtCore import QDate, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit,
    QTimeEdit, QVBoxLayout, QWidget
)

import campaigns_logic as C
import database
import loyalty
import loyalty_logic as L
import pos
from admin_access_pages import _button, cloud_action
from cloud.context import ctx
from cloud.orders import OrderError
from money import format_tl, parse_tl
from styles import COLORS

SEGMENTS = (('all', 'Bildirim izni olan herkes'), ('inactive30', '30 gündür gelmeyenler'),
            ('silver', 'Gümüş ve Altın üyeler'), ('gold', 'Altın üyeler'), ('birthday', 'Bu hafta doğum günü olanlar'))
SEGMENT_LABELS = dict(SEGMENTS)


def _muted(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
    return lb


def enabled():
    return database.modules()['campaigns']['enabled']


def campaigns(include_inactive=True):
    rows = [c for c in database.cache_rows('campaigns', include_deleted=True) if not c.get('deleted')]
    if not include_inactive:
        rows = [c for c in rows if c.get('active', True)]
    return sorted(rows, key=lambda c: (not c.get('active', True), database.turkish_sort_key(c.get('name', ''))))


def usage(campaign_id, day_from=None, day_to=None):
    """Bu bilgisayardaki ödenmiş adisyonlarda kaç kez uygulandı ve indirim toplamı."""
    conn = database.get_connection()
    q = "SELECT data FROM pos_orders WHERE status='paid'"
    args = []
    if day_from:
        q += " AND business_day BETWEEN ? AND ?"
        args = [day_from, day_to]
    rows = conn.execute(q, args).fetchall()
    conn.close()
    import json
    count = amount = 0
    for r in rows:
        for c in json.loads(r['data']).get('campaigns') or []:
            if c['campaignId'] == campaign_id:
                count += 1
                amount += c['amount']
    return count, amount


# =====================================================================
# Kasa: adisyondaki kampanyalar
# =====================================================================

class CampaignBox(QFrame):
    """🏷 Happy Hour %20 (kahveler)  −38,00 ₺  [✕] — kendiliğinden uygulanır, kasiyer kaldırabilir."""
    changed = Signal(object)

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.order = None
        self.setObjectName("campaignBox")
        self.setStyleSheet(f"QFrame#campaignBox {{ background: {COLORS['bg_success']}; border-radius: 10px; }}")
        self.ly = QVBoxLayout(self)
        self.ly.setContentsMargins(10, 6, 10, 6)
        self.ly.setSpacing(2)

    def set_order(self, order):
        self.order = order
        while self.ly.count():
            w = self.ly.takeAt(0).widget()
            if w:
                w.deleteLater()
        items = (order or {}).get('campaigns') or []
        self.setVisible(bool(items))
        closed = bool(order) and order['status'] != 'open'
        for c in items:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            text = (f"🏷 {c['name']}  {format_tl(-c['amount'])}" if c['amount']
                    else f"🏷 {c['name']} ({c.get('stampMultiplier', 2)}× damga)")
            t = QLabel(text)
            t.setStyleSheet(f"background: transparent; color: {COLORS['success_dark']}; font-weight: bold;")
            h.addWidget(t, 1)
            x = QPushButton("✕")
            x.setFixedSize(28, 24)
            x.setToolTip("Bu adisyondan kaldır (iskonto yetkisi)")
            x.setEnabled(not closed)
            x.clicked.connect(lambda _=False, cid=c['campaignId'], name=c['name']: self._remove(cid, name))
            h.addWidget(x)
            self.ly.addWidget(row)

    def _remove(self, campaign_id, name):
        from pos_screen import authorize
        approver, _ = authorize(self.window(), self.user, 'discount', f"Kampanyayı kaldır: {name}", need_reason=False)
        if not approver:
            return
        try:
            order = pos.exclude_campaign(self.user, self.order['id'], campaign_id, approver)
        except OrderError as e:
            QMessageBox.warning(self, "Kampanya", str(e))
            return
        ctx.request_sync()
        self.changed.emit(order)


# =====================================================================
# Panel: Kampanyalar
# =====================================================================

class CampaignsPage(QWidget):
    COLUMNS = ["", "Kampanya", "Tür", "Ne zaman", "Kime", "Kullanım (30 gün)", "İndirim (30 gün)"]

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.rows = []
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 12, 28, 20)
        ly.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b style='font-size:18px'>Kampanyalar</b><br><span style='color:#64748b'>"
                              "Kasada koşulu tutan kampanya kendiliğinden uygulanır; bir ürüne tek kampanya "
                              "(müşteri için en avantajlısı).</span>"), 1)
        for text, fn, primary in (("+ Kampanya", lambda: self._edit(None), True), ("Düzenle", self._edit_selected, False),
                                  ("Aç / Kapat", self._toggle, False), ("Sil", self._delete, False)):
            b = _button(text, primary=primary)
            b.clicked.connect(fn)
            head.addWidget(b, 0, Qt.AlignVCenter)
        ly.addLayout(head)
        self.module_note = _muted("")
        ly.addWidget(self.module_note)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _: self._edit_selected())
        ly.addWidget(self.table, 1)
        ly.addWidget(_muted("Kampanyayı düzenlemek internet ister; kasada uygulanması internetsiz çalışır. "
                            "Kullanım sayıları bu bilgisayardaki adisyonlardandır."))
        self.refresh()

    def refresh(self):
        self.module_note.setText("" if enabled() else "⚠ Kampanyalar modülü kapalı: kasada uygulanmıyor. "
                                 "Ayarlar → Modüller'den açabilirsiniz.")
        self.rows = campaigns()
        today = pos.business_day()
        start = (date.fromisoformat(today).toordinal() - 29)
        day_from = date.fromordinal(start).isoformat()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for r, c in enumerate(self.rows):
            count, amount = usage(c['id'], day_from, today)
            on = c.get('active', True)
            cells = ["●" if on else "○", c['name'], C.describe(c), C.schedule_text(c),
                     C.AUDIENCE_LABELS.get(c.get('audience', 'all'), ''), str(count), format_tl(amount)]
            for col, v in enumerate(cells):
                item = QTableWidgetItem(v)
                if col == 0:
                    item.setData(Qt.UserRole, c['id'])
                    item.setToolTip("Aktif" if on else "Pasif")
                    item.setForeground(Qt.darkGreen if on else Qt.gray)
                if col >= 5:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, col, item)

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        cid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((c for c in self.rows if c['id'] == cid), None)

    def _need(self):
        c = self.selected()
        if not c:
            QMessageBox.information(self, "Kampanya", "Önce listeden bir kampanya seçin.")
        return c

    def _edit_selected(self):
        c = self._need()
        if c:
            self._edit(c)

    def _edit(self, campaign):
        dlg = CampaignDialog(campaign, self)
        if dlg.exec() != QDialog.Accepted:
            return
        data, cid = dlg.data, (campaign or {}).get('id')
        cloud_action(self, lambda api: api.save_campaign(data, cid), "Kampanya kaydedildi.", lambda _: self.refresh())

    def _toggle(self):
        c = self._need()
        if not c:
            return
        data = {k: c.get(k) for k in ('name', 'type', 'value', 'nthQty', 'bundle', 'stampMultiplier', 'appliesTo',
                                      'schedule', 'audience', 'minTotal', 'showInApp', 'description')}
        data['active'] = not c.get('active', True)
        cloud_action(self, lambda api: api.save_campaign(data, c['id']),
                     "Kampanya açıldı." if data['active'] else "Kampanya kapatıldı.", lambda _: self.refresh())

    def _delete(self):
        c = self._need()
        if c and QMessageBox.question(self, "Kampanyayı sil", f"{c['name']} silinsin mi? Geçmiş adisyonlar etkilenmez.",
                                      QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            cloud_action(self, lambda api: api.delete_campaign(c['id']), "Kampanya silindi.", lambda _: self.refresh())


class CampaignDialog(QDialog):
    def __init__(self, campaign, parent=None):
        super().__init__(parent)
        self.data = None
        c = campaign or {'type': 'percent', 'value': 20, 'schedule': {'days': [1, 2, 3, 4, 5]}, 'audience': 'all',
                         'active': True}
        self.setWindowTitle("Kampanya" if campaign else "Yeni kampanya")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumWidth(620)
        form = QFormLayout(self)
        form.setContentsMargins(22, 18, 22, 18)
        self.name = QLineEdit(c.get('name', ''))
        self.name.setMaxLength(60)
        self.name.setPlaceholderText("Ör. Happy Hour")
        form.addRow("Ad:", self.name)
        self.type = QComboBox()
        for k in C.TYPES:
            self.type.addItem(C.TYPE_LABELS[k], k)
        self.type.setCurrentIndex(max(self.type.findData(c['type']), 0))
        form.addRow("Tür:", self.type)
        self.value = QSpinBox()
        self.value.setRange(1, 100)
        self.value.setSuffix(" %")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("₺")
        self.nth = QSpinBox()
        self.nth.setRange(2, 10)
        self.mult = QSpinBox()
        self.mult.setRange(2, 5)
        self.mult.setSuffix("× damga")
        self.bundle_price = QLineEdit()
        self.bundle_price.setPlaceholderText("Menü fiyatı ₺")
        self.value_row = QWidget()
        vr = QHBoxLayout(self.value_row)
        vr.setContentsMargins(0, 0, 0, 0)
        self.nth_label = QLabel("Her")
        self.nth_label2 = QLabel(". üründe en ucuzu")
        for w in (self.nth_label, self.nth, self.nth_label2, self.value, self.amount, self.bundle_price, self.mult):
            vr.addWidget(w)
        vr.addStretch()
        form.addRow("İndirim:", self.value_row)
        if c['type'] in ('percent', 'nth'):
            self.value.setValue(c.get('value') or 20)
        if c['type'] == 'amount':
            self.amount.setText(format_tl(c['value']).replace(' ₺', ''))
        self.nth.setValue(c.get('nthQty') or 2)
        self.mult.setValue(c.get('stampMultiplier') or 2)
        if c.get('bundle'):
            self.bundle_price.setText(format_tl(c['bundle']['price']).replace(' ₺', ''))

        # Hangi ürünler: kategoriler + ürünler (işaretli liste)
        self.targets = QListWidget()
        self.targets.setMinimumHeight(150)
        self.targets.setMaximumHeight(220)
        applies = c.get('appliesTo') or {}
        bundle_ids = (c.get('bundle') or {}).get('productIds') or []
        for cat in database.menu_categories():
            it = QListWidgetItem(f"📁 {cat['name']} (bütün kategori)")
            it.setData(Qt.UserRole, ('cat', cat['id']))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if cat['id'] in (applies.get('categoryIds') or []) else Qt.Unchecked)
            self.targets.addItem(it)
            for p in database.menu_products(cat['id']):
                pi = QListWidgetItem(f"      {p['name']}  ·  {format_tl(p['price'])}")
                pi.setData(Qt.UserRole, ('prod', p['id']))
                pi.setFlags(pi.flags() | Qt.ItemIsUserCheckable)
                chosen = p['id'] in (applies.get('productIds') or []) or p['id'] in bundle_ids
                pi.setCheckState(Qt.Checked if chosen else Qt.Unchecked)
                self.targets.addItem(pi)
        self.targets_label = QLabel("Ürünler:")
        form.addRow(self.targets_label, self.targets)
        self.targets_hint = _muted("")
        form.addRow(self.targets_hint)

        s = c.get('schedule') or {}
        days_row = QWidget()
        dr = QHBoxLayout(days_row)
        dr.setContentsMargins(0, 0, 0, 0)
        self.days = []
        for i, d in enumerate(C.WEEKDAYS, start=1):
            cb = QCheckBox(d)
            cb.setChecked(i in (s.get('days') or [1, 2, 3, 4, 5, 6, 7]))
            dr.addWidget(cb)
            self.days.append(cb)
        dr.addStretch()
        form.addRow("Günler:", days_row)
        hours_row = QWidget()
        hr = QHBoxLayout(hours_row)
        hr.setContentsMargins(0, 0, 0, 0)
        self.all_day = QCheckBox("Bütün gün")
        self.t_from, self.t_to = QTimeEdit(), QTimeEdit()
        for t in (self.t_from, self.t_to):
            t.setDisplayFormat("HH:mm")
            t.setMinimumHeight(36)
        self.t_from.setTime(QTime.fromString(s.get('from') or '14:00', 'HH:mm'))
        self.t_to.setTime(QTime.fromString(s.get('to') or '17:00', 'HH:mm'))
        self.all_day.setChecked(not s.get('from'))
        self.all_day.toggled.connect(self._mode)
        for w in (self.all_day, self.t_from, QLabel("–"), self.t_to):
            hr.addWidget(w)
        hr.addStretch()
        form.addRow("Saat:", hours_row)
        dates_row = QWidget()
        dtr = QHBoxLayout(dates_row)
        dtr.setContentsMargins(0, 0, 0, 0)
        self.has_dates = QCheckBox("Tarih aralığı")
        self.d_from, self.d_to = QDateEdit(), QDateEdit()
        for de in (self.d_from, self.d_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("dd.MM.yyyy")
            de.setMinimumHeight(36)
        today = QDate.currentDate()
        self.d_from.setDate(QDate.fromString(s['startDate'], 'yyyy-MM-dd') if s.get('startDate') else today)
        self.d_to.setDate(QDate.fromString(s['endDate'], 'yyyy-MM-dd') if s.get('endDate') else today.addDays(30))
        self.has_dates.setChecked(bool(s.get('startDate') or s.get('endDate')))
        self.has_dates.toggled.connect(self._mode)
        for w in (self.has_dates, self.d_from, QLabel("→"), self.d_to):
            dtr.addWidget(w)
        dtr.addStretch()
        form.addRow("Geçerlilik:", dates_row)
        self.audience = QComboBox()
        for k in C.AUDIENCES:
            self.audience.addItem(C.AUDIENCE_LABELS[k], k)
        self.audience.setCurrentIndex(max(self.audience.findData(c.get('audience', 'all')), 0))
        form.addRow("Kime:", self.audience)
        self.min_total = QLineEdit(format_tl(c['minTotal']).replace(' ₺', '') if c.get('minTotal') else '')
        self.min_total.setPlaceholderText("yok")
        form.addRow("En az adisyon (₺):", self.min_total)
        self.show_app = QCheckBox("Müşteri uygulamasında göster (11. ekran)")
        self.show_app.setChecked(bool(c.get('showInApp')))
        self.description = QLineEdit(c.get('description', ''))
        self.description.setMaxLength(200)
        self.description.setPlaceholderText("Uygulamada görünecek kısa açıklama")
        form.addRow(self.show_app)
        form.addRow("Açıklama:", self.description)
        self.active = QCheckBox("Aktif")
        self.active.setChecked(c.get('active', True))
        form.addRow(self.active)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
        form.addRow(self.error)
        ok = _button("Kaydet")
        ok.clicked.connect(self._ok)
        form.addRow(ok)
        self.type.currentIndexChanged.connect(self._mode)
        self._mode()

    def _mode(self, *_):
        t = self.type.currentData()
        self.value.setVisible(t in ('percent', 'nth'))
        self.amount.setVisible(t == 'amount')
        for w in (self.nth_label, self.nth, self.nth_label2):
            w.setVisible(t == 'nth')
        self.bundle_price.setVisible(t == 'bundle')
        self.mult.setVisible(t == 'double_stamps')
        self.targets.setVisible(t != 'double_stamps')
        self.targets_label.setVisible(t != 'double_stamps')
        self.targets_hint.setText({
            'bundle': "Menüdeki ürünleri işaretleyin (2-4 farklı ürün); birlikte alınınca menü fiyatı uygulanır.",
            'double_stamps': "Kampanya saatinde üyeler damga kazandıran ürünlerden kat kat damga alır.",
        }.get(t, "Kategori ya da ürün seçin; hiçbiri seçilmezse bütün menüye uygulanır."))
        self.t_from.setEnabled(not self.all_day.isChecked())
        self.t_to.setEnabled(not self.all_day.isChecked())
        self.d_from.setEnabled(self.has_dates.isChecked())
        self.d_to.setEnabled(self.has_dates.isChecked())

    def _checked(self, kind):
        out = []
        for i in range(self.targets.count()):
            it = self.targets.item(i)
            k, v = it.data(Qt.UserRole)
            if k == kind and it.checkState() == Qt.Checked:
                out.append(v)
        return out

    def collect(self):
        t = self.type.currentData()
        d = {'name': self.name.text().strip(), 'type': t, 'active': self.active.isChecked(),
             'audience': self.audience.currentData(), 'showInApp': self.show_app.isChecked(),
             'description': self.description.text().strip(),
             'minTotal': parse_tl(self.min_total.text()) if self.min_total.text().strip() else 0,
             'schedule': {'days': [i + 1 for i, cb in enumerate(self.days) if cb.isChecked()],
                          'from': None if self.all_day.isChecked() else self.t_from.time().toString('HH:mm'),
                          'to': None if self.all_day.isChecked() else self.t_to.time().toString('HH:mm'),
                          'startDate': self.d_from.date().toString('yyyy-MM-dd') if self.has_dates.isChecked() else None,
                          'endDate': self.d_to.date().toString('yyyy-MM-dd') if self.has_dates.isChecked() else None}}
        if t in ('percent', 'nth'):
            d['value'] = self.value.value()
        if t == 'amount':
            d['value'] = parse_tl(self.amount.text())
        if t == 'nth':
            d['nthQty'] = self.nth.value()
        if t == 'bundle':
            d['bundle'] = {'productIds': self._checked('prod'), 'price': parse_tl(self.bundle_price.text())}
        if t == 'double_stamps':
            d['stampMultiplier'] = self.mult.value()
        if t in ('percent', 'amount', 'nth'):
            d['appliesTo'] = {'categoryIds': self._checked('cat'), 'productIds': self._checked('prod')}
        return C.validate_campaign(d)

    def _ok(self):
        try:
            self.data = self.collect()
        except (ValueError, C.CampaignError) as e:
            self.error.setText(str(e))
            return
        self.accept()


# =====================================================================
# Panel: Bildirimler
# =====================================================================

def reach(segment, today=None):
    """Bildirim izni veren ve kitleye giren üye sayısı (bu bilgisayardaki listeden tahmin)."""
    today = today or pos.business_day()
    limit = date.fromordinal(date.fromisoformat(today).toordinal() - 30).isoformat()
    n = 0
    for c in loyalty.customers():
        if not c.get('marketingConsent'):
            continue
        ok = {'all': True,
              'inactive30': (c.get('lastVisitAt') or c.get('createdAt') or '')[:10] < limit,
              'silver': c.get('tier') in ('silver', 'gold'), 'gold': c.get('tier') == 'gold',
              'birthday': L.is_birthday_week(c.get('birthDate'), today)}[segment]
        n += 1 if ok else 0
    return n


class NotificationsPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 12, 28, 20)
        ly.setSpacing(10)
        ly.addWidget(QLabel("<b style='font-size:18px'>Bildirimler</b><br><span style='color:#64748b'>"
                            "Müşteri uygulamasına (11. ekran) gider; yalnızca bildirim izni veren üyelere, kişi başı "
                            "günde en fazla 1 bildirim.</span>"))
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setMaxLength(60)
        self.title.setPlaceholderText("Yağmurlu günlere sıcak çikolata ☕")
        self.body = QTextEdit()
        self.body.setFixedHeight(70)
        self.body.setPlaceholderText("Bugün sıcak çikolata %20 indirimli")
        self.segment = QComboBox()
        for k, v in SEGMENTS:
            self.segment.addItem(v, k)
        self.segment.currentIndexChanged.connect(self._reach)
        self.campaign = QComboBox()
        self.campaign.addItem("—", None)
        for c in campaigns(include_inactive=False):
            self.campaign.addItem(c['name'], c['id'])
        self.reach = QLabel()
        form.addRow("Başlık:", self.title)
        form.addRow("Metin:", self.body)
        form.addRow("Kime:", self.segment)
        form.addRow("Kampanyaya bağla:", self.campaign)
        form.addRow("Tahmini erişim:", self.reach)
        ly.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(_muted("Gönderim, müşteri uygulaması yayınlanınca başlar; şimdi kaydedilen bildirim "
                             "\"uygulama bekleniyor\" olarak görünür. SMS/WhatsApp toplu gönderim yoktur."), 1)
        self.send = _button("Kaydet ve gönder")
        self.send.clicked.connect(self._send)
        row.addWidget(self.send)
        ly.addLayout(row)
        ly.addWidget(QLabel("<b>Geçmiş</b>"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Tarih", "Başlık", "Kime", "Erişim", "Durum"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        ly.addWidget(self.table, 1)
        self.refresh()

    def _reach(self, *_):
        self.reach.setText(f"{reach(self.segment.currentData())} kişi")

    def refresh(self):
        self._reach()
        rows = sorted(database.cache_rows('notifications', include_deleted=True),
                      key=lambda n: str(n.get('createdAt') or ''), reverse=True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        status = {'waiting_app': 'Uygulama bekleniyor', 'sent': 'Gönderildi'}
        for r, n in enumerate(rows):
            cells = [str(n.get('createdAt') or '')[:16].replace('T', ' '), n.get('title', ''),
                     SEGMENT_LABELS.get(n.get('segment'), ''), str(n.get('reach', 0)),
                     status.get(n.get('status'), n.get('status', ''))]
            for col, v in enumerate(cells):
                self.table.setItem(r, col, QTableWidgetItem(v))

    def _send(self):
        title, body = self.title.text().strip(), self.body.toPlainText().strip()
        if not title or not body or len(body) > 200:
            QMessageBox.warning(self, "Bildirim", "Başlık ve metin (en fazla 200 karakter) gerekli.")
            return
        data = {'title': title, 'body': body, 'segment': self.segment.currentData(),
                'campaignId': self.campaign.currentData(), 'day': pos.business_day()}

        def done(result):
            self.title.clear()
            self.body.clear()
            self.refresh()
        cloud_action(self, lambda api: api.save_notification(data), "Bildirim kaydedildi.", done)
