"""
NexPOS - Kasa ekranı (6. ekran)

Sekmeler:
  - Kasa: açılış, para giriş/çıkışı, X raporu, kapanış (Z)
  - Bugünün adisyonları: ödenmiş adisyonlar ve iade
  - Geçmiş oturumlar: kapanmış kasaların Z raporları

Hem yönetim panelinde hem garson/kasiyer panelinde kullanılır. Kasa işlemleri `cash`,
iade `refund` yetkisi ister; yetkisi olmayana yetkili onayı penceresi açılır.
Her şey internetsiz çalışır (cash.py, pos.py).
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QTabWidget, QLineEdit, QComboBox, QCheckBox, QDialog, QFormLayout,
    QTextBrowser, QMessageBox, QAbstractItemView
)
from PySide6.QtGui import QFont, QColor

import cash
import database
import pos
import printing
from cloud.context import ctx
from money import format_tl, parse_tl
from pos_screen import authorize, _btn, _show_error
from styles import COLORS, FONTS
from widgets import PageHeader, ToastNotification


def _time(iso, fmt='%H:%M'):
    return printing._local_time(iso, fmt) or '—'


def _amount_edit(placeholder='0,00'):
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setMinimumHeight(40)
    e.setStyleSheet("font-size: 16px;")
    return e


def _parse(edit, default=None):
    text = edit.text().strip()
    return default if not text else parse_tl(text)


def print_or_pdf(parent, html, name):
    try:
        kind, where = printing.print_html(html, name)
    except Exception as e:  # yazıcı hatası işlemi engellemesin
        _show_error(parent, f"Yazdırılamadı: {e}")
        return
    ToastNotification(parent.window(), "Yazıcıya gönderildi." if kind == 'printer' else f"PDF kaydedildi: {where}",
                      "success" if kind == 'printer' else "info")


class _Card(QFrame):
    def __init__(self, title, color, parent=None):
        super().__init__(parent)
        self.setObjectName("cashCard")
        self.setStyleSheet(f"QFrame#cashCard {{ background: white; border-radius: 12px; "
                           f"border: 1px solid {COLORS['border_light']}; border-left: 4px solid {color}; }}")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(14, 10, 14, 10)
        t = QLabel(title)
        t.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; font-weight: bold; background: transparent;")
        self.value = QLabel("—")
        self.value.setFont(QFont(FONTS['family'], FONTS['size_xl'], QFont.Bold))
        self.value.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        ly.addWidget(t)
        ly.addWidget(self.value)


class CashPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)
        root.addWidget(PageHeader("Kasa", "Kasa açılışı, hareketler, Z raporu ve iade", COLORS['success'], "₺"))
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{ padding: 10px 18px; font-weight: bold; color: {COLORS['text_secondary']};
                background: transparent; border-bottom: 3px solid transparent; }}
            QTabBar::tab:selected {{ color: {COLORS['primary']}; border-bottom-color: {COLORS['primary']}; }}
        """)
        self.tabs.addTab(self._build_session_tab(), "Kasa")
        self.tabs.addTab(self._build_orders_tab(), "Bugünün Adisyonları")
        self.tabs.addTab(self._build_history_tab(), "Geçmiş Oturumlar")
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        root.addWidget(self.tabs, 1)
        self.refresh()

    # ================================================================== Kasa
    def _build_session_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        ly.setSpacing(12)
        self.status = QLabel()
        self.status.setStyleSheet("font-size: 15px; font-weight: bold; background: transparent;")
        ly.addWidget(self.status)

        # Kapalıyken: açılış
        self.open_box = QFrame()
        self.open_box.setStyleSheet(f"QFrame {{ background: white; border-radius: 12px; border: 1px solid {COLORS['border_light']}; }}"
                                    " QLabel { border: none; }")
        ob = QHBoxLayout(self.open_box)
        ob.setContentsMargins(18, 14, 18, 14)
        ob.addWidget(QLabel("Açılış nakdi:"))
        self.opening = _amount_edit("ör. 500,00")
        self.opening.setFixedWidth(180)
        ob.addWidget(self.opening)
        self.btn_open = _btn("Kasayı Aç", COLORS['success'], height=42)
        self.btn_open.clicked.connect(self._open)
        ob.addWidget(self.btn_open)
        ob.addStretch()
        ly.addWidget(self.open_box)

        # Açıkken: özet + işlemler
        self.cards = {}
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, (key, title, color) in enumerate((
                ('opening', 'Açılış', COLORS['text_muted']), ('cash', 'Nakit satış', COLORS['success']),
                ('card', 'Kredi kartı', COLORS['primary']), ('meal', 'Yemek kartı', COLORS['warning_dark']),
                ('refunds', 'İade', COLORS['danger']), ('expected', 'Beklenen nakit', COLORS['info_dark']))):
            card = _Card(title, color)
            self.cards[key] = card
            grid.addWidget(card, 0, i)
        self.summary = QWidget()
        self.summary.setLayout(grid)
        ly.addWidget(self.summary)

        actions = QHBoxLayout()
        self.btn_in = _btn("＋ Para Girişi", height=44)
        self.btn_in.clicked.connect(lambda: self._movement('in'))
        self.btn_out = _btn("－ Para Çıkışı", height=44)
        self.btn_out.clicked.connect(lambda: self._movement('out'))
        self.btn_x = _btn("📄 X Raporu", height=44)
        self.btn_x.clicked.connect(self._x_report)
        self.btn_close = _btn("🔒 Kasayı Kapat (Z)", COLORS['danger'], height=44)
        self.btn_close.clicked.connect(self._close)
        for b in (self.btn_in, self.btn_out, self.btn_x):
            actions.addWidget(b)
        actions.addStretch()
        actions.addWidget(self.btn_close)
        self.actions = QWidget()
        self.actions.setLayout(actions)
        ly.addWidget(self.actions)

        self.moves = QTableWidget(0, 5)
        self.moves.setHorizontalHeaderLabels(["Saat", "Tür", "Tutar", "Gerekçe", "Personel"])
        self._table_style(self.moves)
        self.moves.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        ly.addWidget(self.moves, 1)
        return w

    def _table_style(self, t):
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setAlternatingRowColors(True)
        t.setStyleSheet(f"QTableWidget {{ background: white; border-radius: 10px; border: 1px solid {COLORS['border_light']}; }}")

    def _refresh_session(self):
        s = cash.current_session()
        required = database.modules()['cashSession']['required']
        self.open_box.setVisible(not s)
        self.summary.setVisible(bool(s))
        self.actions.setVisible(bool(s))
        self.moves.setVisible(bool(s))
        if not s:
            note = " Nakit ödeme almak için kasa açılmalıdır." if required else ""
            self.status.setText(f"🔴 Kasa kapalı.{note}")
            self.status.setStyleSheet(f"color: {COLORS['danger']}; font-size: 15px; font-weight: bold; background: transparent;")
            return
        r = cash.build_report(s)
        self.status.setText(f"🟢 Kasa açık · {_time(s['openedAt'], '%d.%m %H:%M')} · açan: {r['openedBy']}")
        self.status.setStyleSheet(f"color: {COLORS['success_dark']}; font-size: 15px; font-weight: bold; background: transparent;")
        values = {'opening': s['openingCash'], 'cash': r['sales']['cash'], 'card': r['sales']['card'],
                  'meal': r['sales']['meal'], 'refunds': r['refunds']['total'], 'expected': r['cash']['expected']}
        for k, v in values.items():
            self.cards[k].value.setText(format_tl(v))
        self.moves.setRowCount(len(s['movements']))
        for i, m in enumerate(reversed(s['movements'])):
            cells = [_time(m['at']), 'Giriş' if m['type'] == 'in' else ('Gider' if m.get('expense') else 'Çıkış'),
                     format_tl(m['amount'] if m['type'] == 'in' else -m['amount']), m['reason'],
                     cash._staff_name(m['by'])]
            for j, c in enumerate(cells):
                item = QTableWidgetItem(c)
                if j == 2:
                    item.setForeground(QColor(COLORS['success'] if m['type'] == 'in' else COLORS['danger']))
                self.moves.setItem(i, j, item)

    def _authorize(self, text):
        approver, _ = authorize(self, self.user, 'cash', text, need_reason=False)
        return approver

    def _run(self, fn, *args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except (pos.OrderError, ValueError) as e:
            _show_error(self, e)
            return None
        ctx.request_sync()
        self.refresh()
        return result

    def _open(self):
        try:
            amount = _parse(self.opening, 0)
        except ValueError as e:
            _show_error(self, e)
            return
        approver = self._authorize(f"Kasa açılışı ({format_tl(amount)})")
        if approver and self._run(cash.open_session, self.user, amount, approver):
            self.opening.clear()
            ToastNotification(self.window(), f"Kasa {format_tl(amount)} ile açıldı.", "success")

    def _movement(self, kind):
        dlg = MovementDialog(kind, self)
        if dlg.exec() != QDialog.Accepted:
            return
        approver = self._authorize(f"Kasa {'girişi' if kind == 'in' else 'çıkışı'} ({format_tl(dlg.amount)})")
        if approver and self._run(cash.add_movement, self.user, kind, dlg.amount, dlg.reason, dlg.expense, approver):
            ToastNotification(self.window(), "Kasa hareketi kaydedildi.", "success")

    def _x_report(self):
        s = cash.current_session()
        if s:
            ReportDialog(cash.build_report(s), self).exec()

    def _close(self):
        s = cash.current_session()
        if not s:
            return
        open_orders = pos.open_orders()
        if open_orders:
            names = ", ".join(f"{o.get('tableName') or 'Paket'} ({o['no']})" for o in open_orders[:8])
            if QMessageBox.question(self, "Açık adisyon var",
                                    f"{len(open_orders)} açık adisyon var: {names}\n\n"
                                    "Bunlar sonraki kasa oturumunda tahsil edilecek. Yine de kapatılsın mı?",
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        dlg = CloseDialog(s, self)
        if dlg.exec() != QDialog.Accepted:
            return
        approver = self._authorize("Kasa kapanışı (Z raporu)")
        if not approver:
            return
        report = self._run(cash.close_session, self.user, dlg.counted, dlg.reason, approver)
        if report:
            print_or_pdf(self, printing.report_html(report), f"Z raporu {report['businessDay']}")
            ReportDialog(report, self).exec()

    # ================================================================== Adisyonlar / İade
    def _build_orders_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        hint = QLabel("Ödenmiş adisyonlar. İade için satırı seçip “İade Et”e basın (iade yetkisi ve gerekçe gerekir).")
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        ly.addWidget(hint)
        self.orders = QTableWidget(0, 7)
        self.orders.setHorizontalHeaderLabels(["No", "Masa", "Kapanış", "Tutar", "Ödeme", "İade", ""])
        self._table_style(self.orders)
        self.orders.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        ly.addWidget(self.orders, 1)
        return w

    def _refresh_orders(self):
        orders = pos.closed_orders()
        self.orders.setRowCount(len(orders))
        for i, o in enumerate(orders):
            methods = {}
            for p in o['payments']:
                methods[p['method']] = methods.get(p['method'], 0) + p['amount']
            cells = [o['no'], o.get('tableName') or 'Paket', _time(o.get('closedAt')), format_tl(o['total']),
                     " + ".join(f"{pos.PAYMENT_LABELS[m]} {format_tl(v)}" for m, v in methods.items()),
                     format_tl(-o['refunded']) if o.get('refunded') else '']
            for j, c in enumerate(cells):
                self.orders.setItem(i, j, QTableWidgetItem(c))
            b = _btn("İade Et", height=30, bold=False)
            b.setEnabled(o['paid'] - (o.get('refunded') or 0) > 0)
            b.clicked.connect(lambda _, oid=o['id']: self._refund(oid))
            self.orders.setCellWidget(i, 6, b)
            self.orders.setRowHeight(i, 38)

    def _refund(self, order_id):
        order = pos.get_order(order_id)
        dlg = RefundDialog(order, self)
        if dlg.exec() != QDialog.Accepted:
            return
        approver, reason = authorize(self, self.user, 'refund', f"{order['no']} iadesi ({format_tl(dlg.amount)})")
        if not approver:
            return
        if self._run(pos.refund, self.user, order_id, dlg.method, dlg.amount, dlg.reason or reason, approver):
            ToastNotification(self.window(), f"{order['no']}: {format_tl(dlg.amount)} iade edildi.", "success")

    # ================================================================== Geçmiş
    def _build_history_tab(self):
        w = QWidget()
        ly = QVBoxLayout(w)
        ly.setContentsMargins(0, 10, 0, 0)
        self.history = QTableWidget(0, 7)
        self.history.setHorizontalHeaderLabels(["İş günü", "Açılış", "Kapanış", "Satış", "Beklenen", "Fark", ""])
        self._table_style(self.history)
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        ly.addWidget(self.history, 1)
        return w

    def _refresh_history(self):
        sessions = cash.past_sessions()
        self.history.setRowCount(len(sessions))
        for i, s in enumerate(sessions):
            r = s.get('report') or {}
            diff = s.get('difference') or 0
            cells = [s['businessDay'], _time(s['openedAt'], '%d.%m %H:%M'), _time(s['closedAt'], '%d.%m %H:%M'),
                     format_tl((r.get('sales') or {}).get('total', 0)), format_tl(s.get('expectedCash') or 0),
                     format_tl(diff, sign=True)]
            for j, c in enumerate(cells):
                item = QTableWidgetItem(c)
                if j == 5 and diff:
                    item.setForeground(QColor(COLORS['danger'] if diff < 0 else COLORS['success']))
                self.history.setItem(i, j, item)
            b = _btn("Raporu Aç", height=30, bold=False)
            b.setEnabled(bool(r))
            b.clicked.connect(lambda _, rep=r: ReportDialog(rep, self).exec())
            self.history.setCellWidget(i, 6, b)
            self.history.setRowHeight(i, 38)

    # ==================================================================
    def refresh(self):
        i = self.tabs.currentIndex() if hasattr(self, 'tabs') else 0
        if i == 0:
            self._refresh_session()
        elif i == 1:
            self._refresh_orders()
        else:
            self._refresh_history()


# =====================================================================
# Diyaloglar
# =====================================================================

class _Dialog(QDialog):
    def __init__(self, title, parent=None, width=440):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setStyleSheet("QDialog { background: white; }")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 20, 24, 20)
        self.body.setSpacing(10)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold; background: transparent;")

    def _finish(self, label, color):
        self.body.addWidget(self.warn)
        self.ok = _btn(label, color, height=48)
        self.ok.clicked.connect(self._accept)
        self.body.addWidget(self.ok)


class MovementDialog(_Dialog):
    def __init__(self, kind, parent=None):
        super().__init__("Para Girişi" if kind == 'in' else "Para Çıkışı", parent)
        self.kind = kind
        form = QFormLayout()
        self.amount_edit = _amount_edit()
        self.reason_edit = QComboBox()
        self.reason_edit.setEditable(True)
        self.reason_edit.addItems(["Bozuk para eklendi", "Diğer"] if kind == 'in'
                                  else ["Tedarikçi ödemesi", "Market alışverişi", "Bankaya yatırıldı", "Diğer"])
        self.reason_edit.setCurrentText("")
        form.addRow("Tutar:", self.amount_edit)
        form.addRow("Gerekçe:", self.reason_edit)
        self.body.addLayout(form)
        self.expense_box = QCheckBox("Gider olarak Masraflar'a da yaz")
        self.expense_box.setChecked(kind == 'out')
        self.expense_box.setVisible(kind == 'out')
        self.body.addWidget(self.expense_box)
        self._finish("Kaydet", COLORS['primary'])

    def _accept(self):
        try:
            self.amount = _parse(self.amount_edit, 0)
            if self.amount <= 0:
                raise ValueError("Tutar girin.")
        except ValueError as e:
            self.warn.setText(str(e))
            return
        self.reason = self.reason_edit.currentText().strip()
        if not self.reason:
            self.warn.setText("Gerekçe zorunludur.")
            return
        self.expense = self.kind == 'out' and self.expense_box.isChecked()
        self.accept()


class CloseDialog(_Dialog):
    def __init__(self, session, parent=None):
        super().__init__("Kasayı Kapat (Z)", parent, 460)
        self.session = session
        self.expected = cash.expected_cash(session)
        r = cash.build_report(session)['cash']
        info = QLabel(f"Açılış {format_tl(r['opening'])} + nakit satış {format_tl(r['sales'])} − nakit iade "
                      f"{format_tl(r['refunds'])} + giriş {format_tl(r['in'])} − çıkış {format_tl(r['out'])}")
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        self.body.addWidget(info)
        form = QFormLayout()
        exp = QLabel(format_tl(self.expected))
        exp.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        self.counted_edit = _amount_edit("Kasada sayılan nakit")
        self.counted_edit.textChanged.connect(self._recalc)
        self.diff = QLabel("—")
        self.diff.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("Fark varsa gerekçe")
        form.addRow("Beklenen nakit:", exp)
        form.addRow("Sayılan nakit:", self.counted_edit)
        form.addRow("Fark:", self.diff)
        form.addRow("Gerekçe:", self.reason_edit)
        self.body.addLayout(form)
        self._finish("Z Raporunu Al ve Kasayı Kapat", COLORS['danger'])

    def _recalc(self, *_):
        self.warn.setText("")
        try:
            counted = _parse(self.counted_edit)
        except ValueError:
            self.diff.setText("—")
            return
        if counted is None:
            self.diff.setText("—")
            return
        d = counted - self.expected
        color = COLORS['success'] if d == 0 else COLORS['danger']
        self.diff.setText(format_tl(d, sign=True) + ("  ⚠ gerekçe zorunlu" if cash.needs_difference_reason(
            self.session, counted) else ""))
        self.diff.setStyleSheet(f"color: {color}; background: transparent;")

    def _accept(self):
        try:
            self.counted = _parse(self.counted_edit)
        except ValueError as e:
            self.warn.setText(str(e))
            return
        if self.counted is None:
            self.warn.setText("Sayılan nakdi girin.")
            return
        self.reason = self.reason_edit.text().strip()
        if cash.needs_difference_reason(self.session, self.counted) and not self.reason:
            self.warn.setText("Kasa farkı için gerekçe zorunludur.")
            return
        self.accept()


class RefundDialog(_Dialog):
    def __init__(self, order, parent=None):
        super().__init__(f"İade · {order['no']}", parent)
        self.order = order
        self.max = order['paid'] - (order.get('refunded') or 0)
        self.body.addWidget(QLabel(f"Ödenen {format_tl(order['paid'])} · iade edilebilir {format_tl(self.max)}"))
        form = QFormLayout()
        self.amount_edit = _amount_edit()
        self.amount_edit.setText(format_tl(self.max).replace(' ₺', ''))
        self.method_box = QComboBox()
        used = [p['method'] for p in order['payments']]
        for key, label in pos.PAYMENT_LABELS.items():
            self.method_box.addItem(label, key)
        self.method_box.setCurrentIndex(max(0, self.method_box.findData(used[-1] if used else 'cash')))
        self.reason_edit = QComboBox()
        self.reason_edit.setEditable(True)
        self.reason_edit.addItems(["Ürün beğenilmedi", "Yanlış ürün", "Fazla tahsilat", "Diğer"])
        self.reason_edit.setCurrentText("")
        form.addRow("Tutar:", self.amount_edit)
        form.addRow("Yöntem:", self.method_box)
        form.addRow("Gerekçe:", self.reason_edit)
        self.body.addLayout(form)
        self._finish("İade Et", COLORS['danger'])

    def _accept(self):
        try:
            self.amount = _parse(self.amount_edit, 0)
            if not 0 < self.amount <= self.max:
                raise ValueError(f"Tutar 0 ile {format_tl(self.max)} arasında olmalı.")
        except ValueError as e:
            self.warn.setText(str(e))
            return
        self.reason = self.reason_edit.currentText().strip()
        if not self.reason:
            self.warn.setText("Gerekçe zorunludur.")
            return
        self.method = self.method_box.currentData()
        self.accept()


class ReportDialog(QDialog):
    """X/Z raporunu gösterir; yazdır ya da PDF kaydet."""

    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("Z Raporu" if report['kind'] == 'Z' else "X Raporu")
        self.setStyleSheet("QDialog { background: white; }")
        self.resize(460, 680)
        ly = QVBoxLayout(self)
        view = QTextBrowser()
        view.setHtml(printing.report_html(report))
        view.setStyleSheet(f"border: 1px solid {COLORS['border_light']}; border-radius: 8px;")
        ly.addWidget(view, 1)
        row = QHBoxLayout()
        p = _btn("🖨 Yazdır / PDF", COLORS['primary'], height=44)
        p.clicked.connect(lambda: print_or_pdf(self, printing.report_html(report),
                                               f"{report['kind']} raporu {report['businessDay']}"))
        close = _btn("Kapat", height=44)
        close.clicked.connect(self.accept)
        row.addWidget(p)
        row.addWidget(close)
        ly.addLayout(row)
