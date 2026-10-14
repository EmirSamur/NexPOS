"""
NexPOS - Premium Admin Paneli
Koyu sidebar, glassmorphism üst bar, tam fonksiyonlu dashboard ve animasyonlu widgetlar.
"""
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
    QStackedWidget, QScrollArea, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QDateEdit, QDialog, QFormLayout,
    QMessageBox, QHeaderView, QGridLayout, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal, QDate, QTimer, QRegularExpression
from PySide6.QtGui import QFont, QColor, QDoubleValidator, QRegularExpressionValidator, QIntValidator
from styles import COLORS, FONTS, ICONS
from widgets import (StatCard, TableCard, ProductCard, SidebarButton,
                     ExpandableSection, PageHeader, BarChart, DonutChart, InfoDialog, add_shadow, ToastNotification)
from admin_access_pages import StaffPage, PermissionsPage, TerminalsPage
from menu_pages import MenuPage
from cloud.permissions import PANEL_ROLES
import database

# Sayfa → görmek için gereken yetki (None: herkes). Sıra, self.pages sırasıyla aynıdır.
PAGE_PERMISSIONS = [
    'viewReports',   # 0 Dashboard
    'editMenu',      # 1 Masa / Bölgeler
    'editMenu',      # 2 Menü / Ürünler
    'expense',       # 3 Gider
    'expense',       # 4 Zayi
    'viewReports',   # 5 İstatistikler
    'manageUsers',   # 6 Kullanıcılar
    'manageUsers',   # 7 Yetkiler
    'settings',      # 8 Ayarlar
    'settings',      # 9 Terminaller
]

class AdminPanel(QWidget):
    logout_signal = Signal()
    open_pos_signal = Signal()

    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.user = user_data
        self._setup_ui()
        
        # Sistemi test etmesi için açılışta bir Toast bildirimi gösterelim
        QTimer.singleShot(600, lambda: ToastNotification(self, f"Hoş Geldiniz, {self.user.get('ad_soyad', 'Kullanıcı')}!", "success"))

    def _setup_ui(self):
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(self._create_sidebar())

        content_w = QVBoxLayout()
        content_w.setContentsMargins(0, 0, 0, 0)
        content_w.setSpacing(0)
        content_w.addWidget(self._create_topbar())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._create_dashboard_page())     # 0
        self.pages.addWidget(self._create_masa_bolge_page())    # 1
        self.pages.addWidget(self._create_menu_urunler_page())  # 2
        self.pages.addWidget(self._create_gider_masraf_page())  # 3
        self.pages.addWidget(self._create_zayi_page())          # 4
        self.pages.addWidget(self._create_raporlar_page())      # 5
        self.pages.addWidget(self._create_kullanicilar_page())  # 6
        self.pages.addWidget(self._create_yetkiler_page())      # 7
        self.pages.addWidget(self._create_settings_page())      # 8
        self.terminals_page = TerminalsPage(self.user)
        self.pages.addWidget(self.terminals_page)               # 9
        content_w.addWidget(self.pages, 1)

        cf = QFrame()
        cf.setLayout(content_w)
        cf.setStyleSheet(f"background-color: {COLORS['bg_main']};")
        main.addWidget(cf, 1)
        self._apply_permissions()

    def _can_see(self, idx):
        perm = PAGE_PERMISSIONS[idx] if idx < len(PAGE_PERMISSIONS) else None
        return perm is None or database.user_can(self.user, perm)

    def _apply_permissions(self):
        """Yetkisi olmayan sayfaların menü düğmelerini gizler, ilk görünür sayfayı açar."""
        for idx, btn in enumerate(self.sidebar_buttons):
            btn.setVisible(self._can_see(idx))
        first = next((i for i in range(self.pages.count()) if self._can_see(i)), None)
        if first is None:
            self.pages.setCurrentIndex(0)
            self.pages.currentWidget().setEnabled(False)
        else:
            self._show_page(first)

    def _create_sidebar(self):
        sidebar = QFrame()
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS['sidebar_bg']}; border-right: none; }}
        """)
        add_shadow(sidebar, blur=20, offset_y=0, color=QColor(0,0,0,50))
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Logo header
        logo_f = QFrame()
        logo_f.setFixedHeight(75)
        logo_f.setStyleSheet(f"background: {COLORS['sidebar_header']};")
        ll = QHBoxLayout(logo_f)
        ll.setContentsMargins(20, 0, 20, 0)
        
        logo_circle = QFrame()
        logo_circle.setFixedSize(36, 36)
        logo_circle.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {COLORS['primary_light']}, stop:1 {COLORS['primary']});
            border-radius: 18px;
        """)
        lc_ly = QVBoxLayout(logo_circle)
        lc_ly.setContentsMargins(0, 0, 0, 0)
        lc_txt = QLabel("N")
        lc_txt.setAlignment(Qt.AlignCenter)
        lc_txt.setFont(QFont(FONTS['family'], 18, QFont.Bold))
        lc_txt.setStyleSheet("color: white; background: transparent;")
        lc_ly.addWidget(lc_txt)
        ll.addWidget(logo_circle)
        ll.addSpacing(12)
        
        text_ly = QVBoxLayout()
        text_ly.setSpacing(0)
        ltxt = QLabel("NexPOS")
        ltxt.setFont(QFont(FONTS['family'], 18, QFont.Bold))
        ltxt.setStyleSheet("color: white; background: transparent;")
        ver = QLabel("v3.2")
        ver.setFont(QFont(FONTS['family'], 9))
        ver.setStyleSheet(f"color: {COLORS['sidebar_text']}; background: transparent;")
        text_ly.addWidget(ltxt)
        text_ly.addWidget(ver)
        text_ly.addStretch()
        ll.addLayout(text_ly)
        ll.addStretch()
        layout.addWidget(logo_f)

        # İşletme adı
        shop = QLabel(f"  {ICONS['home']}  VELVET LOUNGE - 34001")
        shop.setFixedHeight(40)
        shop.setFont(QFont(FONTS['family'], FONTS['size_xs'], QFont.Bold))
        shop.setStyleSheet(f"color: {COLORS['sidebar_text_active']}; background: rgba(255,255,255,0.05); padding-left: 12px;")
        layout.addWidget(shop)
        layout.addSpacing(10)

        # Menü scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")
        mw = QWidget()
        mw.setStyleSheet("background: transparent;")
        self.menu_layout = QVBoxLayout(mw)
        self.menu_layout.setContentsMargins(0, 4, 0, 4)
        self.menu_layout.setSpacing(4)

        self.sidebar_buttons = []

        btn_home = SidebarButton("Ana Sayfa", ICONS['chart'])
        btn_home.clicked.connect(lambda: self._show_page(0))
        self.menu_layout.addWidget(btn_home)
        self.sidebar_buttons.append(btn_home)

        tan = ExpandableSection("Tanımlamalar", ICONS['table'])
        btn_masa = tan.add_sub_button("Masa / Bölgeler", ICONS['dot'])
        btn_masa.clicked.connect(lambda: self._show_page(1))
        self.sidebar_buttons.append(btn_masa)
        btn_menu = tan.add_sub_button("Menü / Ürünler", ICONS['dot'])
        btn_menu.clicked.connect(lambda: self._show_page(2))
        self.sidebar_buttons.append(btn_menu)
        self.menu_layout.addWidget(tan)

        btn_siparis = SidebarButton("Sipariş (Garson Ekranı)", ICONS['menu_food'])
        btn_siparis.clicked.connect(self.open_pos_signal.emit)
        self.menu_layout.addWidget(btn_siparis)

        isl = ExpandableSection("İşlemler", ICONS['money'])
        btn_gd = isl.add_sub_button("Gider / Masraf", ICONS['dot'])
        btn_gd.clicked.connect(lambda: self._show_page(3))
        self.sidebar_buttons.append(btn_gd)
        btn_zy = isl.add_sub_button("Zayi İşlemleri", ICONS['dot'])
        btn_zy.clicked.connect(lambda: self._show_page(4))
        self.sidebar_buttons.append(btn_zy)
        self.menu_layout.addWidget(isl)

        rap = ExpandableSection("Raporlar", ICONS['chart'])
        btn_rapor = rap.add_sub_button("İstatistikler", ICONS['dot'])
        btn_rapor.clicked.connect(lambda: self._show_page(5))
        self.sidebar_buttons.append(btn_rapor)
        self.menu_layout.addWidget(rap)

        kul = ExpandableSection("Kullanıcılar", ICONS['user'])
        btn_k = kul.add_sub_button("Kullanıcı Listesi", ICONS['dot'])
        btn_k.clicked.connect(lambda: self._show_page(6))
        self.sidebar_buttons.append(btn_k)
        btn_y = kul.add_sub_button("Yetkiler", ICONS['dot'])
        btn_y.clicked.connect(lambda: self._show_page(7))
        self.sidebar_buttons.append(btn_y)
        self.menu_layout.addWidget(kul)

        btn_ayar = SidebarButton("Ayarlar", ICONS['settings'])
        btn_ayar.clicked.connect(lambda: self._show_page(8))
        self.sidebar_buttons.append(btn_ayar)
        self.menu_layout.addWidget(btn_ayar)

        btn_term = SidebarButton("Terminaller", ICONS['table'])
        btn_term.clicked.connect(lambda: self._show_page(9))
        self.sidebar_buttons.append(btn_term)
        self.menu_layout.addWidget(btn_term)

        self.menu_layout.addStretch()

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,0.1); margin: 0 16px;")
        self.menu_layout.addWidget(sep)

        # Çıkış
        logout = QPushButton(f"  {ICONS['logout']}   Kullanıcı Değiştir")
        logout.setFixedHeight(50)
        logout.setCursor(Qt.PointingHandCursor)
        logout.setStyleSheet(f"""
            QPushButton {{ border: none; text-align: left; padding-left: 20px;
                font-size: {FONTS['size_md']}px; color: {COLORS['danger']};
                background: transparent; font-weight: bold; margin: 4px 8px; border-radius: 8px; }}
            QPushButton:hover {{ background: rgba(239, 68, 68, 0.1); }}
        """)
        logout.clicked.connect(self.logout_signal.emit)
        self.menu_layout.addWidget(logout)

        scroll.setWidget(mw)
        layout.addWidget(scroll, 1)
        return sidebar

    def _create_topbar(self):
        bar = QFrame()
        bar.setFixedHeight(64)
        bar.setStyleSheet(f"background: white; border-bottom: 1px solid {COLORS['border']};")
        add_shadow(bar, blur=8, offset_y=2, color=QColor(0,0,0,10))
        ly = QHBoxLayout(bar)
        ly.setContentsMargins(24, 0, 24, 0)
        ly.setSpacing(12)

        self.page_title = QLabel("Velvet Lounge Analytics")
        self.page_title.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        self.page_title.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent;")
        ly.addWidget(self.page_title)
        ly.addStretch()

        # Uniform Buton Stili
        def apply_topbar_style(btn, bg, border, color):
            btn.setFixedHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{ background: {bg}; border: 1px solid {border}; border-radius: 8px;
                    padding: 0 16px; color: {color}; font-size: 12px; font-weight: bold; }}
                QPushButton:hover {{ background: {border}; color: white; }}
            """)

        btn_katil = QPushButton("Katıl")
        apply_topbar_style(btn_katil, "transparent", COLORS['primary'], COLORS['primary'])
        btn_katil.clicked.connect(lambda: ToastNotification(self, "Kurumsal ağa katılma isteği gönderildi.", "info"))
        ly.addWidget(btn_katil)

        btn_yenile = QPushButton(ICONS['refresh'] + " Yenile")
        apply_topbar_style(btn_yenile, "transparent", COLORS['border'], COLORS['text_secondary'])
        btn_yenile.setStyleSheet(btn_yenile.styleSheet().replace("color: white;", f"color: {COLORS['text_primary']}; background: {COLORS['bg_hover']};"))
        btn_yenile.clicked.connect(lambda: self._show_page(self.pages.currentIndex()))
        ly.addWidget(btn_yenile)

        ly.addSpacing(16)

        kasa = QPushButton("Kasa İşlemleri")
        apply_topbar_style(kasa, COLORS['bg_warning'], COLORS['warning'], COLORS['warning_dark'])
        kasa.clicked.connect(lambda: InfoDialog("Kasa İşlemleri", "Son açılış: Bugün 08:30\nKasadaki Nakit: ₺1,450.00\nKasa işlemlerine sadece yöneticiler müdahale edebilir.", COLORS['warning'], self).exec())
        ly.addWidget(kasa)

        destek = QPushButton("Destek İste")
        apply_topbar_style(destek, COLORS['bg_danger'], COLORS['danger'], COLORS['danger_dark'])
        destek.clicked.connect(lambda: InfoDialog("Destek Çağrısı", "Destek talebiniz NexPOS destek ekibine iletildi. En kısa sürede sizinle iletişime geçilecektir.", COLORS['danger'], self).exec())
        ly.addWidget(destek)

        # Kullanıcı profili
        user_btn = QPushButton(f"  {ICONS['user']} {self.user.get('ad_soyad', '')}  ")
        user_btn.setCursor(Qt.PointingHandCursor)
        user_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary_bg']}; border: none; border-radius: 8px;
                padding: 8px 16px; color: {COLORS['primary']}; font-size: 13px; font-weight: bold; }}
            QPushButton:hover {{ background: {COLORS['primary']}; color: white; }}
        """)
        ly.addWidget(user_btn)
        return bar

    def _show_page(self, idx):
        if not self._can_see(idx):
            return
        self.pages.setCurrentIndex(idx)
        page = self.pages.widget(idx)
        if hasattr(page, 'refresh_local'):
            page.refresh_local()
        elif hasattr(page, 'refresh'):
            page.refresh()
        for b in self.sidebar_buttons:
            b.setChecked(False)
        if idx < len(self.sidebar_buttons):
            self.sidebar_buttons[idx].setChecked(True)
        titles = ["Dashboard Analytics", "Tanımlamalar / Masa ve Bölgeler",
                   "Kategori ve Ürün Tanımlama / Şube Ürünleri",
                   "Gider/Masraf İşlemleri", "Zayi İşlemleri",
                   "Restaurant İstatistikleri", "Kullanıcılar", "Yetki / İzin Ekranı", "Sistem Ayarları",
                   "Terminaller"]
        if idx < len(titles):
            self.page_title.setText(titles[idx])

    # ==================== DASHBOARD ====================
    def _create_dashboard_page(self):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        ly = QVBoxLayout(content)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(24)

        stats = database.get_dashboard_stats()

        # Hoş Geldiniz Banner
        from datetime import datetime
        hour = datetime.now().hour
        if hour < 12:
            greeting = "Günaydın"
            greeting_icon = "☀️"
        elif hour < 18:
            greeting = "İyi Günler"
            greeting_icon = "🌤️"
        else:
            greeting = "İyi Akşamlar"
            greeting_icon = "🌙"
        
        welcome_frame = QFrame()
        welcome_frame.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {COLORS['primary']}, stop:0.6 {COLORS['primary_dark']}, stop:1 #312E81);
                border-radius: 16px; border: none;
            }}
        """)
        add_shadow(welcome_frame, blur=20, offset_y=6, color=QColor(79, 70, 229, 50))
        wl = QHBoxLayout(welcome_frame)
        wl.setContentsMargins(32, 20, 32, 20)
        
        w_text_ly = QVBoxLayout()
        w_text_ly.setSpacing(4)
        w_greet = QLabel(f"{greeting_icon}  {greeting}, {self.user.get('ad_soyad', 'Yönetici')}!")
        w_greet.setFont(QFont(FONTS['family'], FONTS['size_xl'], QFont.Bold))
        w_greet.setStyleSheet("color: white; background: transparent;")
        w_sub = QLabel(f"Velvet Lounge yönetim panelinize hoş geldiniz. Son 30 günlük özetiniz aşağıda.")
        w_sub.setFont(QFont(FONTS['family'], FONTS['size_sm']))
        w_sub.setStyleSheet("color: rgba(255,255,255,0.7); background: transparent;")
        w_text_ly.addWidget(w_greet)
        w_text_ly.addWidget(w_sub)
        wl.addLayout(w_text_ly, 1)
        
        w_date = QLabel(datetime.now().strftime("%d %B %Y, %A").replace(
            "Monday", "Pazartesi").replace("Tuesday", "Salı").replace("Wednesday", "Çarşamba").replace(
            "Thursday", "Perşembe").replace("Friday", "Cuma").replace("Saturday", "Cumartesi").replace(
            "Sunday", "Pazar").replace("January", "Ocak").replace("February", "Şubat").replace(
            "March", "Mart").replace("April", "Nisan").replace("May", "Mayıs").replace(
            "June", "Haziran").replace("July", "Temmuz").replace("August", "Ağustos").replace(
            "September", "Eylül").replace("October", "Ekim").replace("November", "Kasım").replace(
            "December", "Aralık"))
        w_date.setFont(QFont(FONTS['family'], FONTS['size_md']))
        w_date.setStyleSheet("color: rgba(255,255,255,0.6); background: transparent;")
        wl.addWidget(w_date)
        ly.addWidget(welcome_frame)

        # Premium kartlar
        cards = QHBoxLayout()
        cards.setSpacing(16)
        data = [
            (ICONS['money'], "Son 30 Gün Satış", f"₺{stats['total_sales']:,.2f}", "Tamamlanan siparişler", COLORS['primary'], COLORS['primary_bg']),
            (ICONS['user'], "Ağırlanan Misafir", str(stats['guest_count']), "+%12 düne göre", COLORS['success'], COLORS['bg_success']),
            (ICONS['menu_food'], "Açık Siparişler", f"₺{stats['open_orders']:,.2f}", "Hazırlanıyor", COLORS['warning'], COLORS['bg_warning']),
            (ICONS['arrow_down'], "Son 30 Gün Giderler", f"₺{stats['total_expense']:,.2f}", "Masraflar", COLORS['danger'], COLORS['bg_danger']),
        ]
        for icon, title, val, sub, color, bg in data:
            c = StatCard(icon, title, val, sub, color, bg)
            cards.addWidget(c, 1)
        ly.addLayout(cards)

        # Grafikler
        chart_row = QHBoxLayout()
        chart_row.setSpacing(20)

        # Bar chart alanı
        bar_chart_frame = QFrame()
        bar_chart_frame.setStyleSheet(f"background: white; border: 1px solid {COLORS['border']}; border-radius: 16px;")
        add_shadow(bar_chart_frame, blur=15, offset_y=4, color=QColor(0,0,0,10))
        bl = QVBoxLayout(bar_chart_frame)
        bl.setContentsMargins(24, 20, 24, 20)
        
        b_header = QHBoxLayout()
        b_title = QLabel("Saatlik Satış Dağılımı")
        b_title.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        b_title.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        b_header.addWidget(b_title)
        b_header.addStretch()
        bl.addLayout(b_header)

        self.bar_chart = BarChart([
            ("08:00", 120), ("10:00", 350), ("12:00", 850), 
            ("14:00", 620), ("16:00", 710), ("18:00", 1250),
            ("20:00", 1540), ("22:00", 980)
        ])
        bl.addWidget(self.bar_chart)
        chart_row.addWidget(bar_chart_frame, 2)

        # Donut chart
        donut_frame = QFrame()
        donut_frame.setStyleSheet(f"background: white; border: 1px solid {COLORS['border']}; border-radius: 16px;")
        add_shadow(donut_frame, blur=15, offset_y=4, color=QColor(0,0,0,10))
        dl = QVBoxLayout(donut_frame)
        dl.setContentsMargins(24, 20, 24, 20)
        
        d_title = QLabel("Masa Doluluk Oranı")
        d_title.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        d_title.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        dl.addWidget(d_title)

        total = max(stats['total_tables'], 1)
        occ_pct = int(stats['occupied_tables'] / total * 100)
        
        dl.addStretch()
        donut_ly = QHBoxLayout()
        donut_ly.addStretch()
        self.donut_chart = DonutChart(percentage=occ_pct, color=COLORS['primary'])
        donut_ly.addWidget(self.donut_chart)
        donut_ly.addStretch()
        dl.addLayout(donut_ly)
        dl.addStretch()

        detail = QLabel(f"<span style='color:{COLORS['primary']}; font-weight:bold;'>{stats['occupied_tables']} Dolu</span> / {total} Toplam Masa")
        detail.setAlignment(Qt.AlignCenter)
        detail.setStyleSheet(f"color: {COLORS['text_secondary']};")
        dl.addWidget(detail)
        
        chart_row.addWidget(donut_frame, 1)

        ly.addLayout(chart_row)
        ly.addStretch()

        scroll.setWidget(content)
        pg = QVBoxLayout(page)
        pg.setContentsMargins(0, 0, 0, 0)
        pg.addWidget(scroll)
        return page

    # ==================== MASA / BÖLGELER ====================
    def _create_masa_bolge_page(self):
        page = QWidget()
        ly = QVBoxLayout(page)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        header = PageHeader("Masa & Bölge Yönetimi",
                           "Restoranınıza ait fiziksel alanları ve masaları konfigüre edin.",
                           COLORS['primary'], ICONS['table'])
        ly.addWidget(header)

        # Aksiyonlar
        acts = QHBoxLayout()
        acts.addStretch()
        
        btn_duzenle = QPushButton(f"{ICONS['edit']} Bölgeleri Düzenle")
        btn_duzenle.setObjectName("ghostBtn")
        btn_duzenle.clicked.connect(lambda: InfoDialog("Bölgeleri Düzenle", "Bölge sıralamasını ve ayarlarını değiştirmek için yakında gelişmiş sürükle-bırak desteği eklenecektir.", COLORS['info'], self).exec())

        btn_yeni_bolge = QPushButton(f"{ICONS['plus']} Yeni Bölge")
        btn_yeni_bolge.setObjectName("outlineBtn")
        btn_yeni_bolge.clicked.connect(self._add_region_dialog)

        btn_yeni_masa = QPushButton(f"{ICONS['plus']} Yeni Masa")
        btn_yeni_masa.setFixedHeight(44)
        btn_yeni_masa.setCursor(Qt.PointingHandCursor)
        btn_yeni_masa.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary']}; border: none; color: white;
                font-size: 14px; font-weight: bold; border-radius: 8px; padding: 0 20px; }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        btn_yeni_masa.clicked.connect(self._add_table_dialog)

        acts.addWidget(btn_duzenle)
        acts.addSpacing(16)
        acts.addWidget(btn_yeni_bolge)
        acts.addWidget(btn_yeni_masa)
        ly.addLayout(acts)

        # Bölge tabları
        self.admin_region_tabs = QHBoxLayout()
        self.admin_region_tabs.setSpacing(8)
        ly.addLayout(self.admin_region_tabs)

        self.masa_scroll = QScrollArea()
        self.masa_scroll.setWidgetResizable(True)
        self.masa_scroll.setStyleSheet("border: none; background: transparent;")
        ly.addWidget(self.masa_scroll, 1)

        self.admin_current_region = None
        self._refresh_masa_grid()
        return page

    def _refresh_masa_grid(self):
        while self.admin_region_tabs.count():
            item = self.admin_region_tabs.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        regions = database.get_all_regions()
        if not self.admin_current_region and regions:
            self.admin_current_region = regions[0]['id']

        for r in regions:
            btn = QPushButton(r['ad'])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setChecked(r['id'] == self.admin_current_region)
            rid = r['id']
            btn.clicked.connect(lambda _, rid=rid: self._select_admin_region(rid))

            if btn.isChecked():
                btn.setStyleSheet(f"""
                    QPushButton {{ border: none; border-bottom: 3px solid {COLORS['primary']};
                        padding: 8px 24px; font-size: {FONTS['size_md']}px;
                        font-weight: bold; color: {COLORS['primary']}; background: transparent; }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ border: none; padding: 8px 24px; border-bottom: 3px solid transparent;
                        font-size: {FONTS['size_md']}px; color: {COLORS['text_secondary']};
                        background: transparent; font-weight: bold; }}
                    QPushButton:hover {{ color: {COLORS['text_primary']}; background: {COLORS['bg_hover']}; border-radius: 4px; }}
                """)
            self.admin_region_tabs.addWidget(btn)
        self.admin_region_tabs.addStretch()

        if self.admin_current_region:
            tables = database.get_tables_by_region(self.admin_current_region)
            cw = QWidget()
            cw.setStyleSheet("background: transparent;")
            grid = QGridLayout(cw)
            grid.setSpacing(16)
            grid.setContentsMargins(0, 16, 0, 16)
            for i, t in enumerate(tables):
                card = self._create_admin_table_card(t)
                grid.addWidget(card, i // 5, i % 5)
            # Add stretch to push items to top-left
            grid.setRowStretch(grid.rowCount(), 1)
            grid.setColumnStretch(grid.columnCount(), 1)
            self.masa_scroll.setWidget(cw)

    def _create_admin_table_card(self, t):
        card = QFrame()
        card.setFixedSize(190, 110)
        card.setStyleSheet(f"""
            QFrame {{ background: white; border: 1px solid {COLORS['border']}; border-radius: 12px; }}
            QFrame:hover {{ border-color: {COLORS['primary_light']}; }}
        """)
        add_shadow(card, blur=10, offset_y=2, color=QColor(0,0,0,10))
        ly = QVBoxLayout(card)
        ly.setContentsMargins(14, 10, 14, 10)

        top = QHBoxLayout()
        top.addStretch()
        edit_btn = QPushButton(f"{ICONS['edit']} Düzenle")
        edit_btn.setFixedSize(65, 24)
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setStyleSheet(f"""
            QPushButton {{ border: 1px solid {COLORS['primary']}; font-size: 10px; font-weight: bold;
                background: {COLORS['primary_bg']}; color: {COLORS['primary']}; border-radius: 6px; }}
            QPushButton:hover {{ background: {COLORS['primary']}; color: white; }}
        """)
        m_id = t['id']
        m_ad = t['ad']
        m_durum = t.get('durum', 'bos')

        def edit_table_action():
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Masa Düzenle — {m_ad}")
            dlg.setFixedSize(360, 200)
            fl = QFormLayout(dlg)
            fl.setContentsMargins(28, 24, 28, 24)
            fl.setSpacing(14)
            ad_edit = QLineEdit(m_ad)
            ad_edit.setFixedHeight(38)
            fl.addRow("Masa Adı:", ad_edit)
            warn = QLabel("")
            warn.setStyleSheet(f"color: {COLORS['danger']}; font-size: 11px;")
            fl.addRow(warn)
            btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Discard | QDialogButtonBox.Cancel)
            btns.button(QDialogButtonBox.Save).setText("Kaydet")
            btns.button(QDialogButtonBox.Cancel).setText("İptal")
            btns.button(QDialogButtonBox.Discard).setText("Masayı Sil")
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            btns.button(QDialogButtonBox.Discard).clicked.connect(lambda: setattr(dlg, '_delete', True) or dlg.accept())
            fl.addRow(btns)
            dlg._delete = False
            if dlg.exec() == QDialog.Accepted:
                if dlg._delete:
                    if m_durum == 'dolu':
                        QMessageBox.warning(self, "Uyarı", "Dolu masalar silinemez! Önce masayı kapatın.")
                        return
                    ok = database.delete_table(m_id)
                    if ok:
                        self._refresh_masa_grid()
                        ToastNotification(self, f"{m_ad} silindi.", "warning")
                    else:
                        QMessageBox.warning(self, "Uyarı", "Dolu masa silinemez!")
                else:
                    new_name = ad_edit.text().strip()
                    if not new_name:
                        return
                    conn = database.get_connection()
                    conn.execute("UPDATE tables SET ad=? WHERE id=?", (new_name, m_id))
                    conn.commit()
                    conn.close()
                    self._refresh_masa_grid()
                    ToastNotification(self, f"Masa adı güncellendi.", "success")

        edit_btn.clicked.connect(edit_table_action)
        top.addWidget(edit_btn)
        ly.addLayout(top)

        name = QLabel(t['ad'])
        name.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet(f"color: {COLORS['text_dark']}; background: transparent;")
        ly.addWidget(name)
        ly.addStretch()

        return card

    def _select_admin_region(self, rid):
        self.admin_current_region = rid
        self._refresh_masa_grid()

    def _add_region_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Yeni Bölge Ekle")
        dlg.setFixedSize(400, 200)
        form = QFormLayout(dlg)
        form.setContentsMargins(32, 28, 32, 28)
        form.setSpacing(16)
        inp = QLineEdit()
        inp.setPlaceholderText("Bölge adı girin...")
        form.addRow(QLabel("Bölge Adı:"), inp)
        btn = QPushButton("Bölge Ekle")
        btn.setObjectName("primaryBtn")
        btn.clicked.connect(lambda: (database.add_region(inp.text().strip()), dlg.accept(), self._refresh_masa_grid()) if inp.text().strip() else None)
        form.addRow(btn)
        dlg.exec()

    def _add_table_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Yeni Masa Ekle")
        dlg.setFixedSize(400, 260)
        form = QFormLayout(dlg)
        form.setContentsMargins(32, 28, 32, 28)
        form.setSpacing(16)
        name = QLineEdit()
        name.setPlaceholderText("Masa adı (örn: M-1)")
        rc = QComboBox()
        for r in database.get_all_regions():
            rc.addItem(r['ad'], r['id'])
        form.addRow(QLabel("Masa Adı:"), name)
        form.addRow(QLabel("Bölge Seçimi:"), rc)
        btn = QPushButton("Masa Ekle")
        btn.setObjectName("primaryBtn")
        btn.clicked.connect(lambda: (database.add_table(name.text().strip(), rc.currentData()), dlg.accept(), self._refresh_masa_grid()) if name.text().strip() else None)
        form.addRow(btn)
        dlg.exec()

    # ==================== MENÜ / ÜRÜNLER ====================
    def _create_menu_urunler_page(self):
        self.menu_page = MenuPage(self.user)
        return self.menu_page

    def on_sync_status(self, status):
        """Ana pencere her senkronda çağırır: menü sayfası çevrimiçi durumu ve değişiklikleri günceller."""
        self.menu_page.on_sync_status(status)

    # ==================== GİDER / MASRAF ====================
    def _create_gider_masraf_page(self):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        ly = QVBoxLayout(content)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        hr = QHBoxLayout()
        header = PageHeader("Gider ve Masraflar", "İşletme giderlerinizi detaylı takip edin.", COLORS['warning'], ICONS['arrow_down'])
        hr.addWidget(header, 1)

        csv_btn = QPushButton(f"{ICONS['save']} CSV Dışa Aktar")
        csv_btn.setFixedHeight(44)
        csv_btn.setCursor(Qt.PointingHandCursor)
        csv_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['success']}; border: none; color: white;
                font-size: 13px; font-weight: bold; border-radius: 8px; padding: 0 18px; }}
            QPushButton:hover {{ background: {COLORS['success_dark']}; }}
        """)
        csv_btn.clicked.connect(self._export_expenses_csv)
        hr.addWidget(csv_btn, 0, Qt.AlignVCenter)
        hr.addSpacing(8)

        ab = QPushButton(f"{ICONS['plus']} Masraf Ekle")
        ab.setFixedHeight(44)
        ab.setCursor(Qt.PointingHandCursor)
        ab.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary']}; border: none; color: white;
                font-size: 14px; font-weight: bold; border-radius: 8px; padding: 0 20px; }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        ab.clicked.connect(self._add_expense_dialog)
        hr.addWidget(ab, 0, Qt.AlignVCenter)
        ly.addLayout(hr)

        # Özet İstatistik Kartları
        self.expense_cards_layout = QHBoxLayout()
        self.expense_cards_layout.setSpacing(16)
        ly.addLayout(self.expense_cards_layout)

        # Tarih filtresi
        fr = QHBoxLayout()
        self.exp_start = QDateEdit(QDate.currentDate().addMonths(-1))
        self.exp_end = QDateEdit(QDate.currentDate())
        for de in [self.exp_start, self.exp_end]:
            de.setCalendarPopup(True)
            de.setFixedWidth(140)
            de.setFixedHeight(40)
        
        fr.addWidget(QLabel("Başlangıç:"))
        fr.addWidget(self.exp_start)
        fr.addSpacing(16)
        fr.addWidget(QLabel("Bitiş:"))
        fr.addWidget(self.exp_end)
        
        sb = QPushButton("Listele")
        sb.setObjectName("outlineBtn")
        sb.clicked.connect(self._refresh_expenses)
        fr.addWidget(sb)
        fr.addStretch()
        ly.addLayout(fr)

        # Gruplu Özet Tablosu (masraf tipine göre)
        grp_title = QLabel("Masraf Tipine Göre Dağılım")
        grp_title.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        grp_title.setStyleSheet(f"color: {COLORS['text_dark']};")
        ly.addWidget(grp_title)

        self.expense_summary_table = QTableWidget()
        self.expense_summary_table.setColumnCount(3)
        self.expense_summary_table.setHorizontalHeaderLabels(["Masraf Tipi", "İşlem Sayısı", "Toplam Tutar"])
        self.expense_summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.expense_summary_table.setAlternatingRowColors(True)
        self.expense_summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.expense_summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.expense_summary_table.setMaximumHeight(200)
        ly.addWidget(self.expense_summary_table)

        # Detay Tablosu
        detail_title = QLabel("Detaylı Masraf Kayıtları")
        detail_title.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        detail_title.setStyleSheet(f"color: {COLORS['text_dark']};")
        ly.addWidget(detail_title)

        self.expense_table = QTableWidget()
        self.expense_table.setColumnCount(8)
        self.expense_table.setHorizontalHeaderLabels(["Tip", "Tarih", "Eklenme", "Kullanıcı", "Ödeme", "Tutar", "Detay", "Sil"])
        self.expense_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.expense_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.expense_table.setAlternatingRowColors(True)
        self.expense_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.expense_table.setSelectionBehavior(QTableWidget.SelectRows)
        ly.addWidget(self.expense_table, 1)

        scroll.setWidget(content)
        pg = QVBoxLayout(page)
        pg.setContentsMargins(0, 0, 0, 0)
        pg.addWidget(scroll)
        self._refresh_expenses()
        return page

    def _refresh_expenses(self):
        s = self.exp_start.date().toString("yyyy-MM-dd")
        e = self.exp_end.date().toString("yyyy-MM-dd")

        # Özet kartları güncelle
        while self.expense_cards_layout.count():
            item = self.expense_cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        exps = database.get_expenses(s, e)
        total = sum(ex.get('tutar', 0) or 0 for ex in exps)
        pay_summary = database.get_expense_payment_summary(s, e)
        nakit = pay_summary.get('Nakit', 0) or 0
        kredi = pay_summary.get('Kredi Kartı', 0) or 0

        cards_data = [
            (ICONS['money'], "Toplam Gider", f"₺{total:,.2f}", f"{len(exps)} kayıt", COLORS['danger'], COLORS['bg_danger']),
            (ICONS['money'], "Nakit Ödemeler", f"₺{nakit:,.2f}", "Nakit", COLORS['warning'], COLORS['bg_warning']),
            (ICONS['money'], "Kredi Kartı", f"₺{kredi:,.2f}", "Kart", COLORS['info'], COLORS['card_blue_bg']),
            (ICONS['chart'], "Kayıt Sayısı", str(len(exps)), "Masraf", COLORS['primary'], COLORS['primary_bg']),
        ]
        for icon, title, val, sub, color, bg in cards_data:
            c = StatCard(icon, title, val, sub, color, bg)
            self.expense_cards_layout.addWidget(c, 1)

        # Gruplu özet tablosu
        summary = database.get_expense_summary(s, e)
        self.expense_summary_table.setRowCount(len(summary) + 1)
        sum_total = 0
        sum_count = 0
        for i, sm in enumerate(summary):
            self.expense_summary_table.setItem(i, 0, QTableWidgetItem(sm.get('masraf_tipi', '')))
            cnt = sm.get('islem_sayisi', 0) or 0
            sum_count += cnt
            self.expense_summary_table.setItem(i, 1, QTableWidgetItem(str(cnt)))
            t_val = sm.get('toplam_tutar', 0) or 0
            sum_total += t_val
            tv = QTableWidgetItem(f"₺{t_val:,.2f}")
            tv.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
            tv.setForeground(QColor(COLORS['warning_dark']))
            self.expense_summary_table.setItem(i, 2, tv)
        # Toplam satırı
        tot_lbl = QTableWidgetItem("TOPLAM")
        tot_lbl.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        self.expense_summary_table.setItem(len(summary), 0, tot_lbl)
        self.expense_summary_table.setItem(len(summary), 1, QTableWidgetItem(str(sum_count)))
        tot_val = QTableWidgetItem(f"₺{sum_total:,.2f}")
        tot_val.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        tot_val.setForeground(QColor(COLORS['danger']))
        self.expense_summary_table.setItem(len(summary), 2, tot_val)

        # Detay tablosu
        self.expense_table.setRowCount(len(exps))
        for i, ex in enumerate(exps):
            for j, key in enumerate(['masraf_tipi', 'masraf_tarihi', 'eklenme_tarihi', 'kullanici_adi', 'odeme_tipi']):
                self.expense_table.setItem(i, j, QTableWidgetItem(ex.get(key, '') or ''))
            tv = QTableWidgetItem(f"₺{(ex.get('tutar', 0) or 0):,.2f}")
            tv.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
            tv.setForeground(QColor(COLORS['warning_dark']))
            self.expense_table.setItem(i, 5, tv)
            self.expense_table.setItem(i, 6, QTableWidgetItem(ex.get('masraf_detayi', '') or ''))
            
            # Sil butonu
            del_btn = QPushButton(ICONS['cross'])
            del_btn.setFixedSize(30, 30)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setStyleSheet(f"""
                QPushButton {{ background: {COLORS['bg_danger']}; color: {COLORS['danger']};
                    border-radius: 6px; font-weight: bold; border: none; }}
                QPushButton:hover {{ background: {COLORS['danger']}; color: white; }}
            """)
            eid = ex.get('id')
            del_btn.clicked.connect(lambda _, eid=eid: self._delete_expense(eid))
            self.expense_table.setCellWidget(i, 7, del_btn)

    def _delete_expense(self, eid):
        rep = QMessageBox.question(self, "Masraf Sil", "Bu masraf kaydını silmek istediğinize emin misiniz?",
                                   QMessageBox.Yes | QMessageBox.No)
        if rep == QMessageBox.Yes:
            database.delete_expense(eid)
            self._refresh_expenses()
            ToastNotification(self, "Masraf kaydı silindi.", "warning")

    def _export_expenses_csv(self):
        from datetime import datetime
        default_name = f"NexPOS_Giderler_{datetime.now().strftime('%Y-%m-%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "CSV Olarak Kaydet", default_name, "CSV Dosyaları (*.csv)")
        if not path:
            return
        s = self.exp_start.date().toString("yyyy-MM-dd")
        e = self.exp_end.date().toString("yyyy-MM-dd")
        exps = database.get_expenses(s, e)
        try:
            with open(path, 'w', encoding='utf-8-sig') as f:
                f.write("Masraf Tipi;Tarih;Eklenme Tarihi;Kullanıcı;Ödeme Tipi;Tutar;Detay\n")
                total = 0
                for ex in exps:
                    tutar = ex.get('tutar', 0) or 0
                    total += tutar
                    f.write(f"{ex.get('masraf_tipi', '')};{ex.get('masraf_tarihi', '')};{ex.get('eklenme_tarihi', '')};"
                            f"{ex.get('kullanici_adi', '')};{ex.get('odeme_tipi', '')};{tutar:.2f};{ex.get('masraf_detayi', '')}\n")
                f.write(f"\nTOPLAM;;;;;{total:.2f};\n")
            ToastNotification(self, f"Gider raporu CSV olarak kaydedildi!", "success")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"CSV kaydedilemedi:\n{str(ex)}")

    def _add_expense_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Masraf Ekle")
        dlg.setFixedSize(450, 400)
        form = QFormLayout(dlg)
        form.setContentsMargins(32, 28, 32, 28)
        form.setSpacing(16)
        tip = QLineEdit()
        tutar = QDoubleSpinBox()
        tutar.setMaximum(999999)
        tutar.setPrefix("₺ ")
        odeme = QComboBox()
        odeme.addItems(["Nakit", "Kredi Kartı", "Havale", "Diğer"])
        detay = QLineEdit()
        
        form.addRow("Tip:", tip)
        form.addRow("Tutar:", tutar)
        form.addRow("Ödeme:", odeme)
        form.addRow("Detay:", detay)
        
        btn = QPushButton("Kaydet")
        btn.setObjectName("primaryBtn")
        def save():
            if tip.text().strip() and tutar.value() > 0:
                from datetime import datetime
                database.add_expense(tip.text(), tutar.value(), odeme.currentText(),
                    detay.text(), self.user['id'], datetime.now().strftime("%Y-%m-%d"))
                dlg.accept()
                self._refresh_expenses()
        btn.clicked.connect(save)
        form.addRow(btn)
        dlg.exec()

    def _create_zayi_page(self):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        ly = QVBoxLayout(content)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        hr = QHBoxLayout()
        header = PageHeader("Zayi İşlemleri", "Ürün kayıtlarından düşülmesi gereken zayiatları girin.", COLORS['danger'], ICONS['trash'])
        hr.addWidget(header, 1)

        csv_btn = QPushButton(f"{ICONS['save']} CSV Dışa Aktar")
        csv_btn.setFixedHeight(44)
        csv_btn.setCursor(Qt.PointingHandCursor)
        csv_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['success']}; border: none; color: white;
                font-size: 13px; font-weight: bold; border-radius: 8px; padding: 0 18px; }}
            QPushButton:hover {{ background: {COLORS['success_dark']}; }}
        """)
        csv_btn.clicked.connect(self._export_waste_csv)
        hr.addWidget(csv_btn, 0, Qt.AlignVCenter)
        hr.addSpacing(8)

        ab = QPushButton(f"{ICONS['plus']} Zayi Ekle")
        ab.setFixedHeight(44)
        ab.setCursor(Qt.PointingHandCursor)
        ab.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary']}; border: none; color: white;
                font-size: 14px; font-weight: bold; border-radius: 8px; padding: 0 20px; }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        ab.clicked.connect(self._add_waste_dialog)
        hr.addWidget(ab, 0, Qt.AlignVCenter)
        ly.addLayout(hr)

        # Özet İstatistik Kartları
        self.waste_cards_layout = QHBoxLayout()
        self.waste_cards_layout.setSpacing(16)
        ly.addLayout(self.waste_cards_layout)

        # Tarih filtresi
        fr = QHBoxLayout()
        self.waste_start = QDateEdit(QDate.currentDate().addMonths(-1))
        self.waste_end = QDateEdit(QDate.currentDate())
        for de in [self.waste_start, self.waste_end]:
            de.setCalendarPopup(True)
            de.setFixedWidth(140)
            de.setFixedHeight(40)
        fr.addWidget(QLabel("Başlangıç:"))
        fr.addWidget(self.waste_start)
        fr.addSpacing(16)
        fr.addWidget(QLabel("Bitiş:"))
        fr.addWidget(self.waste_end)
        wb = QPushButton("Listele")
        wb.setObjectName("outlineBtn")
        wb.clicked.connect(self._refresh_waste)
        fr.addWidget(wb)
        fr.addStretch()
        ly.addLayout(fr)

        # Ürüne Göre Zayi Dağılımı
        grp_title = QLabel("Ürüne Göre Zayi Dağılımı")
        grp_title.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        grp_title.setStyleSheet(f"color: {COLORS['text_dark']};")
        ly.addWidget(grp_title)

        self.waste_summary_table = QTableWidget()
        self.waste_summary_table.setColumnCount(3)
        self.waste_summary_table.setHorizontalHeaderLabels(["Ürün Adı", "Toplam Adet", "Toplam Maliyet"])
        self.waste_summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.waste_summary_table.setAlternatingRowColors(True)
        self.waste_summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.waste_summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.waste_summary_table.setMaximumHeight(200)
        ly.addWidget(self.waste_summary_table)

        # Detay Tablosu
        detail_title = QLabel("Detaylı Zayi Kayıtları")
        detail_title.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        detail_title.setStyleSheet(f"color: {COLORS['text_dark']};")
        ly.addWidget(detail_title)

        self.waste_table = QTableWidget()
        self.waste_table.setColumnCount(8)
        self.waste_table.setHorizontalHeaderLabels(["Ürün", "Neden", "Adet", "Zayi Tarihi", "Kayıt Tarihi", "Sorumlu", "Maliyet(₺)", "Sil"])
        self.waste_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.waste_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.waste_table.setAlternatingRowColors(True)
        self.waste_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.waste_table.setSelectionBehavior(QTableWidget.SelectRows)
        ly.addWidget(self.waste_table, 1)

        scroll.setWidget(content)
        pg = QVBoxLayout(page)
        pg.setContentsMargins(0, 0, 0, 0)
        pg.addWidget(scroll)
        self._refresh_waste()
        return page

    def _refresh_waste(self):
        s = self.waste_start.date().toString("yyyy-MM-dd")
        e = self.waste_end.date().toString("yyyy-MM-dd")

        # Özet kartları güncelle
        while self.waste_cards_layout.count():
            item = self.waste_cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        ws = database.get_waste(s, e)
        total_cost = sum((w.get('maliyet_tutari') or 0) for w in ws)
        total_adet = sum((w.get('adet') or 0) for w in ws)
        
        # En çok zayi olan ürün
        summary = database.get_waste_summary(s, e)
        top_product = summary[0]['urun_adi'] if summary else "—"
        top_adet = summary[0]['toplam_adet'] if summary else 0
        last_date = ws[0].get('zayi_tarihi', '—') if ws else "—"

        cards_data = [
            (ICONS['trash'], "Toplam Zayi Maliyet", f"₺{total_cost:,.2f}", f"{len(ws)} kayıt", COLORS['danger'], COLORS['bg_danger']),
            (ICONS['menu_food'], "Zayi Ürün Adedi", str(total_adet), "Toplam adet", COLORS['warning'], COLORS['bg_warning']),
            (ICONS['star'], "En Çok Zayi Ürün", str(top_product), f"x{top_adet}", COLORS['info'], COLORS['card_blue_bg']),
            (ICONS['chart'], "Son Kayıt", str(last_date), "Zayi tarihi", COLORS['primary'], COLORS['primary_bg']),
        ]
        for icon, title, val, sub, color, bg in cards_data:
            c = StatCard(icon, title, val, sub, color, bg)
            self.waste_cards_layout.addWidget(c, 1)

        # Ürüne göre gruplu tablo
        self.waste_summary_table.setRowCount(len(summary) + 1)
        sum_adet = 0
        sum_cost = 0
        for i, sm in enumerate(summary):
            self.waste_summary_table.setItem(i, 0, QTableWidgetItem(sm.get('urun_adi', '') or ''))
            adet = sm.get('toplam_adet', 0) or 0
            sum_adet += adet
            self.waste_summary_table.setItem(i, 1, QTableWidgetItem(str(adet)))
            cost = sm.get('toplam_maliyet', 0) or 0
            sum_cost += cost
            tv = QTableWidgetItem(f"₺{cost:,.2f}")
            tv.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
            tv.setForeground(QColor(COLORS['danger']))
            self.waste_summary_table.setItem(i, 2, tv)
        # Toplam
        tot_lbl = QTableWidgetItem("TOPLAM")
        tot_lbl.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        self.waste_summary_table.setItem(len(summary), 0, tot_lbl)
        self.waste_summary_table.setItem(len(summary), 1, QTableWidgetItem(str(sum_adet)))
        tot_val = QTableWidgetItem(f"₺{sum_cost:,.2f}")
        tot_val.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        tot_val.setForeground(QColor(COLORS['danger']))
        self.waste_summary_table.setItem(len(summary), 2, tot_val)

        # Detay tablosu
        self.waste_table.setRowCount(len(ws))
        for i, w in enumerate(ws):
            self.waste_table.setItem(i, 0, QTableWidgetItem(w.get('urun_adi', '') or ''))
            self.waste_table.setItem(i, 1, QTableWidgetItem(w.get('zayi_nedeni', '') or ''))
            self.waste_table.setItem(i, 2, QTableWidgetItem(str(w.get('adet', 0))))
            self.waste_table.setItem(i, 3, QTableWidgetItem(w.get('zayi_tarihi', '') or ''))
            self.waste_table.setItem(i, 4, QTableWidgetItem(w.get('eklenme_tarihi', '') or ''))
            self.waste_table.setItem(i, 5, QTableWidgetItem(w.get('sorumlu_adi', '') or ''))
            m = w.get('maliyet_tutari') or 0
            tv = QTableWidgetItem(f"₺{m:,.2f}")
            tv.setForeground(QColor(COLORS['danger']))
            tv.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
            self.waste_table.setItem(i, 6, tv)

            # Sil butonu
            del_btn = QPushButton(ICONS['cross'])
            del_btn.setFixedSize(30, 30)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setStyleSheet(f"""
                QPushButton {{ background: {COLORS['bg_danger']}; color: {COLORS['danger']};
                    border-radius: 6px; font-weight: bold; border: none; }}
                QPushButton:hover {{ background: {COLORS['danger']}; color: white; }}
            """)
            wid = w.get('id')
            del_btn.clicked.connect(lambda _, wid=wid: self._delete_waste(wid))
            self.waste_table.setCellWidget(i, 7, del_btn)

    def _delete_waste(self, wid):
        rep = QMessageBox.question(self, "Zayi Sil", "Bu zayi kaydını silmek istediğinize emin misiniz?",
                                   QMessageBox.Yes | QMessageBox.No)
        if rep == QMessageBox.Yes:
            database.delete_waste(wid)
            self._refresh_waste()
            ToastNotification(self, "Zayi kaydı silindi.", "warning")

    def _export_waste_csv(self):
        from datetime import datetime
        default_name = f"NexPOS_Zayi_{datetime.now().strftime('%Y-%m-%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "CSV Olarak Kaydet", default_name, "CSV Dosyaları (*.csv)")
        if not path:
            return
        s = self.waste_start.date().toString("yyyy-MM-dd")
        e = self.waste_end.date().toString("yyyy-MM-dd")
        ws = database.get_waste(s, e)
        try:
            with open(path, 'w', encoding='utf-8-sig') as f:
                f.write("Ürün;Neden;Adet;Zayi Tarihi;Kayıt Tarihi;Sorumlu;Maliyet\n")
                total = 0
                for w in ws:
                    m = w.get('maliyet_tutari') or 0
                    total += m
                    f.write(f"{w.get('urun_adi', '')};{w.get('zayi_nedeni', '')};{w.get('adet', 0)};"
                            f"{w.get('zayi_tarihi', '')};{w.get('eklenme_tarihi', '')};{w.get('sorumlu_adi', '')};{m:.2f}\n")
                f.write(f"\nTOPLAM;;;;;;{total:.2f}\n")
            ToastNotification(self, "Zayi raporu CSV olarak kaydedildi!", "success")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"CSV kaydedilemedi:\n{str(ex)}")

    def _add_waste_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Zayi Ekle")
        dlg.setFixedSize(450, 320)
        form = QFormLayout(dlg)
        form.setContentsMargins(32, 28, 32, 28)
        form.setSpacing(16)
        pc = QComboBox()
        for p in database.get_products_by_category():
            pc.addItem(f"{p['ad']} (₺{p['fiyat']})", p['id'])
        nd = QLineEdit()
        nd.setPlaceholderText("Zayi nedeni girin (örn: Düşürüldü, Bozuldu)")
        ad = QSpinBox()
        ad.setMinimum(1); ad.setMaximum(999)
        form.addRow("Ürün:", pc)
        form.addRow("Neden:", nd)
        form.addRow("Adet:", ad)
        btn = QPushButton("Kaydet")
        btn.setObjectName("dangerBtn")
        def save():
            pid = pc.currentData()
            if pid and nd.text().strip():
                from datetime import datetime
                prods = database.get_products_by_category()
                m = sum(p['fiyat'] * ad.value() for p in prods if p['id'] == pid)
                database.add_waste(pid, nd.text(), ad.value(), m, self.user['id'], datetime.now().strftime("%Y-%m-%d"))
                dlg.accept()
                self._refresh_waste()
                ToastNotification(self, "Zayi kaydı eklendi.", "warning")
        btn.clicked.connect(save)
        form.addRow(btn)
        dlg.exec()

    def _create_raporlar_page(self):
        page = QWidget()
        ly = QVBoxLayout(page)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        hr = QHBoxLayout()
        header = PageHeader("Gelişmiş Raporlar", "İşletmenizin performans metrikleri.", COLORS['info'], ICONS['chart'])
        hr.addWidget(header, 1)

        csv_btn = QPushButton(f"{ICONS['save']} CSV Dışa Aktar")
        csv_btn.setFixedHeight(44)
        csv_btn.setCursor(Qt.PointingHandCursor)
        csv_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['success']}; border: none; color: white;
                font-size: 13px; font-weight: bold; border-radius: 8px; padding: 0 18px; }}
            QPushButton:hover {{ background: {COLORS['success_dark']}; }}
        """)
        csv_btn.clicked.connect(self._export_reports_csv)
        hr.addWidget(csv_btn, 0, Qt.AlignVCenter)
        ly.addLayout(hr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        cw = QWidget()
        grid = QGridLayout(cw)
        grid.setSpacing(16)

        s = database.get_dashboard_stats()
        
        # Calculate real dynamic values based on basic stats
        t_sales = s['total_sales']
        o_count = max(1, s['guest_count'] // 2) # approx orders
        g_count = max(1, s['guest_count'])
        
        avg_order = t_sales / o_count if o_count > 0 else 0
        avg_guest = t_sales / g_count if g_count > 0 else 0
        
        toplam_iskonto = database.get_toplam_iskonto()
        iskonto_pct = f"%{(toplam_iskonto / (t_sales + toplam_iskonto) * 100):.1f}" if (t_sales + toplam_iskonto) > 0 else "%0"

        stats_data = [
            (ICONS['money'], "Gerçekleşen Satış", f"₺{t_sales:,.2f}", "Kasa giriş", COLORS['success'], COLORS['bg_success']),
            (ICONS['chart'], "Ortalama Adisyon", f"₺{avg_order:,.2f}", "Sipariş başı", COLORS['info'], COLORS['card_blue_bg']),
            (ICONS['user'], "Kişi Başı Ortalama", f"₺{avg_guest:,.2f}", "Misafir", COLORS['primary'], COLORS['primary_bg']),
            (ICONS['menu_food'], "Adisyon Sayısı", f"{o_count}", "Kapanan", COLORS['warning'], COLORS['bg_warning']),
            (ICONS['arrow_down'], "İskonto & İndirim", f"₺{toplam_iskonto:,.2f}", f"{iskonto_pct} İndirim", COLORS['danger'], COLORS['bg_danger']),
            (ICONS['star'], "Tahmini Bahşiş", f"₺{t_sales*0.05:,.2f}", "%5 Ortalama", COLORS['accent'], COLORS['bg_warning']),
        ]
        
        for i, (icon, desc, val, sub, color, bg) in enumerate(stats_data):
            c = StatCard(icon, desc, val, sub, color, bg)
            grid.addWidget(c, i // 3, i % 3)
            
        grid.setRowStretch(grid.rowCount(), 1)

        # En Popüler Ürünler
        pop_title = QLabel("🏆  En Çok Sipariş Edilen Ürünler (Top 5)")
        pop_title.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        pop_title.setStyleSheet(f"color: {COLORS['text_dark']}; margin-top: 8px;")
        grid.addWidget(pop_title, grid.rowCount(), 0, 1, 3)

        popular = database.get_popular_products(5)
        if popular:
            rank_colors = [COLORS['warning'], COLORS['text_secondary'], '#CD7F32', COLORS['text_muted'], COLORS['text_muted']]
            for rank, prod in enumerate(popular, 1):
                pop_row = QFrame()
                pop_row.setStyleSheet(f"QFrame {{ background: white; border-radius: 10px; border: 1px solid {COLORS['border_light']}; }}")
                prl = QHBoxLayout(pop_row)
                prl.setContentsMargins(16, 10, 16, 10)
                rank_lbl = QLabel(f"#{rank}")
                rank_lbl.setFixedWidth(32)
                rank_lbl.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
                rank_lbl.setStyleSheet(f"color: {rank_colors[rank-1]};")
                name_lbl = QLabel(prod['urun_adi'])
                name_lbl.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
                adet_lbl = QLabel(f"{prod['toplam_adet']} adet")
                adet_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
                tutar_lbl = QLabel(f"₺{(prod['toplam_tutar'] or 0):,.2f}")
                tutar_lbl.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
                tutar_lbl.setStyleSheet(f"color: {COLORS['success']};")
                prl.addWidget(rank_lbl)
                prl.addWidget(name_lbl, 1)
                prl.addWidget(adet_lbl)
                prl.addSpacing(16)
                prl.addWidget(tutar_lbl)
                grid.addWidget(pop_row, grid.rowCount(), 0, 1, 3)
        else:
            no_data = QLabel("Henüz tamamlanmış sipariş yok — veriler biriktikçe burada görünecek.")
            no_data.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 13px; padding: 12px;")
            grid.addWidget(no_data, grid.rowCount(), 0, 1, 3)

        scroll.setWidget(cw)
        ly.addWidget(scroll, 1)
        return page

    def _export_reports_csv(self):
        from datetime import datetime
        default_name = f"NexPOS_Rapor_{datetime.now().strftime('%Y-%m-%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "CSV Olarak Kaydet", default_name, "CSV Dosyaları (*.csv)")
        if not path:
            return
        s = database.get_dashboard_stats()
        t_sales = s['total_sales']
        o_count = max(1, s['guest_count'] // 2)
        g_count = max(1, s['guest_count'])
        avg_order = t_sales / o_count if o_count > 0 else 0
        avg_guest = t_sales / g_count if g_count > 0 else 0
        try:
            with open(path, 'w', encoding='utf-8-sig') as f:
                f.write("Metrik;Değer\n")
                f.write(f"Gerçekleşen Satış;{t_sales:.2f}\n")
                f.write(f"Ortalama Adisyon;{avg_order:.2f}\n")
                f.write(f"Kişi Başı Ortalama;{avg_guest:.2f}\n")
                f.write(f"Adisyon Sayısı;{o_count}\n")
                f.write(f"Misafir Sayısı;{g_count}\n")
                f.write(f"Toplam Gider;{s['total_expense']:.2f}\n")
                f.write(f"Açık Siparişler;{s['open_orders']:.2f}\n")
                f.write(f"Toplam Masa;{s['total_tables']}\n")
                f.write(f"Dolu Masa;{s['occupied_tables']}\n")
                f.write(f"Tahmini Bahşiş;{t_sales*0.05:.2f}\n")
            ToastNotification(self, "İstatistik raporu CSV olarak kaydedildi!", "success")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"CSV kaydedilemedi:\n{str(ex)}")

    def _create_kullanicilar_page(self):
        self.staff_page = StaffPage(self.user)
        return self.staff_page

    def _create_yetkiler_page(self):
        self.permissions_page = PermissionsPage(self.user)
        return self.permissions_page

    # ==================== SİSTEM AYARLARI ====================
    def _create_settings_page(self):
        import json, os
        page = QWidget()
        ly = QVBoxLayout(page)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        header = PageHeader("Sistem Ayarları", "İşletme ayarlarını, tema ve servis bağlantılarını buradan yönetin.", COLORS['primary'], ICONS['settings'])
        ly.addWidget(header)
        
        from PySide6.QtWidgets import QTabWidget
        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {COLORS['border_light']}; border-radius: 8px; background: white; }}
            QTabBar::tab {{ background: {COLORS['primary_bg']}; color: {COLORS['primary']}; padding: 12px 24px; font-weight: bold; font-size: 14px; border: 1px solid {COLORS['border_light']}; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px; }}
            QTabBar::tab:selected {{ background: {COLORS['primary']}; color: white; }}
        """)
        
        genel = QWidget()
        gl = QFormLayout(genel)
        gl.setContentsMargins(24, 24, 24, 24)
        gl.setSpacing(20)
        
        isim = QLineEdit()
        isim.setFixedHeight(40)
        tema = QComboBox()
        tema.addItems(["Açık Tema (Varsayılan)", "Koyu Tema"])
        tema.setFixedHeight(40)
        
        gl.addRow("İşletme Adı:", isim)
        gl.addRow("Uygulama Teması:", tema)
        
        prnt = QWidget()
        pl = QFormLayout(prnt)
        pl.setContentsMargins(24, 24, 24, 24)
        pl.setSpacing(20)
        yazici = QComboBox()
        yazici.addItems(["Varsayılan Sistem Yazıcısı", "Mutfak Fişi (Ağ)", "Kapat"])
        yazici.setFixedHeight(40)
        kagit = QComboBox()
        kagit.addItems(["80mm Termal", "58mm Termal", "A4"])
        kagit.setFixedHeight(40)
        
        pl.addRow("Bağlı Yazıcı:", yazici)
        pl.addRow("Kağıt Boyutu:", kagit)
        
        tabs.addTab(genel, "Genel Ayarlar")
        tabs.addTab(prnt, "Yazıcı Ayarları")
        
        ly.addWidget(tabs, 1)
        
        conf_path = "config.json"
        
        if os.path.exists(conf_path):
            try:
                with open(conf_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    isim.setText(cfg.get("isletme_adi", "VELVET LOUNGE - 34001"))
                    tema.setCurrentIndex(cfg.get("tema", 0))
                    yazici.setCurrentIndex(cfg.get("yazici", 0))
                    kagit.setCurrentIndex(cfg.get("kagit", 0))
            except Exception: pass
        else:
            isim.setText("VELVET LOUNGE - 34001")
        
        act_ly = QHBoxLayout()
        act_ly.addStretch()
        sv_btn = QPushButton(f"{ICONS['save']} Ayarları Kaydet")
        sv_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary']}; color: white; font-weight: bold;
                border-radius: 8px; padding: 12px 24px; font-size: 14px; border: none; }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        def save():
            cfg = {"isletme_adi": isim.text(), "tema": tema.currentIndex(), "yazici": yazici.currentIndex(), "kagit": kagit.currentIndex()}
            with open(conf_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            QMessageBox.information(self, "Başarılı", "Sistem ayarları başarıyla kaydedildi! (Tema/İsim değişiklikleri tekrar başlatmada uygulanır.)")
        sv_btn.clicked.connect(save)
        act_ly.addWidget(sv_btn)
        ly.addLayout(act_ly)
        
        return page
