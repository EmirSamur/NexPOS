"""
NexPOS - Menü Yönetimi (2. ekran)

Menü bulutta tutulur, bu ekran yerel önbellekten okur. Düzenleme (kategori, ürün,
seçenek grubu, sıralama, toplu fiyat) internet ister ve yöneticinin kendi hesabıyla
Cloud Functions üzerinden yapılır. "Tükendi" internetsiz de çalışır (işlem kuyruğu).
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QFrame, QScrollArea,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QDialog, QFormLayout, QCheckBox,
    QTabWidget, QTextEdit, QSpinBox, QRadioButton, QButtonGroup, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QAbstractItemView, QDoubleSpinBox, QSlider
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPixmap
from styles import COLORS, FONTS, ICONS
from widgets import PageHeader, ToastNotification, add_shadow
from admin_access_pages import _button, cloud_action
from access import require_admin_api
from cloud.context import ctx
from cloud.images import fetch_pixmap, prepare_upload
from cloud.qt_sync import run_async
from money import format_tl, parse_tl
import database
import stock
from stock_pages import EffectDialog, RecipeEditor, describe_effect

CATEGORY_COLORS = [
    ('#8D6E63', 'Kahve'), ('#795548', 'Koyu kahve'), ('#FF7043', 'Turuncu'), ('#42A5F5', 'Mavi'),
    ('#EC407A', 'Pembe'), ('#FFA726', 'Amber'), ('#66BB6A', 'Yeşil'), ('#EF5350', 'Kırmızı'),
    ('#26A69A', 'Turkuaz'), ('#AB47BC', 'Mor'), ('#6C5CE7', 'Lavanta'), ('#607D8B', 'Gri'),
]
ALLERGENS = [('milk', 'Süt'), ('gluten', 'Gluten'), ('nuts', 'Kuruyemiş'), ('soy', 'Soya'), ('egg', 'Yumurta')]
TAX_RATES = [10, 20, 1, 0]
ROUNDING = [(500, "En yakın 5 ₺'ye yukarı"), (100, "En yakın 1 ₺'ye yukarı"),
            (1000, "En yakın 10 ₺'ye yukarı"), (0, "Yuvarlama yok")]
FILTERS = [('all', 'Tümü'), ('soldout', 'Tükenenler'), ('hidden', 'Uygulamada gizli'), ('inactive', 'Satış dışı')]


def _offline_tip(widget, online):
    widget.setEnabled(online)
    widget.setToolTip('' if online else 'Menü düzenlemek için internet bağlantısı gerekir.')


def _category_is_bar(category_id):
    cat = database.menu_item('categories', category_id) if category_id else None
    return bool(cat and cat.get('station') == 'bar')


# =====================================================================
# Ürün kartı
# =====================================================================

class MenuProductCard(QFrame):
    clicked = Signal(dict)
    sold_out_toggled = Signal(dict)

    def __init__(self, product, color, can_sold_out, parent=None):
        super().__init__(parent)
        self.product = product
        self.setFixedSize(190, 230)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("menuCard")
        dim = product.get('soldOut') or not product.get('active', True)
        self.setStyleSheet(f"""
            QFrame#menuCard {{ background: {'#F8FAFC' if dim else 'white'}; border-radius: 14px;
                border: 1.5px solid {COLORS['border_light']}; border-top: 4px solid {color}; }}
            QFrame#menuCard:hover {{ border: 1.5px solid {COLORS['primary']}; border-top: 4px solid {color}; }}
        """)
        add_shadow(self, blur=12, offset_y=3, color=QColor(0, 0, 0, 16))
        ly = QVBoxLayout(self)
        ly.setContentsMargins(12, 10, 12, 10)
        ly.setSpacing(4)

        self.photo = QLabel("☕" if not product.get('imageUrl') else "")
        self.photo.setFixedHeight(96)
        self.photo.setAlignment(Qt.AlignCenter)
        self.photo.setStyleSheet(f"background: {COLORS['bg_input']}; border-radius: 10px; font-size: 30px; border: none;")
        ly.addWidget(self.photo)
        if product.get('imageUrl'):
            fetch_pixmap(product['imageUrl'], self._set_photo)

        name = QLabel(product.get('name', ''))
        name.setWordWrap(True)
        name.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        name.setStyleSheet(f"color: {COLORS['text_muted'] if dim else COLORS['text_dark']}; border: none; background: transparent;")
        ly.addWidget(name)
        price = QLabel(format_tl(product.get('price', 0)))
        price.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        price.setStyleSheet(f"color: {COLORS['primary']}; border: none; background: transparent;")
        ly.addWidget(price)

        badges = QHBoxLayout()
        badges.setSpacing(4)
        for text, fg, bg, show in (
            ("TÜKENDİ", COLORS['danger'], COLORS['bg_danger'], product.get('soldOut')),
            ("SATIŞ DIŞI", COLORS['text_secondary'], COLORS['bg_input'], not product.get('active', True)),
            ("GİZLİ", COLORS['warning_dark'], COLORS['bg_warning'], not product.get('visibleInApp', True)),
            ("SEÇENEKLİ", COLORS['info_dark'], '#E0F2FE', bool(product.get('optionGroupIds'))),
        ):
            if show:
                b = QLabel(text)
                b.setStyleSheet(f"color: {fg}; background: {bg}; border: none; border-radius: 6px; "
                                f"padding: 2px 6px; font-size: 9px; font-weight: bold;")
                badges.addWidget(b)
        badges.addStretch()
        ly.addLayout(badges)
        ly.addStretch()

        self.sold_btn = QPushButton("↺ Satışa aç" if product.get('soldOut') else "⛔ Tükendi")
        self.sold_btn.setCursor(Qt.PointingHandCursor)
        self.sold_btn.setVisible(can_sold_out)
        self.sold_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: 1px solid {COLORS['border']}; border-radius: 7px;
                padding: 4px; font-size: 11px; font-weight: bold;
                color: {COLORS['success_dark'] if product.get('soldOut') else COLORS['danger']}; }}
            QPushButton:hover {{ background: {COLORS['bg_hover']}; }}
        """)
        self.sold_btn.clicked.connect(lambda: self.sold_out_toggled.emit(self.product))
        ly.addWidget(self.sold_btn)

    def _set_photo(self, pm):
        if pm and not pm.isNull():
            self.photo.setText("")
            self.photo.setPixmap(pm.scaled(166, 96, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                                 .copy(0, 0, 166, 96))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.product)
        super().mouseReleaseEvent(e)


# =====================================================================
# Menü sayfası
# =====================================================================

class MenuPage(QWidget):
    GRID_COLUMNS = 4

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.can_edit = database.user_can(user, 'editMenu')
        self.can_sold_out = database.user_can(user, 'markSoldOut')
        self.selected_category = None
        self._edit_widgets = []

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(14)
        root.addWidget(PageHeader("Menü / Ürünler",
                                  "Kategoriler, ürünler, seçenekler ve fiyatlar. Değişiklikler buluta kaydedilir.",
                                  COLORS['card_amber'], ICONS['menu_food']))

        self.import_banner = QFrame()
        self.import_banner.setStyleSheet(f"background: {COLORS['primary_bg']}; border-radius: 10px;")
        ib = QHBoxLayout(self.import_banner)
        ib.setContentsMargins(16, 10, 16, 10)
        self.import_label = QLabel()
        self.import_label.setStyleSheet(f"color: {COLORS['primary_dark']}; font-weight: bold; background: transparent;")
        ib.addWidget(self.import_label, 1)
        self.import_btn = _button("☁ Buluta Aktar")
        self.import_btn.clicked.connect(self._import_legacy)
        ib.addWidget(self.import_btn)
        root.addWidget(self.import_banner)

        self.offline_banner = QLabel("🟠 Çevrimdışı: menü görüntülenebilir, düzenlenemez. \"Tükendi\" işaretleme çalışmaya devam eder.")
        self.offline_banner.setStyleSheet(f"color: {COLORS['warning_dark']}; background: {COLORS['bg_warning']}; "
                                          f"padding: 8px 12px; border-radius: 8px; font-weight: bold;")
        root.addWidget(self.offline_banner)

        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)

        # ---- Kategoriler
        left = QFrame()
        left.setFixedWidth(260)
        left.setObjectName("catPanel")
        left.setStyleSheet(f"QFrame#catPanel {{ background: white; border-radius: 12px; border: 1px solid {COLORS['border_light']}; }}")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        title = QLabel("KATEGORİLER")
        title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 11px; background: transparent;")
        ll.addWidget(title)
        self.cat_list = QListWidget()
        self.cat_list.setStyleSheet(f"""
            QListWidget {{ border: none; background: transparent; font-size: 13px; }}
            QListWidget::item {{ padding: 9px 6px; border-radius: 8px; color: {COLORS['text_primary']}; }}
            QListWidget::item:selected {{ background: {COLORS['primary_bg']}; color: {COLORS['primary']}; font-weight: bold; }}
        """)
        self.cat_list.currentRowChanged.connect(self._on_category_changed)
        self.cat_list.itemDoubleClicked.connect(lambda _: self._edit_category())
        ll.addWidget(self.cat_list, 1)
        cat_btns = QGridLayout()
        cat_btns.setSpacing(6)
        self.add_cat_btn = _button(f"{ICONS['plus']} Kategori")
        self.add_cat_btn.clicked.connect(lambda: self._edit_category(new=True))
        self.edit_cat_btn = _button(f"{ICONS['edit']} Düzenle", primary=False)
        self.edit_cat_btn.clicked.connect(self._edit_category)
        self.del_cat_btn = _button(f"{ICONS['trash']} Sil", primary=False)
        self.del_cat_btn.clicked.connect(self._delete_category)
        self.sort_cat_btn = _button("⇅ Sırala", primary=False)
        self.sort_cat_btn.clicked.connect(self._sort_categories)
        cat_btns.addWidget(self.add_cat_btn, 0, 0, 1, 2)
        cat_btns.addWidget(self.edit_cat_btn, 1, 0)
        cat_btns.addWidget(self.del_cat_btn, 1, 1)
        cat_btns.addWidget(self.sort_cat_btn, 2, 0, 1, 2)
        ll.addLayout(cat_btns)
        body.addWidget(left)
        self._edit_widgets += [self.add_cat_btn, self.edit_cat_btn, self.del_cat_btn, self.sort_cat_btn]

        # ---- Ürünler
        right = QVBoxLayout()
        right.setSpacing(10)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"{ICONS['search']} Ürün ya da etiket ara…")
        self.search.setFixedHeight(40)
        self.search.textChanged.connect(self._render_products)
        bar.addWidget(self.search, 1)
        self.filter_box = QComboBox()
        self.filter_box.setFixedHeight(40)
        for key, label in FILTERS:
            self.filter_box.addItem(label, key)
        self.filter_box.currentIndexChanged.connect(self._render_products)
        bar.addWidget(self.filter_box)
        self.add_prod_btn = _button(f"{ICONS['plus']} Ürün")
        self.add_prod_btn.clicked.connect(lambda: self._edit_product(None))
        bar.addWidget(self.add_prod_btn)
        right.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(holder)
        self.grid.setSpacing(16)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(holder)
        right.addWidget(scroll, 1)

        self.empty = QLabel("Bu kategoride ürün yok.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; padding: 30px;")
        right.addWidget(self.empty)

        tools = QHBoxLayout()
        self.sort_prod_btn = _button("⇅ Ürünleri Sırala", primary=False)
        self.sort_prod_btn.clicked.connect(self._sort_products)
        self.bulk_btn = _button("₺ Toplu Fiyat", primary=False)
        self.bulk_btn.clicked.connect(self._bulk_prices)
        self.groups_btn = _button("⚙ Seçenek Grupları", primary=False)
        self.groups_btn.clicked.connect(self._option_groups)
        for b in (self.sort_prod_btn, self.bulk_btn, self.groups_btn):
            tools.addWidget(b)
        tools.addStretch()
        right.addLayout(tools)
        body.addLayout(right, 1)
        self._edit_widgets += [self.add_prod_btn, self.sort_prod_btn, self.bulk_btn, self.groups_btn, self.import_btn]
        self.refresh()

    # ------------------------------------------------------------------
    def on_sync_status(self, status):
        self._apply_online()
        if status and (status.changed & {'categories', 'optionGroups', 'products'}):
            self.refresh()

    def _apply_online(self):
        online = ctx.online
        self.offline_banner.setVisible(not online)
        for w in self._edit_widgets:
            _offline_tip(w, online and self.can_edit)

    def refresh(self):
        self.categories = database.menu_categories()
        current = self.selected_category
        self.cat_list.blockSignals(True)
        self.cat_list.clear()
        all_products = database.menu_products()
        counts = {}
        for p in all_products:
            counts[p.get('categoryId')] = counts.get(p.get('categoryId'), 0) + 1
        all_item = QListWidgetItem(f"★  Tüm ürünler   ({len(all_products)})")
        all_item.setData(Qt.UserRole, None)
        self.cat_list.addItem(all_item)
        row_to_select = 0
        for i, c in enumerate(self.categories, start=1):
            mark = "🥤" if c.get('station') == 'bar' else "🍳"
            hidden = "  · gizli" if not c.get('visibleInApp', True) else ""
            item = QListWidgetItem(f"{mark}  {c['name']}   ({counts.get(c['id'], 0)}){hidden}")
            item.setData(Qt.UserRole, c['id'])
            item.setForeground(QColor(c.get('color', COLORS['text_primary'])))
            self.cat_list.addItem(item)
            if c['id'] == current:
                row_to_select = i
        self.cat_list.setCurrentRow(row_to_select)
        self.cat_list.blockSignals(False)
        self.selected_category = self.cat_list.currentItem().data(Qt.UserRole) if self.cat_list.currentItem() else None
        self._render_products()
        self._update_import_banner()
        self._apply_online()
        has_cat = self.selected_category is not None
        if self.can_edit and ctx.online:
            self.edit_cat_btn.setEnabled(has_cat)
            self.del_cat_btn.setEnabled(has_cat)

    def _on_category_changed(self, row):
        item = self.cat_list.item(row)
        self.selected_category = item.data(Qt.UserRole) if item else None
        self._render_products()
        if self.can_edit and ctx.online:
            self.edit_cat_btn.setEnabled(self.selected_category is not None)
            self.del_cat_btn.setEnabled(self.selected_category is not None)

    def _render_products(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        products = database.menu_products(self.selected_category)
        text = self.search.text().strip().lower()
        flt = self.filter_box.currentData()
        colors = {c['id']: c.get('color', COLORS['primary']) for c in self.categories}
        shown = []
        for p in products:
            if text and text not in p.get('name', '').lower() and not any(text in t.lower() for t in p.get('tags', [])):
                continue
            if flt == 'soldout' and not p.get('soldOut'):
                continue
            if flt == 'hidden' and p.get('visibleInApp', True):
                continue
            if flt == 'inactive' and p.get('active', True):
                continue
            shown.append(p)
        for i, p in enumerate(shown):
            card = MenuProductCard(p, colors.get(p.get('categoryId'), COLORS['primary']), self.can_sold_out)
            card.clicked.connect(self._edit_product)
            card.sold_out_toggled.connect(self._toggle_sold_out)
            self.grid.addWidget(card, i // self.GRID_COLUMNS, i % self.GRID_COLUMNS)
        self.empty.setVisible(not shown)

    def _update_import_banner(self):
        cats, prods = database.legacy_menu_for_import()
        show = not self.categories and bool(cats)
        self.import_banner.setVisible(show)
        if show:
            self.import_label.setText(f"Bulutta henüz menü yok. Bu bilgisayardaki menüyü buluta aktarabilirsiniz "
                                      f"({len(prods)} ürün, {len(cats)} kategori). Fiyatlar kuruşa çevrilir.")

    # ------------------------------------------------------------------ işlemler
    def _toggle_sold_out(self, product):
        new_state = not product.get('soldOut')
        database.set_sold_out(self.user['cloud_id'], new_state, product_id=product['id'])
        ctx.request_sync()
        ToastNotification(self.window(), f"{product['name']} {'tükendi olarak işaretlendi' if new_state else 'yeniden satışta'}.",
                          "warning" if new_state else "success")
        self._render_products()

    def _edit_category(self, new=False):
        cat = None if new else database.menu_item('categories', self.selected_category) if self.selected_category else None
        if not new and not cat:
            return
        dlg = CategoryDialog(cat, self)
        if dlg.exec() == QDialog.Accepted:
            cloud_action(self, lambda api: api.save_category(dlg.values, cat['id'] if cat else None),
                         f"{dlg.values['name']} kaydedildi.", lambda _: self.refresh())

    def _delete_category(self):
        cat = database.menu_item('categories', self.selected_category) if self.selected_category else None
        if not cat:
            return
        if QMessageBox.question(self, "Kategoriyi Sil", f"{cat['name']} silinsin mi?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.selected_category = None
            cloud_action(self, lambda api: api.delete_category(cat['id']), f"{cat['name']} silindi.",
                         lambda _: self.refresh())

    def _sort_categories(self):
        dlg = ReorderDialog("Kategorileri Sırala", [(c['id'], c['name']) for c in self.categories], self)
        if dlg.exec() == QDialog.Accepted:
            cloud_action(self, lambda api: api.reorder('categories', dlg.ids), "Kategori sırası kaydedildi.",
                         lambda _: self.refresh())

    def _sort_products(self):
        if not self.selected_category:
            QMessageBox.information(self, "Kategori seçin", "Ürünleri sıralamak için soldan bir kategori seçin.")
            return
        items = [(p['id'], p['name']) for p in database.menu_products(self.selected_category)]
        dlg = ReorderDialog("Ürünleri Sırala", items, self)
        if dlg.exec() == QDialog.Accepted:
            cloud_action(self, lambda api: api.reorder('products', dlg.ids), "Ürün sırası kaydedildi.",
                         lambda _: self.refresh())

    def _edit_product(self, product):
        if not self.can_edit:
            return
        if not ctx.online:
            QMessageBox.information(self, "Çevrimdışı", "Ürün düzenlemek için internet bağlantısı gerekir.")
            return
        if not self.categories:
            QMessageBox.information(self, "Önce kategori", "Ürün eklemeden önce bir kategori oluşturun.")
            return
        dlg = ProductDialog(product, self.selected_category, self, user=self.user)
        result = dlg.exec()
        if result == ProductDialog.DELETE and product:
            cloud_action(self, lambda api: api.delete_product(product['id']), f"{product['name']} silindi.",
                         lambda _: self.refresh())
        elif result == QDialog.Accepted:
            values, image_path = dlg.values, dlg.image_path

            def save(api):
                data = dict(values)
                if image_path:
                    data['imageUrl'] = api.upload_product_image(prepare_upload(image_path))
                return api.save_product(data, product['id'] if product else None)

            cloud_action(self, save, f"{values['name']} kaydedildi.", lambda _: self.refresh())

    def _option_groups(self):
        OptionGroupsDialog(self.user, self).exec()
        self.refresh()

    def _bulk_prices(self):
        BulkPriceDialog(self.user, self.categories, self).exec()
        self.refresh()

    def _import_legacy(self):
        cats, prods = database.legacy_menu_for_import()
        if QMessageBox.question(
                self, "Menüyü Buluta Aktar",
                f"{len(cats)} kategori ve {len(prods)} ürün buluta aktarılacak.\n\n"
                "İçecek kategorileri bar istasyonuna ve damga kazandıranlara, diğerleri mutfağa atanır; "
                "sonradan değiştirebilirsiniz. Devam edilsin mi?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        payload_cats, payload_prods = database.legacy_import_payload()

        def work(api):
            result = api.import_menu(payload_cats, payload_prods)
            database.apply_import_mapping(result['categories'], result['products'])
            return result

        cloud_action(self, work, f"{len(prods)} ürün buluta aktarıldı.", lambda _: self.refresh())


# =====================================================================
# Diyaloglar
# =====================================================================

class ReorderDialog(QDialog):
    def __init__(self, title, items, parent=None):
        super().__init__(parent)
        self.ids = None
        self.setWindowTitle(title)
        self.setMinimumSize(380, 480)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.addWidget(QLabel("Sürükleyip bırakarak sıralayın:"))
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.InternalMove)
        self.lst.setStyleSheet("QListWidget::item { padding: 10px; }")
        for item_id, name in items:
            it = QListWidgetItem(f"☰  {name}")
            it.setData(Qt.UserRole, item_id)
            self.lst.addItem(it)
        ly.addWidget(self.lst, 1)
        ok = QPushButton("Kaydet")
        ok.setObjectName("primaryBtn")
        ok.clicked.connect(self._ok)
        ly.addWidget(ok)

    def _ok(self):
        self.ids = [self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())]
        self.accept()


class CategoryDialog(QDialog):
    def __init__(self, category=None, parent=None):
        super().__init__(parent)
        self.values = None
        c = category or {}
        self.setWindowTitle("Kategoriyi Düzenle" if category else "Yeni Kategori")
        self.setFixedWidth(440)
        self.setStyleSheet("QDialog { background: white; }")
        form = QFormLayout(self)
        form.setContentsMargins(28, 24, 28, 24)
        form.setSpacing(12)
        self.name = QLineEdit(c.get('name', ''))
        self.name.setPlaceholderText("Örn: Sıcak Kahveler")
        self.color = QComboBox()
        for hexc, label in CATEGORY_COLORS:
            pm = QPixmap(14, 14)
            pm.fill(QColor(hexc))
            self.color.addItem(pm, label, hexc)
        idx = self.color.findData(c.get('color'))
        if idx < 0 and c.get('color'):
            pm = QPixmap(14, 14)
            pm.fill(QColor(c['color']))
            self.color.addItem(pm, c['color'], c['color'])
            idx = self.color.count() - 1
        self.color.setCurrentIndex(max(idx, 0))
        self.station = QComboBox()
        self.station.addItem("🥤 Bar (içecekler)", 'bar')
        self.station.addItem("🍳 Mutfak (yiyecekler)", 'kitchen')
        self.station.setCurrentIndex(0 if c.get('station', 'bar') == 'bar' else 1)
        self.visible = QCheckBox("Müşteri uygulamasında göster")
        self.visible.setChecked(c.get('visibleInApp', True))
        self.stamp = QCheckBox("Bu kategoriden alınan ürünler damga kazandırır")
        self.stamp.setChecked(c.get('stampEligible', self.station.currentData() == 'bar'))
        form.addRow("Ad*:", self.name)
        form.addRow("Renk:", self.color)
        form.addRow("İstasyon:", self.station)
        form.addRow(self.visible)
        form.addRow(self.stamp)
        hint = QLabel("İstasyon, siparişin hangi ekrana (bar / mutfak) düşeceğini belirler.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        form.addRow(hint)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
        form.addRow(self.warn)
        ok = QPushButton("Kaydet")
        ok.setObjectName("primaryBtn")
        ok.clicked.connect(self._save)
        form.addRow(ok)

    def _save(self):
        name = self.name.text().strip()
        if not name:
            self.warn.setText("Kategori adı gerekli.")
            return
        self.values = {'name': name, 'color': self.color.currentData(), 'station': self.station.currentData(),
                       'visibleInApp': self.visible.isChecked(), 'stampEligible': self.stamp.isChecked()}
        self.accept()


class ProductDialog(QDialog):
    DELETE = 2

    def __init__(self, product=None, default_category=None, parent=None, user=None):
        super().__init__(parent)
        self.values = None
        self.user = user
        self.image_path = None
        p = product or {}
        self.product = product
        self.setWindowTitle(f"Ürünü Düzenle · {p['name']}" if product else "Yeni Ürün")
        self.setMinimumSize(660, 720)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(24, 20, 24, 20)
        tabs = QTabWidget()
        ly.addWidget(tabs, 1)

        # ---- Genel
        gen = QWidget()
        f = QFormLayout(gen)
        f.setHorizontalSpacing(12)
        f.setVerticalSpacing(16)
        f.setContentsMargins(16, 16, 16, 16)
        self.name = QLineEdit(p.get('name', ''))
        self.category = QComboBox()
        for c in database.menu_categories():
            self.category.addItem(c['name'], c['id'])
        idx = self.category.findData(p.get('categoryId') or default_category)
        self.category.setCurrentIndex(max(idx, 0))
        price_row = QHBoxLayout()
        self.price = QLineEdit(format_tl(p['price']).replace(' ₺', '') if product else '')
        self.price.setPlaceholderText("95,00")
        self.price.setFixedWidth(140)
        price_row.addWidget(self.price)
        price_row.addWidget(QLabel("₺   KDV:"))
        self.tax = QComboBox()
        for r in TAX_RATES:
            self.tax.addItem(f"%{r}", r)
        self.tax.setCurrentIndex(max(self.tax.findData(p.get('taxRate', 10)), 0))
        price_row.addWidget(self.tax)
        price_row.addWidget(QLabel("(fiyatlar KDV dahil)"))
        price_row.addStretch()
        self.description = QTextEdit(p.get('description', ''))
        self.description.setFixedHeight(70)
        self.description.setPlaceholderText("Müşteri uygulamasında görünür (en fazla 300 karakter)")
        photo_row = QHBoxLayout()
        self.photo_preview = QLabel("Fotoğraf yok")
        self.photo_preview.setFixedSize(120, 80)
        self.photo_preview.setAlignment(Qt.AlignCenter)
        self.photo_preview.setStyleSheet(f"background: {COLORS['bg_input']}; border-radius: 8px; color: {COLORS['text_muted']};")
        if p.get('imageUrl'):
            fetch_pixmap(p['imageUrl'], self._show_photo)
        photo_row.addWidget(self.photo_preview)
        pick = QPushButton("📷 Seç…")
        pick.clicked.connect(self._pick_photo)
        photo_row.addWidget(pick)
        self.remove_photo = QCheckBox("Fotoğrafı kaldır")
        self.remove_photo.setVisible(bool(p.get('imageUrl')))
        photo_row.addWidget(self.remove_photo)
        photo_row.addStretch()
        self.tags = QLineEdit(", ".join(p.get('tags', [])))
        self.tags.setPlaceholderText("yeni, mevsimlik, vegan (virgülle ayırın)")
        self.active = QCheckBox("Satışta")
        self.active.setChecked(p.get('active', True))
        self.visible = QCheckBox("Müşteri uygulamasında göster")
        self.visible.setChecked(p.get('visibleInApp', True))
        self.stamp = QComboBox()
        self.stamp.addItem("Kategoriden gelsin", None)
        self.stamp.addItem("Evet, damga kazandırır", True)
        self.stamp.addItem("Hayır, damga kazandırmaz", False)
        self.stamp.setCurrentIndex(max(self.stamp.findData(p.get('stampEligible')), 0))
        f.addRow("Ad*:", self.name)
        f.addRow("Kategori*:", self.category)
        f.addRow("Fiyat*:", price_row)
        f.addRow("Açıklama:", self.description)
        photo_box = QWidget()
        photo_box.setLayout(photo_row)
        photo_box.setMinimumHeight(88)
        photo_row.setContentsMargins(0, 4, 0, 4)
        f.addRow("Fotoğraf:", photo_box)
        f.addRow("Etiketler:", self.tags)
        f.addRow("Damga:", self.stamp)
        f.addRow(self.active)
        f.addRow(self.visible)
        tabs.addTab(gen, "Genel")

        # ---- Seçenekler
        opt = QWidget()
        ol = QVBoxLayout(opt)
        ol.setContentsMargins(16, 16, 16, 16)
        info = QLabel("Ürüne bağlanacak seçenek gruplarını işaretleyin. Gruplar menü sayfasındaki "
                      "\"Seçenek Grupları\" düğmesinden yönetilir.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        ol.addWidget(info)
        self.group_checks = []
        linked = set(p.get('optionGroupIds', []))
        groups = database.menu_option_groups()
        for g in groups:
            opts = ", ".join(f"{o['name']} {format_tl(o['priceDelta'], sign=True)}" if o.get('priceDelta') else o['name']
                             for o in g.get('options', []))
            cb = QCheckBox(f"{g['name']}  —  {opts}".replace('&', '&&'))
            cb.setChecked(g['id'] in linked)
            cb.setProperty('group_id', g['id'])
            self.group_checks.append(cb)
            ol.addWidget(cb)
        if not groups:
            ol.addWidget(QLabel("Henüz seçenek grubu yok."))
        ol.addStretch()
        tabs.addTab(opt, "Seçenekler")

        # ---- Reçete (8. ekran, stok modülü açıkken)
        self.recipe_editor = None
        if stock.enabled():
            def price_now():
                try:
                    return parse_tl(self.price.text())
                except ValueError:
                    return 0
            show_cost = bool(user) and database.user_can(user, 'viewReports')
            self.recipe_editor = RecipeEditor(product, price_now, lambda: self.tax.currentData(), show_cost)
            self.price.textChanged.connect(self.recipe_editor.update_summary)
            self.tax.currentIndexChanged.connect(self.recipe_editor.update_summary)
            tabs.addTab(self.recipe_editor, "Reçete")

        # ---- Müşteri bilgisi
        cust = QWidget()
        cf = QFormLayout(cust)
        cf.setContentsMargins(16, 16, 16, 16)
        cf.setSpacing(12)
        allergen_row = QHBoxLayout()
        self.allergen_checks = {}
        for key, label in ALLERGENS:
            cb = QCheckBox(label)
            cb.setChecked(key in p.get('allergens', []))
            self.allergen_checks[key] = cb
            allergen_row.addWidget(cb)
        allergen_row.addStretch()
        self.calories = self._optional_spin(p.get('calories'), 5000, " kcal")
        self.caffeine = self._optional_spin(p.get('caffeineMg'), 1000, " mg")
        cf.addRow("Alerjenler:", allergen_row)
        cf.addRow("Kalori:", self.calories)
        cf.addRow("Kafein:", self.caffeine)
        tabs.addTab(cust, "Müşteri Bilgisi")

        # ---- Tat profili
        flav = QWidget()
        fl = QFormLayout(flav)
        fl.setContentsMargins(16, 16, 16, 16)
        fl.setSpacing(12)
        fv = p.get('flavor') or {}
        self.has_flavor = QCheckBox("Bu ürünün tat profili var (kahve önerisinde kullanılır)")
        self.has_flavor.setChecked(bool(p.get('flavor')))
        fl.addRow(self.has_flavor)
        self.flavor_box = QFrame()
        fb = QFormLayout(self.flavor_box)
        fb.setContentsMargins(0, 0, 0, 0)
        self.sliders = {}
        for key, label in (('strength', 'Sertlik'), ('sweetness', 'Tatlılık'), ('acidity', 'Asidite'), ('body', 'Gövde')):
            row = QHBoxLayout()
            s = QSlider(Qt.Horizontal)
            s.setRange(1, 5)
            s.setValue(fv.get(key, 3))
            s.setTickPosition(QSlider.TicksBelow)
            val = QLabel()
            val.setFixedWidth(80)
            s.valueChanged.connect(lambda v, l=val: l.setText("●" * v + "○" * (5 - v)))
            val.setText("●" * s.value() + "○" * (5 - s.value()))
            row.addWidget(s, 1)
            row.addWidget(val)
            self.sliders[key] = s
            fb.addRow(f"{label}:", row)
        self.milk = QCheckBox("Sütlü")
        self.milk.setChecked(fv.get('milk', False))
        temp_row = QHBoxLayout()
        self.hot = QRadioButton("Sıcak")
        self.iced = QRadioButton("Soğuk")
        (self.iced if fv.get('temperature') == 'iced' else self.hot).setChecked(True)
        temp_row.addWidget(self.hot)
        temp_row.addWidget(self.iced)
        temp_row.addStretch()
        self.notes = QLineEdit(", ".join(fv.get('notes', [])))
        self.notes.setPlaceholderText("çikolata, fındık, meyvemsi")
        fb.addRow(self.milk)
        fb.addRow("Sıcaklık:", temp_row)
        fb.addRow("Notalar:", self.notes)
        # Hazır şablon: yaygın içeceklerin profili tek seçimle dolar (sonra elle ayarlanabilir)
        import quiz_logic
        self.flavor_template = QComboBox()
        self.flavor_template.addItem("Hazır şablondan doldur…", None)
        for t in quiz_logic.flavor_templates():
            self.flavor_template.addItem(t['name'], t['flavor'])
        self.flavor_template.currentIndexChanged.connect(self._apply_flavor_template)
        fb.insertRow(0, "Şablon:", self.flavor_template)
        fl.addRow(self.flavor_box)
        self.has_flavor.toggled.connect(self.flavor_box.setEnabled)
        self.flavor_box.setEnabled(self.has_flavor.isChecked())
        self.flavor_tab_index = tabs.addTab(flav, "Tat Profili")
        self.tabs = tabs
        self.category.currentIndexChanged.connect(self._update_flavor_tab)
        self._update_flavor_tab()

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold; background: transparent;")
        ly.addWidget(self.warn)
        btns = QHBoxLayout()
        if product:
            delete = QPushButton(f"{ICONS['trash']} Ürünü Sil")
            delete.setObjectName("ghostBtn")
            delete.setStyleSheet(f"color: {COLORS['danger']};")
            delete.clicked.connect(self._delete)
            btns.addWidget(delete)
        btns.addStretch()
        cancel = QPushButton("Vazgeç")
        cancel.setObjectName("ghostBtn")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Kaydet")
        save.setObjectName("primaryBtn")
        save.setMinimumWidth(140)
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        ly.addLayout(btns)

    @staticmethod
    def _optional_spin(value, maximum, suffix):
        s = QSpinBox()
        s.setRange(-1, maximum)
        s.setSpecialValueText("— (belirtilmemiş)")
        s.setSuffix(suffix)
        s.setValue(-1 if value is None else value)
        s.setFixedWidth(200)
        return s

    def _apply_flavor_template(self, *_):
        f = self.flavor_template.currentData()
        if not f:
            return
        for key, slider in self.sliders.items():
            slider.setValue(f[key])
        self.milk.setChecked(f['milk'])
        (self.iced if f['temperature'] == 'iced' else self.hot).setChecked(True)
        self.notes.setText(", ".join(f['notes']))

    def _update_flavor_tab(self):
        is_bar = _category_is_bar(self.category.currentData())
        self.tabs.setTabEnabled(self.flavor_tab_index, is_bar)
        self.tabs.setTabToolTip(self.flavor_tab_index, "" if is_bar else "Yalnızca bar (içecek) kategorilerinde")

    def _show_photo(self, pm):
        if pm and not pm.isNull():
            self.photo_preview.setPixmap(pm.scaled(120, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _pick_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ürün fotoğrafı seç", "", "Görseller (*.jpg *.jpeg *.png *.webp)")
        if path:
            pm = QPixmap(path)
            if pm.isNull():
                self.warn.setText("Görsel açılamadı.")
                return
            self.image_path = path
            self._show_photo(pm)
            self.remove_photo.setChecked(False)

    def _delete(self):
        if QMessageBox.question(self, "Ürünü Sil",
                                f"{self.product['name']} silinsin mi?\nGeçmiş adisyonlarda görünmeye devam eder.",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.done(self.DELETE)

    def _save(self):
        problems = []
        name = self.name.text().strip()
        if not name:
            problems.append("Ürün adı gerekli.")
        try:
            price = parse_tl(self.price.text())
        except ValueError as e:
            problems.append(f"Fiyat: {e}")
            price = 0
        description = self.description.toPlainText().strip()
        if len(description) > 300:
            problems.append("Açıklama en fazla 300 karakter olabilir.")
        tags = [t.strip() for t in self.tags.text().split(',') if t.strip()]
        if len(tags) > 10 or any(len(t) > 24 for t in tags):
            problems.append("En fazla 10 etiket, her biri en fazla 24 karakter.")
        flavor = None
        if self.has_flavor.isChecked() and _category_is_bar(self.category.currentData()):
            notes = [n.strip() for n in self.notes.text().split(',') if n.strip()]
            flavor = {k: s.value() for k, s in self.sliders.items()}
            flavor.update(milk=self.milk.isChecked(), temperature='iced' if self.iced.isChecked() else 'hot',
                          notes=notes[:8])
        if problems:
            self.warn.setText("\n".join(problems))
            return
        image_url = None if self.remove_photo.isChecked() else (self.product or {}).get('imageUrl')
        self.values = {
            'categoryId': self.category.currentData(),
            'name': name,
            'price': price,
            'taxRate': self.tax.currentData(),
            'description': description,
            'imageUrl': image_url,
            'tags': tags,
            'active': self.active.isChecked(),
            'visibleInApp': self.visible.isChecked(),
            'stampEligible': self.stamp.currentData(),
            'optionGroupIds': [cb.property('group_id') for cb in self.group_checks if cb.isChecked()],
            'allergens': [k for k, cb in self.allergen_checks.items() if cb.isChecked()],
            'calories': None if self.calories.value() < 0 else self.calories.value(),
            'caffeineMg': None if self.caffeine.value() < 0 else self.caffeine.value(),
            'flavor': flavor,
        }
        if self.recipe_editor:
            self.values['recipe'] = self.recipe_editor.recipe()
        self.accept()


class OptionGroupsDialog(QDialog):
    """Ortak seçenek grupları: boy, süt, şurup, ekstra shot…"""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.can_sold_out = database.user_can(user, 'markSoldOut')
        self.current = None
        self.setWindowTitle("Seçenek Grupları")
        self.setMinimumSize(920, 600)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QHBoxLayout(self)
        ly.setContentsMargins(20, 20, 20, 20)
        ly.setSpacing(16)

        left = QVBoxLayout()
        self.lst = QListWidget()
        self.lst.setFixedWidth(220)
        self.lst.currentRowChanged.connect(self._select)
        left.addWidget(self.lst, 1)
        new = _button(f"{ICONS['plus']} Yeni Grup")
        new.clicked.connect(self._new)
        left.addWidget(new)
        ly.addLayout(left)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Örn: Süt Seçimi")
        sel_row = QHBoxLayout()
        self.single = QRadioButton("Tek seçim")
        self.multi = QRadioButton("Çoklu seçim")
        self.single.setChecked(True)
        self.required = QCheckBox("Zorunlu")
        self.min = QSpinBox()
        self.min.setRange(0, 30)
        self.max = QSpinBox()
        self.max.setRange(1, 30)
        for w in (self.single, self.multi, self.required):
            sel_row.addWidget(w)
        sel_row.addStretch()
        count_row = QHBoxLayout()
        for sp in (self.min, self.max):
            sp.setFixedWidth(90)
        count_row.addWidget(QLabel("En az"))
        count_row.addWidget(self.min)
        count_row.addSpacing(16)
        count_row.addWidget(QLabel("En çok"))
        count_row.addWidget(self.max)
        count_row.addStretch()
        self.single.toggled.connect(lambda on: self.max.setEnabled(not on))
        form.addRow("Grup adı:", self.name)
        form.addRow("Seçim:", sel_row)
        form.addRow("Adet:", count_row)
        right.addLayout(form)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Seçenek", "Fiyat farkı (₺)", "Satışta", "Reçete etkisi"])
        self.table.setColumnHidden(3, not stock.enabled())
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 90)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        right.addWidget(self.table, 1)
        row_btns = QHBoxLayout()
        for text, fn in (("+ Seçenek", self._add_row), ("▲", lambda: self._move(-1)), ("▼", lambda: self._move(1)),
                         (f"{ICONS['trash']} Kaldır", self._remove_row)):
            b = QPushButton(text)
            b.setObjectName("ghostBtn")
            b.clicked.connect(fn)
            row_btns.addWidget(b)
        self.sold_btn = QPushButton("⛔ Seçili seçenek tükendi")
        self.sold_btn.setObjectName("ghostBtn")
        self.sold_btn.setVisible(self.can_sold_out)
        self.sold_btn.clicked.connect(self._toggle_option_sold_out)
        row_btns.addWidget(self.sold_btn)
        row_btns.addStretch()
        right.addLayout(row_btns)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold; background: transparent;")
        right.addWidget(self.warn)
        bottom = QHBoxLayout()
        self.del_btn = QPushButton(f"{ICONS['trash']} Grubu Sil")
        self.del_btn.setObjectName("ghostBtn")
        self.del_btn.clicked.connect(self._delete)
        bottom.addWidget(self.del_btn)
        bottom.addStretch()
        self.save_btn = _button("Kaydet")
        self.save_btn.clicked.connect(self._save)
        bottom.addWidget(self.save_btn)
        right.addLayout(bottom)
        ly.addLayout(right, 1)
        for w in (self.save_btn, self.del_btn):
            _offline_tip(w, ctx.online and database.user_can(user, 'editMenu'))
        self._reload()

    def _reload(self, select_id=None):
        self.groups = database.menu_option_groups()
        self.lst.blockSignals(True)
        self.lst.clear()
        row = 0
        for i, g in enumerate(self.groups):
            self.lst.addItem(f"{g['name']}  ({len(g.get('options', []))})")
            if g['id'] == (select_id or (self.current or {}).get('id')):
                row = i
        self.lst.blockSignals(False)
        if self.groups:
            self.lst.setCurrentRow(row)
            self._select(row)
        else:
            self._new()

    def _select(self, row):
        if row < 0 or row >= len(self.groups):
            return
        self.current = self.groups[row]
        self._fill(self.current)

    def _new(self):
        self.current = None
        self.lst.clearSelection()
        self._fill({'name': '', 'selection': 'single', 'required': False, 'min': 0, 'max': 1,
                    'options': [{'id': 'o1', 'name': '', 'priceDelta': 0, 'active': True}]})
        self.name.setFocus()

    def _fill(self, g):
        self.name.setText(g.get('name', ''))
        (self.single if g.get('selection', 'single') == 'single' else self.multi).setChecked(True)
        self.required.setChecked(g.get('required', False))
        self.min.setValue(g.get('min', 0))
        self.max.setValue(g.get('max', 1))
        self.table.setRowCount(0)
        for o in g.get('options', []):
            self._add_row(o)
        self.del_btn.setEnabled(bool(self.current) and ctx.online)
        self.warn.setText("")

    def _add_row(self, option=None):
        o = option if isinstance(option, dict) else {'id': '', 'name': '', 'priceDelta': 0, 'active': True}
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QTableWidgetItem(o.get('name', '') + ("  (tükendi)" if o.get('soldOut') else ""))
        name.setData(Qt.UserRole, {'id': o.get('id', ''), 'soldOut': o.get('soldOut', False),
                                   'recipeEffect': o.get('recipeEffect')})
        self.table.setItem(r, 0, name)
        delta = QDoubleSpinBox()
        delta.setStyleSheet("QDoubleSpinBox { padding: 2px 8px; min-height: 32px; max-height: 32px; }")
        delta.setRange(-10000, 10000)
        delta.setDecimals(2)
        delta.setPrefix("+" if o.get('priceDelta', 0) >= 0 else "")
        delta.setValue(o.get('priceDelta', 0) / 100)
        delta.valueChanged.connect(lambda v, d=delta: d.setPrefix("+" if v >= 0 else ""))
        self.table.setCellWidget(r, 1, delta)
        cb = QCheckBox()
        cb.setChecked(o.get('active', True))
        w = QWidget()
        l = QHBoxLayout(w)
        l.addWidget(cb)
        l.setAlignment(Qt.AlignCenter)
        l.setContentsMargins(0, 0, 0, 0)
        self.table.setCellWidget(r, 2, w)
        effect_btn = QPushButton()
        effect_btn.setObjectName("ghostBtn")
        effect_btn.clicked.connect(lambda _, b=effect_btn: self._edit_effect(b))
        self.table.setCellWidget(r, 3, effect_btn)
        self._paint_effect(r)

    def _row_of(self, widget):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 3) is widget:
                return r
        return -1

    def _paint_effect(self, r):
        meta = self.table.item(r, 0).data(Qt.UserRole) or {}
        names = {i['id']: i['name'] for i in stock.ingredients(include_deleted=True)}
        e = meta.get('recipeEffect')
        self.table.cellWidget(r, 3).setText(describe_effect(e, names) if e else "+ Tanımla")

    def _edit_effect(self, button):
        r = self._row_of(button)
        if r < 0:
            return
        item = self.table.item(r, 0)
        meta = dict(item.data(Qt.UserRole) or {})
        dlg = EffectDialog(item.text(), meta.get('recipeEffect'), self)
        if dlg.exec() == QDialog.Accepted:
            meta['recipeEffect'] = dlg.effect
            item.setData(Qt.UserRole, meta)
            self._paint_effect(r)

    def _row_values(self, r):
        meta = self.table.item(r, 0).data(Qt.UserRole) or {}
        name = self.table.item(r, 0).text().replace("  (tükendi)", "").strip()
        delta = int(round(self.table.cellWidget(r, 1).value() * 100))
        active = self.table.cellWidget(r, 2).findChild(QCheckBox).isChecked()
        return meta, name, delta, active

    def _move(self, step):
        r = self.table.currentRow()
        t = r + step
        if r < 0 or t < 0 or t >= self.table.rowCount():
            return
        a, b = self._row_values(r), self._row_values(t)
        for row, (meta, name, delta, active) in ((r, b), (t, a)):
            item = QTableWidgetItem(name + ("  (tükendi)" if meta.get('soldOut') else ""))
            item.setData(Qt.UserRole, meta)
            self.table.setItem(row, 0, item)
            self.table.cellWidget(row, 1).setValue(delta / 100)
            self.table.cellWidget(row, 2).findChild(QCheckBox).setChecked(active)
            self._paint_effect(row)
        self.table.setCurrentCell(t, 0)

    def _remove_row(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())

    def _collect(self):
        options, used = [], set()
        for r in range(self.table.rowCount()):
            meta, name, delta, active = self._row_values(r)
            if not name:
                continue
            oid = meta.get('id') or ''
            if not oid or oid in used:
                oid = f"o{r + 1}"
                while oid in used:
                    oid += "x"
            used.add(oid)
            options.append({'id': oid, 'name': name, 'priceDelta': delta, 'active': active,
                            'soldOut': bool(meta.get('soldOut')), 'recipeEffect': meta.get('recipeEffect')})
        single = self.single.isChecked()
        return {'name': self.name.text().strip(), 'selection': 'single' if single else 'multi',
                'required': self.required.isChecked(), 'min': self.min.value(),
                'max': 1 if single else self.max.value(), 'options': options}

    def _save(self):
        data = self._collect()
        if not data['name'] or not data['options']:
            self.warn.setText("Grup adı ve en az bir seçenek gerekli.")
            return
        gid = self.current['id'] if self.current else None
        cloud_action(self, lambda api: api.save_option_group(data, gid), f"{data['name']} kaydedildi.",
                     lambda res: self._reload(res['id']))

    def _delete(self):
        if not self.current:
            return
        if QMessageBox.question(self, "Grubu Sil", f"{self.current['name']} silinsin mi?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            gid, name = self.current['id'], self.current['name']
            self.current = None
            cloud_action(self, lambda api: api.delete_option_group(gid), f"{name} silindi.",
                         lambda _: self._reload())

    def _toggle_option_sold_out(self):
        r = self.table.currentRow()
        if r < 0 or not self.current:
            return
        meta, name, _, _ = self._row_values(r)
        if not meta.get('id'):
            return
        new_state = not meta.get('soldOut')
        database.set_sold_out(self.user['cloud_id'], new_state, option_group_id=self.current['id'],
                              option_id=meta['id'])
        ctx.request_sync()
        self._reload(self.current['id'])


class BulkPriceDialog(QDialog):
    """Toplu fiyat güncelleme: önce sunucudan önizleme, sonra onayla uygula."""

    def __init__(self, user, categories, parent=None):
        super().__init__(parent)
        self.user = user
        self.preview = None
        self.setWindowTitle("Toplu Fiyat Güncelleme")
        self.setMinimumSize(720, 640)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(24, 20, 24, 20)
        ly.setSpacing(10)

        ly.addWidget(QLabel("<b>Kapsam</b> (kategoriler):"))
        cat_grid = QGridLayout()
        self.cat_checks = []
        for i, c in enumerate(categories):
            cb = QCheckBox(c['name'].replace('&', '&&'))  # & Qt'de kısayol işaretidir
            cb.setProperty('cid', c['id'])
            cb.setChecked(c.get('station') == 'bar')
            cb.toggled.connect(self._invalidate)
            self.cat_checks.append(cb)
            cat_grid.addWidget(cb, i // 3, i % 3)
        ly.addLayout(cat_grid)

        rule = QFormLayout()
        mode_row = QHBoxLayout()
        self.percent = QRadioButton("Yüzde")
        self.amount = QRadioButton("Sabit tutar")
        self.percent.setChecked(True)
        self.value = QDoubleSpinBox()
        self.value.setRange(-90, 500)
        self.value.setDecimals(2)
        self.value.setValue(10)
        self.value.setSuffix(" %")
        self.value.setFixedWidth(140)
        for w in (self.percent, self.amount, self.value):
            mode_row.addWidget(w)
        mode_row.addStretch()
        self.percent.toggled.connect(self._mode_changed)
        self.rounding = QComboBox()
        for step, label in ROUNDING:
            self.rounding.addItem(label, step)
        self.include_options = QCheckBox("Seçenek fiyat farklarını da güncelle (yalnızca yüzde)")
        rule.addRow("Değişim:", mode_row)
        rule.addRow("Yuvarlama:", self.rounding)
        rule.addRow(self.include_options)
        ly.addLayout(rule)
        for w in (self.value, self.rounding, self.include_options):
            sig = w.valueChanged if hasattr(w, 'valueChanged') else (
                w.currentIndexChanged if hasattr(w, 'currentIndexChanged') else w.toggled)
            sig.connect(self._invalidate)

        preview_btn = _button("👁 Önizle", primary=False)
        preview_btn.clicked.connect(self._preview)
        ly.addWidget(preview_btn, 0, Qt.AlignLeft)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Ürün / Seçenek", "Eski", "Yeni", "Fark"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        ly.addWidget(self.table, 1)
        self.summary = QLabel("Önizleme için kapsamı ve kuralı seçip \"Önizle\"ye basın.")
        self.summary.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        ly.addWidget(self.summary)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Vazgeç")
        cancel.setObjectName("ghostBtn")
        cancel.clicked.connect(self.reject)
        self.apply_btn = _button("Uygula")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        btns.addWidget(cancel)
        btns.addWidget(self.apply_btn)
        ly.addLayout(btns)

    def _mode_changed(self, percent):
        self.value.setSuffix(" %" if percent else " ₺")
        self.value.setRange(-90, 500) if percent else self.value.setRange(-1000, 1000)
        self.include_options.setEnabled(percent)
        self._invalidate()

    def _invalidate(self, *_):
        self.preview = None
        self.apply_btn.setEnabled(False)
        self.apply_btn.setText("Uygula")

    def _request(self):
        cats = [cb.property('cid') for cb in self.cat_checks if cb.isChecked()]
        if self.percent.isChecked():
            rule = {'mode': 'percent', 'value': round(self.value.value(), 2), 'rounding': self.rounding.currentData()}
        else:
            rule = {'mode': 'amount', 'value': int(round(self.value.value() * 100)), 'rounding': self.rounding.currentData()}
        return cats, rule, self.include_options.isChecked() and self.percent.isChecked()

    def _preview(self):
        cats, rule, inc = self._request()
        if not cats:
            QMessageBox.information(self, "Kapsam", "En az bir kategori seçin.")
            return
        api = require_admin_api(self, self.user)
        if not api:
            return
        self.summary.setText("Önizleme hazırlanıyor…")
        run_async(lambda: api.bulk_prices(cats, rule, inc, True), self._show_preview,
                  lambda m: QMessageBox.warning(self, "Önizleme alınamadı", m))

    def _show_preview(self, result):
        self.preview = result
        rows = [(c['name'], c['before'], c['after']) for c in result['products']] + \
               [(f"↳ {c['name']}", c['before'], c['after']) for c in result['options']]
        self.table.setRowCount(len(rows))
        for i, (name, before, after) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(name))
            self.table.setItem(i, 1, QTableWidgetItem(format_tl(before)))
            new = QTableWidgetItem(format_tl(after))
            new.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
            self.table.setItem(i, 2, new)
            diff = QTableWidgetItem(format_tl(after - before, sign=True))
            diff.setForeground(QColor(COLORS['danger'] if after > before else COLORS['success']))
            self.table.setItem(i, 3, diff)
        n = len(result['products'])
        self.summary.setText(f"{n} ürün ve {len(result['options'])} seçenek değişecek. "
                             "Uygulamak için düğmeye basın; değişiklik kayıt altına alınır.")
        self.apply_btn.setEnabled(bool(rows))
        self.apply_btn.setText(f"{n} ürünü güncelle")

    def _apply(self):
        if not self.preview:
            return
        cats, rule, inc = self._request()
        n = len(self.preview['products'])
        cloud_action(self, lambda api: api.bulk_prices(cats, rule, inc, False), f"{n} ürünün fiyatı güncellendi.",
                     lambda _: self.accept())


class SoldOutDialog(QDialog):
    """Garson/barista ekranından hızlı "tükendi" yönetimi (internetsiz çalışır)."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Tükendi Yönetimi")
        self.setMinimumSize(520, 620)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(20, 18, 20, 18)
        info = QLabel("İşaretli olanlar satışa kapalıdır; garson ekranında gri görünür ve sepete eklenemez. "
                      "İnternet olmasa da çalışır.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        ly.addWidget(info)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"{ICONS['search']} Ara…")
        self.search.textChanged.connect(self._fill)
        ly.addWidget(self.search)
        self.lst = QListWidget()
        self.lst.setStyleSheet("QListWidget::item { padding: 8px; }")
        self.lst.itemChanged.connect(self._changed)
        ly.addWidget(self.lst, 1)
        close = QPushButton("Kapat")
        close.setObjectName("primaryBtn")
        close.clicked.connect(self.accept)
        ly.addWidget(close)
        self._fill()

    def _fill(self):
        text = self.search.text().strip().lower()
        self.lst.blockSignals(True)
        self.lst.clear()
        cats = {c['id']: c['name'] for c in database.menu_categories()}
        for p in database.menu_products():
            if not p.get('active', True) or (text and text not in p['name'].lower()):
                continue
            it = QListWidgetItem(f"{p['name']}   ·   {cats.get(p.get('categoryId'), '')}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if p.get('soldOut') else Qt.Unchecked)
            it.setData(Qt.UserRole, ('product', p['id'], None))
            self.lst.addItem(it)
        for g in database.menu_option_groups():
            for o in g.get('options', []):
                if not o.get('active', True) or (text and text not in o['name'].lower()):
                    continue
                it = QListWidgetItem(f"↳ {o['name']}   ·   {g['name']}")
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if o.get('soldOut') else Qt.Unchecked)
                it.setData(Qt.UserRole, ('option', g['id'], o['id']))
                self.lst.addItem(it)
        self.lst.blockSignals(False)

    def _changed(self, item):
        kind, a, b = item.data(Qt.UserRole)
        sold = item.checkState() == Qt.Checked
        if kind == 'product':
            database.set_sold_out(self.user['cloud_id'], sold, product_id=a)
        else:
            database.set_sold_out(self.user['cloud_id'], sold, option_group_id=a, option_id=b)
        ctx.request_sync()
