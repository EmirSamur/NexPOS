"""
NexPOS - Salon ve Masa Planı (3. ekran)

- FloorPlanPage: yönetim panelindeki sürükle-bırak plan editörü (bölgeler, masalar, dekor, QR)
- FloorStatusView: garson ekranındaki salt okunur plan; masalar durum renkleriyle görünür

Plan, ekrandan bağımsız 1200 × 800 birimlik sanal bir tuvalde tutulur ve görünüme sığdırılır.
"""
import re
import uuid
from datetime import datetime

import shiboken6
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QGraphicsScene, QGraphicsView,
    QGraphicsObject, QGraphicsItem, QTabBar, QLineEdit, QSpinBox, QCheckBox, QRadioButton, QButtonGroup,
    QMessageBox, QInputDialog, QFileDialog, QMenu, QFormLayout, QDialog, QStackedWidget
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QPen, QBrush, QFont, QFontMetrics, QPainter, QPainterPath
from styles import COLORS, FONTS, ICONS
from widgets import PageHeader, ToastNotification
from admin_access_pages import _button, cloud_action
from cloud.context import ctx
from cloud.qt_sync import run_async
from qr_print import default_base_url, write_qr_pdf
import database

CANVAS_W, CANVAS_H = 1200, 800
GRID = 20
TABLE_DEFAULTS = {  # şekil → (genişlik, yükseklik, kişi)
    'round': (100, 100, 2),
    'square': (120, 120, 4),
    'rect': (200, 120, 6),
}
FIXTURE_DEFAULTS = {  # tür → (genişlik, yükseklik, etiket)
    'wall': (300, 20, ''),
    'bar': (320, 70, 'Bar Tezgâhı'),
    'door': (100, 30, 'Giriş'),
    'plant': (60, 60, ''),
}
FIXTURE_NAMES = {'wall': 'Duvar', 'bar': 'Bar tezgâhı', 'door': 'Kapı', 'plant': 'Bitki'}
STATUS_STYLE = {  # yerel durum → (dolgu, kenar, yazı)
    'bos': ('#FFFFFF', '#CBD5E1', '#334155'),
    'dolu': ('#FEE2E2', '#EF4444', '#991B1B'),
    'rezerve': ('#DBEAFE', '#3B82F6', '#1E40AF'),
    'hesap': ('#FFEDD5', '#F97316', '#9A3412'),
}


def snap(value, enabled=True):
    return int(round(value / GRID) * GRID) if enabled else int(round(value))


def elapsed_text(started):
    """'2026-10-14 13:05' → '1s 05dk'"""
    try:
        minutes = int((datetime.now() - datetime.strptime(started, "%Y-%m-%d %H:%M")).total_seconds() // 60)
    except (TypeError, ValueError):
        return ''
    return f"{minutes // 60}s {minutes % 60:02d}dk" if minutes >= 60 else f"{max(minutes, 0)} dk"


# =====================================================================
# Plan öğeleri
# =====================================================================

class PlanItem(QGraphicsObject):
    """Masa ya da dekor öğesi. data: x, y, w, h, rotation (+ masa: name, shape, capacity)."""
    HANDLE = 14
    changed = Signal()
    clicked = Signal(object)
    context = Signal(object, object)  # (öğe, ekran konumu)

    def __init__(self, data, is_table, editable, status=None):
        super().__init__()
        self.info = dict(data)
        self.is_table = is_table
        self.editable = editable
        self.status = status or {}
        self.snap_enabled = True
        self._resizing = False
        self.setPos(self.info['x'], self.info['y'])
        self.setZValue(2 if is_table else 1)
        if editable:
            self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                          QGraphicsItem.ItemSendsGeometryChanges)
        else:
            self.setCursor(Qt.PointingHandCursor if is_table else Qt.ArrowCursor)
            self.setAcceptHoverEvents(is_table)

    # 90° döndürme görüntüde genişlik/yüksekliği yer değiştirir
    def size(self):
        w, h = self.info['w'], self.info['h']
        return (h, w) if self.info.get('rotation') == 90 else (w, h)

    def boundingRect(self):
        w, h = self.size()
        return QRectF(-2, -2, w + 4 + self.HANDLE / 2, h + 4 + self.HANDLE / 2)

    def shape(self):
        p = QPainterPath()
        w, h = self.size()
        p.addRect(QRectF(0, 0, w, h))
        if self.editable and self.isSelected():
            p.addRect(self._handle_rect())
        return p

    def _handle_rect(self):
        w, h = self.size()
        return QRectF(w - self.HANDLE / 2, h - self.HANDLE / 2, self.HANDLE, self.HANDLE)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.size()
        rect = QRectF(0, 0, w, h)
        selected = self.isSelected()
        if self.is_table:
            self._paint_table(painter, rect, selected)
        else:
            self._paint_fixture(painter, rect, selected)
        if self.editable and selected:
            painter.setPen(QPen(QColor(COLORS['primary']), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(-1, -1, 1, 1))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS['primary']))
            painter.drawRect(self._handle_rect())

    def _paint_table(self, painter, rect, selected):
        state = (self.status.get('durum') or 'bos') if not self.editable else 'bos'
        fill, border, text = STATUS_STYLE.get(state, STATUS_STYLE['bos'])
        if self.editable:
            fill, border, text = '#FFFFFF', '#94A3B8', '#0F172A'
        painter.setPen(QPen(QColor(border), 3))
        painter.setBrush(QColor(fill))
        shape = self.info.get('shape', 'square')
        if shape == 'round':
            painter.drawEllipse(rect.adjusted(2, 2, -2, -2))
        else:
            radius = 10 if shape == 'square' else 14
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius, radius)
        # Ad
        f = QFont(FONTS['family'])
        f.setBold(True)
        f.setPixelSize(max(12, int(min(rect.width(), rect.height()) * 0.2)))
        painter.setFont(f)
        painter.setPen(QColor(text))
        top = QRectF(rect.x(), rect.y() + rect.height() * 0.14, rect.width(), rect.height() * 0.42)
        painter.drawText(top, Qt.AlignCenter, self.info.get('name', ''))
        # Alt satır: editörde kişi sayısı, garsonda durum
        f.setBold(False)
        f.setPixelSize(max(10, int(min(rect.width(), rect.height()) * 0.13)))
        painter.setFont(f)
        if self.editable:
            sub = f"👤 {self.info.get('capacity', 0)}"
        elif state in ('dolu', 'hesap'):
            total = self.status.get('toplam_tutar')
            sub = elapsed_text(self.status.get('siparis_tarihi'))
            if total:
                sub = f"{total:,.0f} ₺ · {sub}".replace(',', '.')
        elif state == 'rezerve':
            sub = "rezerve"
        else:
            sub = f"👤 {self.info.get('capacity', 0)}"
        if not self.editable and self.status.get('ready'):
            sub = f"🔔 {sub}"  # mutfakta/barda hazır ürün var
        bottom = QRectF(rect.x() + 6, rect.y() + rect.height() * 0.52, rect.width() - 12, rect.height() * 0.36)
        # Yuvarlak/küçük masada "tutar · süre" sığmazsa iki satıra bölünür
        usable = bottom.width() * (0.75 if shape == 'round' else 1.0)
        if ' · ' in sub and QFontMetrics(f).horizontalAdvance(sub) > usable:
            sub = sub.replace(' · ', '\n')
        painter.drawText(bottom, Qt.AlignCenter, sub)

    def _paint_fixture(self, painter, rect, selected):
        kind = self.info.get('kind')
        if kind == 'wall':
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#475569'))
            painter.drawRect(rect)
        elif kind == 'bar':
            painter.setPen(QPen(QColor('#5D4037'), 2))
            painter.setBrush(QColor('#A1887F'))
            painter.drawRoundedRect(rect, 8, 8)
        elif kind == 'door':
            painter.setPen(QPen(QColor('#64748B'), 2, Qt.DashLine))
            painter.setBrush(QColor('#F1F5F9'))
            painter.drawRect(rect)
        elif kind == 'plant':
            painter.setPen(QPen(QColor('#15803D'), 2))
            painter.setBrush(QColor('#86EFAC'))
            painter.drawEllipse(rect.adjusted(2, 2, -2, -2))
        label = self.info.get('label') or ('🪴' if kind == 'plant' else '')
        if label:
            f = QFont(FONTS['family'])
            f.setBold(True)
            f.setPixelSize(max(11, min(18, int(min(rect.width(), rect.height()) * 0.35))))
            painter.setFont(f)
            painter.setPen(QColor('white' if kind == 'bar' else '#334155'))
            painter.drawText(rect, Qt.AlignCenter, label)

    # ---------------------------------------------------------- etkileşim
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            w, h = self.size()
            x = min(max(snap(value.x(), self.snap_enabled), 0), CANVAS_W - w)
            y = min(max(snap(value.y(), self.snap_enabled), 0), CANVAS_H - h)
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.info['x'], self.info['y'] = int(self.pos().x()), int(self.pos().y())
            self.changed.emit()
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        if self.editable and self.isSelected() and self._handle_rect().contains(e.pos()):
            self._resizing = True
            e.accept()
            return
        if e.button() == Qt.RightButton and not self.editable:
            self.context.emit(self, e.screenPos())
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resizing:
            minimum = 40 if self.is_table else 10
            w = min(max(snap(e.pos().x(), self.snap_enabled), minimum), min(400 if self.is_table else CANVAS_W, CANVAS_W - self.pos().x()))
            h = min(max(snap(e.pos().y(), self.snap_enabled), minimum), min(400 if self.is_table else CANVAS_H, CANVAS_H - self.pos().y()))
            self.prepareGeometryChange()
            if self.info.get('rotation') == 90:
                self.info['w'], self.info['h'] = int(h), int(w)
            else:
                self.info['w'], self.info['h'] = int(w), int(h)
            self.update()
            self.changed.emit()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resizing:
            self._resizing = False
            return
        if not self.editable and e.button() == Qt.LeftButton and self.is_table:
            self.clicked.emit(self)
        super().mouseReleaseEvent(e)

    def rotate(self):
        self.prepareGeometryChange()
        self.info['rotation'] = 0 if self.info.get('rotation') == 90 else 90
        w, h = self.size()
        self.setPos(min(self.pos().x(), CANVAS_W - w), min(self.pos().y(), CANVAS_H - h))
        self.update()
        self.changed.emit()

    def set_field(self, key, value):
        self.prepareGeometryChange()
        self.info[key] = value
        self.update()
        self.changed.emit()


class FloorScene(QGraphicsScene):
    def __init__(self, editable):
        super().__init__(0, 0, CANVAS_W, CANVAS_H)
        self.editable = editable

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor(COLORS['bg_main']))
        painter.fillRect(QRectF(0, 0, CANVAS_W, CANVAS_H), QColor('#FFFFFF' if self.editable else '#FAFAF9'))
        if self.editable:
            painter.setPen(QPen(QColor('#E2E8F0'), 1))
            for x in range(0, CANVAS_W + 1, GRID * 2):
                painter.drawLine(x, 0, x, CANVAS_H)
            for y in range(0, CANVAS_H + 1, GRID * 2):
                painter.drawLine(0, y, CANVAS_W, y)
        painter.setPen(QPen(QColor('#CBD5E1'), 2))
        painter.drawRect(QRectF(0, 0, CANVAS_W, CANVAS_H))


class FloorView(QGraphicsView):
    delete_pressed = Signal()
    duplicate_pressed = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def fit(self):
        self.fitInView(QRectF(-10, -10, CANVAS_W + 20, CANVAS_H + 20), Qt.KeepAspectRatio)

    def keyPressEvent(self, e):
        items = self.scene().selectedItems()
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and items:
            self.delete_pressed.emit()
            return
        if e.key() == Qt.Key_D and e.modifiers() & Qt.ControlModifier and items:
            self.duplicate_pressed.emit()
            return
        step = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(e.key())
        if step and items:
            amount = 1 if e.modifiers() & Qt.ShiftModifier else GRID
            for it in items:
                old = it.snap_enabled
                it.snap_enabled = False
                it.setPos(it.pos().x() + step[0] * amount, it.pos().y() + step[1] * amount)
                it.snap_enabled = old
            return
        super().keyPressEvent(e)


# =====================================================================
# Yönetim paneli: plan editörü
# =====================================================================

class FloorPlanPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.can_edit = database.user_can(user, 'editMenu')
        self.areas = []
        self.area_id = None
        self.dirty = False
        self._edit_widgets = []
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 20, 32, 20)
        root.setSpacing(10)
        root.addWidget(PageHeader("Masa / Bölgeler", "Salon planı: masaları sürükleyin, boyutlandırın, QR etiketlerini basın.",
                                  COLORS['card_teal'], ICONS['table']))

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

        self.offline_banner = QLabel("🟠 Çevrimdışı: plan görüntülenebilir, düzenlenemez.")
        self.offline_banner.setStyleSheet(f"color: {COLORS['warning_dark']}; background: {COLORS['bg_warning']}; "
                                          f"padding: 8px 12px; border-radius: 8px; font-weight: bold;")
        root.addWidget(self.offline_banner)

        # Bölge sekmeleri
        tabs_row = QHBoxLayout()
        self.tabbar = QTabBar()
        self.tabbar.setExpanding(False)
        self.tabbar.setStyleSheet(f"""
            QTabBar::tab {{ background: white; color: {COLORS['text_secondary']}; padding: 9px 22px; margin-right: 6px;
                border: 1px solid {COLORS['border_light']}; border-radius: 16px; font-weight: bold; }}
            QTabBar::tab:selected {{ background: {COLORS['primary']}; color: white; border-color: {COLORS['primary']}; }}
        """)
        self.tabbar.currentChanged.connect(self._on_tab)
        tabs_row.addWidget(self.tabbar, 1)
        self.add_area_btn = _button(f"{ICONS['plus']} Bölge")
        self.add_area_btn.clicked.connect(self._add_area)
        self.rename_area_btn = _button(f"{ICONS['edit']} Ad", primary=False)
        self.rename_area_btn.clicked.connect(self._rename_area)
        self.sort_area_btn = _button("⇅ Sırala", primary=False)
        self.sort_area_btn.clicked.connect(self._sort_areas)
        self.del_area_btn = _button(f"{ICONS['trash']} Sil", primary=False)
        self.del_area_btn.clicked.connect(self._delete_area)
        for b in (self.add_area_btn, self.rename_area_btn, self.sort_area_btn, self.del_area_btn):
            tabs_row.addWidget(b)
        root.addLayout(tabs_row)
        self._edit_widgets += [self.add_area_btn, self.rename_area_btn, self.sort_area_btn, self.del_area_btn,
                               self.import_btn]

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # Araç kutusu
        tools = QFrame()
        tools.setObjectName("floorTools")
        tools.setFixedWidth(170)
        tools.setStyleSheet(f"QFrame#floorTools {{ background: white; border-radius: 12px; border: 1px solid {COLORS['border_light']}; }}")
        tl = QVBoxLayout(tools)
        tl.setContentsMargins(10, 12, 10, 12)
        tl.setSpacing(6)
        t = QLabel("EKLE")
        t.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 11px; background: transparent;")
        tl.addWidget(t)
        for label, fn in (("◯  Yuvarlak masa", lambda: self._add_table('round')),
                          ("▢  Kare masa", lambda: self._add_table('square')),
                          ("▭  Dikdörtgen masa", lambda: self._add_table('rect')),
                          ("━  Duvar", lambda: self._add_fixture('wall')),
                          ("▓  Bar tezgâhı", lambda: self._add_fixture('bar')),
                          ("⌂  Kapı", lambda: self._add_fixture('door')),
                          ("🪴  Bitki", lambda: self._add_fixture('plant'))):
            b = _button(label, primary=False)
            b.setStyleSheet(b.styleSheet() + "QPushButton { text-align: left; padding-left: 10px; }")
            b.clicked.connect(fn)
            tl.addWidget(b)
            self._edit_widgets.append(b)
        tl.addStretch()
        hint = QLabel("Ok tuşları: kaydır\nShift+ok: ince ayar\nCtrl+D: çoğalt\nDelete: sil\nKöşe: boyutlandır")
        hint.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;")
        tl.addWidget(hint)
        body.addWidget(tools)

        # Tuval
        self.scene = FloorScene(editable=True)
        self.scene.selectionChanged.connect(self._on_selection)
        self.view = FloorView(self.scene)
        self.view.delete_pressed.connect(self._delete_selected)
        self.view.duplicate_pressed.connect(self._duplicate_selected)
        body.addWidget(self.view, 1)

        # Özellikler
        insp = QFrame()
        insp.setObjectName("floorInsp")
        insp.setFixedWidth(250)
        insp.setStyleSheet(f"QFrame#floorInsp {{ background: white; border-radius: 12px; border: 1px solid {COLORS['border_light']}; }}")
        il = QVBoxLayout(insp)
        il.setContentsMargins(14, 12, 14, 12)
        self.insp_title = QLabel("SEÇİLİ: —")
        self.insp_title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 11px; background: transparent;")
        il.addWidget(self.insp_title)
        form = QFormLayout()
        form.setSpacing(8)
        self.f_name = QLineEdit()
        self.f_name.setMaxLength(20)
        self.f_name.textEdited.connect(lambda v: self._set_selected('name' if self._sel_is_table() else 'label', v.strip()))
        self.f_cap = QSpinBox()
        self.f_cap.setRange(1, 30)
        self.f_cap.valueChanged.connect(lambda v: self._set_selected('capacity', v) if not self._loading else None)
        shape_row = QHBoxLayout()
        self.shape_group = QButtonGroup(self)
        for i, (key, label) in enumerate((('round', '◯'), ('square', '▢'), ('rect', '▭'))):
            rb = QRadioButton(label)
            rb.setProperty('shape', key)
            self.shape_group.addButton(rb, i)
            shape_row.addWidget(rb)
        self.shape_group.buttonClicked.connect(lambda b: self._set_selected('shape', b.property('shape')))
        form.addRow("Ad:", self.f_name)
        form.addRow("Kişi:", self.f_cap)
        form.addRow("Şekil:", shape_row)
        il.addLayout(form)
        self.rotate_btn = _button("↻ 90° döndür", primary=False)
        self.rotate_btn.clicked.connect(self._rotate_selected)
        self.dup_btn = _button("⧉ Çoğalt", primary=False)
        self.dup_btn.clicked.connect(self._duplicate_selected)
        self.del_btn = _button(f"{ICONS['trash']} Sil", primary=False)
        self.del_btn.clicked.connect(self._delete_selected)
        for b in (self.rotate_btn, self.dup_btn, self.del_btn):
            il.addWidget(b)
        il.addSpacing(10)
        qt = QLabel("QR ETİKETLERİ")
        qt.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; font-size: 11px; background: transparent;")
        il.addWidget(qt)
        self.qr_sel_btn = _button("🖨 Seçilileri yazdır", primary=False)
        self.qr_sel_btn.clicked.connect(lambda: self._print_qr(selected_only=True))
        self.qr_all_btn = _button("🖨 Bölgenin tümü", primary=False)
        self.qr_all_btn.clicked.connect(lambda: self._print_qr(selected_only=False))
        self.qr_rotate_btn = _button("↻ QR yenile (seçili)", primary=False)
        self.qr_rotate_btn.clicked.connect(self._rotate_qr)
        for b in (self.qr_sel_btn, self.qr_all_btn, self.qr_rotate_btn):
            il.addWidget(b)
        il.addStretch()
        body.addWidget(insp)
        self._edit_widgets += [self.f_name, self.f_cap, self.rotate_btn, self.dup_btn, self.del_btn, self.qr_rotate_btn]
        for b in self.shape_group.buttons():
            self._edit_widgets.append(b)

        # Alt çubuk
        bottom = QHBoxLayout()
        self.stats = QLabel()
        self.stats.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; background: transparent;")
        bottom.addWidget(self.stats)
        bottom.addStretch()
        self.snap_box = QCheckBox("Izgaraya oturt")
        self.snap_box.setChecked(True)
        self.snap_box.toggled.connect(self._toggle_snap)
        bottom.addWidget(self.snap_box)
        self.revert_btn = _button("Vazgeç", primary=False)
        self.revert_btn.clicked.connect(self._revert)
        self.save_btn = _button("💾 Planı Kaydet")
        self.save_btn.clicked.connect(self._save)
        bottom.addWidget(self.revert_btn)
        bottom.addWidget(self.save_btn)
        root.addLayout(bottom)
        self._edit_widgets += [self.save_btn, self.revert_btn]
        self.refresh()

    # ------------------------------------------------------------------ yükleme
    def on_sync_status(self, status):
        self._apply_online()
        if status and (status.changed & {'areas', 'tables'}) and not self.dirty:
            self.refresh()

    def _apply_online(self):
        online = ctx.online
        self.offline_banner.setVisible(not online)
        for w in self._edit_widgets:
            w.setEnabled(online and self.can_edit)
        self._on_selection()
        self.save_btn.setEnabled(online and self.can_edit and self.dirty)
        self.revert_btn.setEnabled(self.dirty)

    def refresh(self):
        self.areas = database.floor_areas()
        self._loading = True
        self.tabbar.blockSignals(True)
        while self.tabbar.count():
            self.tabbar.removeTab(0)
        current = 0
        for i, a in enumerate(self.areas):
            n = len(database.floor_tables(a['id']))
            self.tabbar.addTab(f"{a['name']} ({n})")
            if a['id'] == self.area_id:
                current = i
        self.tabbar.setCurrentIndex(current)
        self.tabbar.blockSignals(False)
        self._loading = False
        self.area_id = self.areas[current]['id'] if self.areas else None
        self._load_area()
        legacy = database.legacy_floor_payload()
        show = not self.areas and bool(legacy)
        self.import_banner.setVisible(show)
        if show:
            n = sum(len(a['tables']) for a in legacy)
            self.import_label.setText(f"Bulutta henüz salon planı yok. Bu bilgisayardaki düzeni buluta aktarabilirsiniz "
                                      f"({len(legacy)} bölge, {n} masa). Masalar ızgaraya yerleştirilir.")
        self._apply_online()

    def _area(self):
        return next((a for a in self.areas if a['id'] == self.area_id), None)

    def _load_area(self):
        self.scene.clear()
        self.dirty = False
        self._removed_ids = []
        area = self._area()
        if area:
            for f in area.get('fixtures', []):
                self._place(PlanItem(f, False, True))
            for t in database.floor_tables(self.area_id):
                self._place(PlanItem(t, True, True))
        self._update_stats()
        self._on_selection()

    def _place(self, item):
        item.snap_enabled = self.snap_box.isChecked()
        item.changed.connect(self._mark_dirty)
        self.scene.addItem(item)
        return item

    def _on_tab(self, index):
        if index < 0 or index >= len(self.areas) or self._loading:
            return
        if self.dirty and not self.can_leave():
            self.tabbar.blockSignals(True)
            self.tabbar.setCurrentIndex(next(i for i, a in enumerate(self.areas) if a['id'] == self.area_id))
            self.tabbar.blockSignals(False)
            return
        self.area_id = self.areas[index]['id']
        self._load_area()
        self._apply_online()

    def can_leave(self):
        """Kaydedilmemiş değişiklik varsa sorar. True: çıkılabilir."""
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Kaydedilmemiş değişiklik",
                                 "Bu bölgenin planında kaydedilmemiş değişiklikler var. Kaydetmeden çıkılsın mı?",
                                 QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self._load_area()
            return True
        return False

    # ------------------------------------------------------------------ düzenleme
    def _items(self, tables=None):
        items = [i for i in self.scene.items() if isinstance(i, PlanItem)]
        if tables is None:
            return items
        return [i for i in items if i.is_table == tables]

    def _mark_dirty(self):
        if not self._loading:
            self.dirty = True
            self._update_stats()
            self.save_btn.setEnabled(ctx.online and self.can_edit)
            self.revert_btn.setEnabled(True)

    def _update_stats(self):
        tables = self._items(tables=True)
        seats = sum(i.info.get('capacity', 0) for i in tables)
        star = "  ·  kaydedilmedi ●" if self.dirty else ""
        self.stats.setText(f"{len(tables)} masa · {seats} kişilik{star}")

    def _next_table_name(self):
        numbers = [int(m.group(1)) for t in database.floor_tables() for m in [re.search(r'(\d+)\s*$', t.get('name', ''))] if m]
        numbers += [int(m.group(1)) for i in self._items(tables=True) for m in [re.search(r'(\d+)\s*$', i.info.get('name', ''))] if m]
        return f"Masa {max(numbers, default=0) + 1}"

    def _free_spot(self, w, h):
        taken = [QRectF(i.pos(), QPointF(i.pos().x() + i.size()[0], i.pos().y() + i.size()[1])) for i in self._items()]
        for y in range(40, CANVAS_H - h, GRID * 2):
            for x in range(40, CANVAS_W - w, GRID * 2):
                r = QRectF(x, y, w, h).adjusted(-20, -20, 20, 20)
                if not any(r.intersects(t) for t in taken):
                    return x, y
        return 40, 40

    def _add_table(self, shape):
        if not self.area_id:
            QMessageBox.information(self, "Önce bölge", "Masa eklemeden önce bir bölge oluşturun.")
            return
        w, h, cap = TABLE_DEFAULTS[shape]
        x, y = self._free_spot(w, h)
        item = self._place(PlanItem({'tempId': uuid.uuid4().hex[:12], 'name': self._next_table_name(), 'shape': shape,
                                     'capacity': cap, 'x': x, 'y': y, 'w': w, 'h': h, 'rotation': 0}, True, True))
        self.scene.clearSelection()
        item.setSelected(True)
        self._mark_dirty()

    def _add_fixture(self, kind):
        if not self.area_id:
            return
        w, h, label = FIXTURE_DEFAULTS[kind]
        x, y = self._free_spot(w, h)
        item = self._place(PlanItem({'id': uuid.uuid4().hex[:12], 'kind': kind, 'label': label,
                                     'x': x, 'y': y, 'w': w, 'h': h, 'rotation': 0}, False, True))
        self.scene.clearSelection()
        item.setSelected(True)
        self._mark_dirty()

    def _selected(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, PlanItem)]
        return sel[0] if len(sel) == 1 else None

    def _sel_is_table(self):
        s = self._selected()
        return bool(s and s.is_table)

    def _on_selection(self):
        if not shiboken6.isValid(self.scene) or not shiboken6.isValid(self.insp_title):
            return  # sayfa kapanırken sahnenin son seçim sinyali
        s = self._selected()
        sel_all = [i for i in self.scene.selectedItems() if isinstance(i, PlanItem)]
        editable = ctx.online and self.can_edit
        self._loading = True
        if s:
            self.insp_title.setText(f"SEÇİLİ: {s.info.get('name') if s.is_table else FIXTURE_NAMES[s.info['kind']]}")
            self.f_name.setText(s.info.get('name', '') if s.is_table else s.info.get('label', ''))
            self.f_cap.setValue(s.info.get('capacity', 1) if s.is_table else 1)
            for b in self.shape_group.buttons():
                b.setChecked(b.property('shape') == s.info.get('shape'))
        else:
            self.insp_title.setText(f"SEÇİLİ: {len(sel_all)} öğe" if sel_all else "SEÇİLİ: —")
            self.f_name.clear()
        self._loading = False
        is_table = bool(s and s.is_table)
        self.f_name.setEnabled(editable and bool(s))
        self.f_cap.setEnabled(editable and is_table)
        for b in self.shape_group.buttons():
            b.setEnabled(editable and is_table)
        for b in (self.rotate_btn, self.dup_btn):
            b.setEnabled(editable and bool(s))
        self.del_btn.setEnabled(editable and bool(sel_all))
        tables_selected = [i for i in sel_all if i.is_table and i.info.get('id')]
        self.qr_sel_btn.setEnabled(bool(tables_selected))
        self.qr_rotate_btn.setEnabled(editable and bool(tables_selected))

    def _set_selected(self, key, value):
        s = self._selected()
        if s and not self._loading:
            s.set_field(key, value)
            if key == 'name':
                self.insp_title.setText(f"SEÇİLİ: {value}")

    def _rotate_selected(self):
        s = self._selected()
        if s:
            s.rotate()

    def _duplicate_selected(self):
        s = self._selected()
        if not s or not (ctx.online and self.can_edit):
            return
        data = {k: v for k, v in s.info.items() if k not in ('id', 'qrToken', 'areaId', 'deleted', 'updatedAt',
                                                             'createdAt', 'order')}
        w, h = s.size()
        data['x'] = min(int(s.pos().x()) + GRID * 2, CANVAS_W - w)
        data['y'] = min(int(s.pos().y()) + GRID * 2, CANVAS_H - h)
        if s.is_table:
            data.update(tempId=uuid.uuid4().hex[:12], name=self._next_table_name())
        else:
            data['id'] = uuid.uuid4().hex[:12]
        item = self._place(PlanItem(data, s.is_table, True))
        self.scene.clearSelection()
        item.setSelected(True)
        self._mark_dirty()

    def _delete_selected(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, PlanItem)]
        if not sel or not (ctx.online and self.can_edit):
            return
        busy = database.area_has_open_orders(table_ids=[i.info['id'] for i in sel if i.is_table and i.info.get('id')])
        if busy:
            QMessageBox.warning(self, "Açık adisyon", f"Açık adisyonu olan masa silinemez: {', '.join(busy)}")
            return
        for i in sel:
            if i.is_table and i.info.get('id'):
                self._removed_ids.append(i.info['id'])
            self.scene.removeItem(i)
        self._mark_dirty()
        self._on_selection()

    def _toggle_snap(self, on):
        for i in self._items():
            i.snap_enabled = on

    def _revert(self):
        self._load_area()
        self._apply_online()

    # ------------------------------------------------------------------ kaydetme
    def _collect(self):
        tables, fixtures, names = [], [], set()
        for i in sorted(self._items(), key=lambda it: (it.info['y'], it.info['x'])):
            geo = {k: int(i.info[k]) for k in ('x', 'y', 'w', 'h')}
            geo['rotation'] = i.info.get('rotation', 0)
            if i.is_table:
                name = (i.info.get('name') or '').strip()
                key = database.turkish_lower(name)
                if not name:
                    raise ValueError("Adı boş bir masa var.")
                if key in names:
                    raise ValueError(f'"{name}" adı birden fazla masada kullanılmış.')
                names.add(key)
                t = {'name': name, 'shape': i.info['shape'], 'capacity': int(i.info['capacity']), **geo}
                if i.info.get('id'):
                    t['id'] = i.info['id']
                else:
                    t['tempId'] = i.info['tempId']
                tables.append(t)
            else:
                fixtures.append({'id': i.info['id'], 'kind': i.info['kind'], 'label': i.info.get('label', ''), **geo})
        return tables, fixtures

    def _save(self):
        area = self._area()
        if not area:
            return
        try:
            tables, fixtures = self._collect()
        except ValueError as e:
            QMessageBox.warning(self, "Plan kaydedilemedi", str(e))
            return
        # Yalnızca bu oturumda editörden silinen masalar silinir (açıkça gönderilir)
        removed = [i for i in self._removed_ids]
        busy = database.area_has_open_orders(table_ids=removed)
        if busy:
            QMessageBox.warning(self, "Açık adisyon", f"Açık adisyonu olan masa silinemez: {', '.join(busy)}")
            return
        version = area.get('layoutVersion', 0)

        def done(_):
            self.dirty = False
            self.refresh()

        cloud_action(self, lambda api: api.save_floor_plan(area['id'], version, tables, fixtures, removed),
                     f"{area['name']} planı kaydedildi.", done)

    # ------------------------------------------------------------------ bölgeler
    def _add_area(self):
        name, ok = QInputDialog.getText(self, "Yeni Bölge", "Bölge adı (ör. Bahçe, Üst Kat):")
        if ok and name.strip():
            if self.dirty and not self.can_leave():
                return
            cloud_action(self, lambda api: api.save_area(name.strip()), f"{name.strip()} eklendi.",
                         lambda res: (setattr(self, 'area_id', res['id']), self.refresh()))

    def _rename_area(self):
        area = self._area()
        if not area:
            return
        name, ok = QInputDialog.getText(self, "Bölge Adı", "Yeni ad:", text=area['name'])
        if ok and name.strip() and name.strip() != area['name']:
            cloud_action(self, lambda api: api.save_area(name.strip(), area['id']), "Bölge adı güncellendi.",
                         lambda _: self.refresh())

    def _sort_areas(self):
        from menu_pages import ReorderDialog
        dlg = ReorderDialog("Bölgeleri Sırala", [(a['id'], a['name']) for a in self.areas], self)
        if dlg.exec() == QDialog.Accepted:
            cloud_action(self, lambda api: api.reorder('areas', dlg.ids), "Bölge sırası kaydedildi.",
                         lambda _: self.refresh())

    def _delete_area(self):
        area = self._area()
        if not area:
            return
        busy = database.area_has_open_orders(area_id=area['id'])
        if busy:
            QMessageBox.warning(self, "Açık adisyon", f"Bu bölgede açık adisyonlu masalar var: {', '.join(busy)}")
            return
        n = len(database.floor_tables(area['id']))
        if QMessageBox.question(self, "Bölgeyi Sil", f"{area['name']} ve içindeki {n} masa silinsin mi?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.area_id = None
            self.dirty = False
            cloud_action(self, lambda api: api.delete_area(area['id']), f"{area['name']} silindi.",
                         lambda _: self.refresh())

    def _import_legacy(self):
        payload = database.legacy_floor_payload()

        def work(api):
            result = api.import_floor(payload)
            database.apply_floor_mapping(result['areas'], result['tables'])
            return result

        cloud_action(self, work, "Salon düzeni buluta aktarıldı.", lambda _: self.refresh())

    # ------------------------------------------------------------------ QR
    def _print_qr(self, selected_only):
        if self.dirty:
            QMessageBox.information(self, "Önce kaydedin", "QR etiketleri kaydedilmiş plandan basılır. Önce planı kaydedin.")
            return
        if selected_only:
            ids = {i.info['id'] for i in self.scene.selectedItems() if isinstance(i, PlanItem) and i.is_table and i.info.get('id')}
            tables = [t for t in database.floor_tables(self.area_id) if t['id'] in ids]
        else:
            tables = database.floor_tables(self.area_id)
        tables = [t for t in tables if t.get('qrToken')]
        if not tables:
            QMessageBox.information(self, "QR", "Basılacak masa yok.")
            return
        settings = database.general_settings()
        base = settings['qrBaseUrl'] or (default_base_url(ctx.config.project_id) if ctx.config else '')
        if not base:
            QMessageBox.warning(self, "QR adresi yok", "Ayarlar sayfasından QR adresini girin.")
            return
        area = self._area()
        path, _ = QFileDialog.getSaveFileName(self, "QR etiketlerini kaydet",
                                              f"{area['name']} QR.pdf" if area else "masa-qr.pdf", "PDF (*.pdf)")
        if not path:
            return
        tables.sort(key=lambda t: (len(t['name']), t['name']))
        pages = write_qr_pdf(path, settings['cafeName'], base, tables)
        ToastNotification(self.window(), f"{len(tables)} etiket, {pages} sayfa PDF olarak kaydedildi.", "success")

    def _rotate_qr(self):
        ids = [i.info['id'] for i in self.scene.selectedItems() if isinstance(i, PlanItem) and i.is_table and i.info.get('id')]
        if not ids:
            return
        if QMessageBox.question(self, "QR Yenile",
                                f"{len(ids)} masanın QR kodu yenilensin mi?\nEski etiketler hemen geçersiz olur; "
                                "yenilerini basıp masalara yapıştırmanız gerekir.",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            cloud_action(self, lambda api: api.rotate_table_qr(ids), f"{len(ids)} masanın QR kodu yenilendi.",
                         lambda _: self.refresh())


# =====================================================================
# Garson ekranı: salt okunur plan
# =====================================================================

class FloorStatusView(QWidget):
    """Bölgenin planı; masalar yerel durumlarıyla (boş/dolu/rezerve) renklenir."""
    table_clicked = Signal(dict)       # eski masa sözlüğü (TableCard ile aynı)
    reserve_toggled = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        self.scene = FloorScene(editable=False)
        self.view = FloorView(self.scene)
        ly.addWidget(self.view, 1)
        legend = QHBoxLayout()
        legend.addStretch()
        for key, label in (('dolu', 'Dolu'), ('hesap', 'Hesap istendi'), ('rezerve', 'Rezerve'), ('bos', 'Boş')):
            fill, border, _ = STATUS_STYLE[key]
            dot = QLabel(f"  {label}  ")
            dot.setStyleSheet(f"background: {fill}; border: 2px solid {border}; border-radius: 8px; "
                              f"padding: 3px 8px; font-size: 12px; font-weight: bold;")
            legend.addWidget(dot)
        hint = QLabel("  Sağ tık: rezerve et / kaldır")
        hint.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        legend.addWidget(hint)
        ly.addLayout(legend)

    def show_area(self, area_id):
        self.scene.clear()
        area = database.menu_item('areas', area_id) if area_id else None
        if not area:
            return False
        for f in area.get('fixtures', []):
            self.scene.addItem(PlanItem(f, False, False))
        for t in database.floor_table_states(area_id):
            if not t.get('legacy'):
                continue
            item = PlanItem(t, True, False, status=t['legacy'])
            item.clicked.connect(lambda it: self.table_clicked.emit(it.status))
            item.context.connect(self._context)
            self.scene.addItem(item)
        self.view.fit()
        return True

    def _context(self, item, screen_pos):
        state = item.status.get('durum')
        if state not in ('bos', 'rezerve'):
            return
        menu = QMenu(self)
        act = menu.addAction("Rezervasyonu kaldır" if state == 'rezerve' else "Rezerve et")
        if menu.exec(screen_pos) == act:
            self.reserve_toggled.emit(item.status)
