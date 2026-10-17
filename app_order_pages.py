"""
NexPOS - Gelen siparişler penceresi (11b)

Uygulamadan gelen masa/gel-al siparişleri (Onayla / Reddet), masadan garson çağır / hesap iste (Tamam) ve
onaylanmış gel-al siparişleri (Adisyonu aç / Gelmedi). Garson ve kasa ekranının üst çubuğundaki
"📲 Gelen siparişler" düğmesinden açılır; yeni istek gelince düğme turuncu olur ve ses çıkar.
"""
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import app_orders
import database
import pos
from money import format_tl
from pos_screen import _btn, _show_error, authorize, print_new_tickets
from styles import COLORS
from widgets import ToastNotification, clear_layout


def incoming_count():
    return len(app_orders.pending()) + len(app_orders.open_calls())


class RejectDialog(QDialog):
    def __init__(self, req, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Siparişi reddet")
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(24, 20, 24, 20)
        ly.addWidget(QLabel(f"{app_orders.place(req)} · {req.get('customerName', '')}\nMüşteriye gidecek gerekçe:"))
        self.reason = QComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(app_orders.REJECT_REASONS)
        ly.addWidget(self.reason)
        row = QHBoxLayout()
        cancel = _btn("Vazgeç", height=40)
        cancel.clicked.connect(self.reject)
        ok = _btn("Reddet", COLORS['danger'], height=40)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        ly.addLayout(row)

    def text(self):
        return self.reason.currentText().strip()


class IncomingOrdersDialog(QDialog):
    """Pencere açıkken arka planda senkron sürer; refresh() yeni gelenleri gösterir."""
    open_order = Signal(str)     # adisyonu sipariş ekranında aç
    changed = Signal()           # masalar ve düğme tazelensin

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Gelen siparişler")
        self.setMinimumSize(640, 560)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_main']}; }}")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(20, 16, 20, 16)
        self.offline = QLabel("İnternet yok: uygulama siparişleri şu an müşterilere kapalı görünüyor.")
        self.offline.setStyleSheet(f"background: {COLORS['bg_warning']}; color: {COLORS['warning_dark']}; "
                                   "padding: 8px 12px; border-radius: 8px; font-weight: bold;")
        self.offline.setVisible(False)
        ly.addWidget(self.offline)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setSpacing(10)
        self.list.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(holder)
        ly.addWidget(scroll, 1)
        close = _btn("Kapat", height=40)
        close.clicked.connect(self.close)
        ly.addWidget(close)
        # Kalan onay süresi her saniye güncellenir; süresi dolan kart düşer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._countdowns = []
        self.refresh()

    # ------------------------------------------------------------- görünüm
    def refresh(self):
        from cloud.context import ctx
        self.offline.setVisible(bool(ctx.engine) and not ctx.online)
        clear_layout(self.list)
        self._countdowns = []
        can_take = database.user_can(self.user, 'openTable')
        pending = app_orders.pending()
        calls = app_orders.open_calls()
        pickups = app_orders.pickups()
        self._section(f"Onay bekleyen ({len(pending)})")
        if not pending:
            self._empty("Yeni sipariş yok.")
        for req in pending:
            self.list.addWidget(self._request_card(req, can_take))
        if calls:
            self._section(f"Masadan çağrılar ({len(calls)})")
            for c in calls:
                self.list.addWidget(self._call_card(c))
        if pickups:
            self._section(f"Gel-al ({len(pickups)})")
            for req in pickups:
                self.list.addWidget(self._pickup_card(req))
        self.list.addStretch()

    def _section(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLORS['text_dark']}; margin-top: 6px;")
        self.list.addWidget(lbl)

    def _empty(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text_muted']}; padding: 6px 2px;")
        self.list.addWidget(lbl)

    def _card(self, accent):
        card = QFrame()
        card.setObjectName("appCard")
        card.setStyleSheet(f"QFrame#appCard {{ background: white; border: 1px solid {COLORS['border_light']}; "
                           f"border-left: 4px solid {accent}; border-radius: 10px; }} QLabel {{ border: none; }}")
        ly = QVBoxLayout(card)
        ly.setContentsMargins(14, 10, 14, 10)
        ly.setSpacing(4)
        return card, ly

    def _request_card(self, req, can_take):
        icon = "🔔" if req.get('kind') == 'table' else "🛍"
        card, ly = self._card(COLORS['warning'])
        head = QHBoxLayout()
        when = f" · {app_orders.local_time(req.get('pickupAt'))}'te gelecek" if req.get('kind') == 'pickup' else ""
        title = QLabel(f"{icon} <b>{app_orders.place(req)}</b> · {req.get('customerName', '')}{when}")
        head.addWidget(title, 1)
        left = QLabel()
        left.setStyleSheet(f"color: {COLORS['warning_dark']}; font-weight: bold;")
        self._countdowns.append((left, req))
        head.addWidget(left)
        ly.addLayout(head)
        items = QLabel(app_orders.items_text(req))
        items.setWordWrap(True)
        ly.addWidget(items)
        if req.get('note'):
            ly.addWidget(QLabel(f"📝 {req['note']}"))
        row = QHBoxLayout()
        total = QLabel(f"<b>{format_tl(req.get('total', 0))}</b>")
        row.addWidget(total, 1)
        reject = _btn("Reddet", height=38)
        reject.clicked.connect(lambda _, r=req: self._reject(r))
        accept = _btn("Onayla", COLORS['success'], height=38)
        accept.clicked.connect(lambda _, r=req: self._accept(r))
        for b in (reject, accept):
            b.setEnabled(can_take)
            b.setMinimumWidth(110)
            row.addWidget(b)
        ly.addLayout(row)
        self._tick()
        return card

    def _call_card(self, call):
        card, ly = self._card(COLORS['info'])
        row = QHBoxLayout()
        name = call.get('tableName') or ''
        place = f"Masa {name}" if name.isdigit() or not name else name
        icon = app_orders.CALL_ICONS.get(call.get('kind'), '🔔')
        row.addWidget(QLabel(f"{icon} <b>{place}</b> · {app_orders.CALL_LABELS.get(call.get('kind'), '')} · "
                             f"{app_orders.local_time(call.get('at'))}"), 1)
        ok = _btn("Tamam", COLORS['primary'], height=36)
        ok.setMinimumWidth(110)
        ok.clicked.connect(lambda _, c=call: self._ack(c))
        row.addWidget(ok)
        ly.addLayout(row)
        return card

    def _pickup_card(self, req):
        ready = req.get('status') == 'ready'
        card, ly = self._card(COLORS['success'] if ready else COLORS['primary'])
        row = QHBoxLayout()
        row.addWidget(QLabel(f"🛍 <b>{req.get('orderNo') or ''}</b> · {req.get('customerName', '')} · "
                             f"{app_orders.local_time(req.get('pickupAt'))} · "
                             f"{app_orders.STATUS_LABELS.get(req.get('status'), '')}"), 1)
        open_btn = _btn("Adisyonu aç", height=36)
        open_btn.setEnabled(bool(pos.get_order(req.get('orderId') or '')))
        open_btn.clicked.connect(lambda _, r=req: (self.open_order.emit(r['orderId']), self.close()))
        no_show = _btn("Gelmedi", height=36)
        no_show.clicked.connect(lambda _, r=req: self._no_show(r))
        row.addWidget(open_btn)
        row.addWidget(no_show)
        ly.addLayout(row)
        items = QLabel(app_orders.items_text(req))
        items.setWordWrap(True)
        items.setStyleSheet(f"color: {COLORS['text_secondary']};")
        ly.addWidget(items)
        return card

    def _tick(self):
        expired = False
        for label, req in self._countdowns:
            left = app_orders.seconds_left(req)
            expired = expired or left == 0
            label.setText(f"⏱ {left // 60}:{left % 60:02d}")
        if expired:
            self.refresh()
            self.changed.emit()

    # -------------------------------------------------------------- işlemler
    def _accept(self, req):
        try:
            order = app_orders.accept(self.user, req)
        except pos.OrderError as e:
            _show_error(self, e)
            self.refresh()
            self.changed.emit()
            return
        print_new_tickets(self, order['id'])
        from cloud.context import ctx
        ctx.request_sync()
        ToastNotification(self.parent() or self, f"{app_orders.place(req)}: sipariş onaylandı, fişler gönderildi.",
                          "success")
        self.refresh()
        self.changed.emit()

    def _reject(self, req):
        dlg = RejectDialog(req, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            app_orders.reject(self.user, req, dlg.text())
        except pos.OrderError as e:
            _show_error(self, e)
        self.refresh()
        self.changed.emit()

    def _ack(self, call):
        app_orders.ack_call(self.user, call)
        from cloud.context import ctx
        ctx.request_sync()
        self.refresh()
        self.changed.emit()

    def _no_show(self, req):
        if QMessageBox.question(self, "Gelmedi", f"{req.get('customerName', '')} gel-al siparişine gelmedi mi?\n"
                                "Adisyon iptal edilir. Üst üste 2 kez gelmeyen müşteriye gel-al kapanır.",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        order = pos.get_order(req.get('orderId') or '')
        approver = self.user['cloud_id']
        if order and order['status'] == 'open' and pos.needs_approval_to_cancel(order):
            approver, _ = authorize(self, self.user, 'voidItem', "Gel-al: gelinmedi (adisyon iptali)", need_reason=False)
            if not approver:
                return
        try:
            result = app_orders.no_show(self.user, req)
            if order and order['status'] == 'open':
                pos.cancel_order(self.user, order['id'], "Gel-al: müşteri gelmedi", approver, prepared=True)
        except pos.OrderError as e:
            _show_error(self, e)
            return
        if result.get('pickupBlocked'):
            QMessageBox.information(self, "Gel-al kapandı", "Bu müşteri üst üste 2 kez gelmedi; gel-al ona kapatıldı. "
                                    "Pazarlama → Müşteriler'den yeniden açılabilir.")
        from cloud.context import ctx
        ctx.request_sync()
        self.refresh()
        self.changed.emit()
