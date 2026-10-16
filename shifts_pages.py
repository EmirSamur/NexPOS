"""
NexPOS - Personel vardiya ve mesai ekranları (9. ekran)

- clock_badge: giriş kartındaki durum (🟢 Mesaide 08:58 / ☕ Molada / İzinli / Bugün 16:00)
- ClockPromptDialog: PIN girişinden sonra "Mesaiye başla / Sadece giriş yap"
- ShiftDialog: Vardiyam (bugünkü mesai, düğmeler, bu ve gelecek hafta planı, haftalık saat, satış)
- PlanPage: haftalık vardiya planı (hücre, şablon, izin, geçen haftayı kopyala, 45 saat uyarısı,
  günlük kişi sayısı, yayınla, PDF, WhatsApp metni) — kaydetmek internet ister
- TimesheetPage: mesai raporu, gün gün döküm, düzeltilecekler, düzeltme, ücret ve işçilik maliyeti
"""
from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QRadioButton, QSpinBox, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QTimeEdit,
    QVBoxLayout, QWidget
)

import database
import reports
import shifts
import shifts_logic as L
from admin_access_pages import _button, cloud_action
from cloud.context import ctx
from cloud.orders import OrderError
from money import format_tl, parse_tl
from styles import COLORS
from widgets import ToastNotification

LEAVE_COLOR = '#FEF3C7'
OVER_COLOR = '#FEE2E2'
DIRTY_COLOR = '#E0E7FF'
TEMPLATES = (
    ('Sabah 08–16', {'start': '08:00', 'end': '16:00', 'breakMinutes': 30}),
    ('Akşam 16–24', {'start': '16:00', 'end': '00:00', 'breakMinutes': 30}),
    ('Ara 12–22', {'start': '12:00', 'end': '22:00', 'breakMinutes': 60}),
    ('İzin', {'leave': 'annual'}),
    ('Temizle', None),
)


class _BgDelegate(QStyledItemDelegate):
    """Genel tablo stili (::item kenarlığı) hücre arka planını yok sayar; burada elle boyanır."""

    def paint(self, painter, option, index):
        bg = index.data(Qt.BackgroundRole)
        if bg is not None:
            painter.fillRect(option.rect, bg)
        super().paint(painter, option, index)


def hours(minutes):
    """Tabloda saat: 480 → '8 sa', 495 → '8,3 sa'"""
    if minutes % 60 == 0:
        return f"{minutes // 60} sa"
    return f"{minutes / 60:.1f}".replace('.', ',') + " sa"


def clock_time(iso):
    return iso[11:16] if iso else '—'


def _muted(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
    return lb


def _short_plan(plan):
    """Izgara hücresi: '09–17', '09:30–17', '16–24'; izinde izin türü."""
    if not plan:
        return ''
    if plan.get('leave'):
        return L.LEAVE_TYPES.get(plan['leave'], 'İzin')

    def short(t, end=False):
        if end and t == '00:00':
            return '24'
        return t[:2] if t.endswith(':00') else t
    return f"{short(plan['start'])}–{short(plan['end'], True)}"


# =====================================================================
# Giriş ekranı
# =====================================================================

def clock_badge(staff_id):
    """Giriş kartındaki durum metni; modül kapalıyken boş."""
    if not shifts.enabled():
        return ''
    state, e = shifts.status(staff_id)
    if state == 'working':
        return f"🟢 Mesaide {clock_time(e['clockIn'])}"
    if state == 'break':
        return f"☕ Molada {clock_time(e['breaks'][-1]['start'])}"
    plan = shifts.plan_for(staff_id, shifts.today())
    if plan and plan.get('leave'):
        return "İzinli"
    if plan and plan.get('published'):
        return f"⚪ Bugün {plan['start']}"
    return ''


def greeting():
    h = datetime.now().hour
    return "Günaydın" if 5 <= h < 12 else "İyi günler" if h < 18 else "İyi akşamlar"


class ClockPromptDialog(QDialog):
    """PIN girişinden sonra (mesaide değilse): Mesaiye başla / Sadece giriş yap."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Mesai")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumWidth(440)
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 24, 28, 22)
        ly.setSpacing(12)
        first = (user.get('ad_soyad') or '').split(' ')[0]
        plan = shifts.plan_for(user['cloud_id'], shifts.today())
        if plan and plan.get('leave'):
            sub = f"Bugün planda {L.LEAVE_TYPES.get(plan['leave'], 'izin').lower()} görünüyor."
        elif plan:
            sub = f"Bugünkü vardiyan {shifts.plan_label(plan).replace('–', ' – ')}"
        else:
            sub = "Bugün için planlı vardiyan yok."
        title = QLabel(f"<b style='font-size:17px'>{greeting()} {first}!</b>")
        ly.addWidget(title)
        ly.addWidget(_muted(sub))
        row = QHBoxLayout()
        self.start_btn = _button("▶ Mesaiye başla")
        self.start_btn.clicked.connect(self._start)
        skip = _button("Sadece giriş yap", primary=False)
        skip.clicked.connect(self.reject)
        row.addWidget(self.start_btn)
        row.addWidget(skip)
        ly.addLayout(row)
        ly.addWidget(_muted("Mesaiye başlamadan da sipariş alabilirsiniz; saat bu bilgisayarın saatidir."))

    def _start(self):
        try:
            shifts.clock(self.user, 'in')
        except OrderError as e:
            QMessageBox.warning(self, "Mesai", str(e))
            return
        ctx.request_sync()
        self.accept()


def maybe_prompt_clock_in(parent, user):
    """Giriş akışı: modül açıksa ve mesaide değilse sorar."""
    if not user or not user.get('cloud_id') or not shifts.enabled():
        return
    if shifts.status(user['cloud_id'])[0] != 'off':
        return
    ClockPromptDialog(user, parent).exec()


# =====================================================================
# Vardiyam
# =====================================================================

class ShiftDialog(QDialog):
    """Garson/barista/kasiyer: bugünkü mesai, düğmeler, plan, haftalık saat ve bugünkü satış."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Vardiyam")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumSize(860, 520)
        ly = QVBoxLayout(self)
        ly.setContentsMargins(24, 20, 24, 18)
        ly.setSpacing(10)
        self.status = QLabel()
        self.status.setWordWrap(True)
        ly.addWidget(self.status)
        row = QHBoxLayout()
        self.buttons = {}
        for action, text, primary in (('in', "▶ Mesaiye başla", True), ('breakStart', "☕ Molaya çık", False),
                                      ('breakEnd', "↩ Moladan dön", True), ('out', "■ Mesaiyi bitir", False)):
            b = _button(text, primary=primary)
            b.clicked.connect(lambda _=False, a=action: self._clock(a))
            row.addWidget(b)
            self.buttons[action] = b
        row.addStretch()
        ly.addLayout(row)
        self.plan_table = QTableWidget(2, 7)
        self.plan_table.verticalHeader().setDefaultSectionSize(40)
        self.plan_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.plan_table.setSelectionMode(QTableWidget.NoSelection)
        self.plan_table.setVerticalHeaderLabels(["Bu hafta", "Gelecek hafta"])
        self.plan_table.setItemDelegate(_BgDelegate(self.plan_table))
        self.plan_table.setFixedHeight(40 * 2 + 56)
        self.plan_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.plan_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.plan_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ly.addWidget(QLabel("<b>Vardiya planım</b>"))
        ly.addWidget(self.plan_table)
        self.week = QLabel()
        self.week.setWordWrap(True)
        ly.addWidget(self.week)
        self.sales = QLabel()
        self.sales.setWordWrap(True)
        ly.addWidget(self.sales)
        ly.addStretch()
        close = _button("Kapat", primary=False)
        close.clicked.connect(self.accept)
        ly.addWidget(close, 0, Qt.AlignRight)
        self.refresh()

    def _clock(self, action):
        try:
            shifts.clock(self.user, action)
        except OrderError as e:
            QMessageBox.warning(self, "Mesai", str(e))
            return
        ctx.request_sync()
        ToastNotification(self.window(), {'in': "Mesai başladı.", 'out': "Mesai bitti. İyi dinlenmeler!",
                                          'breakStart': "Mola başladı.", 'breakEnd': "Moladan dönüldü."}[action],
                          "success")
        self.refresh()

    def refresh(self):
        sid = self.user['cloud_id']
        on = shifts.enabled()
        state, e = shifts.status(sid) if on else ('off', None)
        today = shifts.today()
        if not on:
            text = "Mesai takibi kapalı (Ayarlar → Modüller → Personel ve mesai)."
        elif state == 'working':
            text = f"🟢 <b>Mesaidesiniz</b> · giriş {clock_time(e['clockIn'])}"
            if e.get('late'):
                text += f" · {e['late']} dk geç"
        elif state == 'break':
            text = f"☕ <b>Moladasınız</b> · {clock_time(e['breaks'][-1]['start'])}'dan beri"
        else:
            done = [x for x in shifts.entries(today, today, sid) if x.get('clockOut')]
            text = ("⚪ Mesai dışındasınız" + (f" · bugün {clock_time(done[-1]['clockIn'])}–"
                                               f"{clock_time(done[-1]['clockOut'])}" if done else ""))
        self.status.setText(f"<span style='font-size:15px'>{text}</span>")
        for action, b in self.buttons.items():
            b.setVisible(on and {'in': state == 'off', 'breakStart': state == 'working',
                                 'breakEnd': state == 'break', 'out': state != 'off'}[action])
        # Plan: bu hafta + gelecek hafta (yalnızca yayınlanmış)
        start = shifts.week_start(today)
        nxt = (date.fromisoformat(start) + timedelta(days=7)).isoformat()
        pl = shifts.plans(start, (date.fromisoformat(nxt) + timedelta(days=6)).isoformat(), published_only=True)
        self.plan_table.setHorizontalHeaderLabels(
            [f"{shifts.WEEKDAYS_SHORT[i]} {date.fromisoformat(d).day}" for i, d in enumerate(shifts.week_days(start))])
        for r, ws in enumerate((start, nxt)):
            for c, d in enumerate(shifts.week_days(ws)):
                item = QTableWidgetItem(_short_plan(pl.get((sid, d))) or '—')
                item.setTextAlignment(Qt.AlignCenter)
                if d == today:
                    item.setBackground(QColor(COLORS['primary_bg']))
                self.plan_table.setItem(r, c, item)
        week_days = shifts.week_days(start)
        worked = sum(L.worked_minutes(x, pl.get((sid, x['businessDay'])))
                     for x in shifts.entries(week_days[0], week_days[-1], sid))
        planned = sum(L.planned_minutes(p) for (s, d), p in pl.items() if s == sid and d <= week_days[-1])
        self.week.setText(f"Bu hafta çalışılan: <b>{L.format_minutes(worked)}</b> · planlanan {L.format_minutes(planned)}")
        r = reports.my_shift(sid)
        self.sales.setText(f"Bugün: {r['orders']} adisyon · ciro {format_tl(r['revenue'])} · "
                           f"bahşiş {format_tl(r['tips'])} · ikram {r['comps']} · iptal {r['voids']}")


# =====================================================================
# Vardiya planı
# =====================================================================

class CellDialog(QDialog):
    """Hücre: başlangıç, bitiş, mola, not ya da izin."""

    def __init__(self, name, day, plan, parent=None):
        super().__init__(parent)
        self.result_plan = None
        self.cleared = False
        self.setWindowTitle("Vardiya")
        self.setStyleSheet("QDialog { background: white; }")
        form = QFormLayout(self)
        form.setContentsMargins(24, 20, 24, 20)
        d = date.fromisoformat(day)
        form.addRow(QLabel(f"<b>{name}</b> · {reports.WEEKDAYS[d.weekday()]} {d.strftime('%d.%m.%Y')}"))
        self.work = QRadioButton("Çalışıyor")
        self.leave = QRadioButton("İzin")
        row = QHBoxLayout()
        row.addWidget(self.work)
        row.addWidget(self.leave)
        row.addStretch()
        form.addRow(row)
        self.start, self.end = QTimeEdit(), QTimeEdit()
        for t in (self.start, self.end):
            t.setDisplayFormat("HH:mm")
            t.setMinimumHeight(40)
        self.brk = QSpinBox()
        self.brk.setRange(0, 240)
        self.brk.setSingleStep(15)
        self.brk.setSuffix(" dk")
        self.leave_type = QComboBox()
        for k, v in L.LEAVE_TYPES.items():
            self.leave_type.addItem(v, k)
        self.note = QLineEdit()
        self.note.setMaxLength(80)
        form.addRow("Başlangıç:", self.start)
        form.addRow("Bitiş:", self.end)
        form.addRow("Mola:", self.brk)
        form.addRow("İzin türü:", self.leave_type)
        form.addRow("Not:", self.note)
        form.addRow(_muted("Gece yarısını geçen vardiya (16:00–01:00) aynı güne aittir."))
        p = plan or {'start': '09:00', 'end': '17:00', 'breakMinutes': 30}
        (self.leave if p.get('leave') else self.work).setChecked(True)
        self.start.setTime(QTime.fromString(p.get('start') or '09:00', 'HH:mm'))
        self.end.setTime(QTime.fromString(p.get('end') or '17:00', 'HH:mm'))
        self.brk.setValue(p.get('breakMinutes') or 0)
        if p.get('leave'):
            self.leave_type.setCurrentIndex(max(self.leave_type.findData(p['leave']), 0))
        self.note.setText(p.get('note') or '')
        self.work.toggled.connect(self._mode)
        self._mode()
        btns = QHBoxLayout()
        clear = _button("Boşalt", primary=False)
        clear.clicked.connect(self._clear)
        ok = _button("Tamam")
        ok.clicked.connect(self._ok)
        btns.addWidget(clear)
        btns.addStretch()
        btns.addWidget(ok)
        form.addRow(btns)

    def _mode(self, *_):
        w = self.work.isChecked()
        for x in (self.start, self.end, self.brk):
            x.setEnabled(w)
        self.leave_type.setEnabled(not w)

    def _clear(self):
        self.cleared = True
        self.accept()

    def _ok(self):
        note = self.note.text().strip()
        if self.leave.isChecked():
            self.result_plan = {'leave': self.leave_type.currentData(), 'note': note}
        else:
            s, e = self.start.time().toString('HH:mm'), self.end.time().toString('HH:mm')
            if s == e:
                QMessageBox.warning(self, "Vardiya", "Başlangıç ve bitiş aynı olamaz.")
                return
            self.result_plan = {'start': s, 'end': e, 'breakMinutes': self.brk.value(), 'note': note}
        self.accept()


class PlanPage(QWidget):
    """Haftalık plan: satırlar personel, sütunlar günler + toplam; en altta günlük kişi sayısı."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.week = shifts.week_start()
        self.saved = {}
        self.changes = {}
        self.staff = []
        self.paint = None
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 12, 28, 20)
        ly.setSpacing(10)
        head = QHBoxLayout()
        self.title = QLabel()
        head.addWidget(self.title, 1)
        for text, fn in (("◀ Önceki", lambda: self._go(-7)), ("Bu hafta", lambda: self._go(None)),
                         ("Sonraki ▶", lambda: self._go(7)), ("Geçen haftayı kopyala", self._copy_last)):
            b = _button(text, primary=False)
            b.clicked.connect(fn)
            head.addWidget(b, 0, Qt.AlignVCenter)
        ly.addLayout(head)
        self.table = QTableWidget(0, 9)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.horizontalHeader().setMinimumSectionSize(84)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setItemDelegate(_BgDelegate(self.table))
        self.table.cellClicked.connect(self._cell_clicked)
        ly.addWidget(self.table, 1)
        tpl = QHBoxLayout()
        tpl.addWidget(QLabel("Şablon (seçip hücrelere tıklayın):"))
        self.tpl_buttons = []
        for label, plan in TEMPLATES:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setMinimumHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ padding: 0 12px; border: 1px solid {COLORS['border']}; border-radius: 8px;"
                            f" background: white; }} QPushButton:checked {{ background: {COLORS['primary']};"
                            f" color: white; border-color: {COLORS['primary']}; }}")
            b.toggled.connect(lambda on, btn=b, p=plan: self._pick_template(btn, p, on))
            tpl.addWidget(b)
            self.tpl_buttons.append(b)
        tpl.addStretch()
        ly.addLayout(tpl)
        bottom = QHBoxLayout()
        self.info = _muted("")
        bottom.addWidget(self.info, 1)
        self.revert_btn = _button("Geri al", primary=False)
        self.revert_btn.clicked.connect(self._revert)
        self.save_btn = _button("Kaydet")
        self.save_btn.clicked.connect(self._save)
        self.publish_btn = _button("Yayınla")
        self.publish_btn.clicked.connect(self._publish)
        pdf = _button("PDF", primary=False)
        pdf.clicked.connect(lambda: self.export_pdf())
        wa = _button("WhatsApp metni", primary=False)
        wa.clicked.connect(self._whatsapp)
        for b in (self.revert_btn, self.save_btn, self.publish_btn, pdf, wa):
            bottom.addWidget(b)
        ly.addLayout(bottom)
        self.refresh()

    # ------------------------------------------------------------------ veri
    def days(self):
        return shifts.week_days(self.week)

    def cell(self, sid, day):
        return self.changes[(sid, day)] if (sid, day) in self.changes else self.saved.get((sid, day))

    def pending_cells(self):
        """Buluta gidecek hücreler (saveShiftPlans)."""
        out = []
        for (sid, day), p in sorted(self.changes.items()):
            if p is None:
                out.append({'staffId': sid, 'date': day, 'clear': True})
            else:
                out.append({'staffId': sid, 'date': day, **{k: v for k, v in p.items()
                                                             if k in ('start', 'end', 'breakMinutes', 'leave', 'note')}})
        return out

    def week_totals(self):
        """{staffId: planlanan dakika}"""
        return {s['id']: sum(L.planned_minutes(self._dated(s['id'], d)) for d in self.days()) for s in self.staff}

    def daily_counts(self):
        return [sum(1 for s in self.staff if (p := self.cell(s['id'], d)) and not p.get('leave')) for d in self.days()]

    def _dated(self, sid, day):
        p = self.cell(sid, day)
        return {**p, 'date': day} if p else None

    def set_cell(self, sid, day, plan):
        old = self.saved.get((sid, day))
        same = (old is None and plan is None) or (old and plan and all(
            (old.get(k) or None) == (plan.get(k) or None) for k in ('start', 'end', 'breakMinutes', 'leave', 'note')))
        if same:
            self.changes.pop((sid, day), None)
        else:
            self.changes[(sid, day)] = plan
        self._fill()

    # ------------------------------------------------------------------ ekran
    def refresh(self):
        self.staff = database.get_login_staff()
        days = self.days()
        self.saved = shifts.plans(days[0], days[-1])
        self._fill()

    def _fill(self):
        days = self.days()
        d0, d6 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        published = [p.get('published') for p in self.saved.values()]
        state = ("yayınlandı" if published and all(published) else
                 "taslak (personel görmüyor)" if published else "boş")
        self.title.setText(f"<b style='font-size:18px'>Vardiya Planı · {d0.day} {reports_month(d0)} – "
                           f"{d6.day} {reports_month(d6)}</b><br><span style='color:#64748b'>Durum: {state}</span>")
        self.table.clear()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["Personel"] + [f"{shifts.WEEKDAYS_SHORT[i]} {date.fromisoformat(d).day}" for i, d in enumerate(days)]
            + ["Toplam"])
        self.table.setRowCount(len(self.staff) + 1)
        totals = self.week_totals()
        for r, s in enumerate(self.staff):
            name = QTableWidgetItem(s['name'])
            name.setData(Qt.UserRole, s['id'])
            self.table.setItem(r, 0, name)
            for c, d in enumerate(days, start=1):
                p = self.cell(s['id'], d)
                item = QTableWidgetItem(_short_plan(p) or '—')
                item.setTextAlignment(Qt.AlignCenter)
                if p and p.get('note'):
                    item.setToolTip(p['note'])
                if (s['id'], d) in self.changes:
                    item.setBackground(QColor(DIRTY_COLOR))
                elif p and p.get('leave'):
                    item.setBackground(QColor(LEAVE_COLOR))
                self.table.setItem(r, c, item)
            over = totals[s['id']] > L.WEEKLY_LIMIT_MINUTES
            tot = QTableWidgetItem(hours(totals[s['id']]) + (" ⚠" if over else ""))
            tot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if over:
                tot.setBackground(QColor(OVER_COLOR))
                tot.setToolTip("Haftalık 45 saati aşıyor (iş kanunu sınırı; bilgi amaçlı).")
            self.table.setItem(r, 8, tot)
        last = len(self.staff)
        label = QTableWidgetItem("Günlük kişi")
        f = label.font()
        f.setBold(True)
        label.setFont(f)
        self.table.setItem(last, 0, label)
        for c, n in enumerate(self.daily_counts(), start=1):
            item = QTableWidgetItem(str(n))
            item.setTextAlignment(Qt.AlignCenter)
            item.setFont(f)
            self.table.setItem(last, c, item)
        self.table.setItem(last, 8, QTableWidgetItem(""))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        dirty = bool(self.changes)
        can = database.user_can(self.user, 'shifts')
        self.save_btn.setEnabled(dirty and can)
        self.revert_btn.setEnabled(dirty)
        self.publish_btn.setEnabled(can and not dirty and bool(self.saved))
        self.info.setText((f"{len(self.changes)} hücre kaydedilmedi · " if dirty else "") +
                          "Planı kaydetmek ve yayınlamak internet ister. Mor: kaydedilmedi · sarı: izin.")

    def _go(self, days):
        if not self.can_leave():
            return
        self.week = shifts.week_start() if days is None else \
            (date.fromisoformat(self.week) + timedelta(days=days)).isoformat()
        self.changes = {}
        self.refresh()

    def _pick_template(self, btn, plan, on):
        if on:
            for b in self.tpl_buttons:
                if b is not btn:
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
            self.paint = ('clear',) if plan is None else ('plan', plan)
        elif self.paint and all(not b.isChecked() for b in self.tpl_buttons):
            self.paint = None

    def _cell_clicked(self, row, col):
        if row >= len(self.staff) or not 1 <= col <= 7:
            return
        s = self.staff[row]
        day = self.days()[col - 1]
        if self.paint:
            self.set_cell(s['id'], day, None if self.paint[0] == 'clear' else dict(self.paint[1]))
            return
        dlg = CellDialog(s['name'], day, self.cell(s['id'], day), self)
        if dlg.exec() == QDialog.Accepted:
            self.set_cell(s['id'], day, None if dlg.cleared else dlg.result_plan)

    def copy_last_week(self):
        prev = shifts.week_days((date.fromisoformat(self.week) - timedelta(days=7)).isoformat())
        old = shifts.plans(prev[0], prev[-1])
        n = 0
        for s in self.staff:
            for i, d in enumerate(self.days()):
                p = old.get((s['id'], prev[i]))
                if p and not self.cell(s['id'], d):
                    self.set_cell(s['id'], d, {k: p.get(k) for k in ('start', 'end', 'breakMinutes', 'leave', 'note')
                                               if p.get(k) is not None})
                    n += 1
        return n

    def _copy_last(self):
        n = self.copy_last_week()
        ToastNotification(self.window(), f"{n} hücre geçen haftadan kopyalandı (boş günlere)." if n else
                          "Geçen haftadan kopyalanacak (boş güne denk gelen) vardiya yok.", "info")

    def _revert(self):
        self.changes = {}
        self._fill()

    def can_leave(self):
        if not self.changes:
            return True
        r = QMessageBox.question(self, "Kaydedilmemiş değişiklik",
                                 "Vardiya planında kaydedilmemiş değişiklikler var. Kaydetmeden çıkılsın mı?",
                                 QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self.changes = {}
            return True
        return False

    def _save(self):
        cells = self.pending_cells()
        if not cells:
            return

        def saved(_):
            self.changes = {}
            self.refresh()

        cloud_action(self, lambda api: api.save_shift_plans(cells), "Vardiya planı kaydedildi (taslak).", saved)

    def _publish(self):
        week = self.week
        cloud_action(self, lambda api: api.publish_shift_week(week),
                     "Plan yayınlandı; personel Vardiyam penceresinde görür.", lambda _: self.refresh())

    def export_rows(self):
        headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
        rows = [[self.table.item(r, c).text() if self.table.item(r, c) else '' for c in range(self.table.columnCount())]
                for r in range(self.table.rowCount())]
        return headers, rows

    def export_pdf(self, path=None):
        import printing
        from reports_screen import table_html
        days = self.days()
        title = f"Vardiya planı {date.fromisoformat(days[0]):%d.%m} – {date.fromisoformat(days[-1]):%d.%m.%Y}"
        path = path or QFileDialog.getSaveFileName(self, "PDF kaydet", f"{title}.pdf", "PDF (*.pdf)")[0]
        if not path:
            return None
        headers, rows = self.export_rows()
        printing.save_pdf(table_html(database.general_settings()['cafeName'], title, headers, rows), title, 'A4', path)
        return path

    def _whatsapp(self):
        if self.changes:
            QMessageBox.information(self, "WhatsApp metni", "Önce değişiklikleri kaydedin.")
            return
        text = shifts.week_text(self.week)
        QGuiApplication.clipboard().setText(text)
        dlg = QDialog(self)
        dlg.setWindowTitle("WhatsApp metni")
        dlg.setMinimumSize(520, 420)
        v = QVBoxLayout(dlg)
        v.addWidget(_muted("Metin panoya kopyalandı; WhatsApp grubuna yapıştırabilirsiniz."))
        box = QTextEdit()
        box.setPlainText(text)
        box.setReadOnly(True)
        v.addWidget(box, 1)
        dlg.exec()


def reports_month(d):
    from reports_screen import MONTHS
    return MONTHS[d.month - 1]


# =====================================================================
# Mesai raporu
# =====================================================================

COLUMNS = ["Personel", "Plan", "Çalışılan", "Mola", "Fazla mesai", "Geç (kez/dk)", "Gelmedi", "İzin",
           "Unutulan çıkış", "Ciro/saat", "İşçilik"]


def report_cells(r, cost=None):
    return [r['name'], hours(r['planned']), hours(r['worked']), hours(r['breaks']),
            hours(r['overtime']) if r['overtime'] else '0',
            f"{r['lateCount']} / {r['lateMinutes']} dk" if r['lateCount'] else '0', str(r['absent']), str(r['leave']),
            str(r['forgot']), format_tl(r['revenuePerHour']) if r['worked'] else '—',
            format_tl(cost) if cost is not None else '—']


class TimesheetPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.rows = []
        self.wages = None
        self.range = reports.period('week')
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 12, 28, 20)
        ly.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b style='font-size:18px'>Mesai</b>"))
        self.preset = QComboBox()
        for key, label in reports.PERIODS:
            self.preset.addItem(label, key)
        self.preset.setCurrentIndex(2)
        self.preset.setMinimumHeight(36)
        self.preset.currentIndexChanged.connect(self._period)
        bar.addWidget(self.preset)
        self.range_label = _muted("")
        bar.addWidget(self.range_label, 1)
        self.wage_btn = _button("Saatlik ücretler", primary=False)
        self.wage_btn.clicked.connect(self._wages)
        self.wage_btn.setVisible(user.get('role') == 'owner')
        bar.addWidget(self.wage_btn)
        for text, fn in (("⬇ CSV", lambda: self.export_csv()), ("⬇ PDF", lambda: self.export_pdf())):
            b = _button(text, primary=False)
            b.clicked.connect(fn)
            bar.addWidget(b)
        ly.addLayout(bar)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda idx: self._detail(idx.row()))
        ly.addWidget(self.table, 2)
        self.labor = QLabel()
        ly.addWidget(self.labor)
        ly.addWidget(_muted("Fazla mesai: haftalık 45 saati aşan çalışma (bilgi amaçlı, bordro değildir). "
                            "Kişiye çift tıklayınca gün gün döküm açılır."))
        fix_head = QHBoxLayout()
        self.fix_title = QLabel()
        fix_head.addWidget(self.fix_title, 1)
        self.fix_btn = _button("Seçiliyi düzelt", primary=False)
        self.fix_btn.clicked.connect(self._fix_selected)
        fix_head.addWidget(self.fix_btn)
        add = _button("+ Eksik kayıt ekle", primary=False)
        add.clicked.connect(lambda: self.edit_entry(None, None))
        fix_head.addWidget(add)
        ly.addLayout(fix_head)
        self.fix_table = QTableWidget(0, 5)
        self.fix_table.setHorizontalHeaderLabels(["Personel", "Gün", "Giriş", "Kapatılan çıkış", "Durum"])
        self.fix_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.fix_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.fix_table.verticalHeader().setVisible(False)
        self.fix_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fix_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.fix_table.setSelectionMode(QTableWidget.SingleSelection)
        self.fix_table.doubleClicked.connect(lambda _: self._fix_selected())
        ly.addWidget(self.fix_table, 1)
        self.refresh()

    def _period(self, *_):
        self.range = reports.period(self.preset.currentData())
        self.refresh()

    def refresh(self):
        shifts.auto_close_forgotten()
        a, b = self.range
        self.range_label.setText(f"{date.fromisoformat(a):%d.%m.%Y} – {date.fromisoformat(b):%d.%m.%Y}")
        self.rows = shifts.report(a, b)
        costs, total = shifts.labor_cost(self.rows, self.wages) if self.wages is not None else ({}, None)
        self.table.setColumnHidden(len(COLUMNS) - 1, self.wages is None)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            for c, v in enumerate(report_cells(row, costs.get(row['staffId']) if self.wages is not None else None)):
                item = QTableWidgetItem(v)
                if c:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole, row['staffId'])
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        if total is not None:
            revenue = sum(r['revenue'] for r in self.rows)
            pct = f" · cironun %{round(total * 100 / revenue)}'i" if revenue else ""
            self.labor.setText(f"<b>İşçilik: {format_tl(total)}</b>{pct} (çalışılan saat × saatlik ücret)")
        else:
            self.labor.setText("")
        fix = shifts.to_fix()
        self.fix_title.setText(f"<b>Düzeltilecekler</b> ({len(fix)}) — çıkışı unutulup gün sonunda kapatılan mesailer")
        self.fix_table.setRowCount(0)
        self.fix_table.setRowCount(len(fix))
        for r, e in enumerate(fix):
            st = database.get_staff(e['staffId'])
            cells = [st['name'] if st else '—', date.fromisoformat(e['businessDay']).strftime('%d.%m.%Y'),
                     clock_time(e['clockIn']), clock_time(e['clockOut']), "Çıkış unutuldu"]
            for c, v in enumerate(cells):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setData(Qt.UserRole, e['id'])
                self.fix_table.setItem(r, c, item)
        can = database.user_can(self.user, 'shifts')
        self.fix_btn.setEnabled(can and bool(fix))

    def _fix_selected(self):
        sel = self.fix_table.selectionModel().selectedRows()
        if not sel:
            if self.fix_table.rowCount():
                self.fix_table.selectRow(0)
                sel = self.fix_table.selectionModel().selectedRows()
            else:
                return
        entry_id = self.fix_table.item(sel[0].row(), 0).data(Qt.UserRole)
        e = next((x for x in shifts.to_fix() if x['id'] == entry_id), None)
        if e:
            self.edit_entry(e['staffId'], e)

    def edit_entry(self, staff_id, entry):
        from pos_screen import authorize
        dlg = EditEntryDialog(staff_id, entry, self)
        if dlg.exec() != QDialog.Accepted:
            return False
        approver, _ = authorize(self, self.user, 'shifts', "Mesai düzeltme", need_reason=False)
        if not approver:
            return False
        try:
            shifts.edit(self.user, dlg.staff_id, dlg.clock_in, dlg.clock_out, dlg.reason, approver_id=approver,
                        entry_id=(entry or {}).get('id'))
        except OrderError as e:
            QMessageBox.warning(self, "Mesai düzeltme", str(e))
            return False
        ctx.request_sync()
        ToastNotification(self.window(), "Mesai düzeltildi; eski ve yeni değer kayda geçti.", "success")
        self.refresh()
        return True

    def _detail(self, row):
        if row < 0 or row >= len(self.rows):
            return
        DetailDialog(self, self.rows[row]['staffId'], self.rows[row]['name'], *self.range).exec()
        self.refresh()

    def _wages(self):
        WagesDialog(self).exec()

    def export_data(self):
        a, b = self.range
        title = f"Mesai {date.fromisoformat(a):%d.%m.%Y}-{date.fromisoformat(b):%d.%m.%Y}"
        cols = [c for c in range(len(COLUMNS)) if not self.table.isColumnHidden(c)]
        headers = [COLUMNS[c] for c in cols]
        rows = [[self.table.item(r, c).text() if self.table.item(r, c) else '' for c in cols]
                for r in range(self.table.rowCount())]
        return title, headers, rows

    def export_csv(self, path=None):
        from reports_screen import write_csv
        title, headers, rows = self.export_data()
        path = path or QFileDialog.getSaveFileName(self, "CSV kaydet", f"{title}.csv", "CSV (*.csv)")[0]
        if path:
            write_csv(path, headers, rows)
        return path

    def export_pdf(self, path=None):
        import printing
        from reports_screen import table_html
        title, headers, rows = self.export_data()
        path = path or QFileDialog.getSaveFileName(self, "PDF kaydet", f"{title}.pdf", "PDF (*.pdf)")[0]
        if path:
            printing.save_pdf(table_html(database.general_settings()['cafeName'], title, headers, rows), title, 'A4', path)
        return path


class DetailDialog(QDialog):
    """Gün gün döküm: plan, giriş, çıkış, mola, çalışılan, geç, işaretler; satırdan düzeltme."""

    def __init__(self, page, staff_id, name, day_from, day_to):
        super().__init__(page)
        self.page, self.staff_id = page, staff_id
        self.range = (day_from, day_to)
        self.setWindowTitle(f"Mesai dökümü · {name}")
        self.setMinimumSize(760, 480)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Gün", "Plan", "Giriş", "Çıkış", "Mola", "Çalışılan", "Geç", "Not"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        ly.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(_muted("Satırı seçip düzeltin; gerekçe zorunludur ve eski/yeni değer kayda geçer."), 1)
        fix = _button("Düzelt", primary=False)
        fix.clicked.connect(self._fix)
        fix.setEnabled(database.user_can(page.user, 'shifts'))
        row.addWidget(fix)
        close = _button("Kapat", primary=False)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        ly.addLayout(row)
        self.refresh()

    def refresh(self):
        self.items = shifts.detail(self.staff_id, *self.range)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.items))
        for r, x in enumerate(self.items):
            e, p = x['entry'], x['plan']
            flags = []
            if e and 'forgotClockOut' in e.get('flags', []):
                flags.append("çıkış unutuldu" + (" (düzeltildi)" if e.get('resolved') else ""))
            elif e and 'edited' in e.get('flags', []):
                flags.append(f"düzeltildi: {e.get('reason', '')}")
            if not e and p and not p.get('leave') and x['day'] < shifts.today():
                flags.append("gelmedi")
            d = date.fromisoformat(x['day'])
            cells = [f"{shifts.WEEKDAYS_SHORT[d.weekday()]} {d:%d.%m}", shifts.plan_label(p) or '—',
                     clock_time(e['clockIn']) if e else '—', clock_time(e.get('clockOut')) if e else '—',
                     L.format_minutes(x['breaks']) if e else '', L.format_minutes(x['worked']) if e else '',
                     f"{x['late']} dk" if x['late'] else '', ", ".join(flags)]
            for c, v in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(v))

    def _fix(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return
        x = self.items[sel[0].row()]
        if self.page.edit_entry(self.staff_id, x['entry'] or _blank_entry(self.staff_id, x['day'], x['plan'])):
            self.refresh()


def _blank_entry(staff_id, day, plan):
    """Gelmedi görünen güne kayıt eklerken önerilen saatler (plandan)."""
    return {'staffId': staff_id, 'businessDay': day, 'new': True,
            'clockIn': f"{day}T{(plan or {}).get('start') or '09:00'}:00",
            'clockOut': f"{day}T{(plan or {}).get('end') or '17:00'}:00"}


class EditEntryDialog(QDialog):
    """Giriş/çıkış saatini düzelt; çıkış girişten önceyse ertesi gün sayılır. Gerekçe zorunlu."""

    def __init__(self, staff_id, entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.staff_id = staff_id
        self.setWindowTitle("Mesai düzeltme" if entry and not entry.get('new') else "Eksik mesai kaydı")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        form.setContentsMargins(24, 20, 24, 20)
        self.person = QComboBox()
        for s in database.get_login_staff():
            self.person.addItem(s['name'], s['id'])
        if staff_id:
            self.person.setCurrentIndex(max(self.person.findData(staff_id), 0))
            self.person.setEnabled(False)
        form.addRow("Personel:", self.person)
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd.MM.yyyy")
        self.cin, self.cout = QTimeEdit(), QTimeEdit()
        for t in (self.cin, self.cout):
            t.setDisplayFormat("HH:mm")
            t.setMinimumHeight(40)
        e = entry or {}
        ci = e.get('clockIn') or f"{shifts.today()}T09:00:00"
        co = e.get('clockOut') or f"{ci[:10]}T17:00:00"
        self.day.setDate(QDate.fromString(e.get('businessDay') or ci[:10], 'yyyy-MM-dd'))
        self.cin.setTime(QTime.fromString(ci[11:16], 'HH:mm'))
        self.cout.setTime(QTime.fromString(co[11:16], 'HH:mm'))
        form.addRow("İş günü:", self.day)
        form.addRow("Giriş:", self.cin)
        form.addRow("Çıkış:", self.cout)
        if e.get('clockIn') and not e.get('new'):
            form.addRow(_muted(f"Kayıttaki: {clock_time(e['clockIn'])} – {clock_time(e.get('clockOut'))}"))
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("Ör. kapanışta kaldı, çıkış basmayı unuttu")
        self.reason_edit.setMaxLength(120)
        form.addRow("Gerekçe:", self.reason_edit)
        self.error = QLabel()
        self.error.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
        form.addRow(self.error)
        ok = _button("Kaydet")
        ok.clicked.connect(self._ok)
        form.addRow(ok)
        self.clock_in = self.clock_out = self.reason = None

    def iso(self, day, t):
        """İş günü + saat → yerel ISO (05:00'ten önceki saat ertesi takvim günüdür)."""
        d = date.fromisoformat(day)
        if t.hour() < L.DAY_START_HOUR:
            d += timedelta(days=1)
        offset = shifts.now_iso()[19:]
        return f"{d.isoformat()}T{t.toString('HH:mm')}:00{offset}"

    def _ok(self):
        self.reason = self.reason_edit.text().strip()
        if not self.reason:
            self.error.setText("Gerekçe zorunludur.")
            return
        day = self.day.date().toString('yyyy-MM-dd')
        self.staff_id = self.person.currentData()
        self.clock_in = self.iso(day, self.cin.time())
        self.clock_out = self.iso(day, self.cout.time())
        if L.local_minutes(self.clock_out) <= L.local_minutes(self.clock_in):
            nxt = (date.fromisoformat(self.clock_out[:10]) + timedelta(days=1)).isoformat()
            self.clock_out = nxt + self.clock_out[10:]
        if L.local_minutes(self.clock_out) - L.local_minutes(self.clock_in) > 20 * 60:
            self.error.setText("Mesai 20 saati geçemez; saatleri kontrol edin.")
            return
        self.accept()


class WagesDialog(QDialog):
    """Saatlik ücretler: yalnızca Yönetici; buluttan okunur, terminal önbelleğine yazılmaz."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.user = page.user
        self.setWindowTitle("Saatlik ücretler")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumWidth(420)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(24, 20, 24, 20)
        self.form.addRow(_muted("Ücretler yalnızca Yönetici'ye görünür ve bu bilgisayara kaydedilmez. "
                                "Boş bırakılan kişi işçilik maliyetine katılmaz."))
        self.edits = {}
        for s in database.get_login_staff():
            e = QLineEdit()
            e.setPlaceholderText("₺ / saat")
            self.edits[s['id']] = e
            self.form.addRow(s['name'], e)
        row = QHBoxLayout()
        load = _button("Getir", primary=False)
        load.clicked.connect(self._load)
        save = _button("Kaydet")
        save.clicked.connect(self._save)
        row.addStretch()
        row.addWidget(load)
        row.addWidget(save)
        self.form.addRow(row)
        if page.wages is not None:
            self._show(page.wages)
        else:
            self._load()

    def _show(self, wages):
        for sid, e in self.edits.items():
            v = wages.get(sid)
            e.setText(format_tl(v).replace(' ₺', '') if v else '')

    def _load(self):
        def done(wages):
            self.page.wages = wages
            self._show(wages)
            self.page.refresh()
        cloud_action(self, lambda api: api.get_wages(), "Ücretler getirildi.", done)

    def values(self):
        out = {}
        for sid, e in self.edits.items():
            t = e.text().strip()
            out[sid] = parse_tl(t) if t else None
        return out

    def _save(self):
        try:
            wages = self.values()
        except ValueError:
            QMessageBox.warning(self, "Saatlik ücret", "Tutar geçersiz.")
            return

        def done(_):
            self.page.wages = wages
            self.page.refresh()
            self.accept()
        cloud_action(self, lambda api: api.save_wages(wages), "Ücretler kaydedildi.", done)


# =====================================================================
# Panel sayfası
# =====================================================================

class StaffShiftsPage(QWidget):
    """Personel: Vardiya Planı · Mesai"""

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
        self.plan = PlanPage(user)
        self.timesheet = TimesheetPage(user)
        self.tabs.addTab(self.plan, "Vardiya Planı")
        self.tabs.addTab(self.timesheet, "Mesai")
        self._last = 0
        self.tabs.currentChanged.connect(self._tab)
        ly.addWidget(self.tabs)

    def _tab(self, idx):
        if self._last == 0 and idx != 0 and not self.plan.can_leave():
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(0)
            self.tabs.blockSignals(False)
            return
        self._last = idx
        self.refresh()

    def can_leave(self):
        return self.plan.can_leave()

    def refresh(self):
        w = self.tabs.currentWidget()
        if w is self.plan and self.plan.changes:
            return  # düzenleme sürerken yerel değişiklikler korunur
        w.refresh()
