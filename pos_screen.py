"""
NexPOS - Sipariş ekranı (4. ekran)

- POSScreen: tam ekran adisyon (kategoriler → ürün kartları → adisyon paneli)
- OptionPickerDialog, LineDialog, DiscountDialog, PaymentDialog, TablePickerDialog
- TicketBoard: mutfak/bar fişleri panosu (Yeni → Hazırlanıyor → Hazır)

Bütün işlemler pos.py üzerinden yapılır; internet yokken de çalışır.
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QFrame, QScrollArea, QListWidget,
    QListWidgetItem, QLineEdit, QDialog, QFormLayout, QCheckBox, QRadioButton, QButtonGroup, QSpinBox,
    QMessageBox, QComboBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QColor
from styles import COLORS, FONTS, ICONS
from widgets import ToastNotification, add_shadow, clear_layout
from access import request_approval, DEFAULT_REASONS
from cloud.context import ctx
from money import format_tl, parse_tl
import database
import pos

STATE_BADGE = {
    ('pending', 'active'): ("⏳ bekliyor", COLORS['warning_dark']),
    ('sent', 'active'): ("✓ gönderildi", COLORS['success_dark']),
}
STATUS_BADGE = {'void': ("İPTAL", COLORS['danger']), 'comp': ("İKRAM", COLORS['info_dark'])}


def _btn(text, color=None, height=48, bold=True):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(height)
    bg = color or 'white'
    fg = 'white' if color else COLORS['text_dark']
    border = 'none' if color else f"1px solid {COLORS['border']}"
    b.setStyleSheet(f"""
        QPushButton {{ background: {bg}; color: {fg}; border: {border}; border-radius: 10px;
            font-size: 13px; font-weight: {'bold' if bold else 'normal'}; padding: 0 10px; }}
        QPushButton:hover {{ border: 2px solid {COLORS['primary']}; }}
        QPushButton:disabled {{ background: {COLORS['bg_input']}; color: {COLORS['text_muted']}; border: none; }}
    """)
    return b


def _show_error(parent, e):
    QMessageBox.warning(parent, "İşlem yapılamadı", str(e))


def _ask_reason(parent, title, permission, required=True):
    """Yetkisi olan kullanıcı için gerekçe sorar (yetkisi olmayan için onay penceresi zaten sorar)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setStyleSheet("QDialog { background: white; }")
    ly = QVBoxLayout(dlg)
    ly.setContentsMargins(24, 20, 24, 20)
    ly.addWidget(QLabel("Gerekçe:"))
    box = QComboBox()
    box.setEditable(True)
    box.addItems(DEFAULT_REASONS.get(permission, ["Diğer"]))
    ly.addWidget(box)
    ok = QPushButton("Tamam")
    ok.setObjectName("primaryBtn")
    ok.clicked.connect(dlg.accept)
    ly.addWidget(ok)
    if dlg.exec() != QDialog.Accepted:
        return None
    text = box.currentText().strip()
    return text if text or not required else None


def authorize(parent, user, permission, action_text, need_reason=True):
    """(onaylayan_id, gerekçe) ya da vazgeçildiyse (None, None)."""
    approver, reason = request_approval(parent, user, permission, action_text)
    if not approver:
        return None, None
    if need_reason and not reason:
        reason = _ask_reason(parent, action_text, permission)
        if not reason:
            return None, None
    approver_id = approver.get('cloud_id') or approver.get('id')
    return approver_id, reason or ''


# =====================================================================
# Sipariş ekranı
# =====================================================================

class ProductTile(QPushButton):
    def __init__(self, product, color, parent=None):
        super().__init__(parent)
        self.product = product
        sold = bool(product.get('soldOut'))
        self.setEnabled(not sold)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(150, 92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        has_opts = "  ⚙" if product.get('optionGroupIds') else ""
        price = "TÜKENDİ" if sold else format_tl(product['price'])
        self.setText(f"{product['name']}{has_opts}\n{price}")
        self.setStyleSheet(f"""
            QPushButton {{ background: white; border: 1.5px solid {COLORS['border_light']}; border-top: 4px solid {color};
                border-radius: 12px; font-size: 14px; font-weight: bold; color: {COLORS['text_dark']}; padding: 8px; }}
            QPushButton:hover {{ border: 2px solid {COLORS['primary']}; border-top: 4px solid {color}; background: {COLORS['primary_bg']}; }}
            QPushButton:pressed {{ background: {COLORS['primary']}; color: white; }}
            QPushButton:disabled {{ background: {COLORS['bg_input']}; color: {COLORS['text_muted']}; }}
        """)


class LineRow(QFrame):
    clicked = Signal(dict)

    def __init__(self, line, parent=None):
        super().__init__(parent)
        self.line = line
        self.setCursor(Qt.PointingHandCursor)
        dead = line['status'] != 'active'
        self.setObjectName("lineRow")
        self.setStyleSheet(f"QFrame#lineRow {{ background: {'#FAFAFA' if dead else 'white'}; border-bottom: 1px solid {COLORS['border_light']}; }}"
                           f"QFrame#lineRow:hover {{ background: {COLORS['primary_bg']}; }}")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(10, 8, 10, 8)
        ly.setSpacing(2)
        top = QHBoxLayout()
        name = QLabel(f"{line['qty']}× {line['name']}")
        name.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        strike = "text-decoration: line-through;" if line['status'] == 'void' else ""
        name.setStyleSheet(f"color: {COLORS['text_muted'] if dead else COLORS['text_dark']}; {strike} background: transparent;")
        top.addWidget(name, 1)
        price = QLabel(format_tl(pos.line_total(line)) if not dead else STATUS_BADGE[line['status']][0])
        price.setStyleSheet(f"color: {STATUS_BADGE[line['status']][1] if dead else COLORS['text_dark']}; "
                            f"font-weight: bold; background: transparent;")
        top.addWidget(price)
        ly.addLayout(top)
        details = []
        if line['options']:
            details.append(", ".join(o['name'] + (f" {format_tl(o['priceDelta'], sign=True)}" if o['priceDelta'] else "")
                                     for o in line['options']))
        if line.get('note'):
            details.append(f"“{line['note']}”")
        if line['status'] != 'active' and line.get('reason'):
            details.append(f"Gerekçe: {line['reason']}")
        for d in details:
            lbl = QLabel(d)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent;")
            ly.addWidget(lbl)
        if not dead:
            text, color = STATE_BADGE[(line['state'], line['status'])]
            if line.get('paidBy'):
                text, color = "💳 ödendi", COLORS['info_dark']
            badge = QLabel(text)
            badge.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; background: transparent;")
            ly.addWidget(badge)
        for w in self.findChildren(QLabel):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mouseReleaseEvent(self, e):
        self.clicked.emit(self.line)


class POSScreen(QWidget):
    back_requested = Signal()
    GRID_COLUMNS = 4

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.table = None      # {'id', 'name'} ya da masasız siparişte None
        self.order = None
        self.category = '__top__'
        self.split_people = {}  # adisyon → eşit bölmede kalan kişi sayısı

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # Üst bilgi
        head = QHBoxLayout()
        back = _btn("← Masalar", height=40)
        back.setFixedWidth(130)
        back.clicked.connect(self._back)
        head.addWidget(back)
        self.title = QLabel()
        self.title.setFont(QFont(FONTS['family'], FONTS['size_xl'], QFont.Bold))
        self.title.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        head.addWidget(self.title, 1)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # Kategoriler
        left = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"{ICONS['search']} Ürün ara…")
        self.search.setFixedHeight(42)
        self.search.textChanged.connect(self._render_products)
        left.addWidget(self.search)
        self.cat_list = QListWidget()
        self.cat_list.setFixedWidth(200)
        self.cat_list.setStyleSheet(f"""
            QListWidget {{ border: none; background: white; border-radius: 12px; font-size: 14px; padding: 4px; }}
            QListWidget::item {{ padding: 12px 8px; border-radius: 8px; }}
            QListWidget::item:selected {{ background: {COLORS['primary']}; color: white; font-weight: bold; }}
        """)
        self.cat_list.currentRowChanged.connect(self._on_category)
        left.addWidget(self.cat_list, 1)
        body.addLayout(left)

        # Ürün kartları
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(holder)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignTop)
        scroll.setWidget(holder)
        body.addWidget(scroll, 1)

        # Adisyon paneli
        panel = QFrame()
        panel.setObjectName("ticketPanel")
        panel.setFixedWidth(400)
        panel.setStyleSheet(f"QFrame#ticketPanel {{ background: white; border-radius: 14px; border: 1px solid {COLORS['border_light']}; }}")
        add_shadow(panel, blur=14, offset_y=3, color=QColor(0, 0, 0, 18))
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(8)
        pt = QLabel("ADİSYON")
        pt.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 11px; background: transparent;")
        pl.addWidget(pt)
        self.lines_holder = QWidget()
        self.lines_layout = QVBoxLayout(self.lines_holder)
        self.lines_layout.setContentsMargins(0, 0, 0, 0)
        self.lines_layout.setSpacing(0)
        self.lines_layout.setAlignment(Qt.AlignTop)
        lscroll = QScrollArea()
        lscroll.setWidgetResizable(True)
        lscroll.setStyleSheet("QScrollArea { border: none; background: white; }")
        self.lines_holder.setStyleSheet("background: white;")
        lscroll.setWidget(self.lines_holder)
        pl.addWidget(lscroll, 1)

        totals = QFormLayout()
        totals.setSpacing(2)
        self.lbl_sub = QLabel()
        self.lbl_disc = QLabel()
        self.lbl_paid = QLabel()
        self.lbl_total = QLabel()
        self.lbl_total.setFont(QFont(FONTS['family'], FONTS['size_xl'], QFont.Bold))
        self.lbl_total.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
        for w in (self.lbl_sub, self.lbl_disc, self.lbl_paid, self.lbl_total):
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.row_disc_label = QLabel("İskonto")
        self.row_paid_label = QLabel("Ödenen")
        for w in (self.lbl_sub, self.lbl_disc, self.lbl_paid, self.row_disc_label, self.row_paid_label):
            w.setStyleSheet(f"background: transparent; color: {COLORS['text_secondary']};")
        sub_label = QLabel("Ara toplam")
        sub_label.setStyleSheet(f"background: transparent; color: {COLORS['text_secondary']};")
        totals.addRow(sub_label, self.lbl_sub)
        totals.addRow(self.row_disc_label, self.lbl_disc)
        totals.addRow(self.row_paid_label, self.lbl_paid)
        tl = QLabel("TOPLAM")
        tl.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        tl.setStyleSheet("background: transparent;")
        totals.addRow(tl, self.lbl_total)
        pl.addLayout(totals)

        actions = QGridLayout()
        actions.setSpacing(6)
        self.btn_send = _btn("📨 Gönder", COLORS['primary'], height=52)
        self.btn_send.clicked.connect(self._send)
        self.btn_pay = _btn("💳 Öde", COLORS['success'], height=52)
        self.btn_pay.clicked.connect(self._pay)
        self.btn_discount = _btn("% İskonto", height=42)
        self.btn_discount.clicked.connect(self._discount)
        self.btn_bill = _btn("🧾 Hesap İste", height=42)
        self.btn_bill.clicked.connect(self._toggle_bill)
        self.btn_move = _btn("⇄ Taşı", height=42)
        self.btn_move.clicked.connect(self._move)
        self.btn_merge = _btn("⧉ Birleştir", height=42)
        self.btn_merge.clicked.connect(self._merge)
        self.btn_cancel = _btn("✖ İptal", height=42)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_print = _btn("🖨 Yazdır", height=42)
        self.btn_print.setToolTip("Adisyonu (bilgi fişi) yazdır")
        self.btn_print.clicked.connect(self._print_bill)
        actions.addWidget(self.btn_send, 0, 0, 1, 2)
        actions.addWidget(self.btn_pay, 0, 2)
        actions.addWidget(self.btn_discount, 1, 0)
        actions.addWidget(self.btn_bill, 1, 1)
        actions.addWidget(self.btn_move, 1, 2)
        actions.addWidget(self.btn_merge, 2, 0)
        actions.addWidget(self.btn_print, 2, 1)
        actions.addWidget(self.btn_cancel, 2, 2)
        pl.addLayout(actions)
        body.addWidget(panel)

    # ------------------------------------------------------------------ açma
    def open_table(self, table):
        """table: {'id': masa bulut kimliği, 'name': ad}"""
        self.table = table
        self.order = pos.open_order_for_table(table['id'])
        self._reload_menu()
        self._refresh()

    def open_existing(self, order_id):
        self.order = pos.get_order(order_id)
        self.table = {'id': self.order['tableId'], 'name': self.order['tableName']} if self.order.get('tableId') else None
        self._reload_menu()
        self._refresh()

    def new_takeaway(self):
        try:
            self.order = pos.open_order(self.user, None)
        except pos.OrderError as e:
            _show_error(self, e)
            return False
        self.table = None
        ctx.request_sync()
        self._reload_menu()
        self._refresh()
        return True

    def _ensure_order(self):
        if self.order is None:
            self.order = pos.open_order(self.user, self.table)
        return self.order

    # ------------------------------------------------------------------ menü
    def _reload_menu(self):
        self.categories = [c for c in database.menu_categories()]
        self.cat_list.blockSignals(True)
        self.cat_list.clear()
        top = QListWidgetItem("★  Sık satanlar")
        top.setData(Qt.UserRole, '__top__')
        self.cat_list.addItem(top)
        for c in self.categories:
            it = QListWidgetItem(c['name'])
            it.setData(Qt.UserRole, c['id'])
            self.cat_list.addItem(it)
        row = next((i for i in range(self.cat_list.count()) if self.cat_list.item(i).data(Qt.UserRole) == self.category), 0)
        if row == 0 and not pos.top_products_today() and self.categories:
            row = 1
        self.cat_list.setCurrentRow(row)
        self.cat_list.blockSignals(False)
        self.category = self.cat_list.currentItem().data(Qt.UserRole) if self.cat_list.currentItem() else None
        self._render_products()

    def _on_category(self, row):
        item = self.cat_list.item(row)
        self.category = item.data(Qt.UserRole) if item else None
        self._render_products()

    def _render_products(self):
        clear_layout(self.grid)
        products = [p for p in database.menu_products() if p.get('active', True)]
        text = database.turkish_lower(self.search.text().strip())
        if text:
            products = [p for p in products if text in database.turkish_lower(p['name'])]
        elif self.category == '__top__':
            order = {pid: i for i, pid in enumerate(pos.top_products_today())}
            products = sorted([p for p in products if p['id'] in order], key=lambda p: order[p['id']])
        elif self.category:
            products = [p for p in products if p.get('categoryId') == self.category]
        colors = {c['id']: c.get('color', COLORS['primary']) for c in self.categories}
        for i, p in enumerate(products):
            tile = ProductTile(p, colors.get(p.get('categoryId'), COLORS['primary']))
            tile.clicked.connect(lambda _, prod=p: self._add_product(prod))
            self.grid.addWidget(tile, i // self.GRID_COLUMNS, i % self.GRID_COLUMNS)
        if not products:
            empty = QLabel("Bugün henüz satış yok; soldan bir kategori seçin." if self.category == '__top__'
                           else "Ürün bulunamadı.")
            empty.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 30px; background: transparent;")
            self.grid.addWidget(empty, 0, 0, 1, self.GRID_COLUMNS)

    # ------------------------------------------------------------------ adisyon
    def _refresh(self):
        o = self.order
        where = f"{self.table['name']}" if self.table else "Masasız sipariş"
        if o:
            self.title.setText(f"{where}  ·  {o['no']}" + ("  ·  🧾 hesap istendi" if o.get('billRequested') else ""))
        else:
            self.title.setText(f"{where}  ·  yeni adisyon")
        clear_layout(self.lines_layout)
        items = o['items'] if o else []
        for line in items:
            row = LineRow(line)
            row.clicked.connect(self._line_clicked)
            self.lines_layout.addWidget(row)
        if not items:
            hint = QLabel("Ürün eklemek için soldaki kartlara dokunun.")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {COLORS['text_muted']}; padding: 20px; background: transparent;")
            self.lines_layout.addWidget(hint)
        t = o or {'subtotal': 0, 'discountAmount': 0, 'total': 0, 'paid': 0}
        self.lbl_sub.setText(format_tl(t['subtotal']))
        disc = (o or {}).get('discount')
        self.row_disc_label.setText(f"İskonto %{disc['value']}" if disc and disc['type'] == 'percent' else "İskonto")
        self.lbl_disc.setText(format_tl(-t['discountAmount']) if t['discountAmount'] else "—")
        self.lbl_paid.setText(format_tl(t['paid']) if t['paid'] else "—")
        self.lbl_total.setText(format_tl(t['total'] - t['paid']))

        pending = sum(1 for l in items if l['state'] == 'pending' and l['status'] == 'active')
        has_items = any(l['status'] == 'active' for l in items)
        self.btn_send.setText(f"📨 Gönder ({pending})" if pending else "📨 Gönder")
        self.btn_send.setEnabled(pending > 0)
        self.btn_discount.setEnabled(bool(o) and has_items)
        self.btn_bill.setEnabled(bool(o) and bool(self.table))
        self.btn_bill.setText("🧾 Hesap İsteğini Kaldır" if o and o.get('billRequested') else "🧾 Hesap İste")
        self.btn_move.setEnabled(bool(o) and bool(self.table))
        self.btn_merge.setEnabled(bool(o) and bool(self.table))
        self.btn_cancel.setEnabled(bool(o) and not (o or {}).get('payments'))
        self.btn_print.setVisible(database.modules()['printing']['enabled'])
        self.btn_print.setEnabled(bool(o) and has_items)
        self.btn_pay.setEnabled(bool(o) and bool(items) and pending == 0)
        self.btn_pay.setToolTip("Önce bekleyen ürünleri gönderin." if pending else "")

    def _do(self, fn, *args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except pos.OrderError as e:
            _show_error(self, e)
            return None
        ctx.request_sync()
        return result

    def _add_product(self, product):
        groups = [database.menu_item('optionGroups', g) for g in product.get('optionGroupIds', [])]
        groups = [g for g in groups if g and not g.get('deleted')]
        if groups:
            dlg = OptionPickerDialog(product, groups, self)
            if dlg.exec() != QDialog.Accepted:
                return
            line = pos.product_line(product, dlg.selected, dlg.qty.value(), dlg.note.text().strip())
        else:
            line = pos.product_line(product)
        try:
            order = self._ensure_order()
        except pos.OrderError as e:
            _show_error(self, e)
            return
        result = self._do(pos.add_line, self.user, order['id'], line)
        if result:
            self.order = result
            self._refresh()

    def _line_clicked(self, line):
        if not self.order or line['status'] != 'active' or line.get('paidBy'):
            return
        dlg = LineDialog(line, self)
        if dlg.exec() != QDialog.Accepted:
            return
        oid = self.order['id']
        result = None
        if dlg.action == 'update':
            result = self._do(pos.update_line, self.user, oid, line['lineId'], qty=dlg.qty.value(), note=dlg.note.text().strip())
        elif dlg.action == 'remove':
            result = self._do(pos.remove_line, self.user, oid, line['lineId'])
        elif dlg.action == 'comp':
            approver, reason = authorize(self, self.user, 'comp', f"{line['name']} ikram")
            if approver:
                result = self._do(pos.comp_line, self.user, oid, line['lineId'], reason, approver)
        elif dlg.action == 'void':
            approver, reason = authorize(self, self.user, 'voidItem', f"{line['name']} iptali")
            if approver:
                result = self._do(pos.void_line, self.user, oid, line['lineId'], reason, approver)
        if result:
            self.order = result
            self._refresh()

    def _send(self):
        if not self.order:
            return
        result = self._do(pos.send_pending, self.user, self.order['id'])
        if result:
            self.order, n = result
            self._refresh()
            ToastNotification(self.window(), f"{n} ürün bar/mutfağa gönderildi.", "success")
            printing_cfg = database.modules()['printing']
            if printing_cfg['enabled'] and printing_cfg['kitchenTickets']:
                import printing
                for t in pos.tickets(('new',)):
                    if t['orderId'] == self.order['id'] and not t.get('printed'):
                        try:
                            printing.print_html(printing.ticket_html(t), f"Fiş {t['orderNo']} {t['station']}")
                            pos.mark_ticket_printed(t['id'])
                        except Exception as e:
                            _show_error(self, f"Fiş yazdırılamadı: {e}")
                            break

    def _discount(self):
        dlg = DiscountDialog(self.order, self)
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.discount is None:
            result = self._do(pos.set_discount, self.user, self.order['id'], None)
        else:
            label = (f"%{dlg.discount['value']}" if dlg.discount['type'] == 'percent'
                     else format_tl(dlg.discount['value']))
            approver, reason = authorize(self, self.user, 'discount', f"{self.title.text()} · {label} iskonto",
                                         need_reason=False)
            if not approver:
                return
            result = self._do(pos.set_discount, self.user, self.order['id'], dlg.discount, reason or dlg.reason, approver)
        if result:
            self.order = result
            self._refresh()

    def _toggle_bill(self):
        result = self._do(pos.request_bill, self.user, self.order['id'], not self.order.get('billRequested'))
        if result:
            self.order = result
            self._refresh()
            if result.get('billRequested') and database.modules()['printing']['enabled']:
                self._print_bill()

    def _move(self):
        dlg = TablePickerDialog("Adisyonu taşı: boş masa seçin", mode='empty', exclude=self.table['id'], parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.choice:
            result = self._do(pos.move_order, self.user, self.order['id'], dlg.choice)
            if result:
                self.order, self.table = result, dlg.choice
                self._refresh()
                ToastNotification(self.window(), f"Adisyon {dlg.choice['name']} masasına taşındı.", "success")

    def _merge(self):
        dlg = TablePickerDialog("Birleştir: bu adisyona eklenecek masayı seçin", mode='open', exclude=self.table['id'],
                                parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.choice:
            result = self._do(pos.merge_into, self.user, self.order['id'], dlg.choice['orderId'])
            if result:
                self.order = result
                self._refresh()
                ToastNotification(self.window(), f"{dlg.choice['name']} bu adisyonla birleştirildi.", "success")

    def _cancel(self):
        if pos.needs_approval_to_cancel(self.order):
            approver, reason = authorize(self, self.user, 'voidItem', f"{self.title.text()} adisyon iptali")
        else:
            if QMessageBox.question(self, "Adisyonu İptal", "Adisyon iptal edilsin ve masa boşaltılsın mı?",
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            approver, reason = self.user['cloud_id'], "Gönderilmemiş adisyon"
        if approver:
            if self._do(pos.cancel_order, self.user, self.order['id'], reason, approver):
                self.order = None
                self.back_requested.emit()

    def _pay(self):
        oid = self.order['id']
        dlg = PaymentDialog(self.order, self, people_left=self.split_people.get(oid))
        if dlg.exec() != QDialog.Accepted:
            return
        line_ids = None
        if dlg.line_picks:
            # Kısmi adet seçilen satırlar önce bölünür; tutar gerçek adisyon üzerinden doğrulanır
            line_ids = []
            for line_id, qty in dlg.line_picks.items():
                line = next(l for l in self.order['items'] if l['lineId'] == line_id)
                if qty < line['qty']:
                    result = self._do(pos.split_line, self.user, oid, line_id, qty)
                    if not result:
                        return
                    self.order, new_id = result
                    line_ids.append(new_id)
                else:
                    line_ids.append(line_id)
            dlg.amount = pos.lines_payable(self.order, line_ids)
            if dlg.method == 'cash':
                dlg.received = max(dlg.received or 0, dlg.amount)
        result = self._do(pos.take_payment, self.user, oid, dlg.method, dlg.amount, tip=dlg.tip,
                          received=dlg.received, line_ids=line_ids)
        if not result:
            self._refresh()
            return
        self.order = result
        if dlg.people_left:
            self.split_people[oid] = dlg.people_left
        else:
            self.split_people.pop(oid, None)
        last = result['payments'][-1]
        if result['status'] == 'paid':
            msg = f"{result['no']} tahsil edildi." + (f" Para üstü: {format_tl(last['change'])}" if last['change'] else "")
            ToastNotification(self.window(), msg, "success")
            self.order = None
            self.back_requested.emit()
        else:
            change = f" · para üstü {format_tl(last['change'])}" if last['change'] else ""
            ToastNotification(self.window(), f"{format_tl(last['amount'])} alındı{change}. "
                              f"Kalan: {format_tl(result['remaining'])}", "info")
            self._refresh()

    def _print_bill(self):
        if not self.order:
            return
        import printing
        try:
            kind, where = printing.print_html(printing.bill_html(self.order), f"Adisyon {self.order['no']}")
        except Exception as e:  # yazıcı hatası siparişi engellemesin
            _show_error(self, f"Adisyon yazdırılamadı: {e}")
            return
        ToastNotification(self.window(), "Adisyon yazıcıya gönderildi." if kind == 'printer'
                          else f"Yazıcı yok; PDF kaydedildi: {where}", "success" if kind == 'printer' else "info")

    def _back(self):
        o = self.order
        if o:
            pending = sum(1 for l in o['items'] if l['state'] == 'pending' and l['status'] == 'active')
            if pending:
                box = QMessageBox(self)
                box.setWindowTitle("Gönderilmemiş ürün")
                box.setText(f"Bu adisyonda gönderilmemiş {pending} ürün var.")
                send = box.addButton("Gönder ve çık", QMessageBox.AcceptRole)
                leave = box.addButton("Gönderme, çık", QMessageBox.DestructiveRole)
                box.addButton("Vazgeç", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() == send:
                    self._send()
                elif box.clickedButton() != leave:
                    return
            elif not o['items']:
                # Hiç ürün eklenmeden açılan adisyon masayı boşuna dolu göstermesin
                self._do(pos.cancel_order, self.user, o['id'], "Boş adisyon", self.user['cloud_id'])
        self.order = None
        self.back_requested.emit()


# =====================================================================
# Diyaloglar
# =====================================================================

class _Dialog(QDialog):
    def __init__(self, title, parent=None, width=460):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setStyleSheet("QDialog { background: white; }")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 20, 24, 20)
        self.body.setSpacing(10)


class OptionPickerDialog(_Dialog):
    def __init__(self, product, groups, parent=None):
        super().__init__(product['name'], parent, 480)
        self.product = product
        self.groups = groups
        self.selected = []
        self.controls = []
        head = QLabel(f"<b style='font-size:16px'>{product['name']}</b>  ·  {format_tl(product['price'])}")
        self.body.addWidget(head)
        for g in groups:
            title = QLabel(f"<b>{g['name']}</b>" + ("  <span style='color:#EF4444'>(zorunlu)</span>" if g.get('required') else "")
                           + (f"  <span style='color:#64748B'>· en çok {g.get('max')}</span>" if g.get('selection') == 'multi' else ""))
            self.body.addWidget(title)
            row = QGridLayout()
            buttons = []
            group = QButtonGroup(self) if g.get('selection', 'single') == 'single' else None
            if group:
                group.setExclusive(True)
            for i, o in enumerate(o for o in g.get('options', []) if o.get('active', True)):
                text = o['name'] + (f"  {format_tl(o['priceDelta'], sign=True)}" if o.get('priceDelta') else "")
                if o.get('soldOut'):
                    text += "  (tükendi)"
                b = QPushButton(text)
                b.setCheckable(True)
                b.setEnabled(not o.get('soldOut'))
                b.setMinimumHeight(44)
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet(f"""
                    QPushButton {{ background: white; border: 1.5px solid {COLORS['border']}; border-radius: 10px; font-size: 13px; }}
                    QPushButton:checked {{ background: {COLORS['primary']}; color: white; border-color: {COLORS['primary']}; font-weight: bold; }}
                    QPushButton:disabled {{ color: {COLORS['text_muted']}; background: {COLORS['bg_input']}; }}
                """)
                b.toggled.connect(self._update)
                if group:
                    group.addButton(b)
                buttons.append((b, o))
                row.addWidget(b, i // 3, i % 3)
            # Tek seçimli zorunlu grupta ilk uygun seçenek varsayılan gelir
            if group and g.get('required'):
                first = next((b for b, o in buttons if b.isEnabled()), None)
                if first:
                    first.setChecked(True)
            self.body.addLayout(row)
            self.controls.append((g, buttons))
        form = QFormLayout()
        self.qty = QSpinBox()
        self.qty.setRange(1, 99)
        self.qty.setFixedWidth(100)
        self.qty.valueChanged.connect(self._update)
        self.note = QLineEdit()
        self.note.setMaxLength(120)
        self.note.setPlaceholderText("az şekerli, alerji var…")
        form.addRow("Adet:", self.qty)
        form.addRow("Not:", self.note)
        self.body.addLayout(form)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold; background: transparent;")
        self.body.addWidget(self.warn)
        self.ok = _btn("Ekle", COLORS['primary'])
        self.ok.clicked.connect(self._accept)
        self.body.addWidget(self.ok)
        self._update()

    def _collect(self):
        chosen, problems = [], []
        for g, buttons in self.controls:
            picked = [o for b, o in buttons if b.isChecked()]
            lo = g.get('min', 1 if g.get('required') else 0)
            hi = g.get('max', 1)
            if len(picked) < lo:
                problems.append(f"{g['name']}: en az {lo} seçim")
            if len(picked) > hi:
                problems.append(f"{g['name']}: en çok {hi} seçim")
            chosen += [(g['id'], o) for o in picked]
        return chosen, problems

    def _update(self, *_):
        if not hasattr(self, 'ok'):
            return  # pencere kurulurken varsayılan seçim; kurulum bitince bir kez hesaplanır
        chosen, problems = self._collect()
        unit = self.product['price'] + sum(o.get('priceDelta', 0) for _, o in chosen)
        self.ok.setText(f"Ekle  ·  {format_tl(unit * self.qty.value())}")
        self.ok.setEnabled(not problems)
        self.warn.setText(" · ".join(problems))

    def _accept(self):
        chosen, problems = self._collect()
        if problems:
            return
        self.selected = chosen
        self.accept()


class LineDialog(_Dialog):
    def __init__(self, line, parent=None):
        super().__init__(f"{line['qty']}× {line['name']}", parent, 420)
        self.action = None
        pending = line['state'] == 'pending'
        info = QLabel(("⏳ Henüz gönderilmedi: adet ve not değiştirilebilir, satır silinebilir." if pending else
                       "✓ Bar/mutfağa gönderildi: yalnızca ikram ya da gerekçeli iptal yapılabilir."))
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        self.body.addWidget(info)
        form = QFormLayout()
        self.qty = QSpinBox()
        self.qty.setRange(1, 99)
        self.qty.setValue(line['qty'])
        self.qty.setEnabled(pending)
        self.note = QLineEdit(line.get('note', ''))
        self.note.setMaxLength(120)
        self.note.setEnabled(pending)
        form.addRow("Adet:", self.qty)
        form.addRow("Not:", self.note)
        self.body.addLayout(form)
        grid = QGridLayout()
        buttons = []
        if pending:
            buttons += [("💾 Kaydet", 'update', COLORS['primary']), ("🗑 Satırı sil", 'remove', COLORS['danger'])]
        else:
            buttons += [("✖ İptal et", 'void', COLORS['danger'])]
        buttons += [("🎁 İkram", 'comp', COLORS['info'])]
        for i, (text, action, color) in enumerate(buttons):
            b = _btn(text, color)
            b.clicked.connect(lambda _, a=action: self._choose(a))
            grid.addWidget(b, i // 2, i % 2)
        self.body.addLayout(grid)

    def _choose(self, action):
        self.action = action
        self.accept()


class DiscountDialog(_Dialog):
    def __init__(self, order, parent=None):
        super().__init__("İskonto", parent, 420)
        self.discount = None
        self.reason = ''
        current = order.get('discount')
        info = QLabel(f"Ara toplam: <b>{format_tl(order['subtotal'])}</b>. İskonto ara toplama bir kez uygulanır; "
                      "sonradan eklenen ürünlerde yeniden hesaplanır.")
        info.setWordWrap(True)
        self.body.addWidget(info)
        row = QHBoxLayout()
        self.percent = QRadioButton("Yüzde (%)")
        self.amount = QRadioButton("Tutar (₺)")
        (self.amount if current and current['type'] == 'amount' else self.percent).setChecked(True)
        row.addWidget(self.percent)
        row.addWidget(self.amount)
        row.addStretch()
        self.body.addLayout(row)
        quick = QHBoxLayout()
        for v in (5, 10, 15, 20, 25):
            b = _btn(f"%{v}", height=40)
            b.clicked.connect(lambda _, x=v: (self.percent.setChecked(True), self.value.setText(str(x))))
            quick.addWidget(b)
        self.body.addLayout(quick)
        self.value = QLineEdit()
        self.value.setFixedHeight(42)
        if current:
            self.value.setText(str(current['value']) if current['type'] == 'percent'
                               else format_tl(current['value']).replace(' ₺', ''))
        self.body.addWidget(self.value)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
        self.body.addWidget(self.warn)
        btns = QHBoxLayout()
        if current:
            rm = _btn("İskontoyu kaldır")
            rm.clicked.connect(self._remove)
            btns.addWidget(rm)
        ok = _btn("Uygula", COLORS['primary'])
        ok.clicked.connect(self._apply)
        btns.addWidget(ok)
        self.body.addLayout(btns)

    def _remove(self):
        self.discount = None
        self.accept()

    def _apply(self):
        text = self.value.text().strip()
        try:
            if self.percent.isChecked():
                value = int(text.replace('%', ''))
                if not 1 <= value <= 100:
                    raise ValueError
                self.discount = {'type': 'percent', 'value': value}
            else:
                self.discount = {'type': 'amount', 'value': parse_tl(text)}
                if self.discount['value'] <= 0:
                    raise ValueError
        except ValueError:
            self.warn.setText("Geçerli bir değer girin (yüzde 1-100 arası tam sayı).")
            return
        self.accept()


class PaymentDialog(_Dialog):
    """
    Ödeme: tamamı ya da kısmi tutar, eşit bölme (kişi sayısı) veya ürün seçerek bölme.
    Ürün seçerek bölmede birden fazla adetli satırın bir kısmı seçilebilir (3 latteden 1'i);
    ekran ödeme öncesinde o satırı böler (pos.split_line).

    Sonuç: method, amount, received, tip, line_picks ({lineId: adet} ya da None), people_left.
    """
    MODES = (('full', 'Tamamı'), ('equal', 'Eşit böl'), ('items', 'Ürün seç'))

    def __init__(self, order, parent=None, people_left=None):
        super().__init__(f"Ödeme · {order.get('tableName') or 'Masasız'} · {order['no']}", parent, 520)
        self.order = order
        self.modules = database.modules()
        self.remaining = order['total'] - order['paid']
        self.method = None
        self.mode = 'full'
        self.amount = self.remaining
        self.received = None
        self.tip = 0
        self.line_picks = None
        self.people_left = people_left
        self.total_label = QLabel(format_tl(self.remaining))
        self.total_label.setAlignment(Qt.AlignCenter)
        self.total_label.setFont(QFont(FONTS['family'], 30, QFont.Bold))
        self.total_label.setStyleSheet(f"color: {COLORS['success']}; background: transparent;")
        self.body.addWidget(self.total_label)
        if order['paid']:
            self.body.addWidget(QLabel(f"Adisyon {format_tl(order['total'])} · daha önce ödenen: {format_tl(order['paid'])}"))

        # Bölme biçimi
        self.mode_buttons = {}
        mode_row = QHBoxLayout()
        amount_paid = any(not p.get('lineIds') for p in order['payments'])
        for key, label in self.MODES:
            b = self._toggle(label)
            b.clicked.connect(lambda _, k=key: self._set_mode(k))
            if key == 'items' and amount_paid:
                b.setEnabled(False)
                b.setToolTip("Tutar olarak ödeme alınmış adisyonda ürün seçerek bölünemez.")
            self.mode_buttons[key] = b
            mode_row.addWidget(b)
        self.body.addLayout(mode_row)

        # Eşit böl: kalan kişi sayısı
        self.equal_box = QWidget()
        el = QHBoxLayout(self.equal_box)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(QLabel("Kalan kişi sayısı:"))
        self.people = QSpinBox()
        self.people.setRange(1, 20)
        self.people.setValue(people_left or 2)
        self.people.setMinimumHeight(38)
        self.people.valueChanged.connect(self._mode_amount)
        el.addWidget(self.people)
        self.equal_hint = QLabel("")
        self.equal_hint.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        el.addWidget(self.equal_hint, 1)
        self.body.addWidget(self.equal_box)

        # Ürün seç: ödenmemiş satırlar, adet seçilebilir
        self.items_box = QFrame()
        self.items_box.setStyleSheet(f"QFrame {{ border: 1px solid {COLORS['border_light']}; border-radius: 8px; }}"
                                     " QLabel, QCheckBox { border: none; }")
        il = QVBoxLayout(self.items_box)
        il.setContentsMargins(10, 8, 10, 8)
        self.picks = []
        for line in order['items']:
            if line['status'] != 'active' or line.get('paidBy'):
                continue
            row = QHBoxLayout()
            check = QCheckBox(f"{line['name']}" + (f" ({', '.join(o['name'] for o in line['options'])})"
                                                   if line.get('options') else ''))
            qty = QSpinBox()
            qty.setRange(1, line['qty'])
            qty.setValue(line['qty'])
            qty.setSuffix(f" / {line['qty']}")
            qty.setEnabled(line['qty'] > 1)
            qty.setFixedWidth(84)
            unit = pos.line_total(line) // line['qty']
            price = QLabel(format_tl(pos.line_total(line)))
            price.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            price.setFixedWidth(90)
            check.toggled.connect(self._mode_amount)
            qty.valueChanged.connect(self._mode_amount)
            qty.valueChanged.connect(lambda v, lbl=price, u=unit: lbl.setText(format_tl(u * v)))
            row.addWidget(check, 1)
            row.addWidget(qty)
            row.addWidget(price)
            il.addLayout(row)
            self.picks.append((line, check, qty))
        self.body.addWidget(self.items_box)

        # Ödeme yöntemi (Modüller → kapalı yöntemler görünmez)
        mrow = QHBoxLayout()
        self.method_buttons = {}
        for key, label in pos.PAYMENT_LABELS.items():
            if not self.modules['paymentMethods'].get(key, True):
                continue
            b = self._toggle(label)
            b.clicked.connect(lambda _, k=key: self._set_method(k))
            self.method_buttons[key] = b
            mrow.addWidget(b)
        self.body.addLayout(mrow)

        form = QFormLayout()
        self.amount_edit = QLineEdit(format_tl(self.remaining).replace(' ₺', ''))
        self.amount_edit.setToolTip("Kısmi ödeme için tutarı değiştirin; kalan adisyonda açık kalır.")
        self.amount_edit.textChanged.connect(self._recalc)
        self.received_edit = QLineEdit()
        self.received_edit.setPlaceholderText("Müşteriden alınan nakit")
        self.received_edit.textChanged.connect(self._recalc)
        self.tip_edit = QLineEdit()
        self.tip_edit.setPlaceholderText("0,00")
        self.tip_edit.textChanged.connect(self._recalc)
        self.change = QLabel("—")
        self.change.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        form.addRow("Tahsil edilecek:", self.amount_edit)
        self.received_label = QLabel("Alınan nakit:")
        form.addRow(self.received_label, self.received_edit)
        self.quick = QHBoxLayout()
        form.addRow("", self.quick)
        self.change_label = QLabel("Para üstü:")
        form.addRow(self.change_label, self.change)
        self.tip_label = QLabel("Bahşiş:")
        form.addRow(self.tip_label, self.tip_edit)
        self.body.addLayout(form)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold; background: transparent;")
        self.body.addWidget(self.warn)
        self.ok = _btn("✓ Tahsil Et", COLORS['success'], height=54)
        self.ok.clicked.connect(self._accept)
        self.body.addWidget(self.ok)
        self._set_mode('equal' if people_left else 'full')
        self._set_method(next(iter(self.method_buttons)))

    def _toggle(self, label):
        b = QPushButton(label)
        b.setCheckable(True)
        b.setMinimumHeight(44)
        b.setStyleSheet(f"""
            QPushButton {{ background: white; border: 1.5px solid {COLORS['border']}; border-radius: 10px; font-weight: bold; }}
            QPushButton:checked {{ background: {COLORS['primary']}; color: white; border-color: {COLORS['primary']}; }}
            QPushButton:disabled {{ color: {COLORS['text_muted']}; background: {COLORS['bg_input']}; }}
        """)
        return b

    # ------------------------------------------------------------------ bölme
    def _set_mode(self, key):
        self.mode = key
        for k, b in self.mode_buttons.items():
            b.setChecked(k == key)
        self.equal_box.setVisible(key == 'equal')
        self.items_box.setVisible(key == 'items')
        self.amount_edit.setReadOnly(key == 'items')
        self._mode_amount()
        self.adjustSize()

    def selected_picks(self):
        return {line['lineId']: qty.value() for line, check, qty in self.picks if check.isChecked()}

    def preview_items_amount(self, picks):
        """Seçilen satırlar (kısmi adet dahil) için alınacak tutar; bölme sanal olarak uygulanır."""
        from cloud.orders import apply_order_op
        order, ids = self.order, []
        for i, (line_id, qty) in enumerate(picks.items()):
            line = next(l for l in order['items'] if l['lineId'] == line_id)
            if qty < line['qty']:
                new_id = f"__onizleme{i}"
                order = apply_order_op(order, 'splitLine', {'lineId': line_id, 'qty': qty, 'newLineId': new_id},
                                       'onizleme', '')
                ids.append(new_id)
            else:
                ids.append(line_id)
        return pos.lines_payable(order, ids)

    def _mode_amount(self, *_):
        if self.mode == 'full':
            value = self.remaining
        elif self.mode == 'equal':
            left = self.people.value()
            value = pos.equal_share(self.remaining, left)
            self.equal_hint.setText("son kişi: kalanın tamamı" if left == 1 else f"kişi başı ≈ {format_tl(value)}")
        else:
            picks = self.selected_picks()
            value = self.preview_items_amount(picks) if picks else 0
        self.total_label.setText(format_tl(value))
        self.amount_edit.setText(format_tl(value).replace(' ₺', ''))
        self._rebuild_quick(value)

    def _rebuild_quick(self, amount):
        clear_layout(self.quick)
        values = [amount]
        for step in (5000, 10000, 20000):
            v = -(-amount // step) * step
            if v not in values:
                values.append(v)
        for v in values[:4]:
            b = _btn(format_tl(v).replace(',00', ''), height=36, bold=False)
            b.clicked.connect(lambda _, x=v: self.received_edit.setText(format_tl(x).replace(' ₺', '')))
            b.setVisible(self.method == 'cash')
            self.quick.addWidget(b)

    # ------------------------------------------------------------------ yöntem
    def _set_method(self, key):
        self.method = key
        for k, b in self.method_buttons.items():
            b.setChecked(k == key)
        cash = key == 'cash'
        for w in (self.received_label, self.received_edit, self.change_label, self.change):
            w.setVisible(cash)
        for i in range(self.quick.count()):
            self.quick.itemAt(i).widget().setVisible(cash)
        tips = not cash and self.modules['tips']
        for w in (self.tip_label, self.tip_edit):
            w.setVisible(tips)
        self._recalc()

    def _parse(self, edit, default=None):
        text = edit.text().strip()
        if not text:
            return default
        return parse_tl(text)

    def _recalc(self, *_):
        self.warn.setText("")
        try:
            if self.mode == 'items' and not self.selected_picks():
                raise ValueError("Ödenecek ürünleri işaretleyin.")
            amount = self._parse(self.amount_edit, 0)
            if amount <= 0 and self.remaining > 0:
                raise ValueError("Tutar sıfırdan büyük olmalı.")
            if amount > self.remaining:
                raise ValueError("Tutar kalan tutardan fazla olamaz.")
            if self.method == 'cash':
                received = self._parse(self.received_edit, amount)
                if received < amount:
                    raise ValueError("Alınan nakit tutardan az.")
                self.change.setText(format_tl(received - amount))
            elif self.tip_edit.isVisible():
                self._parse(self.tip_edit, 0)
            self.ok.setEnabled(True)
        except ValueError as e:
            self.warn.setText(str(e))
            self.ok.setEnabled(False)

    def _accept(self):
        self.amount = self._parse(self.amount_edit, 0)
        if self.method == 'cash':
            self.received = self._parse(self.received_edit, self.amount)
            self.tip = 0
        else:
            self.received = None
            self.tip = self._parse(self.tip_edit, 0) if self.tip_edit.isVisible() else 0
        self.line_picks = self.selected_picks() if self.mode == 'items' else None
        self.people_left = self.people.value() - 1 if self.mode == 'equal' and self.people.value() > 1 else None
        self.accept()


class TablePickerDialog(_Dialog):
    """mode='empty': boş masalar (taşıma); mode='open': açık adisyonlu masalar (birleştirme)."""

    def __init__(self, title, mode, exclude=None, parent=None):
        super().__init__(title, parent, 420)
        self.choice = None
        self.lst = QListWidget()
        self.lst.setStyleSheet("QListWidget::item { padding: 10px; font-size: 14px; }")
        open_by_table = {o['tableId']: o for o in pos.open_orders('dine_in')}
        for area in database.floor_areas():
            for t in sorted(database.floor_tables(area['id']), key=lambda x: (len(x['name']), x['name'])):
                if t['id'] == exclude:
                    continue
                o = open_by_table.get(t['id'])
                if (mode == 'empty') == bool(o):
                    continue
                text = f"{area['name']} · {t['name']}"
                if o:
                    text += f"   ({o['no']} · {format_tl(o['total'])})"
                it = QListWidgetItem(text)
                it.setData(Qt.UserRole, {'id': t['id'], 'name': t['name'], 'orderId': o['id'] if o else None})
                self.lst.addItem(it)
        if not self.lst.count():
            self.lst.addItem("Uygun masa yok.")
        self.lst.itemDoubleClicked.connect(lambda _: self._ok())
        self.body.addWidget(self.lst, 1)
        ok = _btn("Seç", COLORS['primary'])
        ok.clicked.connect(self._ok)
        self.body.addWidget(ok)
        self.resize(440, 520)

    def _ok(self):
        it = self.lst.currentItem()
        if it and it.data(Qt.UserRole):
            self.choice = it.data(Qt.UserRole)
            self.accept()


# =====================================================================
# Mutfak / bar fiş panosu
# =====================================================================

class TicketBoard(QWidget):
    """
    Gönderilen fişler: Yeni → Hazırlanıyor → Hazır → (teslim edildi).
    Mutfak ekranı (KDS) modülü açıkken Başla/Hazır tabletten gelir; pano yedek olarak çalışır.
    """
    COLUMNS = (('new', 'Yeni', COLORS['warning']), ('preparing', 'Hazırlanıyor', COLORS['info']),
               ('ready', 'Hazır', COLORS['success']))
    NEXT = {'new': ('preparing', "Hazırlamaya başla"), 'preparing': ('ready', "Hazır"), 'ready': ('served', "Teslim edildi")}

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        bar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem("Tüm istasyonlar", None)
        self.filter.addItem("🥤 Bar", 'bar')
        self.filter.addItem("🍳 Mutfak", 'kitchen')
        self.filter.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.filter)
        self.kds_note = QLabel()
        self.kds_note.setWordWrap(True)
        bar.addWidget(self.kds_note, 1)
        root.addLayout(bar)
        cols = QHBoxLayout()
        cols.setSpacing(14)
        self.col_layouts = {}
        for key, title, color in self.COLUMNS:
            frame = QFrame()
            frame.setObjectName("ticketCol")
            frame.setStyleSheet(f"QFrame#ticketCol {{ background: {COLORS['bg_input']}; border-radius: 12px; }}")
            fl = QVBoxLayout(frame)
            head = QLabel(title)
            head.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 15px; background: transparent;")
            fl.addWidget(head)
            self.col_layouts[key] = (head, QVBoxLayout())
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            holder = QWidget()
            holder.setStyleSheet("background: transparent;")
            inner = QVBoxLayout(holder)
            inner.setAlignment(Qt.AlignTop)
            self.col_layouts[key] = (head, inner, title)
            scroll.setWidget(holder)
            fl.addWidget(scroll, 1)
            cols.addWidget(frame, 1)
        root.addLayout(cols, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)

    def refresh(self):
        kds = database.modules()['kds']['enabled']
        offline = bool(ctx.last_status) and not ctx.last_status.online
        if kds and offline:
            self.kds_note.setText("⚠ İnternet yok: mutfak ekranına ulaşılamıyor, fişleri buradan takip edin.")
            self.kds_note.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold; background: transparent;")
        else:
            self.kds_note.setText("Mutfak ekranı açık: Başla / Hazır tabletten gelir. 🔔 Hazır fişi teslim edince işaretleyin."
                                  if kds else "")
            self.kds_note.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        station = self.filter.currentData()
        all_tickets = [t for t in pos.tickets() if station is None or t['station'] == station]
        for key, (head, inner, title) in self.col_layouts.items():
            clear_layout(inner)
            subset = [t for t in all_tickets if t['status'] == key]
            head.setText(f"{title}  ({len(subset)})")
            for t in subset:
                inner.addWidget(self._card(t))

    def _card(self, t):
        card = QFrame()
        card.setObjectName("tcard")
        card.setStyleSheet("QFrame#tcard { background: white; border-radius: 10px; }")
        ly = QVBoxLayout(card)
        icon = "🥤" if t['station'] == 'bar' else "🍳"
        where = t['tableName'] or "Masasız"
        mins = _minutes_since(t.get('createdAt'))
        head = QLabel(f"<b>{icon} {where}</b> · {t['orderNo']}  <span style='color:#64748B'>{mins} dk</span>")
        ly.addWidget(head)
        for line in t['lines']:
            extra = (" — " + ", ".join(line['options'])) if line.get('options') else ""
            note = f"<br><i style='color:#B45309'>“{line['note']}”</i>" if line.get('note') else ""
            lbl = QLabel(f"{line['qty']}× {line['name']}{extra}{note}")
            lbl.setWordWrap(True)
            ly.addWidget(lbl)
        nxt, label = self.NEXT[t['status']]
        b = _btn(label, COLORS['primary'], height=36)
        b.clicked.connect(lambda _, tid=t['id'], st=nxt: self._advance(tid, st))
        ly.addWidget(b)
        return card

    def _advance(self, ticket_id, status):
        try:
            pos.set_ticket_status(self.user, ticket_id, status)
        except pos.OrderError as e:
            _show_error(self, e)
        ctx.request_sync()
        self.refresh()


def _minutes_since(iso):
    from datetime import datetime
    try:
        return max(0, int((datetime.now().astimezone() - datetime.fromisoformat(iso)).total_seconds() // 60))
    except (TypeError, ValueError):
        return 0
