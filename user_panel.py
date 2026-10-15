"""
NexPOS - Premium Kullanıcı (Garson) Paneli
Modern, açık tema, glassmorphism üst bar, gelişmiş dialoglar
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
    QStackedWidget, QScrollArea, QGridLayout, QDialog, QFormLayout,
    QComboBox, QSpinBox, QMessageBox, QLineEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from styles import COLORS, FONTS, ICONS
from widgets import TableCard, OrderCard, InfoDialog, add_shadow, ToastNotification, clear_layout
from menu_pages import SoldOutDialog
from floor_editor import FloorStatusView
from pos_screen import POSScreen, TicketBoard
from cloud.context import ctx
import pos
from money import format_tl
from cloud.permissions import PANEL_ROLES
import database

class UserPanel(QWidget):
    logout_signal = Signal()
    open_admin_signal = Signal()

    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user = user_data
        self._setup_ui()

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self._create_topbar())
        
        # Sayfalar
        self.pages = QStackedWidget()
        self.pages.setStyleSheet(f"background: {COLORS['bg_main']};")
        self.pages.addWidget(self._create_bolgeler_page())
        self.ticket_board = TicketBoard(self.user)
        self.pages.addWidget(self.ticket_board)
        self.pos_screen = POSScreen(self.user)
        self.pos_screen.back_requested.connect(self._close_pos)
        self.pages.addWidget(self.pos_screen)

        # NexPOS'un eski sürümünde açık kalmış adisyonlar bir kez yeni yapıya taşınır
        try:
            moved = pos.migrate_legacy_open_orders(self.user)
        except pos.OrderError:
            moved = 0
        if moved:
            ctx.request_sync()
            self._refresh_bolgeler()
        main.addWidget(self.pages, 1)

    def _create_topbar(self):
        bar = QFrame()
        bar.setFixedHeight(70)
        bar.setStyleSheet(f"background: white; border-bottom: 1px solid {COLORS['border_light']};")
        add_shadow(bar, blur=12, offset_y=4, color=QColor(0,0,0,10))
        
        ly = QHBoxLayout(bar)
        ly.setContentsMargins(24, 0, 24, 0)
        ly.setSpacing(16)

        # Marka/Alan
        logo = QLabel(f"<span style='color:{COLORS['primary']}; font-weight:bold;'>Nex</span>POS")
        logo.setFont(QFont(FONTS['family'], FONTS['size_xl']))
        logo.setStyleSheet("background: transparent;")
        ly.addWidget(logo)
        
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {COLORS['border']}; margin: 16px 0;")
        ly.addWidget(sep)

        # Tablar
        tab_frame = QFrame()
        tab_frame.setStyleSheet(f"background: {COLORS['bg_input']}; border-radius: 12px; border: 1px solid {COLORS['border_light']};")
        tab_ly = QHBoxLayout(tab_frame)
        tab_ly.setContentsMargins(6, 6, 6, 6)
        tab_ly.setSpacing(4)

        self.tab_bolgeler = QPushButton(f"{ICONS['table']}  Bölgeler")
        self.tab_siparisler = QPushButton(f"{ICONS['menu_food']}  Fiş Panosu")
        
        for i, btn in enumerate([self.tab_bolgeler, self.tab_siparisler]):
            btn.setFixedHeight(40)
            btn.setFixedWidth(160)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, x=i: self._switch_tab(x))
            tab_ly.addWidget(btn)
            
        self.tab_bolgeler.setChecked(True)
        self._update_tab_styles()
        ly.addWidget(tab_frame)

        ly.addStretch()

        # Sağ Alan
        btn_yenile = QPushButton(f"{ICONS['refresh']} Yenile")
        btn_yenile.setObjectName("ghostBtn")
        btn_yenile.clicked.connect(lambda: self._switch_tab(self.pages.currentIndex()))
        ly.addWidget(btn_yenile)

        btn_duyuru = QPushButton(f"{ICONS['bell']} Duyurular")
        btn_duyuru.setObjectName("ghostBtn")
        btn_duyuru.clicked.connect(lambda: InfoDialog("Bildirim Merkezi", "Şu an için yeni bir duyuru bulunmamaktadır.\n(Yakında: Mutfağın ilettiği uyarılar burada listelenecektir)", COLORS['info'], self).exec())
        ly.addWidget(btn_duyuru)

        if database.user_can(self.user, 'markSoldOut'):
            btn_tukendi = QPushButton("⛔ Tükendi")
            btn_tukendi.setObjectName("ghostBtn")
            btn_tukendi.setCursor(Qt.PointingHandCursor)
            btn_tukendi.clicked.connect(lambda: SoldOutDialog(self.user, self).exec())
            ly.addWidget(btn_tukendi)

        btn_vardiya = QPushButton(f"📊 Vardiyam")
        btn_vardiya.setObjectName("ghostBtn")
        btn_vardiya.clicked.connect(self._show_shift_summary)
        ly.addWidget(btn_vardiya)

        user_btn = QPushButton(f"  {ICONS['user']} {self.user.get('ad_soyad', '')}  ")
        user_btn.setCursor(Qt.PointingHandCursor)
        user_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary_bg']}; border: none; border-radius: 8px;
                padding: 10px 16px; color: {COLORS['primary']}; font-size: 13px; font-weight: bold; }}
            QPushButton:hover {{ background: {COLORS['primary']}; color: white; }}
        """)
        ly.addWidget(user_btn)
        ly.addSpacing(8)

        # Yönetici/müdür garson ekranından panele geri dönebilir
        if self.user.get('role') in PANEL_ROLES:
            admin_btn = QPushButton(f"{ICONS['chart']} Yönetim Paneli")
            admin_btn.setObjectName("ghostBtn")
            admin_btn.setCursor(Qt.PointingHandCursor)
            admin_btn.clicked.connect(self.open_admin_signal.emit)
            ly.addWidget(admin_btn)

        # Kullanıcı değiştir (giriş ekranına döner, açık siparişler olduğu yerde kalır)
        logout = QPushButton(f"{ICONS['logout']} Kullanıcı Değiştir")
        logout.setCursor(Qt.PointingHandCursor)
        logout.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['danger']}; border: none; border-radius: 8px;
                padding: 10px 16px; color: white; font-size: 13px; font-weight: bold; }}
            QPushButton:hover {{ background: {COLORS['danger_dark']}; }}
        """)
        logout.clicked.connect(self.logout_signal.emit)
        ly.addWidget(logout)
        
        return bar

    def on_menu_changed(self):
        """Menü buluttan güncellendiğinde (fiyat, tükendi) açık ekranları tazeler."""
        if self.pages.currentWidget() is self.pos_screen:
            self.pos_screen._render_products()
        else:
            self._switch_tab(self.pages.currentIndex())

    def _switch_tab(self, idx):
        if self.pages.currentWidget() is self.pos_screen and idx != 2:
            self.pos_screen._back()
            if self.pages.currentWidget() is self.pos_screen:
                return  # kullanıcı vazgeçti
        self.pages.setCurrentIndex(idx)
        self.tab_bolgeler.setChecked(idx == 0)
        self.tab_siparisler.setChecked(idx == 1)
        self._update_tab_styles()
        if idx == 0:
            self._refresh_bolgeler()
        elif idx == 1:
            self.ticket_board.refresh()

    def _update_tab_styles(self):
        active_style = f"""
            QPushButton {{ background: white; color: {COLORS['text_dark']};
                border: 1px solid {COLORS['border']}; border-radius: 8px;
                font-size: 13px; font-weight: bold; }}
        """
        inactive_style = f"""
            QPushButton {{ background: transparent; color: {COLORS['text_secondary']};
                border: none; border-radius: 8px; font-size: 13px; }}
            QPushButton:hover {{ background: rgba(0,0,0,0.04); color: {COLORS['text_primary']}; }}
        """
        
        self.tab_bolgeler.setStyleSheet(active_style if self.tab_bolgeler.isChecked() else inactive_style)
        self.tab_siparisler.setStyleSheet(active_style if self.tab_siparisler.isChecked() else inactive_style)
        
        if self.tab_bolgeler.isChecked():
            add_shadow(self.tab_bolgeler, blur=8, offset_y=2, color=QColor(0,0,0,10))
            self.tab_siparisler.setGraphicsEffect(None)
        else:
            add_shadow(self.tab_siparisler, blur=8, offset_y=2, color=QColor(0,0,0,10))
            self.tab_bolgeler.setGraphicsEffect(None)

    # ==================== BÖLGELER ====================
    def _create_bolgeler_page(self):
        page = QWidget()
        ly = QVBoxLayout(page)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        # Bölge filtreleri
        self.region_tabs_layout = QHBoxLayout()
        self.region_tabs_layout.setSpacing(12)
        self.region_tabs_layout.setAlignment(Qt.AlignLeft)
        ly.addLayout(self.region_tabs_layout)

        # Plan / Liste görünümü (seçim bu bilgisayarda hatırlanır)
        self.floor_mode = database.get_sync_state('ui:floor_view', 'plan')
        self.view_toggle = QPushButton()
        self.view_toggle.setCursor(Qt.PointingHandCursor)
        self.view_toggle.setObjectName("ghostBtn")
        self.view_toggle.clicked.connect(self._toggle_floor_mode)

        self.table_stack = QStackedWidget()
        self.user_masa_scroll = QScrollArea()
        self.user_masa_scroll.setWidgetResizable(True)
        self.user_masa_scroll.setStyleSheet("border: none; background: transparent;")
        self.floor_view = FloorStatusView()
        self.floor_view.table_clicked.connect(self._on_table_clicked)
        self.floor_view.reserve_toggled.connect(self._toggle_reserved)
        self.table_stack.addWidget(self.user_masa_scroll)
        self.table_stack.addWidget(self.floor_view)
        ly.addWidget(self.table_stack, 1)

        self.current_region = None
        self._refresh_bolgeler()
        return page

    def _refresh_bolgeler(self):
        clear_layout(self.region_tabs_layout, keep=(self.view_toggle,))

        regions = database.get_all_regions()
        
        # Current region kontrolü
        valid_rids = [r['id'] for r in regions]
        if self.current_region not in valid_rids and regions:
            self.current_region = regions[0]['id']

        for region in regions:
            tables = database.get_tables_by_region(region['id'])
            occ = sum(1 for t in tables if t['durum'] in ('dolu', 'hesap'))
            total = len(tables)

            btn = QPushButton(f"{region['ad']} ({occ}/{total})")
            btn.setCursor(Qt.PointingHandCursor)
            
            if region['id'] == self.current_region:
                btn.setStyleSheet(f"""
                    QPushButton {{ background-color: {COLORS['primary']}; color: white;
                        border: none; border-radius: 18px; padding: 10px 24px; font-weight: bold; font-size: 14px; }}
                """)
                add_shadow(btn, blur=12, offset_y=4, color=QColor(79, 70, 229, 60))
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #F8FAFC, stop:1 #E2E8F0); color: {COLORS['text_primary']};
                        border: 1px solid #CBD5E1; border-radius: 18px; padding: 10px 24px; font-weight: bold; font-size: 14px; }}
                    QPushButton:hover {{ background: #E2E8F0; border-color: {COLORS['primary_light']}; }}
                """)
                
            rid = region['id']
            btn.clicked.connect(lambda _, r=rid: self._select_region(r))
            self.region_tabs_layout.addWidget(btn)

        self.region_tabs_layout.addStretch()
        # Açık masasız (gel-al / paket) siparişler ve yenisini açma düğmesi
        for o in pos.open_orders('takeaway'):
            chip = QPushButton(f"🛍 {o['no']} · {format_tl(o['total'])}")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(f"""
                QPushButton {{ background: {COLORS['bg_warning']}; color: {COLORS['warning_dark']}; border: none;
                    border-radius: 16px; padding: 8px 14px; font-weight: bold; }}
                QPushButton:hover {{ border: 2px solid {COLORS['warning']}; }}
            """)
            chip.clicked.connect(lambda _, oid=o['id']: self._open_takeaway(oid))
            self.region_tabs_layout.addWidget(chip)
        takeaway = QPushButton("+ Masasız sipariş")
        takeaway.setCursor(Qt.PointingHandCursor)
        takeaway.setObjectName("ghostBtn")
        takeaway.clicked.connect(lambda: self._open_takeaway())
        self.region_tabs_layout.addWidget(takeaway)
        self.region_tabs_layout.addWidget(self.view_toggle)
        self._load_tables(self.current_region)

    def _toggle_floor_mode(self):
        self.floor_mode = 'list' if self.floor_mode == 'plan' else 'plan'
        database.set_sync_state('ui:floor_view', self.floor_mode)
        self._refresh_bolgeler()

    def _toggle_reserved(self, table):
        reserve = table.get('durum') == 'bos'
        if database.set_table_reserved(table['id'], reserve, staff_id=self.user['cloud_id']):
            ToastNotification(self, f"{table['ad']} {'rezerve edildi' if reserve else 'rezervasyonu kaldırıldı'}.", "info")
        self._refresh_bolgeler()

    def _select_region(self, rid):
        self.current_region = rid
        self._refresh_bolgeler()

    def _load_tables(self, rid):
        if not rid:
            return
        region = next((r for r in database.get_all_regions() if r['id'] == rid), None)
        has_plan = bool(region and region.get('cloud_id') and database.menu_item('areas', region['cloud_id']))
        use_plan = has_plan and self.floor_mode == 'plan'
        self.view_toggle.setVisible(has_plan)
        self.view_toggle.setText("☰  Liste görünümü" if use_plan else "▦  Plan görünümü")
        if use_plan:
            self.floor_view.show_area(region['cloud_id'])
            self.table_stack.setCurrentWidget(self.floor_view)
            return
        self.table_stack.setCurrentWidget(self.user_masa_scroll)

        tables = database.get_tables_by_region(rid)
        cw = QWidget()
        cw.setStyleSheet("background: transparent;")
        grid = QGridLayout(cw)
        grid.setSpacing(20)
        grid.setContentsMargins(0, 16, 0, 16)
        
        for i, t in enumerate(tables):
            card = TableCard(t)
            card.clicked.connect(self._on_table_clicked)
            grid.addWidget(card, i // 6, i % 6)
            
        grid.setRowStretch(grid.rowCount(), 1)
        grid.setColumnStretch(grid.columnCount(), 1)
        self.user_masa_scroll.setWidget(cw)

    def _on_table_clicked(self, data):
        """Masaya dokunulunca sipariş ekranı açılır (boş masada yeni, dolu masada mevcut adisyon)."""
        if not data.get('cloud_id'):
            QMessageBox.information(self, "Masa planı gerekli",
                                    "Sipariş alabilmek için yönetim panelinden salon planını buluta aktarın "
                                    "(Tanımlamalar → Masa / Bölgeler → Buluta Aktar).")
            return
        self.pos_screen.open_table({'id': data['cloud_id'], 'name': data['ad']})
        self._show_pos()

    def _open_takeaway(self, order_id=None):
        if order_id:
            self.pos_screen.open_existing(order_id)
        elif not self.pos_screen.new_takeaway():
            return
        self._show_pos()

    def _show_pos(self):
        self.pages.setCurrentWidget(self.pos_screen)
        self.tab_bolgeler.setChecked(True)
        self.tab_siparisler.setChecked(False)
        self._update_tab_styles()

    def _close_pos(self):
        self.pages.setCurrentIndex(0)
        self._refresh_bolgeler()

    def _show_shift_summary(self):
        summary = database.get_shift_summary(self.user['id'])
        tutar = summary['toplam_tutar'] or 0
        sayi = summary['siparis_sayisi'] or 0
        InfoDialog(
            "Vardiya Özetim",
            f"Bugünkü performansınız:\n\n"
            f"✅  Tamamlanan Sipariş: {sayi} adet\n"
            f"💰  Toplam Ciro: ₺{tutar:,.2f}\n"
            f"📊  Ortalama Adisyon: ₺{(tutar/sayi if sayi else 0):,.2f}",
            COLORS['success'], self
        ).exec()

