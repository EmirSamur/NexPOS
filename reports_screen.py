"""
NexPOS - Ana Sayfa (gösterge paneli) ve Raporlar (7. ekran)

Rakamlar reports.py'den gelir (yerel adisyonlar; internetsiz çalışır, kasa Z raporuyla aynı hesap).

Grafik kuralları: tek eksen, ince işaretler, iki seri için açıklama, her işarette fareyle değer
(tooltip), ısı haritası tek renk tonunda açıktan koyuya, artış/azalış ok + metinle (yalnız renk değil).
"""
import csv
from datetime import date, datetime

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget,
    QToolTip, QVBoxLayout, QWidget
)

import database
import reports
from cloud.permissions import PANEL_ROLES
from money import format_tl
from pos import PAYMENT_LABELS
from styles import COLORS, FONTS
from widgets import PageHeader

# Doğrulanmış seri renkleri (açık zemin): bugün / geçen hafta
SERIES_1 = '#2a78d6'
SERIES_2 = '#eb6834'
# Sıralı (ısı haritası) mavi rampa: az → çok
RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']
GRID = '#E2E8F0'
UP, DOWN = '#15803D', '#B91C1C'
MONTHS = ('Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim',
          'Kasım', 'Aralık')
BUSINESS_HOURS = [f"{(reports.DAY_START_HOUR + i) % 24:02d}" for i in range(24)]


def tl(kurus):
    return format_tl(kurus)


def tl_short(kurus):
    """Eksen ve kart için yuvarlak lira: 12480 ₺"""
    return f"{round(kurus / 100):,} ₺".replace(',', '.')


def day_label(iso):
    d = date.fromisoformat(iso)
    return f"{reports.WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def duration(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m} dk {s:02d} sn" if m else f"{s} sn"


def change_text(pct, inverse=False):
    """(metin, renk): '▲ %8' yeşil / '▼ %3' kırmızı; inverse=True iken artış kötüdür (iade, iskonto)."""
    if pct is None:
        return "—", COLORS['text_muted']
    if pct == 0:
        return "= %0", COLORS['text_secondary']
    good = (pct > 0) != inverse
    return (f"▲ %{pct}" if pct > 0 else f"▼ %{-pct}"), (UP if good else DOWN)


def _card(parent=None):
    f = QFrame(parent)
    f.setObjectName("rcard")
    f.setStyleSheet(f"QFrame#rcard {{ background: white; border-radius: 12px; border: 1px solid {GRID}; }}")
    return f


def _title(text):
    t = QLabel(text)
    t.setStyleSheet(f"color: {COLORS['text_dark']}; font-weight: bold; font-size: 14px; background: transparent;")
    return t


def _muted(text):
    t = QLabel(text)
    t.setWordWrap(True)
    t.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
    return t


# =====================================================================
# Bileşenler
# =====================================================================

class KpiTile(QFrame):
    clicked = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("kpi")
        self.setStyleSheet(f"QFrame#kpi {{ background: white; border-radius: 12px; border: 1px solid {GRID}; }}")
        self.setMinimumHeight(104)
        ly = QVBoxLayout(self)
        ly.setContentsMargins(16, 12, 16, 12)
        ly.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; font-weight: bold; background: transparent;")
        self.value = QLabel("—")
        self.value.setFont(QFont(FONTS['family'], 22, QFont.Bold))
        self.value.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        self.sub = QLabel("")
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent;")
        ly.addWidget(t)
        ly.addWidget(self.value)
        ly.addWidget(self.sub)

    def set(self, value, sub="", sub_color=None):
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setStyleSheet(f"color: {sub_color or COLORS['text_secondary']}; font-size: 12px; "
                               f"font-weight: {'bold' if sub_color else 'normal'}; background: transparent;")

    def mousePressEvent(self, e):
        self.clicked.emit()


class HourlyChart(QWidget):
    """Saatlik ciro: bugün çubuk (mavi), geçen haftanın aynı günü çizgi (turuncu, kesikli)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.today, self.last, self.hours = {}, {}, []
        self.until = None
        self.hover = None

    def set_data(self, today, last, until=None):
        """until: geçen hafta çizgisi bu saatte biter (karşılaştırma şu ana kadardır)."""
        self.today, self.last, self.until = today, last, until
        used = [i for i, h in enumerate(BUSINESS_HOURS) if today.get(h) or last.get(h)]
        first = min(used + [3]) if used else 3      # en geç 08:00'den başla
        last_i = max(used + [17]) if used else 17   # en erken 22:00'ye kadar
        self.hours = BUSINESS_HOURS[first:last_i + 1]
        self.update()

    def _geometry(self):
        left, right, top, bottom = 62, 12, 28, 26
        w, h = self.width() - left - right, self.height() - top - bottom
        top_val = max([self.today.get(x, 0) for x in self.hours] + [self.last.get(x, 0) for x in self.hours] + [1])
        step = self._nice_step(top_val)
        top_val = step * 4
        return left, top, w, h, top_val, step

    @staticmethod
    def _nice_step(v):
        raw = v / 4
        mag = 10 ** max(0, len(str(int(raw))) - 1)
        for m in (1, 2, 2.5, 5, 10):
            if raw <= m * mag:
                return int(m * mag)
        return int(10 * mag)

    def paintEvent(self, e):
        if not self.hours:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, top, w, h, top_val, step = self._geometry()
        f = QFont(FONTS['family'])
        f.setPixelSize(11)
        p.setFont(f)
        # Izgara ve eksen etiketleri (sönük)
        for i in range(5):
            y = top + h - h * i / 4
            p.setPen(QPen(QColor(GRID), 1))
            p.drawLine(QPointF(left, y), QPointF(left + w, y))
            p.setPen(QColor(COLORS['text_muted']))
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignRight | Qt.AlignVCenter, tl_short(step * i))
        n = len(self.hours)
        slot = w / n
        bar_w = max(4.0, min(28.0, slot * 0.6))
        for i, hour in enumerate(self.hours):
            x = left + slot * i + slot / 2
            v = self.today.get(hour, 0)
            if v:
                bh = h * v / top_val
                path = QPainterPath()
                r = min(4.0, bar_w / 2, bh)
                rect = QRectF(x - bar_w / 2, top + h - bh, bar_w, bh)
                path.addRoundedRect(rect, r, r)
                path.addRect(QRectF(rect.x(), rect.bottom() - r, rect.width(), r))  # tabana oturur
                color = QColor(SERIES_1)
                if self.hover is not None and self.hover != i:
                    color.setAlpha(150)
                p.fillPath(path.simplified(), color)
            if i % 2 == 0 or n <= 12:
                p.setPen(QColor(COLORS['text_muted']))
                p.drawText(QRectF(x - 20, top + h + 6, 40, 16), Qt.AlignCenter, f"{hour}:00")
        # Geçen hafta: kesikli çizgi + işaretler
        shown = self.hours
        if self.until in self.hours:
            shown = self.hours[:self.hours.index(self.until) + 1]
        pts = [QPointF(left + slot * i + slot / 2, top + h - h * self.last.get(hr, 0) / top_val)
               for i, hr in enumerate(shown)]
        if any(self.last.get(hr) for hr in shown):
            pen = QPen(QColor(SERIES_2), 2, Qt.DashLine)
            p.setPen(pen)
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
            p.setPen(QPen(QColor('white'), 2))
            p.setBrush(QColor(SERIES_2))
            for pt in pts:
                p.drawEllipse(pt, 4, 4)
        # Açıklama (iki seri)
        x = left
        for color, text, dashed in ((SERIES_1, "Bugün", False), (SERIES_2, "Geçen hafta aynı gün", True)):
            if dashed:
                p.setPen(QPen(QColor(color), 2, Qt.DashLine))
                p.drawLine(QPointF(x, 10), QPointF(x + 16, 10))
            else:
                p.fillRect(QRectF(x, 4, 12, 12), QColor(color))
            p.setPen(QColor(COLORS['text_secondary']))
            p.drawText(QRectF(x + 20, 2, 160, 16), Qt.AlignLeft | Qt.AlignVCenter, text)
            x += 40 + p.fontMetrics().horizontalAdvance(text)
        # Fareyle üzerine gelinen saat: dikey çizgi
        if self.hover is not None:
            hx = left + slot * self.hover + slot / 2
            p.setPen(QPen(QColor(COLORS['text_muted']), 1))
            p.drawLine(QPointF(hx, top), QPointF(hx, top + h))
        p.end()

    def mouseMoveEvent(self, e):
        if not self.hours:
            return
        left, top, w, h, *_ = self._geometry()
        i = int((e.position().x() - left) // (w / len(self.hours)))
        if not 0 <= i < len(self.hours):
            self.hover = None
            QToolTip.hideText()
        else:
            self.hover = i
            hour = self.hours[i]
            nxt = f"{(int(hour) + 1) % 24:02d}"
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"<b>{hour}:00–{nxt}:00</b><br>Bugün: {tl(self.today.get(hour, 0))}"
                              f"<br>Geçen hafta: {tl(self.last.get(hour, 0))}", self)
        self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()


class BarList(QWidget):
    """Yatay çubuk listesi (tek seri): etiket · ince çubuk · değer. Fareyle değer."""

    def __init__(self, fmt=tl, parent=None):
        super().__init__(parent)
        self.fmt = fmt
        self.rows = []
        self.setMouseTracking(True)

    def set_rows(self, rows):
        """rows: [(etiket, değer)]"""
        self.rows = rows
        self.setMinimumHeight(max(40, 30 * len(rows)))
        self.update()

    def paintEvent(self, e):
        if not self.rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(FONTS['family'])
        f.setPixelSize(12)
        p.setFont(f)
        label_w = min(170, self.width() * 0.4)
        value_w = 90
        bar_max = self.width() - label_w - value_w - 16
        top = max(v for _, v in self.rows) or 1
        for i, (label, v) in enumerate(self.rows):
            y = i * 30
            p.setPen(QColor(COLORS['text_dark']))
            p.drawText(QRectF(0, y, label_w - 8, 26), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(label, Qt.ElideRight, int(label_w - 8)))
            bw = max(2.0, bar_max * v / top) if v else 0
            if bw:
                path = QPainterPath()
                path.addRoundedRect(QRectF(label_w, y + 8, bw, 10), 4, 4)
                p.fillPath(path, QColor(SERIES_1))
            p.setPen(QColor(COLORS['text_secondary']))
            p.drawText(QRectF(label_w + bw + 6, y, value_w + 40, 26), Qt.AlignVCenter | Qt.AlignLeft, self.fmt(v))
        p.end()

    def mouseMoveEvent(self, e):
        i = int(e.position().y() // 30)
        if 0 <= i < len(self.rows):
            QToolTip.showText(e.globalPosition().toPoint(), f"{self.rows[i][0]}: {self.fmt(self.rows[i][1])}", self)


class Heatmap(QWidget):
    """Gün × saat ısı haritası (ciro). Tek renk tonu: açık = az, koyu = çok."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = {}
        self.hours = []
        self.setMinimumHeight(7 * 30 + 60)
        self.setMouseTracking(True)

    def set_data(self, grid):
        self.grid = grid
        used = sorted({BUSINESS_HOURS.index(h) for (_, h) in grid if h in BUSINESS_HOURS})
        a = min(used + [3]) if used else 3
        b = max(used + [17]) if used else 17
        self.hours = BUSINESS_HOURS[a:b + 1]
        self.update()

    def _cell(self):
        left = 90
        cw = (self.width() - left - 8) / max(1, len(self.hours))
        return left, cw, 30

    def paintEvent(self, e):
        if not self.hours:
            return
        p = QPainter(self)
        f = QFont(FONTS['family'])
        f.setPixelSize(11)
        p.setFont(f)
        left, cw, ch = self._cell()
        top_val = max(self.grid.values() or [1])
        for d in range(7):
            p.setPen(QColor(COLORS['text_secondary']))
            p.drawText(QRectF(0, d * ch, left - 8, ch), Qt.AlignVCenter | Qt.AlignRight, reports.WEEKDAYS[d])
            for i, hour in enumerate(self.hours):
                v = self.grid.get((d, hour), 0)
                rect = QRectF(left + i * cw + 1, d * ch + 1, cw - 2, ch - 2)  # 2px zemin boşluğu
                if v:
                    p.fillRect(rect, QColor(RAMP[min(len(RAMP) - 1, int(v * len(RAMP) / (top_val + 1)))]))
                else:
                    p.fillRect(rect, QColor('#F8FAFC'))
        for i, hour in enumerate(self.hours):
            if i % 2 == 0:
                p.setPen(QColor(COLORS['text_muted']))
                p.drawText(QRectF(left + i * cw - 10, 7 * ch + 4, cw + 20, 16), Qt.AlignCenter, f"{hour}")
        # Açıklama: az → çok
        y = 7 * ch + 28
        p.setPen(QColor(COLORS['text_secondary']))
        p.drawText(QRectF(left, y, 30, 16), Qt.AlignVCenter, "az")
        for i, c in enumerate(RAMP):
            p.fillRect(QRectF(left + 30 + i * 18, y + 3, 16, 10), QColor(c))
        p.drawText(QRectF(left + 34 + len(RAMP) * 18, y, 40, 16), Qt.AlignVCenter, "çok")
        p.end()

    def mouseMoveEvent(self, e):
        if not self.hours:
            return
        left, cw, ch = self._cell()
        d, i = int(e.position().y() // ch), int((e.position().x() - left) // cw)
        if 0 <= d < 7 and 0 <= i < len(self.hours):
            hour = self.hours[i]
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"{reports.WEEKDAYS[d]} {hour}:00 · {tl(self.grid.get((d, hour), 0))}", self)


class SortItem(QTableWidgetItem):
    """Biçimli metin gösterir, sayıya göre sıralar."""

    def __init__(self, text, key):
        super().__init__(text)
        self.key = key

    def __lt__(self, other):
        a, b = self.key, getattr(other, 'key', other.text())
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def make_table(columns, sort=None):
    """columns: [(başlık, genişleyen?)]; sort: (sütun, Qt.SortOrder) varsayılan sıralama, yoksa geliş sırası."""
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels([c[0] for c in columns])
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.setSortingEnabled(True)
    if sort:
        t.sortByColumn(*sort)
    else:
        t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
    t.setStyleSheet(f"QTableWidget {{ background: white; border-radius: 10px; border: 1px solid {GRID}; }}")
    for i, (_, stretch) in enumerate(columns):
        t.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch if stretch else QHeaderView.ResizeToContents)
    return t


def fill_table(table, rows):
    """rows: [[(metin, sıralama anahtarı, sağa yaslı?)]]"""
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, (text, key, right) in enumerate(row):
            item = SortItem(text, key)
            if right:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(i, j, item)
    table.setSortingEnabled(True)


def money_cell(v):
    return (tl(v), v, True)


def num_cell(v, suffix=''):
    return (f"{v}{suffix}", v, True)


def text_cell(v):
    return (str(v), str(v).lower(), False)


# =====================================================================
# Ana Sayfa
# =====================================================================

class DashboardPage(QWidget):
    navigate = Signal(str)   # 'losses' | 'cash' | 'terminals' | 'reports'

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        body = QWidget()
        body.setStyleSheet(f"background: {COLORS['bg_main']};")
        ly = QVBoxLayout(body)
        ly.setContentsMargins(28, 20, 28, 24)
        ly.setSpacing(14)
        self.heading = QLabel()
        self.heading.setFont(QFont(FONTS['family'], FONTS['size_xl'], QFont.Bold))
        self.heading.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        ly.addWidget(self.heading)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.t_revenue, self.t_orders, self.t_avg = KpiTile("Ciro"), KpiTile("Adisyon"), KpiTile("Ortalama adisyon")
        self.t_tables, self.t_cash = KpiTile("Açık masa"), KpiTile("Kasa")
        self.t_cash.setCursor(Qt.PointingHandCursor)
        self.t_cash.clicked.connect(lambda: self.navigate.emit('cash'))
        for t in (self.t_revenue, self.t_orders, self.t_avg, self.t_tables, self.t_cash):
            tiles.addWidget(t, 1)
        ly.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(12)
        c1 = _card()
        l1 = QVBoxLayout(c1)
        l1.setContentsMargins(16, 12, 16, 12)
        l1.addWidget(_title("Saatlik satış"))
        self.hourly = HourlyChart()
        l1.addWidget(self.hourly, 1)
        self.hourly_note = _muted("")
        l1.addWidget(self.hourly_note)
        row.addWidget(c1, 2)
        c2 = _card()
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(16, 12, 16, 12)
        l2.addWidget(_title("En çok satanlar (adet)"))
        self.top = BarList(fmt=lambda v: f"{v} adet")
        l2.addWidget(self.top)
        l2.addStretch()
        row.addWidget(c2, 1)
        ly.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        c3 = _card()
        self.alerts_ly = QVBoxLayout(c3)
        self.alerts_ly.setContentsMargins(16, 12, 16, 12)
        row2.addWidget(c3, 2)
        self.kitchen_card = _card()
        self.kitchen_ly = QVBoxLayout(self.kitchen_card)
        self.kitchen_ly.setContentsMargins(16, 12, 16, 12)
        row2.addWidget(self.kitchen_card, 1)
        ly.addLayout(row2)
        ly.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(30000)
        self.refresh()

    def refresh(self):
        d = reports.dashboard()
        self.heading.setText(f"Bugün · {day_label(d['day'])}  "
                             f"<span style='font-size:13px; color:{COLORS['text_secondary']}; font-weight:normal'>"
                             f"(gün 05:00'te döner)</span>")
        self.heading.setTextFormat(Qt.RichText)
        cmp_note = f"geçen {reports.WEEKDAYS[date.fromisoformat(d['compareDay']).weekday()]}'ya göre"
        for tile, value, pct in ((self.t_revenue, tl_short(d['revenue']), d['revenueChange']),
                                 (self.t_orders, str(d['orders']), d['ordersChange']),
                                 (self.t_avg, tl_short(d['average']), d['averageChange'])):
            text, color = change_text(pct)
            tile.set(value, f"{text} {cmp_note}" if pct is not None else "geçen haftayla karşılaştırma yok", color
                     if pct is not None else None)
        self.t_tables.set(f"{d['openTables']} / {d['totalTables']}",
                          f"{tl(d['openAmount'])} açık hesap" if d['openAmount'] else "açık hesap yok")
        modules = database.modules()
        show_cash = bool(d['cashSession']) or modules['cashSession']['required']
        self.t_cash.setVisible(show_cash)
        if d['cashSession']:
            self.t_cash.set("🟢 Açık", f"Beklenen nakit {tl(d['expectedCash'])}")
        else:
            self.t_cash.set("🔴 Kapalı", "Nakit için kasa açılmalı", DOWN)
        self.hourly.set_data(d['hourly'], d['hourlyLast'], d['hour'])
        self.hourly_note.setText(f"Geçen haftanın aynı günü, şu anki saate kadar ({d['compareDay']}). "
                                 "Ayrıntı için çubuğun üzerine gelin.")
        self.top.set_rows([(p['name'], p['qty']) for p in d['top']])
        self._alerts(d)
        self._kitchen(d)

    def _clear(self, layout):
        while layout.count():
            w = layout.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)

    def _link(self, text, target):
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"QPushButton {{ text-align: left; border: none; background: transparent; padding: 4px 0;"
                        f" color: {COLORS['text_dark']}; font-size: 13px; }}"
                        f"QPushButton:hover {{ color: {COLORS['primary']}; text-decoration: underline; }}")
        b.clicked.connect(lambda: self.navigate.emit(target))
        return b

    def _alerts(self, d):
        self._clear(self.alerts_ly)
        self.alerts_ly.addWidget(_title("Dikkat edilecekler"))
        if not d['alerts']:
            self.alerts_ly.addWidget(_muted("✓ Bugün iptal, ikram ya da iskonto yok; kasa ve senkron sorunsuz."))
        for a in d['alerts']:
            if a['target'] == 'losses':
                v, c = a['voids'], a['comps']
                text = (f"⚠ {v.get('count', 0)} iptal ({tl(v.get('amount', 0))}) · {c.get('count', 0)} ikram "
                        f"({tl(c.get('amount', 0))}) · iskonto {tl(a['discount'])}  →  Kayıp ve Denetim")
            elif a['target'] == 'cash':
                text = (f"⚠ Son kasa farkı ({a['day']}): {format_tl(a['difference'], sign=True)}"
                        + (f" — {a['reason']}" if a['reason'] else "") + "  →  Kasa")
            elif a['target'] == 'stock':
                more = f" (+{len(a['items']) - 4})" if len(a['items']) > 4 else ""
                text = f"⚠ {len(a['items'])} malzeme kritik seviyede: {', '.join(a['items'][:4])}{more}  →  Stok"
            else:
                text = f"⚠ {a['failed']} işlem buluta gönderilemedi  →  Terminaller"
            self.alerts_ly.addWidget(self._link(text, a['target']))
        self.alerts_ly.addStretch()

    def _kitchen(self, d):
        self.kitchen_card.setVisible(d['kitchen'] is not None)
        if d['kitchen'] is None:
            return
        self._clear(self.kitchen_ly)
        self.kitchen_ly.addWidget(_title("Mutfak / bar (bugün)"))
        if not d['kitchen']['stations']:
            self.kitchen_ly.addWidget(_muted("Henüz hazır denen fiş yok."))
        for s in d['kitchen']['stations']:
            name = 'Bar' if s['station'] == 'bar' else 'Mutfak'
            self.kitchen_ly.addWidget(QLabel(f"<b>{name}</b>: ortalama {duration(s['average'])} · "
                                             f"{s['tickets']} fiş · geciken %{s['lateRate']}"))
        self.kitchen_ly.addStretch()


# =====================================================================
# Raporlar
# =====================================================================

class ReportsPage(QWidget):
    open_cash_history = Signal()
    TAB_SUMMARY, TAB_PRODUCTS, TAB_MENU, TAB_TIME, TAB_STAFF, TAB_LOSSES, TAB_INCOME, TAB_KITCHEN = range(8)
    MENU_CLASSES = {'star': ("★ Yıldız", "çok satıyor, kârlı — öne çıkarın"),
                    'plowhorse': ("🐴 İş atı", "çok satıyor, az kârlı — maliyeti düşürün ya da fiyatı gözden geçirin"),
                    'puzzle': ("🧩 Bulmaca", "kârlı ama az satıyor — menüde görünürlüğünü artırın"),
                    'dog': ("🐶 Köpek", "az satıyor, az kârlı — menüden çıkarmayı düşünün")}

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.report = None
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 16, 28, 20)
        ly.setSpacing(10)
        ly.addWidget(PageHeader("Raporlar", "Satış, ürün, saat, personel, kayıp ve gelir-gider raporları",
                                COLORS['info'], "📊"))

        bar = QHBoxLayout()
        self.preset = QComboBox()
        for key, label in reports.PERIODS:
            self.preset.addItem(label, key)
        self.preset.addItem("Özel aralık", 'custom')
        self.preset.setMinimumHeight(36)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        bar.addWidget(self.preset)
        self.d_from, self.d_to = QDateEdit(), QDateEdit()
        for de in (self.d_from, self.d_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("dd.MM.yyyy")
            de.setMinimumHeight(36)
            de.dateChanged.connect(self._custom_changed)
            bar.addWidget(de)
        self.compare = QCheckBox("Önceki dönemle karşılaştır")
        self.compare.setChecked(True)
        self.compare.toggled.connect(self.refresh)
        bar.addWidget(self.compare)
        self.range_label = _muted("")
        bar.addWidget(self.range_label, 1)
        for text, fn in (("⬇ CSV", self.export_csv), ("⬇ PDF", self.export_pdf)):
            b = QPushButton(text)
            b.setMinimumHeight(36)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            bar.addWidget(b)
        cash_btn = QPushButton("Kasa oturumları →")
        cash_btn.setMinimumHeight(36)
        cash_btn.clicked.connect(self.open_cash_history.emit)
        bar.addWidget(cash_btn)
        ly.addLayout(bar)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{ padding: 9px 16px; font-weight: bold; color: {COLORS['text_secondary']};
                background: transparent; border-bottom: 3px solid transparent; }}
            QTabBar::tab:selected {{ color: {COLORS['primary']}; border-bottom-color: {COLORS['primary']}; }}
        """)
        self.tabs.addTab(self._summary_tab(), "Satış Özeti")
        self.tabs.addTab(self._products_tab(), "Ürünler")
        self.tabs.addTab(self._menu_tab(), "Menü Analizi")
        self.tabs.addTab(self._time_tab(), "Saatler ve Günler")
        self.tabs.addTab(self._staff_tab(), "Personel")
        self.tabs.addTab(self._losses_tab(), "Kayıp ve Denetim")
        self.tabs.addTab(self._income_tab(), "Gelir – Gider")
        self.tabs.addTab(self._kitchen_tab(), "Mutfak")
        ly.addWidget(self.tabs, 1)
        self._loading = True
        self._preset_changed()
        self._loading = False
        self.refresh()

    # ------------------------------------------------------------------ dönem
    def _preset_changed(self, *_):
        key = self.preset.currentData()
        custom = key == 'custom'
        for de in (self.d_from, self.d_to):
            de.setVisible(custom)
        if not custom:
            a, b = reports.period(key)
            self._loading, was = True, self._loading
            self.d_from.setDate(QDate.fromString(a, "yyyy-MM-dd"))
            self.d_to.setDate(QDate.fromString(b, "yyyy-MM-dd"))
            self._loading = was
            self.refresh()

    def _custom_changed(self, *_):
        if not getattr(self, '_loading', False) and self.preset.currentData() == 'custom':
            self.refresh()

    def set_period(self, key, tab=None):
        self.preset.setCurrentIndex(self.preset.findData(key))
        if tab is not None:
            self.tabs.setCurrentIndex(tab)

    def period(self):
        a = self.d_from.date().toString("yyyy-MM-dd")
        b = self.d_to.date().toString("yyyy-MM-dd")
        return (a, b) if a <= b else (b, a)

    # ------------------------------------------------------------------ sekmeler
    def _scroll(self, inner):
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner.setStyleSheet(f"background: {COLORS['bg_main']};")
        s.setWidget(inner)
        return s

    def _summary_tab(self):
        w = QWidget()
        ly = QHBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        ly.setSpacing(12)
        left = _card()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 12, 16, 12)
        ll.addWidget(_title("Satış"))
        self.sum_grid = QGridLayout()
        self.sum_grid.setHorizontalSpacing(24)
        ll.addLayout(self.sum_grid)
        ll.addStretch()
        ly.addWidget(left, 3)
        right = QVBoxLayout()
        c1 = _card()
        l1 = QVBoxLayout(c1)
        l1.setContentsMargins(16, 12, 16, 12)
        l1.addWidget(_title("Ödeme yöntemleri"))
        self.pay_bars = BarList()
        l1.addWidget(self.pay_bars)
        right.addWidget(c1)
        c2 = _card()
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(16, 12, 16, 12)
        l2.addWidget(_title("KDV dökümü"))
        self.vat_table = make_table([("KDV oranı", False), ("KDV dahil tutar", True), ("Matrah", True), ("KDV", True)])
        self.vat_table.setMaximumHeight(150)
        l2.addWidget(self.vat_table)
        l2.addWidget(_muted("Bilgi amaçlıdır; resmi kayıt ÖKC / e-Arşiv'dir."))
        right.addWidget(c2)
        right.addStretch()
        ly.addLayout(right, 2)
        return self._scroll(w)

    def _products_tab(self):
        w = QWidget()
        ly = QHBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        ly.setSpacing(12)
        self.product_table = make_table([("Ürün", True), ("Adet", False), ("Ciro", False), ("Pay", False),
                                         ("İkram", False), ("İptal", False), ("Maliyet", False), ("Kâr", False),
                                         ("Marj", False)], sort=(2, Qt.DescendingOrder))
        ly.addWidget(self.product_table, 3)
        side = QVBoxLayout()
        c = _card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.addWidget(_title("Kategoriler (ciro)"))
        self.cat_bars = BarList()
        cl.addWidget(self.cat_bars)
        side.addWidget(c)
        side.addWidget(_title("Seçenekler"))
        self.option_table = make_table([("Seçenek", True), ("Seçilme", False), ("Ek gelir", False)],
                                       sort=(1, Qt.DescendingOrder))
        self.option_table.setMinimumHeight(160)
        side.addWidget(self.option_table)
        self.unsold = _muted("")
        side.addWidget(self.unsold)
        ly.addLayout(side, 2)
        return self._scroll(w)

    def _menu_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        self.menu_note = _muted("")
        ly.addWidget(self.menu_note)
        self.menu_table = make_table([("Grup", False), ("Ürün", True), ("Adet", False), ("Birim kâr", False),
                                      ("Toplam kâr", False), ("Marj", False), ("Öneri", True)])
        ly.addWidget(self.menu_table, 1)
        return w

    def _time_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        c = _card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.addWidget(_title("Gün × saat (ciro, kapanış saatine göre)"))
        self.heatmap = Heatmap()
        cl.addWidget(self.heatmap)
        ly.addWidget(c)
        ly.addWidget(_title("Haftanın günlerine göre ortalama günlük ciro"))
        self.weekday_bars = BarList()
        ly.addWidget(self.weekday_bars)
        ly.addStretch()
        return self._scroll(w)

    def _staff_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        self.staff_table = make_table([("Personel", True), ("Adisyon", False), ("Ciro", False), ("Ortalama", False),
                                       ("İskonto", False), ("İkram", False), ("İptal", False), ("Onayladığı", False),
                                       ("Bahşiş", False)], sort=(2, Qt.DescendingOrder))
        ly.addWidget(self.staff_table, 1)
        ly.addWidget(_muted("Ciro adisyonu açan garsona yazılır. İskonto/ikram/iptal yapana; \"Onayladığı\" başkasının "
                            "işlemini onaylama sayısıdır."))
        return w

    def _losses_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        f = QHBoxLayout()
        self.loss_kind = QComboBox()
        self.loss_kind.addItem("Bütün türler", None)
        for k in ("İptal", "İkram", "İskonto", "İade", "Adisyon iptali", "Kasa farkı"):
            self.loss_kind.addItem(k, k)
        self.loss_staff = QComboBox()
        for cb in (self.loss_kind, self.loss_staff):
            cb.setMinimumHeight(34)
            cb.currentIndexChanged.connect(self._fill_losses)
            f.addWidget(cb)
        self.loss_total = _muted("")
        f.addWidget(self.loss_total, 1)
        ly.addLayout(f)
        self.loss_table = make_table([("Saat", False), ("Tür", False), ("Adisyon", False), ("Yer", False),
                                      ("Ne", True), ("Tutar", False), ("Yapan", False), ("Onaylayan", False),
                                      ("Gerekçe", True)], sort=(0, Qt.DescendingOrder))
        ly.addWidget(self.loss_table, 1)
        return w

    def _income_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        c = _card()
        self.income_grid = QGridLayout(c)
        self.income_grid.setContentsMargins(20, 16, 20, 16)
        self.income_grid.setHorizontalSpacing(30)
        ly.addWidget(c)
        ly.addWidget(_muted("Ürün maliyeti, reçetelerden güncel birim maliyetlerle hesaplanır (Stok modülü)."))
        ly.addStretch()
        return w

    def _kitchen_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        self.kitchen_note = _muted("")
        ly.addWidget(self.kitchen_note)
        self.station_table = make_table([("İstasyon", True), ("Fiş", False), ("Ortalama hazırlama", False),
                                         ("Geciken", False)])
        self.station_table.setMaximumHeight(120)
        ly.addWidget(self.station_table)
        self.kitchen_product_table = make_table([("Ürün", True), ("Fiş", False), ("Ortalama hazırlama", False)])
        ly.addWidget(self.kitchen_product_table, 1)
        return w

    # ------------------------------------------------------------------ doldurma
    def refresh(self, *_):
        if getattr(self, '_loading', False):
            return
        a, b = self.period()
        self.report = reports.Report(a, b)
        self.prev = reports.Report(*reports.previous_period(a, b), include_legacy=False) \
            if self.compare.isChecked() else None
        days = (date.fromisoformat(b) - date.fromisoformat(a)).days + 1
        pa, pb = reports.previous_period(a, b)
        self.range_label.setText(f"{a} – {b} ({days} gün)" + (f" · karşılaştırma: {pa} – {pb}" if self.prev else ""))
        self.tabs.setTabVisible(self.TAB_KITCHEN, database.modules()['kds']['enabled'])
        self.tabs.setTabVisible(self.TAB_LOSSES, self.user.get('role') in PANEL_ROLES)
        self._fill_summary()
        self._fill_products()
        self._fill_menu()
        self._fill_time()
        self._fill_staff()
        self._fill_loss_staff()
        self._fill_losses()
        self._fill_income()
        self._fill_kitchen()

    def summary_rows(self):
        """(etiket, değer, değişim metni, renk) — ekran ve dışa aktarma aynı satırları kullanır."""
        s = self.report.summary()
        p = self.prev.summary() if self.prev else None

        def chg(key, inverse=False):
            if not p:
                return "", None
            return change_text(reports.change(s[key], p[key]), inverse)

        legacy = s['legacy']
        rows = [
            ("Brüt satış (KDV dahil)", tl(s['gross']), *chg('gross')),
            (f"− İskonto ({s['discountCount']} adisyon)", tl(-s['discount']), *chg('discount', True)),
            (f"− İade ({s['refundCount']})", tl(-s['refunds']), *chg('refunds', True)),
            ("= Net satış", tl(s['net']), *chg('net')),
            (f"İkram ({s['comps']['count']} ürün, satışa dahil değil)", tl(s['comps']['amount']), "", None),
            (f"İptal ({s['voids']['count']} ürün, satışa dahil değil)", tl(s['voids']['amount']), "", None),
            ("Bahşiş", tl(s['tips']), *chg('tips')),
            ("Adisyon", str(s['orders']), *chg('orders')),
            ("Ortalama adisyon", tl(s['average']), *chg('average')),
            ("Masa / paket", f"{s['dineIn']} / {s['takeaway']}", "", None),
            ("İptal edilen adisyon", str(s['cancelled']), "", None),
        ]
        if legacy['orders']:
            rows.append((f"Eski kayıt (yeni sisteme geçmeden, {legacy['orders']} adisyon)", tl(legacy['revenue']),
                         "", None))
        return rows

    def _fill_summary(self):
        g = self.sum_grid
        while g.count():
            w = g.takeAt(0).widget()
            if w:
                w.setParent(None)
        for i, (label, value, chg, color) in enumerate(self.summary_rows()):
            strong = label.startswith("= ")
            lb = QLabel(label)
            vl = QLabel(value)
            ch = QLabel(chg)
            vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            weight = "bold" if strong else "normal"
            lb.setStyleSheet(f"font-size: {15 if strong else 13}px; font-weight: {weight}; background: transparent;")
            vl.setStyleSheet(f"font-size: {15 if strong else 13}px; font-weight: {weight}; background: transparent;")
            ch.setStyleSheet(f"color: {color or COLORS['text_muted']}; font-weight: bold; background: transparent;")
            g.addWidget(lb, i, 0)
            g.addWidget(vl, i, 1)
            g.addWidget(ch, i, 2)
        s = self.report.summary()
        self.pay_bars.set_rows([(PAYMENT_LABELS[m], s['byPayment'][m]) for m in reports.METHODS])
        fill_table(self.vat_table, [[(f"%{v['rate']}", v['rate'], False), money_cell(v['gross']), money_cell(v['net']),
                                     money_cell(v['vat'])] for v in s['vat']])

    def _fill_products(self):
        rows = self.report.products()
        costed = self.report.costing()['hasRecipes']
        for c in (6, 7, 8):
            self.product_table.setColumnHidden(c, not costed)

        def opt_money(v):
            return (tl(v), v, True) if v is not None else ("—", -10 ** 12, True)

        fill_table(self.product_table, [[text_cell(r['name']), num_cell(r['qty']), money_cell(r['revenue']),
                                         (f"%{r['share']:.1f}" if r['share'] is not None else "—", r['share'] or 0, True),
                                         num_cell(r['comps']), num_cell(r['voids']),
                                         opt_money(r['cost'] if r['cost'] else None), opt_money(r['profit']),
                                         (f"%{r['margin']}" if r['margin'] is not None else "—",
                                          r['margin'] if r['margin'] is not None else -999, True)] for r in rows])
        self.cat_bars.set_rows([(c['name'], c['revenue']) for c in self.report.categories()])
        fill_table(self.option_table, [[text_cell(o['name']), num_cell(o['count']), money_cell(o['extra'])]
                                       for o in self.report.options()])
        unsold = self.report.unsold()
        self.unsold.setText(("Bu dönemde hiç satılmayan ürünler: " + ", ".join(unsold)) if unsold
                            else "Menüdeki her ürün bu dönemde en az bir kez satıldı.")

    def _fill_menu(self):
        rows = self.report.menu_analysis()
        if not self.report.costing()['hasRecipes']:
            self.menu_note.setText("Menü analizi için ürün reçeteleri gerekir: Stok modülünü açın ve reçeteleri girin "
                                   "(Stok → Malzemeler → Hazır şablon).")
        else:
            self.menu_note.setText("Adet, ürün başına ortalamanın %70'i ve üstündeyse \"çok satıyor\"; birim kâr "
                                   "(KDV hariç fiyat − reçete maliyeti) ağırlıklı ortalamanın üstündeyse \"kârlı\" sayılır. "
                                   "Maliyetler güncel birim maliyetlerle hesaplanır.")
        order = {'star': 0, 'plowhorse': 1, 'puzzle': 2, 'dog': 3}
        fill_table(self.menu_table, [[(self.MENU_CLASSES[r['class']][0], order[r['class']], False), text_cell(r['name']),
                                      num_cell(r['qty']), money_cell(r['unitProfit']), money_cell(r['profit']),
                                      (f"%{r['margin']}", r['margin'] or 0, True),
                                      text_cell(self.MENU_CLASSES[r['class']][1])] for r in rows])

    def _fill_time(self):
        self.heatmap.set_data(self.report.heatmap())
        self.weekday_bars.set_rows([(f"{d['day']} ({d['days']} gün)", d['average']) for d in self.report.weekdays()])

    def _fill_staff(self):
        fill_table(self.staff_table, [[text_cell(r['name']), num_cell(r['orders']), money_cell(r['revenue']),
                                       money_cell(r['average']), num_cell(r['discount']), num_cell(r['comps']),
                                       num_cell(r['voids']), num_cell(r['approved']), money_cell(r['tips'])]
                                      for r in self.report.staff()])

    def _fill_loss_staff(self):
        events = self.report.losses()
        current = self.loss_staff.currentData()
        self.loss_staff.blockSignals(True)
        self.loss_staff.clear()
        self.loss_staff.addItem("Bütün personel", None)
        for name in sorted({e['by'] for e in events} | {e['approvedBy'] for e in events} - {'—'}):
            self.loss_staff.addItem(name, name)
        self.loss_staff.setCurrentIndex(max(0, self.loss_staff.findData(current)))
        self.loss_staff.blockSignals(False)

    def loss_events(self):
        kind, staff = self.loss_kind.currentData(), self.loss_staff.currentData()
        return [e for e in self.report.losses()
                if (not kind or e['kind'] == kind) and (not staff or staff in (e['by'], e['approvedBy']))]

    def _fill_losses(self, *_):
        if not self.report:
            return
        events = self.loss_events()
        fill_table(self.loss_table, [[(_short_time(e['at']), e['at'] or '', False), text_cell(e['kind']),
                                      text_cell(e['order']), text_cell(e['where']), text_cell(e['what']),
                                      money_cell(e['amount']), text_cell(e['by']), text_cell(e['approvedBy']),
                                      text_cell(e['reason'])] for e in events])
        self.loss_total.setText(f"{len(events)} kayıt · toplam {tl(sum(abs(e['amount']) for e in events))}")

    def income_rows(self):
        ie = self.report.income_expense()
        rows = [("Net satış (eski kayıtlar dahil)", tl(ie['net']))]
        for kind, v in sorted(ie['expensesByType'].items()):
            rows.append((f" − Gider ({kind})", tl(-v)))
        rows.append((" − Zayi (Zayi sayfası)", tl(-ie['waste'])))
        if ie['hasRecipes']:
            rows.append((f" − Ürün maliyeti (reçeteden, ikram {tl(ie['compCost'])} dahil)", tl(-ie['cogs'])))
            rows.append((" − Hazırlanıp iptal edilen ürünler", tl(-ie['voidWaste'])))
        rows.append(("= Kalan", tl(ie['remaining'])))
        return rows

    def _fill_income(self):
        g = self.income_grid
        while g.count():
            w = g.takeAt(0).widget()
            if w:
                w.setParent(None)
        for i, (label, value) in enumerate(self.income_rows()):
            strong = label.startswith("=")
            lb, vl = QLabel(label), QLabel(value)
            vl.setAlignment(Qt.AlignRight)
            css = f"font-size: {16 if strong else 14}px; font-weight: {'bold' if strong else 'normal'}; background: transparent;"
            lb.setStyleSheet(css)
            vl.setStyleSheet(css)
            g.addWidget(lb, i, 0)
            g.addWidget(vl, i, 1)

    def _fill_kitchen(self):
        k = self.report.kitchen()
        late = database.modules()['kds']['lateMinutes']
        self.kitchen_note.setText(f"Gönderme → mutfak ekranında \"Hazır\" arası süre. Geciken: {late} dakikayı aşan fiş.")
        fill_table(self.station_table, [[text_cell('Bar' if s['station'] == 'bar' else 'Mutfak'),
                                         num_cell(s['tickets']), (duration(s['average']), s['average'], True),
                                         (f"%{s['lateRate']}", s['lateRate'], True)] for s in k['stations']])
        fill_table(self.kitchen_product_table, [[text_cell(p['name']), num_cell(p['tickets']),
                                                 (duration(p['average']), p['average'], True)] for p in k['products']])

    # ------------------------------------------------------------------ dışa aktarma
    def export_data(self, tab=None):
        """(başlık, sütunlar, satırlar) — açık sekmenin tablosu."""
        tab = self.tabs.currentIndex() if tab is None else tab
        a, b = self.period()
        names = {self.TAB_SUMMARY: "Satış özeti", self.TAB_PRODUCTS: "Ürünler", self.TAB_MENU: "Menü analizi",
                 self.TAB_TIME: "Saatler",
                 self.TAB_STAFF: "Personel", self.TAB_LOSSES: "Kayıp ve denetim", self.TAB_INCOME: "Gelir-gider",
                 self.TAB_KITCHEN: "Mutfak"}
        title = f"{names[tab]} {a} – {b}"
        if tab == self.TAB_SUMMARY:
            s = self.report.summary()
            rows = [[label, value, chg] for label, value, chg, _ in self.summary_rows()]
            rows += [[f"Ödeme: {PAYMENT_LABELS[m]}", tl(s['byPayment'][m]), ""] for m in reports.METHODS]
            rows += [[f"KDV %{v['rate']} (dahil {tl(v['gross'])}, matrah {tl(v['net'])})", tl(v['vat']), ""]
                     for v in s['vat']]
            return title, ["Kalem", "Tutar", "Önceki döneme göre"], rows
        if tab == self.TAB_TIME:
            grid = self.report.heatmap()
            hours = sorted({h for _, h in grid}, key=BUSINESS_HOURS.index)
            return title, ["Gün"] + [f"{h}:00" for h in hours], [
                [reports.WEEKDAYS[d]] + [tl(grid.get((d, h), 0)) for h in hours] for d in range(7)]
        if tab == self.TAB_INCOME:
            return title, ["Kalem", "Tutar"], [list(r) for r in self.income_rows()]
        table = {self.TAB_PRODUCTS: self.product_table, self.TAB_MENU: self.menu_table, self.TAB_STAFF: self.staff_table,
                 self.TAB_LOSSES: self.loss_table, self.TAB_KITCHEN: self.kitchen_product_table}[tab]
        cols = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
        headers = [table.horizontalHeaderItem(c).text() for c in cols]
        rows = [[table.item(r, c).text() if table.item(r, c) else '' for c in cols] for r in range(table.rowCount())]
        return title, headers, rows

    def export_csv(self, path=None):
        title, headers, rows = self.export_data()
        path = path or QFileDialog.getSaveFileName(self, "CSV kaydet", f"{title}.csv", "CSV (*.csv)")[0]
        if not path:
            return None
        write_csv(path, headers, rows)
        if not getattr(self, '_quiet', False):
            QMessageBox.information(self, "Kaydedildi", f"{path}\n\nExcel'de açılabilir.")
        return path

    def export_pdf(self, path=None):
        import printing
        title, headers, rows = self.export_data()
        path = path or QFileDialog.getSaveFileName(self, "PDF kaydet", f"{title}.pdf", "PDF (*.pdf)")[0]
        if not path:
            return None
        printing.save_pdf(table_html(database.general_settings()['cafeName'], title, headers, rows), title, 'A4', path)
        if not getattr(self, '_quiet', False):
            QMessageBox.information(self, "Kaydedildi", path)
        return path


def _short_time(iso):
    if not iso:
        return ''
    try:
        return datetime.fromisoformat(iso).astimezone().strftime('%d.%m %H:%M')
    except ValueError:
        return iso


def write_csv(path, headers, rows):
    """Türkçe Excel uyumlu: noktalı virgül ayraç, UTF-8 BOM."""
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(headers)
        w.writerows(rows)


def table_html(cafe, title, headers, rows):
    import html
    head = ''.join(f"<th align='left'>{html.escape(h)}</th>" for h in headers)
    body = ''.join('<tr>' + ''.join(f"<td>{html.escape(str(c))}</td>" for c in r) + '</tr>' for r in rows)
    return (f"<html><body style='font-family: sans-serif; font-size: 9pt'>"
            f"<h2>{html.escape(cafe)} · {html.escape(title)}</h2>"
            f"<table width='100%' cellspacing='0' cellpadding='3' border='1' style='border-collapse: collapse'>"
            f"<tr style='background:#eef2ff'>{head}</tr>{body}</table>"
            f"<p style='color:#64748b'>Oluşturma: {datetime.now():%d.%m.%Y %H:%M} · NexPOS</p></body></html>")
