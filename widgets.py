"""
NexPOS - Premium Widget Koleksiyonu
Modern, gölgeli, gradient destekli kartlar ve bileşenler
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QFrame, QGraphicsDropShadowEffect, QMessageBox, QDialog
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QTimer, QPoint
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient
from styles import COLORS, FONTS, ICONS


def add_shadow(widget, blur=20, offset_y=4, color=QColor(0, 0, 0, 30)):
    """Widget'a gölge efekti ekle"""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, offset_y)
    shadow.setColor(color)
    widget.setGraphicsEffect(shadow)
    return shadow


class StatCard(QFrame):
    """Dashboard istatistik kartı - Modern gradient arka plan"""

    def __init__(self, icon_char, title, value, subtitle="", color="#3B82F6", bg_color="#EFF6FF", parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setFixedHeight(120)
        self.setMinimumWidth(260)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame#statCard {{
                background-color: {bg_color};
                border-radius: 16px;
                border: 1px solid {COLORS['border_light']};
            }}
            QFrame#statCard:hover {{
                border-color: {color};
            }}
        """)
        add_shadow(self, blur=16, offset_y=4, color=QColor(0, 0, 0, 20))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # Sol ikon daire
        icon_frame = QFrame()
        icon_frame.setFixedSize(56, 56)
        icon_frame.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {color}, stop:1 {color}CC);
            border-radius: 28px;
        """)
        icon_ly = QVBoxLayout(icon_frame)
        icon_ly.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel(icon_char)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setFont(QFont(FONTS['family'], 20, QFont.Bold))
        icon_lbl.setStyleSheet("color: white; background: transparent;")
        icon_ly.addWidget(icon_lbl)
        layout.addWidget(icon_frame)

        # Sağ metin
        text_ly = QVBoxLayout()
        text_ly.setSpacing(4)

        t = QLabel(title)
        t.setFont(QFont(FONTS['family'], FONTS['size_xs']))
        t.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        t.setWordWrap(True)
        text_ly.addWidget(t)

        v = QLabel(value)
        v.setFont(QFont(FONTS['family'], 22, QFont.Bold))
        v.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        text_ly.addWidget(v)

        if subtitle:
            s = QLabel(subtitle)
            s.setFont(QFont(FONTS['family'], FONTS['size_xs']))
            s.setStyleSheet(f"color: {color}; background: transparent; font-weight: bold;")
            text_ly.addWidget(s)

        layout.addLayout(text_ly, 1)


class ProductCard(QFrame):
    """Ürün kartı - Temiz, tıklanabilir"""
    clicked = Signal(dict)

    def __init__(self, product_data, parent=None):
        super().__init__(parent)
        self.product_data = product_data
        self.setObjectName("productCard")
        self.setFixedSize(200, 130)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame#productCard {{
                background-color: white;
                border: 2px solid {COLORS['border']};
                border-radius: 14px;
            }}
            QFrame#productCard:hover {{
                border-color: {COLORS['primary']};
                background-color: {COLORS['primary_bg']};
            }}
        """)
        add_shadow(self, blur=10, offset_y=3, color=QColor(0, 0, 0, 15))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        # Kategori renk şeridi
        cat_color = product_data.get('renk', COLORS['primary'])
        stripe = QFrame()
        stripe.setFixedHeight(4)
        stripe.setStyleSheet(f"background: {cat_color}; border-radius: 2px;")
        layout.addWidget(stripe)

        layout.addSpacing(4)

        # Ürün adı
        name = QLabel(product_data['ad'])
        name.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        name.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        name.setWordWrap(True)
        layout.addWidget(name)

        # Birim
        birim = QLabel(product_data.get('birim', 'Adet'))
        birim.setFont(QFont(FONTS['family'], FONTS['size_xs']))
        birim.setStyleSheet(f"color: {COLORS['text_muted']}; background: transparent;")
        layout.addWidget(birim)

        layout.addStretch()

        # Fiyat
        fiyat = QLabel(f"{ICONS['money']}{product_data['fiyat']:,.2f}")
        fiyat.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        fiyat.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
        layout.addWidget(fiyat)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self.product_data)


class TableCard(QFrame):
    """Masa kartı - Premium, bilgi yoğun"""
    clicked = Signal(dict)

    def __init__(self, table_data, parent=None):
        super().__init__(parent)
        self.table_data = table_data
        self.setObjectName("tableCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(190, 135)

        is_occupied = table_data.get('durum') == 'dolu'
        if is_occupied:
            bg_style = f"background-color: {COLORS['table_occupied']};"
            border_c = COLORS['table_occupied_border']
            bw = "2px"
            shadow_color = QColor(239, 68, 68, 40)
        else:
            bg_style = f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #FFFFFF, stop:1 #F0F4FF);"
            border_c = "#D1D5DB"
            bw = "1px"
            shadow_color = QColor(0, 0, 0, 15)

        self.setStyleSheet(f"""
            QFrame#tableCard {{
                {bg_style}
                border: {bw} solid {border_c};
                border-radius: 14px;
            }}
            QFrame#tableCard:hover {{
                border-color: {COLORS['primary']};
                border-width: 2px;
            }}
        """)
        add_shadow(self, blur=12, offset_y=3, color=shadow_color)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(3)

        if is_occupied:
            # Üst: Masa adı + durum badge
            top = QHBoxLayout()
            nm = QLabel(table_data.get('ad', ''))
            nm.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
            nm.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")

            badge = QLabel("DOLU")
            badge.setFont(QFont(FONTS['family'], 8, QFont.Bold))
            badge.setStyleSheet(f"""
                color: white; background: {COLORS['danger']};
                padding: 2px 8px; border-radius: 4px;
            """)

            top.addWidget(nm)
            top.addStretch()
            top.addWidget(badge)
            layout.addLayout(top)

            # Garson
            garson = table_data.get('garson_adi', '')
            if garson:
                g = QLabel(f"{ICONS['dot']} {garson}")
                g.setFont(QFont(FONTS['family'], FONTS['size_xs']))
                g.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
                layout.addWidget(g)

            # Tutar
            tutar = table_data.get('toplam_tutar', 0)
            if tutar:
                t = QLabel(f"{ICONS['money']}{tutar:,.2f}")
                t.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
                t.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
                layout.addWidget(t)

            # Süre
            tarih = table_data.get('siparis_tarihi', '')
            if tarih:
                try:
                    from datetime import datetime
                    dt = datetime.strptime(tarih, "%Y-%m-%d %H:%M")
                    diff = datetime.now() - dt
                    d, h, m = diff.days, diff.seconds // 3600, (diff.seconds % 3600) // 60
                    if d > 0:
                        txt = f"{d}g {h}s"
                    elif h > 0:
                        txt = f"{h}s {m}dk"
                    else:
                        txt = f"{m} dk"
                    s = QLabel(f"\u23F1 {txt}")
                    s.setFont(QFont(FONTS['family'], FONTS['size_xs']))
                    s.setStyleSheet(f"color: {COLORS['warning']}; background: transparent; font-weight: bold;")
                    layout.addWidget(s)
                except Exception:
                    pass
            layout.addStretch()
        else:
            layout.addStretch()
            # Durum ikonu
            icon = QLabel(ICONS['table'])
            icon.setFont(QFont(FONTS['family'], 24))
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet(f"color: {COLORS['text_muted']}; background: transparent;")
            layout.addWidget(icon)

            nm = QLabel(table_data.get('ad', ''))
            nm.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
            nm.setAlignment(Qt.AlignCenter)
            nm.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
            layout.addWidget(nm)

            reserved = table_data.get('durum') == 'rezerve'
            empty_lbl = QLabel("Rezerve" if reserved else "Boş")
            empty_lbl.setFont(QFont(FONTS['family'], FONTS['size_xs']))
            empty_lbl.setAlignment(Qt.AlignCenter)
            empty_lbl.setStyleSheet(f"color: {COLORS['info'] if reserved else COLORS['success']}; "
                                    f"background: transparent; font-weight: bold;")
            layout.addWidget(empty_lbl)
            layout.addStretch()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self.table_data)


class OrderCard(QFrame):
    """Sipariş kartı - Kanban board için premium kart"""
    status_changed = Signal(int, str)
    detail_requested = Signal(dict)

    def __init__(self, order_data, parent=None):
        super().__init__(parent)
        self.order_data = order_data
        self.setObjectName("orderCard")
        self.setStyleSheet(f"""
            QFrame#orderCard {{
                background-color: white;
                border: 1px solid {COLORS['border']};
                border-radius: 14px;
            }}
            QFrame#orderCard:hover {{
                border-color: {COLORS['primary_light']};
            }}
        """)
        add_shadow(self, blur=10, offset_y=3, color=QColor(0, 0, 0, 15))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # Badge - zaman bazlı
        tarih = order_data.get('tarih', '')
        badge_text = "Yeni Sipariş"
        badge_bg = "#DBEAFE"
        badge_color = "#1D4ED8"
        if tarih:
            try:
                from datetime import datetime
                dt = datetime.strptime(tarih, "%Y-%m-%d %H:%M")
                diff = datetime.now() - dt
                mins = diff.total_seconds() / 60
                if mins > 60:
                    badge_text = "Geciken Sipariş"
                    badge_bg = "#FEE2E2"
                    badge_color = "#DC2626"
                elif mins > 30:
                    badge_text = "Bekleyen Sipariş"
                    badge_bg = "#FEF3C7"
                    badge_color = "#D97706"
            except Exception:
                pass

        badge = QLabel(f"  {badge_text}  ")
        badge.setFont(QFont(FONTS['family'], 9, QFont.Bold))
        badge.setStyleSheet(f"""
            background-color: {badge_bg}; color: {badge_color};
            padding: 3px 10px; border-radius: 6px;
        """)
        layout.addWidget(badge, alignment=Qt.AlignLeft)

        # Masa + No
        top = QHBoxLayout()
        top.setSpacing(10)

        # Renkli avatar
        avatar = QFrame()
        avatar.setFixedSize(40, 40)
        avatar.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {COLORS['accent']}, stop:1 {COLORS['accent_dark']});
            border-radius: 20px;
        """)
        av_ly = QVBoxLayout(avatar)
        av_ly.setContentsMargins(0, 0, 0, 0)
        av_lbl = QLabel(order_data.get('masa_adi', 'M')[:1])
        av_lbl.setAlignment(Qt.AlignCenter)
        av_lbl.setFont(QFont(FONTS['family'], 14, QFont.Bold))
        av_lbl.setStyleSheet("color: white; background: transparent;")
        av_ly.addWidget(av_lbl)

        info = QVBoxLayout()
        info.setSpacing(1)
        masa = QLabel(order_data.get('masa_adi', 'Masa'))
        masa.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        masa.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        tarih_lbl = QLabel(order_data.get('tarih', ''))
        tarih_lbl.setFont(QFont(FONTS['family'], FONTS['size_xs']))
        tarih_lbl.setStyleSheet(f"color: {COLORS['text_muted']}; background: transparent;")
        info.addWidget(masa)
        info.addWidget(tarih_lbl)

        no = QLabel(f"#{order_data.get('id', '')}")
        no.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
        no.setStyleSheet(f"color: {COLORS['text_muted']}; background: transparent;")

        top.addWidget(avatar)
        top.addLayout(info, 1)
        top.addWidget(no)
        layout.addLayout(top)

        # Tutar
        tutar = order_data.get('toplam_tutar', 0)
        tl = QLabel(f"{ICONS['money']}{tutar:,.2f}")
        tl.setFont(QFont(FONTS['family'], 16, QFont.Bold))
        tl.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        tl.setAlignment(Qt.AlignRight)
        layout.addWidget(tl)

        # Ürünlerin listesi (Sipariş Panosu iyileştirmesi)
        items = order_data.get('items', [])
        if items:
            items_frame = QFrame()
            items_frame.setStyleSheet(f"background: {COLORS['bg_main']}; border-radius: 8px; padding: 4px;")
            items_ly = QVBoxLayout(items_frame)
            items_ly.setContentsMargins(8, 6, 8, 6)
            items_ly.setSpacing(2)
            
            display_items = items[:3]
            for item in display_items:
                lbl = QLabel(f"{item['adet']}x {item['urun_adi']}")
                lbl.setFont(QFont(FONTS['family'], FONTS['size_xs']))
                lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
                items_ly.addWidget(lbl)
                
            if len(items) > 3:
                more_lbl = QLabel(f"+ {len(items)-3} ürün daha...")
                more_lbl.setFont(QFont(FONTS['family'], 8, QFont.Bold))
                more_lbl.setStyleSheet(f"color: {COLORS['primary']}; background: transparent;")
                items_ly.addWidget(more_lbl)
                
            layout.addWidget(items_frame)

        # Ayırıcı
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border_light']};")
        layout.addWidget(sep)

        # Aksiyon butonları
        actions = QHBoxLayout()
        actions.setSpacing(4)
        oid = order_data.get('id', 0)
        status = order_data.get('durum', 'hazirlaniyor')

        btns = [("Detay", COLORS['info'], lambda: self.detail_requested.emit(self.order_data))]
        if status == 'hazirlaniyor':
            btns.append(("Hazırla", COLORS['warning'], lambda: self.status_changed.emit(oid, 'bekliyor')))
            btns.append(("İptal", COLORS['danger'], lambda: self.status_changed.emit(oid, 'iptal')))
        elif status == 'bekliyor':
            btns.append(("Teslim Edildi", COLORS['success'], lambda: self.status_changed.emit(oid, 'tamamlandi')))
            btns.append(("İptal", COLORS['danger'], lambda: self.status_changed.emit(oid, 'iptal')))

        for text, color, fn in btns:
            btn = QPushButton(text)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px; background: white;
                    font-size: 10px; color: {color};
                    font-weight: bold; padding: 0 8px;
                }}
                QPushButton:hover {{
                    background: {color}; color: white;
                    border-color: {color};
                }}
            """)
            btn.clicked.connect(fn)
            actions.addWidget(btn)
        actions.addStretch()
        layout.addLayout(actions)


class SidebarButton(QPushButton):
    """Koyu tema sidebar butonu"""

    def __init__(self, text, icon_char="", is_sub=False, parent=None):
        super().__init__(parent)
        display = f"  {icon_char}   {text}" if icon_char else f"       {text}"
        self.setText(display)
        self.setFixedHeight(44 if not is_sub else 38)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)

        fs = FONTS['size_md'] if not is_sub else FONTS['size_sm']
        lp = 18 if not is_sub else 48

        self.setStyleSheet(f"""
            QPushButton {{
                border: none; border-radius: 8px;
                text-align: left; padding-left: {lp}px;
                font-size: {fs}px;
                color: {COLORS['sidebar_text']};
                background: transparent;
                margin: 2px 8px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['sidebar_hover']};
                color: {COLORS['sidebar_text_active']};
            }}
            QPushButton:checked {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {COLORS['primary']}, stop:1 {COLORS['primary_dark']});
                color: white;
                font-weight: bold;
            }}
        """)


class ExpandableSection(QWidget):
    """Açılır koyu sidebar bölüm"""

    def __init__(self, title, icon_char="", parent=None):
        super().__init__(parent)
        self.expanded = False
        self._title = title
        self._icon = icon_char
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header_btn = QPushButton(f"  {icon_char}   {title}     {ICONS['expand']}")
        self.header_btn.setFixedHeight(44)
        self.header_btn.setCursor(Qt.PointingHandCursor)
        self.header_btn.setStyleSheet(f"""
            QPushButton {{
                border: none; text-align: left; padding-left: 18px;
                font-size: {FONTS['size_md']}px;
                color: {COLORS['sidebar_text']};
                background: transparent;
                margin: 2px 8px;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['sidebar_hover']};
                color: {COLORS['sidebar_text_active']};
            }}
        """)
        self.header_btn.clicked.connect(self.toggle)
        main_layout.addWidget(self.header_btn)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self.content_widget.setVisible(False)
        main_layout.addWidget(self.content_widget)

    def add_sub_button(self, text, icon_char=""):
        btn = SidebarButton(text, icon_char, is_sub=True)
        self.content_layout.addWidget(btn)
        return btn

    def toggle(self):
        self.expanded = not self.expanded
        self.content_widget.setVisible(self.expanded)
        arrow = ICONS['collapse'] if self.expanded else ICONS['expand']
        self.header_btn.setText(f"  {self._icon}   {self._title}     {arrow}")


class PageHeader(QFrame):
    """Sayfa başlığı - Gradient arka planlı ikon + başlık"""

    def __init__(self, title, subtitle="", color="#EF4444", icon_char="", parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFixedHeight(76)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)

        # Gradient ikon kutusu
        icon_frame = QFrame()
        icon_frame.setFixedSize(56, 56)
        icon_frame.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {color}, stop:1 {color}CC);
            border-radius: 16px;
        """)
        icon_lbl = QLabel(icon_char)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setFont(QFont(FONTS['family'], 22, QFont.Bold))
        icon_lbl.setStyleSheet("color: white; background: transparent;")
        il = QVBoxLayout(icon_frame)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(icon_lbl)

        add_shadow(icon_frame, blur=12, offset_y=4, color=QColor(color))

        layout.addWidget(icon_frame)
        layout.addSpacing(16)

        text_ly = QVBoxLayout()
        text_ly.setSpacing(3)
        tl = QLabel(title)
        tl.setFont(QFont(FONTS['family'], FONTS['size_xl'], QFont.Bold))
        tl.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        text_ly.addWidget(tl)
        if subtitle:
            sl = QLabel(subtitle)
            sl.setFont(QFont(FONTS['family'], FONTS['size_sm']))
            sl.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
            sl.setWordWrap(True)
            text_ly.addWidget(sl)
        layout.addLayout(text_ly, 1)


class BarChart(QFrame):
    """Basit bar chart widget - QPainter ile çizim"""

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self.data = data or []
        self.setMinimumHeight(180)
        self.setStyleSheet("background: transparent; border: none;")

    def set_data(self, data):
        self.data = data
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.data:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 50
        margin_bottom = 30
        margin_top = 10
        chart_w = w - margin_left - 20
        chart_h = h - margin_bottom - margin_top

        max_val = max(v for _, v in self.data) if self.data else 1
        if max_val == 0:
            max_val = 1

        bar_count = len(self.data)
        bar_width = max(12, min(40, chart_w // (bar_count * 2)))
        gap = bar_width

        # Y ekseni çizgileri
        painter.setPen(QPen(QColor(COLORS['border']), 1))
        for i in range(5):
            y = margin_top + chart_h - (chart_h * i / 4)
            painter.drawLine(margin_left, int(y), w - 20, int(y))
            val_text = f"{int(max_val * i / 4)}"
            painter.setPen(QPen(QColor(COLORS['text_muted']), 1))
            painter.setFont(QFont(FONTS['family'], 9))
            painter.drawText(0, int(y) - 8, margin_left - 8, 16, Qt.AlignRight | Qt.AlignVCenter, val_text)
            painter.setPen(QPen(QColor(COLORS['border']), 1))

        # Barlar
        colors = [
            QColor("#4F46E5"), QColor("#3B82F6"), QColor("#10B981"),
            QColor("#F59E0B"), QColor("#EF4444"), QColor("#8B5CF6"),
            QColor("#EC4899"), QColor("#14B8A6"),
        ]

        for i, (label, value) in enumerate(self.data):
            x = margin_left + i * (bar_width + gap) + gap // 2
            bar_h = (value / max_val) * chart_h
            y = margin_top + chart_h - bar_h

            color = colors[i % len(colors)]
            grad = QLinearGradient(x, y, x, margin_top + chart_h)
            grad.setColorAt(0, color)
            grad.setColorAt(1, color.darker(130))
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(int(x), int(y), bar_width, int(bar_h), 4, 4)

            # Label
            painter.setPen(QPen(QColor(COLORS['text_muted']), 1))
            painter.setFont(QFont(FONTS['family'], 8))
            painter.drawText(int(x) - 5, margin_top + chart_h + 4, bar_width + 10, 20,
                           Qt.AlignCenter, label)

        painter.end()


class DonutChart(QFrame):
    """Donut grafik widget"""

    def __init__(self, percentage=0, color="#4F46E5", label="", parent=None):
        super().__init__(parent)
        self.percentage = percentage
        self.color = color
        self.label = label
        self.setFixedSize(140, 140)
        self.setStyleSheet("background: transparent; border: none;")

    def set_data(self, percentage, color="#4F46E5", label=""):
        self.percentage = percentage
        self.color = color
        self.label = label
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        size = min(w, h) - 20
        x = (w - size) // 2
        y = (h - size) // 2

        # Arka plan dairesi
        painter.setPen(QPen(QColor(COLORS['border']), 12))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(x, y, size, size)

        # Değer yayı
        painter.setPen(QPen(QColor(self.color), 12, Qt.SolidLine, Qt.RoundCap))
        span = int(self.percentage * 360 / 100)
        painter.drawArc(x, y, size, size, 90 * 16, -span * 16)

        # Ortadaki metin
        painter.setPen(QPen(QColor(COLORS['text_dark']), 1))
        painter.setFont(QFont(FONTS['family'], 18, QFont.Bold))
        painter.drawText(x, y, size, size, Qt.AlignCenter, f"%{int(self.percentage)}")

        painter.end()


class InfoDialog(QDialog):
    """Genel bilgi dialog'u - Premium tasarım"""

    def __init__(self, title, message, color=None, parent=None):
        from PySide6.QtWidgets import QDialog
        super().__init__(parent)
        if color is None:
            color = COLORS['primary']
        self.setWindowTitle(title)
        self.setFixedSize(420, 220)
        self.setStyleSheet("background: white; border-radius: 16px;")

        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(0)

        # Banner
        banner = QFrame()
        banner.setObjectName("infoBanner")
        banner.setFixedHeight(60)
        banner.setStyleSheet(f"""
            QFrame#infoBanner {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {color}, stop:1 {color}CC);
                border-top-left-radius: 16px; border-top-right-radius: 16px;
                border-bottom-left-radius: 0px; border-bottom-right-radius: 0px;
                border: none;
            }}
        """)
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(24, 0, 24, 0)
        icon_lbl = QLabel("ℹ️" if "bildirim" not in title.lower() else "🔔")
        icon_lbl.setFont(QFont(FONTS['family'], 16))
        icon_lbl.setStyleSheet("color: white; background: transparent;")
        bl.addWidget(icon_lbl)
        t = QLabel(title)
        t.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        t.setStyleSheet("color: white; background: transparent;")
        bl.addWidget(t)
        bl.addStretch()
        ly.addWidget(banner)

        # İçerik
        content = QWidget()
        content.setStyleSheet("background: white;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(24, 20, 24, 20)

        msg = QLabel(message)
        msg.setFont(QFont(FONTS['family'], FONTS['size_md']))
        msg.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        msg.setWordWrap(True)
        cl.addWidget(msg)

        cl.addStretch()

        ok = QPushButton("Tamam")
        ok.setObjectName("primaryBtn")
        ok.setFixedHeight(42)
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self.accept)
        cl.addWidget(ok)

        ly.addWidget(content, 1)


class ToastNotification(QFrame):
    """Modern Toast Bildirimi (Snackbar) - Ekranın sağ altından belirir"""
    
    def __init__(self, parent, message, type="success"):
        super().__init__(parent)
        self.setObjectName("toastNotification")
        
        # Parent üzerinde en üstte görünmesi için
        self.raise_()
        
        colors = {
            "success": ("#10B981", "✅"),  # Yeşil
            "error": ("#EF4444", "❌"),    # Kırmızı
            "info": ("#3B82F6", "ℹ️"),      # Mavi
            "warning": ("#F59E0B", "⚠️")    # Turuncu
        }
        color, icon_char = colors.get(type, colors["success"])
        
        self.setStyleSheet(f"""
            QFrame#toastNotification {{
                background-color: white;
                border-left: 6px solid {color};
                border-radius: 8px;
            }}
        """)
        add_shadow(self, blur=15, offset_y=4, color=QColor(0, 0, 0, 40))
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 24, 14)
        layout.setSpacing(12)
        
        icon = QLabel(icon_char)
        icon.setFont(QFont(FONTS['family'], 16))
        icon.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(icon)
        
        msg_label = QLabel(message)
        msg_label.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        msg_label.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent; border: none;")
        layout.addWidget(msg_label)
        
        self.adjustSize()
        self.show()
        
        # Konumlandırma & Animasyon
        margin = 30
        parent_width = parent.width()
        parent_height = parent.height()
        
        # Sağ alt köşe
        end_x = parent_width - self.width() - margin
        end_y = parent_height - self.height() - margin
        start_x = end_x
        start_y = parent_height + 20  # Ekranın altından dışarıda başlar
        
        self.setGeometry(start_x, start_y, self.width(), self.height())
        
        # Yukarı çıkma (Geliş) Animasyonu
        self.anim_in = QPropertyAnimation(self, b"pos")
        self.anim_in.setDuration(500)
        self.anim_in.setStartValue(QPoint(start_x, start_y))
        self.anim_in.setEndValue(QPoint(end_x, end_y))
        self.anim_in.setEasingCurve(QEasingCurve.OutBack)
        self.anim_in.start()
        
        # 3.5 saniye sonra kapatma fonksiyonunu çağır
        QTimer.singleShot(3500, self.hide_toast)
        
    def hide_toast(self):
        end_x = self.x()
        end_y = self.parent().height() + 20
        
        # Aşağı inme (Gidiş) Animasyonu
        self.anim_out = QPropertyAnimation(self, b"pos")
        self.anim_out.setDuration(400)
        self.anim_out.setStartValue(self.pos())
        self.anim_out.setEndValue(QPoint(end_x, end_y))
        self.anim_out.setEasingCurve(QEasingCurve.InBack)
        self.anim_out.finished.connect(self.close)
        self.anim_out.start()
