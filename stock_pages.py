"""
NexPOS - Stok ekranları (8. ekran)

- IngredientsPage: malzemeler, stok, kritik uyarı, stok değeri; ilk sayım; hazır şablon
- IngredientDialog: malzeme ekle/düzenle (buluta yazar, internet ister)
- CountDialog: ilk sayım / stok girişi (internetsiz, kuyruktan gider)
- RecipeEditor: ürün düzenleme penceresindeki "Reçete" sekmesi
- EffectDialog: seçeneğin reçeteye etkisi (yerine koy / ekle / çarp)
- TemplateDialog: hazır şablonun önizlemesi ve aktarımı
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from datetime import datetime

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextBrowser, QVBoxLayout, QWidget
)

import database
import stock
import stock_template
from admin_access_pages import _button, cloud_action
from cloud.context import ctx
from money import format_tl, parse_tl
from styles import COLORS
from widgets import PageHeader, ToastNotification


def _muted(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
    return lb


def _cost_label(ing):
    big = stock.UNITS[ing['unit']][0]
    return f"{format_tl(ing.get('unitCost', 0))} / {big}"


class _NumItem(QTableWidgetItem):
    def __init__(self, text, key):
        super().__init__(text)
        self.key = key
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.key < getattr(other, 'key', 0)


# =====================================================================
# Malzemeler
# =====================================================================

class IngredientsPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.rows = []
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 16, 28, 20)
        ly.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(PageHeader("Stok · Malzemeler", "Malzemeler, reçetelerden otomatik düşen stok ve kritik seviyeler",
                                  COLORS['warning'], "📦"), 1)
        for text, fn, primary in (("+ Malzeme", lambda: self._edit(None), True),
                                  ("Stok gir / ilk sayım", self._count, False),
                                  ("Hazır şablon", self._template, False)):
            b = _button(text, primary=primary)
            b.clicked.connect(fn)
            head.addWidget(b, 0, Qt.AlignVCenter)
        ly.addLayout(head)
        self.module_note = _muted("")
        ly.addWidget(self.module_note)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Malzeme ara…")
        self.search.setMinimumHeight(36)
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search, 1)
        self.filter_all, self.filter_crit, self.filter_neg = (QRadioButton("Hepsi"), QRadioButton("Kritik"),
                                                             QRadioButton("Eksi stok"))
        self.filter_all.setChecked(True)
        for r in (self.filter_all, self.filter_crit, self.filter_neg):
            r.toggled.connect(self._fill)
            bar.addWidget(r)
        self.total = _muted("")
        bar.addWidget(self.total)
        ly.addLayout(bar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Malzeme", "Grup", "Stok", "Kritik", "Birim maliyet", "Stok değeri",
                                              "Tedarikçi"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.table.doubleClicked.connect(lambda idx: self._edit(self._row_ingredient(idx.row())))
        ly.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.del_btn = _button("Seçili malzemeyi sil", primary=False)
        self.del_btn.clicked.connect(self._delete)
        actions.addWidget(self.del_btn)
        actions.addStretch()
        actions.addWidget(_muted("Çift tıklayarak düzenleyin. Stok, satışta reçeteden kendiliğinden düşer."))
        ly.addLayout(actions)
        self.refresh()

    def refresh(self):
        on = stock.enabled()
        self.module_note.setText("" if on else "⚠ Stok modülü kapalı: satışta stoktan düşülmüyor. "
                                 "Ayarlar → Modüller'den açabilirsiniz.")
        self.rows = stock.ingredients()
        self._fill()

    def _row_ingredient(self, row):
        item = self.table.item(row, 0)
        return next((i for i in self.rows if i['id'] == item.data(Qt.UserRole)), None) if item else None

    def _fill(self, *_):
        q = self.search.text().strip().lower()
        rows = [i for i in self.rows if q in i['name'].lower()]
        if self.filter_crit.isChecked():
            rows = [i for i in rows if i['isCritical']]
        if self.filter_neg.isChecked():
            rows = [i for i in rows if i['stock'] < 0]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, i in enumerate(rows):
            name = QTableWidgetItem(("⚠ " if i['isCritical'] else "") + i['name'])
            name.setData(Qt.UserRole, i['id'])
            stock_item = _NumItem(stock.format_qty(i['stock'], i['unit']), i['stock'])
            if i['stock'] < 0 or i['isCritical']:
                color = QColor('#B91C1C')
                name.setForeground(color)
                stock_item.setForeground(color)
            cells = [name, QTableWidgetItem(stock.GROUPS.get(i.get('group'), '')), stock_item,
                     _NumItem(stock.format_qty(i.get('critical') or 0, i['unit']), i.get('critical') or 0),
                     _NumItem(_cost_label(i), i.get('unitCost', 0)), _NumItem(format_tl(i['value']), i['value']),
                     QTableWidgetItem(i.get('supplierName') or '')]
            for c, item in enumerate(cells):
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        crit = sum(1 for i in self.rows if i['isCritical'])
        self.total.setText(f"{len(self.rows)} malzeme · stok değeri {format_tl(sum(i['value'] for i in self.rows))}"
                           + (f" · ⚠ {crit} kritik" if crit else ""))

    def _edit(self, ingredient):
        dlg = IngredientDialog(ingredient, self)
        if dlg.exec() != QDialog.Accepted:
            return
        iid = (ingredient or {}).get('id')
        cloud_action(self, lambda api: api.save_ingredient(dlg.values, iid), "Malzeme kaydedildi.",
                     lambda _: self.refresh())

    def _delete(self):
        rows = self.table.selectionModel().selectedRows()
        ing = self._row_ingredient(rows[0].row()) if rows else None
        if not ing:
            return
        if QMessageBox.question(self, "Malzemeyi sil", f"{ing['name']} silinsin mi?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            cloud_action(self, lambda api: api.delete_ingredient(ing['id']), "Malzeme silindi.", lambda _: self.refresh())

    def _count(self):
        if not self.rows:
            QMessageBox.information(self, "Malzeme yok", "Önce malzeme ekleyin ya da hazır şablonu kullanın.")
            return
        from pos_screen import authorize
        dlg = CountDialog(self.rows, self)
        if dlg.exec() != QDialog.Accepted:
            return
        approver, _ = authorize(self, self.user, 'stock', "Stok girişi / sayım", need_reason=False)
        if not approver:
            return
        changed = stock.set_counts(self.user, dlg.counts, dlg.reason, approver, initial=not stock.count_history(1))
        ctx.request_sync()
        self.refresh()
        ToastNotification(self.window(), f"{len(changed)} malzemenin stoğu güncellendi.", "success")

    def _template(self):
        data = stock_template.build(database.menu_products(), database.menu_categories(),
                                    database.menu_option_groups(), stock.ingredients())
        if not data['recipes'] and not data['optionEffects']:
            QMessageBox.information(self, "Hazır şablon", "Menüde şablonla eşleşen ve reçetesi olmayan ürün bulunamadı.")
            return
        if TemplateDialog(data, self).exec() != QDialog.Accepted:
            return
        cloud_action(self, lambda api: api.import_stock(data['ingredients'], data['recipes'], data['optionEffects']),
                     f"{len(data['ingredients'])} malzeme ve {len(data['recipes'])} reçete eklendi.",
                     lambda _: self.refresh())


class IngredientDialog(QDialog):
    def __init__(self, ingredient=None, parent=None):
        super().__init__(parent)
        i = ingredient or {}
        self.values = None
        self.setWindowTitle(f"Malzeme · {i['name']}" if ingredient else "Yeni malzeme")
        self.setMinimumWidth(480)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.setContentsMargins(24, 20, 24, 20)
        f = QFormLayout()
        f.setVerticalSpacing(12)
        self.name = QLineEdit(i.get('name', ''))
        self.name.setMaxLength(60)
        self.unit = QComboBox()
        for u, label in (('g', 'gram (g) — stok kg olarak gösterilir'), ('ml', 'mililitre (ml) — litre'),
                         ('adet', 'adet')):
            self.unit.addItem(label, u)
        self.unit.setCurrentIndex(max(0, self.unit.findData(i.get('unit', 'g'))))
        self.unit.setEnabled(not ingredient)  # birim sonradan değişirse reçeteler bozulur
        self.group = QComboBox()
        for k, v in stock.GROUPS.items():
            self.group.addItem(v, k)
        self.group.setCurrentIndex(max(0, self.group.findData(i.get('group', 'other'))))
        pu = i.get('purchaseUnit') or {}
        self.pu_name = QLineEdit(pu.get('name', ''))
        self.pu_name.setPlaceholderText("koli, paket, şişe…")
        self.pu_size = QSpinBox()
        self.pu_size.setRange(0, 10_000_000)
        self.pu_size.setValue(pu.get('size', 0))
        pu_row = QHBoxLayout()
        pu_row.addWidget(QLabel("1"))
        pu_row.addWidget(self.pu_name, 1)
        pu_row.addWidget(QLabel("="))
        pu_row.addWidget(self.pu_size)
        self.pu_unit = QLabel()
        pu_row.addWidget(self.pu_unit)
        self.critical = QSpinBox()
        self.critical.setRange(0, 10_000_000)
        self.critical.setValue(i.get('critical', 0))
        self.target = QSpinBox()
        self.target.setRange(0, 10_000_000)
        self.target.setSpecialValueText("—")
        self.target.setValue(i.get('target') or 0)
        self.cost = QLineEdit(format_tl(i.get('unitCost', 0)).replace(' ₺', ''))
        self.cost_unit = QLabel()
        cost_row = QHBoxLayout()
        cost_row.addWidget(self.cost, 1)
        cost_row.addWidget(self.cost_unit)
        self.supplier = QComboBox()
        self.supplier.addItem("—", None)
        for sup in stock.suppliers():
            self.supplier.addItem(sup['name'], sup['id'])
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(i.get('supplierId'))))
        f.addRow("Ad:", self.name)
        f.addRow("Stok birimi:", self.unit)
        f.addRow("Grup:", self.group)
        f.addRow("Alış birimi:", pu_row)
        f.addRow("Kritik seviye:", self.critical)
        f.addRow("Hedef seviye:", self.target)
        f.addRow("Birim maliyet:", cost_row)
        f.addRow("Tedarikçi:", self.supplier)
        ly.addLayout(f)
        ly.addWidget(_muted("Kritik seviyenin altına düşünce uyarı çıkar. Hedef seviye sipariş önerisinde kullanılır. "
                            "Birim maliyet alışlarla güncellenecek (8b); şimdilik elle girilir."))
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold;")
        ly.addWidget(self.warn)
        ok = _button("Kaydet")
        ok.clicked.connect(self._save)
        ly.addWidget(ok)
        self.unit.currentIndexChanged.connect(self._units)
        self._units()

    def _units(self, *_):
        u = self.unit.currentData()
        for sp in (self.critical, self.target, self.pu_size):
            sp.setSuffix(f" {u}")
        self.pu_unit.setText("")
        self.cost_unit.setText(f"₺ / {stock.UNITS[u][0]}")

    def _save(self):
        try:
            cost = parse_tl(self.cost.text() or '0')
        except ValueError as e:
            self.warn.setText(f"Birim maliyet: {e}")
            return
        if not self.name.text().strip():
            self.warn.setText("Ad gerekli.")
            return
        pu = None
        if self.pu_name.text().strip() and self.pu_size.value() > 0:
            pu = {'name': self.pu_name.text().strip(), 'size': self.pu_size.value()}
        self.values = {'name': self.name.text().strip(), 'unit': self.unit.currentData(),
                       'group': self.group.currentData(), 'purchaseUnit': pu, 'critical': self.critical.value(),
                       'target': self.target.value() or None, 'unitCost': cost,
                       'supplierId': self.supplier.currentData(),
                       'supplierName': self.supplier.currentText() if self.supplier.currentData() else ''}
        self.accept()


class CountDialog(QDialog):
    """İlk sayım / stok girişi: sayılan miktarı yazılan malzemenin stoğu ona eşitlenir."""

    def __init__(self, ingredients, parent=None):
        super().__init__(parent)
        self.counts, self.reason = {}, 'Sayım'
        self.ingredients = ingredients
        self.setWindowTitle("Stok gir / ilk sayım")
        self.resize(760, 620)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.addWidget(_muted("Saydığınız miktarı yazın (stok biriminde ya da alış biriminde). Boş bırakılan malzeme "
                            "değişmez. Fark, sayım hareketi olarak kaydedilir; internetsiz çalışır."))
        self.table = QTableWidget(len(ingredients), 4)
        self.table.setHorizontalHeaderLabels(["Malzeme", "Sistemde", "Sayılan", "Birim"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.inputs = []
        for r, i in enumerate(ingredients):
            self.table.setItem(r, 0, QTableWidgetItem(i['name']))
            self.table.setItem(r, 1, QTableWidgetItem(stock.format_qty(i['stock'], i['unit'])))
            spin = QDoubleSpinBox()
            spin.setRange(-1, 10_000_000)
            spin.setDecimals(3)
            spin.setSpecialValueText("—")
            spin.setValue(-1)
            self.table.setCellWidget(r, 2, spin)
            unit = QComboBox()
            unit.addItem(i['unit'], 1)
            big, factor = stock.UNITS[i['unit']]
            if factor > 1:
                unit.addItem(big, factor)
            pu = i.get('purchaseUnit')
            if pu:
                unit.addItem(f"{pu['name']} ({stock.format_qty(pu['size'], i['unit'])})", pu['size'])
            self.table.setCellWidget(r, 3, unit)
            self.inputs.append((i, spin, unit))
        ly.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Açıklama:"))
        self.note = QLineEdit("İlk sayım")
        row.addWidget(self.note, 1)
        ly.addLayout(row)
        ok = _button("Kaydet")
        ok.clicked.connect(self._save)
        ly.addWidget(ok)

    def _save(self):
        for i, spin, unit in self.inputs:
            if spin.value() >= 0:
                self.counts[i['id']] = int(round(spin.value() * unit.currentData()))
        self.reason = self.note.text().strip() or 'Sayım'
        self.accept()


class TemplateDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hazır stok şablonu")
        self.resize(720, 640)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        view = QTextBrowser()
        html = [f"<p>Menünüzdeki ürün adlarına göre <b>{len(data['ingredients'])} malzeme</b>, "
                f"<b>{len(data['recipes'])} reçete</b> ve <b>{len(data['optionEffects'])} seçenek etkisi</b> eklenecek. "
                "Miktar ve fiyatlar başlangıç içindir; sonra düzenleyebilirsiniz. Reçetesi olan ürünlere dokunulmaz.</p>",
                "<h4>Reçeteler</h4><ul>"]
        html += [f"<li><b>{name}</b>: {', '.join(parts) or '—'}</li>" for name, parts in data['preview']]
        html.append("</ul>")
        if data['options']:
            html.append("<h4>Seçenekler</h4><ul>")
            html += [f"<li><b>{name}</b>: {text}</li>" for name, text in data['options']]
            html.append("</ul>")
        if data['skipped']:
            html.append(f"<p style='color:#64748b'>Şablonda olmayan ürünler (reçeteyi elle girin): "
                        f"{', '.join(data['skipped'])}</p>")
        view.setHtml("".join(html))
        ly.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch()
        cancel = _button("Vazgeç", primary=False)
        cancel.clicked.connect(self.reject)
        ok = _button("Şablonu ekle")
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        ly.addLayout(row)


# =====================================================================
# Reçete (ürün penceresi) ve seçenek etkisi
# =====================================================================

class RecipeEditor(QWidget):
    """Ürün düzenleme penceresindeki "Reçete" sekmesi."""

    def __init__(self, product, price_getter, tax_getter, show_cost, parent=None):
        super().__init__(parent)
        self.product = product or {}
        self.price_getter, self.tax_getter, self.show_cost = price_getter, tax_getter, show_cost
        self.ingredients = {i['id']: i for i in stock.ingredients()}
        ly = QVBoxLayout(self)
        ly.setContentsMargins(16, 16, 16, 16)
        ly.addWidget(_muted("Ürün bar/mutfağa gönderilince bu malzemeler stoktan düşer. Miktar malzemenin biriminde "
                            "(g, ml, adet). \"Yalnızca paket\": bardak, kapak gibi paket siparişte düşenler."))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Malzeme", "Miktar", "Paket", "Maliyet"])
        self.table.horizontalHeaderItem(2).setToolTip("Yalnızca paket siparişte düşer")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 130), (2, 70), (3, 100)):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        ly.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("+ Malzeme")
        add.setObjectName("ghostBtn")
        add.clicked.connect(lambda: self._add_row())
        rem = QPushButton("Kaldır")
        rem.setObjectName("ghostBtn")
        rem.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        ly.addLayout(row)
        self.effects = _muted("")
        ly.addWidget(self.effects)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size: 14px; font-weight: bold; background: transparent;")
        ly.addWidget(self.summary)
        if not self.ingredients:
            ly.addWidget(_muted("Henüz malzeme yok: Stok → Malzemeler sayfasından ekleyin ya da hazır şablonu kullanın."))
        for r in self.product.get('recipe') or []:
            self._add_row(r)
        self._effects_text()
        self.update_summary()

    def _add_row(self, r=None):
        r = r or {}
        row = self.table.rowCount()
        self.table.insertRow(row)
        combo = QComboBox()
        for i in sorted(self.ingredients.values(), key=lambda x: x['name'].lower()):
            combo.addItem(i['name'], i['id'])
        if r.get('ingredientId') and combo.findData(r['ingredientId']) < 0:
            combo.addItem("(silinmiş malzeme)", r['ingredientId'])
        combo.setCurrentIndex(max(0, combo.findData(r.get('ingredientId'))))
        qty = QSpinBox()
        qty.setRange(1, 100_000)
        qty.setValue(r.get('qty', 1))
        qty.setStyleSheet("QSpinBox { padding: 2px 6px; min-height: 30px; max-height: 30px; }")
        take = QCheckBox()
        take.setChecked(r.get('takeawayOnly', False))
        cost = QLabel("")
        combo.currentIndexChanged.connect(self.update_summary)
        qty.valueChanged.connect(self.update_summary)
        take.toggled.connect(self.update_summary)
        cost.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setAlignment(Qt.AlignCenter)
        hl.addWidget(take)
        for c, w in enumerate((combo, qty, holder, cost)):
            self.table.setCellWidget(row, c, w)
        self.update_summary()

    def _remove(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self.update_summary()

    def recipe(self):
        out = []
        for r in range(self.table.rowCount()):
            combo, qty, holder = (self.table.cellWidget(r, c) for c in range(3))
            take = holder.findChild(QCheckBox)
            if combo.currentData():
                out.append({'ingredientId': combo.currentData(), 'qty': qty.value(), 'takeawayOnly': take.isChecked()})
        return out

    def _effects_text(self):
        names = {i: v['name'] for i, v in self.ingredients.items()}
        lines = []
        for gid in self.product.get('optionGroupIds') or []:
            g = database.menu_item('optionGroups', gid) or {}
            for o in g.get('options') or []:
                e = o.get('recipeEffect')
                if e:
                    lines.append(f"{o['name']}: {describe_effect(e, names)}")
        self.effects.setText(("Seçeneklere göre: " + " · ".join(lines)) if lines else
                             "Seçeneklerin reçeteye etkisi Menü → Seçenek Grupları'nda tanımlanır.")

    def update_summary(self, *_):
        total = 0
        for r in range(self.table.rowCount()):
            combo, qty, holder, label = (self.table.cellWidget(r, c) for c in range(4))
            take = holder.findChild(QCheckBox)
            ing = self.ingredients.get(combo.currentData())
            if not ing:
                continue
            qty.setSuffix(f" {ing['unit']}")
            c = stock.cost_of(qty.value(), ing)
            label.setText(format_tl(c) if self.show_cost else "")
            if not take.isChecked():
                total += c
        if not self.show_cost:
            self.summary.setText("")
            return
        price = self.price_getter() or 0
        net = price * 100 // (100 + (self.tax_getter() or 0))
        profit = net - total
        margin = round(profit * 100 / net) if net else 0
        self.summary.setText(f"Maliyet {format_tl(total)} · Satış {format_tl(price)} (KDV hariç {format_tl(net)}) · "
                             f"Kâr {format_tl(profit)} · %{margin}\n"
                             f"(masada satış; paket malzemeleri hariç)")


def describe_effect(e, names):
    parts = []
    for r in e.get('replace') or []:
        parts.append(f"{names.get(r['from'], '?')} → {names.get(r['to'], '?')}")
    if e.get('scale'):
        parts.append(f"reçete ×{str(e['scale']).replace('.', ',')}")
    for a in e.get('add') or []:
        parts.append(f"+{a['qty']} {names.get(a['ingredientId'], '?')}")
    return ", ".join(parts) or "—"


class EffectDialog(QDialog):
    """Seçeneğin reçeteye etkisi: 2 değiştirme, 2 ekleme satırı ve çarpan."""

    def __init__(self, option_name, effect, parent=None):
        super().__init__(parent)
        self.effect = effect
        e = effect or {}
        self.setWindowTitle(f"Reçete etkisi · {option_name}")
        self.setMinimumWidth(560)
        self.setStyleSheet("QDialog { background: white; }")
        ings = stock.ingredients()
        ly = QVBoxLayout(self)
        ly.addWidget(_muted("Bu seçenek seçilince ürünün reçetesi nasıl değişir? Örn. Yulaf sütü: Süt → Yulaf sütü; "
                            "Büyük boy: ×1,5 (adetli malzemeler çarpılmaz); Ekstra shot: +9 g Espresso çekirdeği."))

        def combo(selected):
            c = QComboBox()
            c.addItem("—", None)
            for i in ings:
                c.addItem(i['name'], i['id'])
            c.setCurrentIndex(max(0, c.findData(selected)))
            return c

        f = QFormLayout()
        rep = (e.get('replace') or []) + [{}, {}]
        self.replaces = []
        for k in range(2):
            row = QHBoxLayout()
            a, b = combo(rep[k].get('from')), combo(rep[k].get('to'))
            row.addWidget(a, 1)
            row.addWidget(QLabel("→"))
            row.addWidget(b, 1)
            self.replaces.append((a, b))
            f.addRow("Yerine koy:" if k == 0 else "", row)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.25, 5)
        self.scale.setSingleStep(0.25)
        self.scale.setPrefix("×")
        self.scale.setValue(e.get('scale') or 1)
        f.addRow("Çarpan:", self.scale)
        add = (e.get('add') or []) + [{}, {}]
        self.adds = []
        for k in range(2):
            row = QHBoxLayout()
            c = combo(add[k].get('ingredientId'))
            q = QSpinBox()
            q.setRange(0, 100_000)
            q.setValue(add[k].get('qty', 0))
            row.addWidget(c, 1)
            row.addWidget(q)
            self.adds.append((c, q))
            f.addRow("Ekle:" if k == 0 else "", row)
        ly.addLayout(f)
        ok = _button("Tamam")
        ok.clicked.connect(self._ok)
        ly.addWidget(ok)

    def _ok(self):
        e = {}
        rep = [{'from': a.currentData(), 'to': b.currentData()} for a, b in self.replaces
               if a.currentData() and b.currentData() and a.currentData() != b.currentData()]
        add = [{'ingredientId': c.currentData(), 'qty': q.value()} for c, q in self.adds if c.currentData() and q.value()]
        if rep:
            e['replace'] = rep
        if add:
            e['add'] = add
        if abs(self.scale.value() - 1) > 1e-9:
            e['scale'] = round(self.scale.value(), 2)
        self.effect = e or None
        self.accept()


# =====================================================================
# 8b: Sayım, Alışlar, Tedarikçiler, Zayi
# =====================================================================

CELL_STYLE = "QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit { padding: 2px 6px; min-height: 30px; max-height: 30px; }"


def _cell(widget):
    """Tablo hücresindeki giriş kutusu: satır yüksekliğine sığsın (genel stil daha yüksek)."""
    widget.setStyleSheet(CELL_STYLE)
    return widget


def _table(headers, stretch=0):
    t = QTableWidget(0, len(headers))
    t.verticalHeader().setDefaultSectionSize(44)
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    return t


def _set_row(table, r, cells, key=None):
    for c, v in enumerate(cells):
        item = QTableWidgetItem(str(v))
        if c == 0 and key is not None:
            item.setData(Qt.UserRole, key)
        table.setItem(r, c, item)


def _selected_key(table):
    rows = table.selectionModel().selectedRows()
    return table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None


def _time(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime('%d.%m %H:%M')
    except (TypeError, ValueError):
        return iso or ''


class StockPage(QWidget):
    """Stok: Malzemeler · Sayım · Alışlar · Tedarikçiler"""

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
        self.ingredients = IngredientsPage(user)
        self.count = CountPage(user)
        self.purchases = PurchasesPage(user)
        self.suppliers = SuppliersPage(user)
        for w, t in ((self.ingredients, "Malzemeler"), (self.count, "Sayım"), (self.purchases, "Alışlar"),
                     (self.suppliers, "Tedarikçiler")):
            self.tabs.addTab(w, t)
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        ly.addWidget(self.tabs)

    def refresh(self):
        w = self.tabs.currentWidget()
        if hasattr(w, 'refresh'):
            w.refresh()


class _Page(QWidget):
    def __init__(self, user, title, subtitle, parent=None):
        super().__init__(parent)
        self.user = user
        self.ly = QVBoxLayout(self)
        self.ly.setContentsMargins(28, 12, 28, 20)
        self.ly.setSpacing(10)
        self.head = QHBoxLayout()
        t = QLabel(f"<b style='font-size:18px'>{title}</b><br><span style='color:#64748b'>{subtitle}</span>")
        self.head.addWidget(t, 1)
        self.ly.addLayout(self.head)

    def button(self, text, fn, primary=False):
        b = _button(text, primary=primary)
        b.clicked.connect(fn)
        self.head.addWidget(b, 0, Qt.AlignVCenter)
        return b

    def authorize(self, permission, text):
        from pos_screen import authorize
        approver, _ = authorize(self, self.user, permission, text, need_reason=False)
        return approver

    def run(self, fn, *args, ok=None, **kwargs):
        from cloud.orders import OrderError
        try:
            result = fn(*args, **kwargs)
        except OrderError as e:
            QMessageBox.warning(self, "İşlem yapılamadı", str(e))
            return None
        ctx.request_sync()
        if ok:
            ToastNotification(self.window(), ok, "success")
        self.refresh()
        return result


class CountPage(_Page):
    """Sayım: gruba göre, kısmi; taslak kaydedilir; onaylanınca stok sayılana eşitlenir."""

    def __init__(self, user, parent=None):
        super().__init__(user, "Sayım", "Sayılan miktarı yazın; boş bırakılan malzeme sayılmamış sayılır. "
                         "Taslak kaydedip sonra bitirebilirsiniz.")
        self.group = QComboBox()
        self.group.addItem("Bütün malzemeler", None)
        for k, v in stock.GROUPS.items():
            self.group.addItem(v, k)
        self.group.currentIndexChanged.connect(self._fill)
        self.head.addWidget(self.group)
        self.button("Taslak kaydet", self._draft)
        self.button("Sayımı onayla", self._approve, primary=True)
        self.table = _table(["Malzeme", "Sistemde", "Sayılan", "Birim", "Fark", "Fark tutarı"])
        for c, w in ((2, 140), (3, 150)):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, w)
        self.ly.addWidget(self.table, 1)
        self.total = QLabel("")
        self.total.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.ly.addWidget(self.total)
        self.ly.addWidget(QLabel("<b>Son sayımlar</b>"))
        self.history = _table(["Tarih", "Açıklama", "Sayılan", "Fark tutarı"], stretch=1)
        self.history.setMaximumHeight(170)
        self.ly.addWidget(self.history)
        self.inputs = {}
        self.refresh()

    def refresh(self):
        self.rows = stock.ingredients()
        draft = stock.load_count_draft() or {}
        self.values = {k: v for k, v in (draft.get('counts') or {}).items()}
        self._fill()
        hist = stock.count_history(20)
        self.history.setRowCount(len(hist))
        for r, h in enumerate(hist):
            counted = len(h['lines'])
            diff = sum(l['cost'] for l in h['lines'])
            reason = h['reason'] if not h['initial'] or 'ilk' in h['reason'].lower() else f"{h['reason']} (ilk sayım)"
            _set_row(self.history, r, [_time(h['at']), reason, f"{counted} malzeme",
                                       "— (başlangıç)" if h['initial'] else format_tl(diff, sign=True)])

    def _collect(self):
        for ing_id, (spin, unit) in self.inputs.items():
            if spin.value() >= 0:
                self.values[ing_id] = int(round(spin.value() * unit.currentData()))
            else:
                self.values.pop(ing_id, None)

    def _fill(self, *_):
        if self.inputs:
            self._collect()
        g = self.group.currentData()
        rows = [i for i in self.rows if g is None or i.get('group') == g]
        self.table.setRowCount(0)  # eski giriş kutuları kalksın
        self.table.setRowCount(len(rows))
        self.inputs = {}
        for r, i in enumerate(rows):
            _set_row(self.table, r, [i['name'], stock.format_qty(i['stock'], i['unit'])], key=i['id'])
            spin = QDoubleSpinBox()
            spin.setRange(-1, 10_000_000)
            spin.setDecimals(3)
            spin.setSpecialValueText("—")
            unit = QComboBox()
            unit.addItem(i['unit'], 1)
            big, factor = stock.UNITS[i['unit']]
            if factor > 1:
                unit.addItem(big, factor)
            pu = i.get('purchaseUnit')
            if pu:
                unit.addItem(pu['name'], pu['size'])
            spin.setValue(self.values[i['id']] if i['id'] in self.values else -1)
            spin.valueChanged.connect(self._update)
            unit.currentIndexChanged.connect(self._update)
            self.table.setCellWidget(r, 2, _cell(spin))
            self.table.setCellWidget(r, 3, _cell(unit))
            self.inputs[i['id']] = (spin, unit)
        self._update()

    def _update(self, *_):
        total = 0
        by_id = {i['id']: i for i in self.rows}
        for r in range(self.table.rowCount()):
            ing = by_id[self.table.item(r, 0).data(Qt.UserRole)]
            spin, unit = self.inputs[ing['id']]
            if spin.value() < 0:
                for c in (4, 5):
                    self.table.setItem(r, c, QTableWidgetItem(""))
                continue
            diff = int(round(spin.value() * unit.currentData())) - ing['stock']
            cost = stock.cost_of(abs(diff), ing) * (1 if diff >= 0 else -1)
            total += cost
            d = QTableWidgetItem(("+" if diff > 0 else "") + stock.format_qty(diff, ing['unit']) + (" ⚠" if diff < 0 else ""))
            if diff < 0:
                d.setForeground(QColor('#B91C1C'))
            self.table.setItem(r, 4, d)
            self.table.setItem(r, 5, QTableWidgetItem(format_tl(cost, sign=True)))
        self.total.setText(f"Görünen satırlardaki toplam fark: {format_tl(total, sign=True)}")

    def _draft(self):
        self._collect()
        stock.save_count_draft(self.values, 'Sayım')
        ToastNotification(self.window(), "Sayım taslağı kaydedildi.", "success")

    def _approve(self):
        self._collect()
        if not self.values:
            QMessageBox.information(self, "Sayım", "Hiçbir malzemeye sayılan miktar girilmedi.")
            return
        initial = not stock.count_history(1)
        approver = self.authorize('stock', "Sayım onayı")
        if not approver:
            return
        changed = self.run(stock.set_counts, self.user, dict(self.values), "İlk sayım" if initial else "Sayım",
                           approver, initial)
        if changed is not None:
            stock.clear_count_draft()
            self.values = {}
            self.refresh()
            ToastNotification(self.window(), f"Sayım kaydedildi; {len(changed)} malzemede fark var.", "success")


class SuppliersPage(_Page):
    def __init__(self, user, parent=None):
        super().__init__(user, "Tedarikçiler", "Borç bakiyesi: \"ödenecek\" teslimler eklenir, ödemelerle düşer.")
        self.button("+ Tedarikçi", lambda: self._edit(None), primary=True)
        self.button("Ödeme yap", self._pay)
        self.table = _table(["Tedarikçi", "Yetkili", "Telefon", "Borç"])
        self.table.doubleClicked.connect(lambda _: self._edit(self._current()))
        self.table.itemSelectionChanged.connect(self._statement)
        self.ly.addWidget(self.table, 1)
        self.ly.addWidget(QLabel("<b>Hareketler (bu bilgisayar)</b>"))
        self.moves = _table(["Tarih", "Tür", "Tutar", "Ödeme", "Not"], stretch=4)
        self.moves.setMaximumHeight(220)
        self.ly.addWidget(self.moves)
        self.refresh()

    def refresh(self):
        self.rows = stock.suppliers()
        self.table.setRowCount(len(self.rows))
        for r, s in enumerate(self.rows):
            _set_row(self.table, r, [s['name'], s.get('contactName', ''), s.get('phone', ''),
                                     format_tl(s['balance']) if s['balance'] else '—'], key=s['id'])
        self._statement()

    def _current(self):
        key = _selected_key(self.table)
        return next((s for s in self.rows if s['id'] == key), None)

    def _statement(self):
        s = self._current()
        rows = stock.supplier_statement(s['id']) if s else []
        self.moves.setRowCount(len(rows))
        for r, m in enumerate(rows):
            kind = "Teslim" if m['kind'] == 'receipt' else "Ödeme"
            pay = "Ödenecek" if m['payment_status'] == 'unpaid' else stock.PAY_METHODS.get(m['method'], '')
            _set_row(self.moves, r, [_time(m['at']), kind, format_tl(m['total']), pay, m.get('note') or ''])

    def _edit(self, supplier):
        dlg = SupplierDialog(supplier, self)
        if dlg.exec() == QDialog.Accepted:
            sid = (supplier or {}).get('id')
            cloud_action(self, lambda api: api.save_supplier(dlg.values, sid), "Tedarikçi kaydedildi.",
                         lambda _: self.refresh())

    def _pay(self):
        s = self._current()
        if not s:
            QMessageBox.information(self, "Tedarikçi seçin", "Önce listeden bir tedarikçi seçin.")
            return
        dlg = PayDialog(s, self)
        if dlg.exec() != QDialog.Accepted:
            return
        approver = self.authorize('stock', f"{s['name']} ödemesi")
        if approver:
            self.run(stock.pay_supplier, self.user, s['id'], dlg.amount, dlg.method, dlg.note, approver,
                     ok=f"{s['name']}: {format_tl(dlg.amount)} ödendi.")


class SupplierDialog(QDialog):
    def __init__(self, supplier=None, parent=None):
        super().__init__(parent)
        s = supplier or {}
        self.setWindowTitle(s.get('name') or "Yeni tedarikçi")
        self.setMinimumWidth(440)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        f = QFormLayout()
        self.fields = {}
        for key, label, mx in (('name', "Ad", 60), ('contactName', "Yetkili", 60), ('phone', "Telefon", 20),
                               ('email', "E-posta", 80), ('note', "Not", 200)):
            e = QLineEdit(s.get(key, ''))
            e.setMaxLength(mx)
            self.fields[key] = e
            f.addRow(f"{label}:", e)
        ly.addLayout(f)
        ok = _button("Kaydet")
        ok.clicked.connect(self._ok)
        ly.addWidget(ok)

    def _ok(self):
        if not self.fields['name'].text().strip():
            return
        self.values = {k: e.text().strip() for k, e in self.fields.items()}
        self.accept()


class PayDialog(QDialog):
    def __init__(self, supplier, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Ödeme · {supplier['name']}")
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        ly.addWidget(QLabel(f"Borç bakiyesi: <b>{format_tl(supplier['balance'])}</b>"))
        f = QFormLayout()
        self.amount_edit = QLineEdit(format_tl(max(supplier['balance'], 0)).replace(' ₺', ''))
        self.method_box = QComboBox()
        for k, v in stock.PAY_METHODS.items():
            self.method_box.addItem(v, k)
        self.note_edit = QLineEdit()
        f.addRow("Tutar:", self.amount_edit)
        f.addRow("Yöntem:", self.method_box)
        f.addRow("Not:", self.note_edit)
        ly.addLayout(f)
        ly.addWidget(_muted("Masraflar'a yazılır. Nakitse ve kasa açıksa kasadan çıkış olarak da düşer."))
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {COLORS['danger']};")
        ly.addWidget(self.warn)
        ok = _button("Öde")
        ok.clicked.connect(self._ok)
        ly.addWidget(ok)

    def _ok(self):
        try:
            self.amount = parse_tl(self.amount_edit.text())
        except ValueError as e:
            self.warn.setText(str(e))
            return
        if self.amount <= 0:
            self.warn.setText("Tutar girin.")
            return
        self.method, self.note = self.method_box.currentData(), self.note_edit.text().strip()
        self.accept()


class PurchasesPage(_Page):
    def __init__(self, user, parent=None):
        super().__init__(user, "Alışlar", "Sipariş taslağı bulutta tutulur (internet gerekir); teslim alma internetsiz yapılır.")
        self.button("+ Sipariş", lambda: self._edit(None), primary=True)
        self.button("Siparişsiz alış gir", self._direct)
        self.table = _table(["No", "Tedarikçi", "Durum", "Tutar", "Tarih"], stretch=1)
        self.table.doubleClicked.connect(lambda _: self._edit(self._current()))
        self.ly.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn in (("Düzenle", lambda: self._edit(self._current())), ("Metni kopyala", self._copy),
                         ("PDF", self._pdf), ("Gönderildi işaretle", self._mark_sent), ("Teslim al", self._receive),
                         ("İptal et", self._cancel)):
            b = _button(text, primary=text == "Teslim al")
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        self.ly.addLayout(row)
        self.refresh()

    def refresh(self):
        self.orders = stock.purchase_orders()
        names = {s['id']: s['name'] for s in stock.suppliers(include_deleted=True)}
        self.table.setRowCount(len(self.orders))
        for r, o in enumerate(self.orders):
            _set_row(self.table, r, [f"#{o.get('no', '')}", names.get(o['supplierId'], '?'),
                                     stock.PO_STATUS.get(o.get('status'), o.get('status')), format_tl(o.get('total', 0)),
                                     _time(str(o.get('receivedAt') or o.get('createdAt') or ''))], key=o['id'])

    def _current(self):
        key = _selected_key(self.table)
        return next((o for o in self.orders if o['id'] == key), None)

    def _edit(self, order):
        if order and order.get('status') not in ('draft', 'sent'):
            QMessageBox.information(self, "Sipariş", "Teslim alınmış ya da iptal edilmiş sipariş değiştirilemez.")
            return
        if not stock.suppliers():
            QMessageBox.information(self, "Tedarikçi yok", "Önce Tedarikçiler sekmesinden tedarikçi ekleyin.")
            return
        dlg = OrderDialog(order, self)
        if dlg.exec() == QDialog.Accepted:
            oid = (order or {}).get('id')
            cloud_action(self, lambda api: api.save_purchase_order(dlg.values, oid), "Sipariş kaydedildi.",
                         lambda _: self.refresh())

    def _copy(self):
        o = self._current()
        if o:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(stock.order_text(o, database.general_settings()['cafeName']))
            ToastNotification(self.window(), "Sipariş metni kopyalandı (WhatsApp / e-posta).", "success")

    def _pdf(self):
        o = self._current()
        if not o:
            return
        import printing
        from reports_screen import table_html
        ings = {i['id']: i for i in stock.ingredients(include_deleted=True)}
        rows = [[ings.get(l['ingredientId'], {}).get('name', '?'),
                 stock.format_qty(l['qty'], ings.get(l['ingredientId'], {}).get('unit', 'adet')), format_tl(l['amount'])]
                for l in o['lines']]
        name = next((s['name'] for s in stock.suppliers(include_deleted=True) if s['id'] == o['supplierId']), '')
        title = f"Sipariş #{o.get('no')} · {name}"
        kind, where = printing.print_html(table_html(database.general_settings()['cafeName'], title,
                                                     ["Malzeme", "Miktar", "Tutar"], rows), title)
        ToastNotification(self.window(), "Yazıcıya gönderildi." if kind == 'printer' else f"PDF: {where}", "info")

    def _mark_sent(self):
        o = self._current()
        if o and o.get('status') == 'draft':
            data = {'supplierId': o['supplierId'], 'status': 'sent', 'lines': o['lines'], 'note': o.get('note', '')}
            cloud_action(self, lambda api: api.save_purchase_order(data, o['id']), "Gönderildi olarak işaretlendi.",
                         lambda _: self.refresh())

    def _cancel(self):
        o = self._current()
        if o and QMessageBox.question(self, "Sipariş iptali", f"#{o.get('no')} iptal edilsin mi?",
                                      QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            cloud_action(self, lambda api: api.cancel_purchase_order(o['id']), "Sipariş iptal edildi.",
                         lambda _: self.refresh())

    def _receive(self, order=None):
        o = order or self._current()
        if not o or o.get('status') not in ('draft', 'sent', 'partial'):
            QMessageBox.information(self, "Teslim al", "Teslim alınacak bir sipariş seçin.")
            return
        lines = [{**l, 'qty': max(l['qty'] - l.get('received', 0), 0)} for l in o['lines']]
        lines = [{**l, 'amount': l['amount'] * l['qty'] // max(1, next(x['qty'] for x in o['lines']
                                                                     if x['ingredientId'] == l['ingredientId']))}
                 for l in lines]
        self._do_receive(o['supplierId'], lines, o['id'])

    def _direct(self):
        sups = stock.suppliers()
        if not sups:
            QMessageBox.information(self, "Tedarikçi yok", "Önce Tedarikçiler sekmesinden tedarikçi ekleyin.")
            return
        self._do_receive(None, [], None)

    def _do_receive(self, supplier_id, lines, order_id):
        dlg = ReceiveDialog(supplier_id, lines, self)
        if dlg.exec() != QDialog.Accepted:
            return
        approver = self.authorize('stock', "Teslim alma")
        if approver:
            self.run(stock.receive, self.user, dlg.supplier_id, dlg.lines, dlg.payment, order_id, dlg.note, approver,
                     ok=f"Teslim alındı: {format_tl(sum(l['amount'] for l in dlg.lines))}")


class _LinesEditor(QWidget):
    """Malzeme · miktar (birim seçilir) · tutar satırları. lines(): temel birim + kuruş."""

    def __init__(self, lines, parent=None):
        super().__init__(parent)
        self.ings = {i['id']: i for i in stock.ingredients()}
        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Malzeme", "Miktar", "Birim", "Tutar (₺)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 120), (2, 170), (3, 130)):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        ly.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("+ Satır")
        add.setObjectName("ghostBtn")
        add.clicked.connect(lambda: self.add())
        rem = QPushButton("Kaldır")
        rem.setObjectName("ghostBtn")
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        self.total = QLabel("")
        self.total.setStyleSheet("font-weight: bold;")
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        row.addWidget(self.total)
        ly.addLayout(row)
        for l in lines:
            self.add(l)

    def add(self, line=None):
        l = line or {}
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        for i in sorted(self.ings.values(), key=lambda x: x['name'].lower()):
            combo.addItem(i['name'], i['id'])
        combo.setCurrentIndex(max(0, combo.findData(l.get('ingredientId'))))
        qty = QDoubleSpinBox()
        qty.setRange(0, 10_000_000)
        qty.setDecimals(3)
        unit = QComboBox()
        amount = QLineEdit(format_tl(l.get('amount', 0)).replace(' ₺', ''))

        def units():
            ing = self.ings.get(combo.currentData())
            unit.blockSignals(True)
            unit.clear()
            if ing:
                pu = ing.get('purchaseUnit')
                if pu:
                    unit.addItem(f"{pu['name']} ({stock.format_qty(pu['size'], ing['unit'])})", pu['size'])
                big, factor = stock.UNITS[ing['unit']]
                if factor > 1:
                    unit.addItem(big, factor)
                unit.addItem(ing['unit'], 1)
            unit.blockSignals(False)

        units()
        if l.get('qty'):
            size = unit.itemData(0) or 1
            if l['qty'] % size:
                unit.setCurrentIndex(unit.count() - 1)
                size = 1
            qty.setValue(l['qty'] / size)
        combo.currentIndexChanged.connect(lambda _: (units(), self._total()))
        for w in (qty,):
            w.valueChanged.connect(self._total)
        amount.textChanged.connect(self._total)
        for c, w in enumerate((combo, qty, unit, amount)):
            self.table.setCellWidget(r, c, _cell(w))
        self._total()

    def lines(self):
        out = []
        for r in range(self.table.rowCount()):
            combo, qty, unit, amount = (self.table.cellWidget(r, c) for c in range(4))
            if not combo.currentData() or qty.value() <= 0:
                continue
            try:
                amt = parse_tl(amount.text() or '0')
            except ValueError:
                amt = 0
            out.append({'ingredientId': combo.currentData(), 'qty': int(round(qty.value() * (unit.currentData() or 1))),
                        'amount': amt})
        return out

    def _total(self, *_):
        self.total.setText(f"Toplam {format_tl(sum(l['amount'] for l in self.lines()))}")


class OrderDialog(QDialog):
    def __init__(self, order=None, parent=None):
        super().__init__(parent)
        o = order or {}
        self.setWindowTitle(f"Sipariş #{o['no']}" if order else "Yeni sipariş")
        self.resize(760, 560)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Tedarikçi:"))
        self.supplier = QComboBox()
        for s in stock.suppliers():
            self.supplier.addItem(s['name'], s['id'])
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(o.get('supplierId'))))
        top.addWidget(self.supplier, 1)
        suggest = _button("Kritik malzemeleri ekle", primary=False)
        suggest.clicked.connect(self._suggest)
        top.addWidget(suggest)
        ly.addLayout(top)
        self.editor = _LinesEditor(o.get('lines') or [])
        ly.addWidget(self.editor, 1)
        self.note = QLineEdit(o.get('note', ''))
        self.note.setPlaceholderText("Not (teslim günü vb.)")
        ly.addWidget(self.note)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {COLORS['danger']};")
        ly.addWidget(self.warn)
        ok = _button("Kaydet")
        ok.clicked.connect(self._ok)
        ly.addWidget(ok)
        self.status = o.get('status', 'draft')

    def _suggest(self):
        lines = stock.suggest_order(self.supplier.currentData())
        if not lines:
            self.warn.setText("Bu tedarikçinin kritik seviyede malzemesi yok (malzemede tedarikçi seçili olmalı).")
        for l in lines:
            self.editor.add(l)

    def _ok(self):
        lines = self.editor.lines()
        if not lines:
            self.warn.setText("En az bir satır girin.")
            return
        self.values = {'supplierId': self.supplier.currentData(), 'status': self.status, 'lines': lines,
                       'note': self.note.text().strip()}
        self.accept()


class ReceiveDialog(QDialog):
    def __init__(self, supplier_id, lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Teslim al")
        self.resize(760, 600)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Tedarikçi:"))
        self.supplier = QComboBox()
        for s in stock.suppliers():
            self.supplier.addItem(s['name'], s['id'])
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(supplier_id)))
        self.supplier.setEnabled(supplier_id is None)
        top.addWidget(self.supplier, 1)
        ly.addLayout(top)
        ly.addWidget(_muted("Gelen miktarı ve faturadaki tutarı yazın (eksik geldiyse düzeltin). Stok artar, birim "
                            "maliyet ağırlıklı ortalamayla güncellenir."))
        self.editor = _LinesEditor(lines)
        ly.addWidget(self.editor, 1)
        pay = QHBoxLayout()
        self.paid = QRadioButton("Ödendi")
        self.unpaid = QRadioButton("Ödenecek (borç)")
        self.paid.setChecked(True)
        self.method = QComboBox()
        for k, v in stock.PAY_METHODS.items():
            self.method.addItem(v, k)
        self.paid.toggled.connect(self.method.setEnabled)
        for w in (self.paid, self.method, self.unpaid):
            pay.addWidget(w)
        pay.addStretch()
        ly.addLayout(pay)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Fatura / irsaliye no")
        ly.addWidget(self.note_edit)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {COLORS['danger']};")
        ly.addWidget(self.warn)
        ok = _button("Teslim al")
        ok.clicked.connect(self._ok)
        ly.addWidget(ok)

    def _ok(self):
        self.lines = self.editor.lines()
        if not self.lines:
            self.warn.setText("Teslim alınan malzeme yok.")
            return
        self.supplier_id = self.supplier.currentData()
        self.payment = ({'status': 'paid', 'method': self.method.currentData()} if self.paid.isChecked()
                        else {'status': 'unpaid'})
        self.note = self.note_edit.text().strip()
        self.accept()


class WastePage(_Page):
    """Zayi: ürün (reçetesi stoktan düşer) ya da malzeme; gerekçe zorunlu. Eski kayıtlar da listelenir."""

    def __init__(self, user, parent=None):
        super().__init__(user, "Zayi", "Bozulan, düşen, yanlış hazırlanan ürün ve malzemeler. Maliyet reçeteden "
                         "hesaplanır; stok modülü açıksa stoktan düşer.")
        self.button("+ Ürün zayisi", lambda: self._add('product'), primary=True)
        self.button("+ Malzeme zayisi", lambda: self._add('ingredient'))
        self.period = QComboBox()
        for key, label in (('today', 'Bugün'), ('week', 'Bu hafta'), ('month', 'Bu ay'), ('last_month', 'Geçen ay')):
            self.period.addItem(label, key)
        self.period.currentIndexChanged.connect(self.refresh)
        self.head.addWidget(self.period)
        self.table = _table(["Tarih", "Ne", "Miktar", "Gerekçe", "Maliyet", "Giren"], stretch=1)
        self.ly.addWidget(self.table, 1)
        self.total = QLabel("")
        self.total.setStyleSheet("font-weight: bold;")
        self.ly.addWidget(self.total)
        self.refresh()

    def refresh(self):
        import reports
        a, b = reports.period(self.period.currentData())
        rows = stock.waste_entries(a, b)
        self.table.setRowCount(len(rows))
        for r, w in enumerate(rows):
            st = database.get_staff(w.get('staff_id')) if w.get('staff_id') else None
            qty = stock.format_qty(w['qty'] or 0, w.get('unit') or 'adet')
            _set_row(self.table, r, [_time(w['at']), w['name'], qty, w['reason'], format_tl(w['cost'] or 0),
                                     st['name'] if st else ''])
        self.total.setText(f"{len(rows)} kayıt · toplam {format_tl(sum(w['cost'] or 0 for w in rows))}")

    def _add(self, kind):
        dlg = WasteDialog(kind, self)
        if dlg.exec() != QDialog.Accepted:
            return
        approver = self.authorize('waste', "Zayi girişi")
        if not approver:
            return
        record_waste(self, self.user, dlg, approver)
        self.refresh()


class WasteDialog(QDialog):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle("Ürün zayisi" if kind == 'product' else "Malzeme zayisi")
        self.setMinimumWidth(480)
        self.setStyleSheet("QDialog { background: white; }")
        ly = QVBoxLayout(self)
        f = QFormLayout()
        self.item = QComboBox()
        if kind == 'product':
            for p in database.menu_products():
                self.item.addItem(p['name'], p['id'])
        else:
            self.ings = {i['id']: i for i in stock.ingredients()}
            for i in self.ings.values():
                self.item.addItem(i['name'], i['id'])
        self.qty = QSpinBox()
        self.qty.setRange(1, 1_000_000)
        self.reason = QComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(stock.WASTE_REASONS)
        self.cost_edit = QLineEdit()
        self.cost_edit.setPlaceholderText("Reçetesi yoksa birim maliyet (₺)")
        self.info = _muted("")
        f.addRow("Ürün:" if kind == 'product' else "Malzeme:", self.item)
        f.addRow("Miktar:", self.qty)
        f.addRow("Gerekçe:", self.reason)
        if kind == 'product':
            f.addRow("Maliyet:", self.cost_edit)
        ly.addLayout(f)
        ly.addWidget(self.info)
        ok = _button("Kaydet")
        ok.clicked.connect(self._ok)
        ly.addWidget(ok)
        self.item.currentIndexChanged.connect(self._update)
        self.qty.valueChanged.connect(self._update)
        self._update()

    def _update(self, *_):
        if self.kind == 'ingredient':
            ing = self.ings.get(self.item.currentData())
            if ing:
                self.qty.setSuffix(f" {ing['unit']}")
                self.info.setText(f"Maliyet: {format_tl(stock.cost_of(self.qty.value(), ing))}")
            return
        rec = stock.Recipes()
        pid = self.item.currentData()
        has = rec.has_recipe(pid) and stock.enabled()
        self.cost_edit.setVisible(not has)
        self.info.setText(f"Reçeteden maliyet: {format_tl(rec.cost(rec.consumption(pid, (), self.qty.value())))}; "
                          "malzemeler stoktan düşer." if has else "Bu ürünün reçetesi yok: maliyeti elle girin.")

    def _ok(self):
        self.ref_id, self.qty_value = self.item.currentData(), self.qty.value()
        self.reason_text = self.reason.currentText().strip()
        self.manual_cost = None
        if self.kind == 'product' and self.cost_edit.isVisible() and self.cost_edit.text().strip():
            try:
                self.manual_cost = parse_tl(self.cost_edit.text()) * self.qty_value
            except ValueError:
                return
        if not self.ref_id or not self.reason_text:
            return
        self.accept()


def record_waste(parent, user, dlg, approver):
    """WasteDialog sonucunu kaydeder (yönetim paneli ve garson/barista paneli ortak)."""
    from cloud.orders import OrderError
    try:
        if dlg.kind == 'product':
            cost = stock.waste_product(user, dlg.ref_id, dlg.qty_value, dlg.reason_text, approver, dlg.manual_cost)
        else:
            cost = stock.waste_ingredient(user, dlg.ref_id, dlg.qty_value, dlg.reason_text, approver)
    except OrderError as e:
        QMessageBox.warning(parent, "İşlem yapılamadı", str(e))
        return False
    ctx.request_sync()
    ToastNotification(parent.window(), f"Zayi kaydedildi ({format_tl(cost)}).", "success")
    return True
