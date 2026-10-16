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
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextBrowser, QVBoxLayout, QWidget
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
        changed = stock.set_counts(self.user, dlg.counts, dlg.reason, approver)
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
        self.supplier = QLineEdit(i.get('supplierName', ''))
        self.supplier.setMaxLength(60)
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
                       'supplierName': self.supplier.text().strip()}
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
        self.table.setHorizontalHeaderLabels(["Malzeme", "Miktar", "Yalnızca paket", "Maliyet"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
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
        take = QCheckBox()
        take.setChecked(r.get('takeawayOnly', False))
        cost = QLabel("")
        combo.currentIndexChanged.connect(self.update_summary)
        qty.valueChanged.connect(self.update_summary)
        take.toggled.connect(self.update_summary)
        for c, w in enumerate((combo, qty, take, cost)):
            self.table.setCellWidget(row, c, w)
        self.update_summary()

    def _remove(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self.update_summary()

    def recipe(self):
        out = []
        for r in range(self.table.rowCount()):
            combo, qty, take = (self.table.cellWidget(r, c) for c in range(3))
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
            combo, qty, take, label = (self.table.cellWidget(r, c) for c in range(4))
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
                             f"Kâr {format_tl(profit)} · %{margin}  (masada; paket malzemeleri hariç)")


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
