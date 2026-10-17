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
from floor_editor import FloorPlanPage
from admin_access_pages import cloud_action
from cloud.context import ctx
from qr_print import default_base_url
from cloud.permissions import PANEL_ROLES
from cash_screen import CashPage
from reports_screen import DashboardPage, ReportsPage
from stock_pages import StockPage, WastePage
from shifts_pages import ShiftDialog, StaffShiftsPage
from loyalty_pages import MarketingPage
import cash
from modules_page import ModulesPanel
from pos import now_iso as pos_now
import database

# Sayfa → görmek için gereken yetki (None: herkes). Sıra, self.pages sırasıyla aynıdır.
PAGE_PERMISSIONS = [
    'viewReports',   # 0 Dashboard
    'editMenu',      # 1 Masa / Bölgeler
    'editMenu',      # 2 Menü / Ürünler
    'expense',       # 3 Gider
    'waste',         # 4 Zayi
    'viewReports',   # 5 İstatistikler
    'manageUsers',   # 6 Kullanıcılar
    'manageUsers',   # 7 Yetkiler
    'settings',      # 8 Ayarlar
    'settings',      # 9 Terminaller
    'cash',          # 10 Kasa
    'stock',         # 11 Stok (modül açıkken)
    'shifts',        # 12 Vardiya ve Mesai (modül açıkken)
    'loyalty',       # 13 Pazarlama: müşteriler, sadakat, kampanya (modül açıkken)
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
        self.cash_page = CashPage(self.user)
        self.pages.addWidget(self.cash_page)                    # 10
        self.stock_page = StockPage(self.user)
        self.pages.addWidget(self.stock_page)                   # 11
        self.shifts_page = StaffShiftsPage(self.user)
        self.pages.addWidget(self.shifts_page)                  # 12
        self.marketing_page = MarketingPage(self.user)
        self.pages.addWidget(self.marketing_page)               # 13
        content_w.addWidget(self.pages, 1)

        cf = QFrame()
        cf.setLayout(content_w)
        cf.setStyleSheet(f"background-color: {COLORS['bg_main']};")
        main.addWidget(cf, 1)
        self._apply_permissions()

    def _can_see(self, idx):
        if idx == 11 and not database.modules()['stock']['enabled']:
            return False  # kapalı modül görünmez
        if idx == 12 and not database.modules()['staff']['enabled']:
            return False
        m = database.modules()
        if idx == 13 and not (m['loyalty']['enabled'] or m['campaigns']['enabled'] or m['app']['enabled']):
            return False
        perm = PAGE_PERMISSIONS[idx] if idx < len(PAGE_PERMISSIONS) else None
        return perm is None or database.user_can(self.user, perm)

    def _apply_sidebar(self):
        for idx, btn in enumerate(self.sidebar_buttons):
            btn.setVisible(self._can_see(idx))

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
        shop = QLabel(f"  {ICONS['home']}  {database.general_settings()['cafeName'].upper()}")
        self.shop_label = shop
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
        btn_kasa = isl.add_sub_button("Kasa", ICONS['dot'])
        btn_kasa.clicked.connect(lambda: self._show_page(10))
        btn_stok = isl.add_sub_button("Stok / Malzemeler", ICONS['dot'])
        btn_stok.clicked.connect(lambda: self._show_page(11))
        btn_gd = isl.add_sub_button("Gider / Masraf", ICONS['dot'])
        btn_gd.clicked.connect(lambda: self._show_page(3))
        self.sidebar_buttons.append(btn_gd)
        btn_zy = isl.add_sub_button("Zayi İşlemleri", ICONS['dot'])
        btn_zy.clicked.connect(lambda: self._show_page(4))
        self.sidebar_buttons.append(btn_zy)
        self.menu_layout.addWidget(isl)

        paz = ExpandableSection("Pazarlama", ICONS['user'])
        btn_pazarlama = paz.add_sub_button("Müşteriler ve Sadakat", ICONS['dot'])
        btn_pazarlama.clicked.connect(lambda: self._show_page(13))
        self.menu_layout.addWidget(paz)

        rap = ExpandableSection("Raporlar", ICONS['chart'])
        btn_rapor = rap.add_sub_button("Satış ve Diğer Raporlar", ICONS['dot'])
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
        btn_vardiya = kul.add_sub_button("Vardiya ve Mesai", ICONS['dot'])
        btn_vardiya.clicked.connect(lambda: self._show_page(12))
        self.menu_layout.addWidget(kul)

        btn_ayar = SidebarButton("Ayarlar", ICONS['settings'])
        btn_ayar.clicked.connect(lambda: self._show_page(8))
        self.sidebar_buttons.append(btn_ayar)
        self.menu_layout.addWidget(btn_ayar)

        btn_term = SidebarButton("Terminaller", ICONS['table'])
        btn_term.clicked.connect(lambda: self._show_page(9))
        self.sidebar_buttons.append(btn_term)
        self.menu_layout.addWidget(btn_term)
        self.sidebar_buttons.append(btn_kasa)  # sayfa 10
        self.sidebar_buttons.append(btn_stok)  # sayfa 11
        self.sidebar_buttons.append(btn_vardiya)  # sayfa 12
        self.sidebar_buttons.append(btn_pazarlama)  # sayfa 13

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

        self.page_title = QLabel("Dashboard")
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
        kasa.clicked.connect(lambda: self._show_page(10))
        kasa.setVisible(database.user_can(self.user, 'cash'))
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
        user_btn.setToolTip("Vardiyam: mesaiye başla / bitir, mola")
        user_btn.clicked.connect(lambda: ShiftDialog(self.user, self).exec())
        ly.addWidget(user_btn)
        return bar

    def _show_page(self, idx):
        if not self._can_see(idx):
            return
        current = self.pages.currentWidget()
        if current is not self.pages.widget(idx) and hasattr(current, 'can_leave') and not current.can_leave():
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
        titles = ["Ana Sayfa", "Tanımlamalar / Masa ve Bölgeler",
                   "Kategori ve Ürün Tanımlama / Şube Ürünleri",
                   "Gider/Masraf İşlemleri", "Zayi İşlemleri",
                   "Raporlar", "Kullanıcılar", "Yetki / İzin Ekranı", "Sistem Ayarları",
                   "Terminaller", "Kasa", "Stok", "Vardiya ve Mesai", "Pazarlama"]
        if idx < len(titles):
            self.page_title.setText(titles[idx])

    # ==================== DASHBOARD ====================
    def _create_dashboard_page(self):
        self.dashboard_page = DashboardPage(self.user)
        self.dashboard_page.navigate.connect(self._dashboard_navigate)
        return self.dashboard_page

    def _dashboard_navigate(self, target):
        """Ana sayfadaki uyarı/kart tıklamaları ilgili ekrana gider."""
        if target == 'losses':
            self._show_page(5)
            self.reports_page.set_period('today', ReportsPage.TAB_LOSSES)
        elif target == 'cash':
            self._show_page(10)
            # Kasa açıksa kasa sekmesi, değilse son Z raporları
            self.cash_page.tabs.setCurrentIndex(0 if cash.current_session() else 2)
        elif target == 'terminals':
            self._show_page(9)
        elif target == 'stock':
            self._show_page(11)

    def _create_masa_bolge_page(self):
        self.floor_page = FloorPlanPage(self.user)
        return self.floor_page

    def _create_menu_urunler_page(self):
        self.menu_page = MenuPage(self.user)
        return self.menu_page

    def on_sync_status(self, status):
        """Ana pencere her senkronda çağırır: menü sayfası çevrimiçi durumu ve değişiklikleri günceller."""
        self.menu_page.on_sync_status(status)
        self.floor_page.on_sync_status(status)
        if self.pages.currentWidget() is self.dashboard_page:
            self.dashboard_page.refresh()  # rakamlar yerelden; her senkronda tazelenir
        if status.changed & {'ingredients', 'suppliers', 'purchaseOrders'} and \
                self.pages.currentWidget() is self.stock_page:
            self.stock_page.refresh()
        if 'modules' in status.changed:
            self._apply_sidebar()
            self.modules_panel.refresh()
            self.cash_page.refresh()
        if status.changed & {'customers', 'rewards', 'loyalty', 'app'} and self.pages.currentWidget() is self.marketing_page:
            self.marketing_page.refresh()
        if 'shiftPlans' in status.changed and self.pages.currentWidget() is self.shifts_page:
            self.shifts_page.refresh()
        if 'general' in status.changed:
            self.shop_label.setText(f"  {ICONS['home']}  {database.general_settings()['cafeName'].upper()}")

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
        # 8b: yeni zayi sayfası (ürün ve malzeme zayisi; eski kayıtlar da listelenir)
        self.waste_page = WastePage(self.user)
        return self.waste_page

    def _create_raporlar_page(self):
        self.reports_page = ReportsPage(self.user)
        self.reports_page.open_cash_history.connect(lambda: (self._show_page(10), self.cash_page.tabs.setCurrentIndex(2)))
        return self.reports_page

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
        
        # Bulutta tutulan genel ayarlar (QR etiketleri, ekranlar, otomatik kilit)
        general = database.general_settings()
        isim = QLineEdit(general['cafeName'])
        isim.setFixedHeight(40)
        isim.setMaxLength(60)
        qr_url = QLineEdit(general['qrBaseUrl'] or (default_base_url(ctx.config.project_id) if ctx.config else ''))
        qr_url.setFixedHeight(40)
        qr_url.setPlaceholderText("https://kafeniz.web.app/masa")
        kilit = QSpinBox()
        kilit.setRange(1, 60)
        kilit.setSuffix(" dk")
        kilit.setValue(int(general['idleLockMinutes']))
        kilit.setFixedHeight(40)
        tema = QComboBox()
        tema.addItems(["Açık Tema (Varsayılan)", "Koyu Tema"])
        tema.setFixedHeight(40)

        gl.addRow("Kafe Adı:", isim)
        gl.addRow("Masa QR Adresi:", qr_url)
        gl.addRow("Otomatik Kilit:", kilit)
        gl.addRow("Uygulama Teması:", tema)
        bulut_not = QLabel("Kafe adı, QR adresi ve otomatik kilit buluta kaydedilir (internet gerekir). "
                           "QR adresi değişirse masa etiketlerini yeniden basın.")
        bulut_not.setWordWrap(True)
        bulut_not.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        gl.addRow(bulut_not)

        prnt = QWidget()
        pl = QFormLayout(prnt)
        pl.setContentsMargins(24, 24, 24, 24)
        pl.setSpacing(20)
        # Yazıcı bu bilgisayara özeldir (bulut ayarı değildir)
        import printing
        current_printer = printing.printer_settings()
        yazici = QComboBox()
        yazici.addItem("Yazıcı yok — PDF olarak kaydet", "")
        for name in printing.available_printers():
            yazici.addItem(name, name)
        if current_printer['name'] and yazici.findData(current_printer['name']) < 0:
            yazici.addItem(f"{current_printer['name']} (bulunamadı)", current_printer['name'])
        yazici.setCurrentIndex(max(0, yazici.findData(current_printer['name'])))
        yazici.setFixedHeight(40)
        kagit = QComboBox()
        for key, (label, _) in printing.PAPERS.items():
            kagit.addItem(label, key)
        kagit.setCurrentIndex(max(0, kagit.findData(current_printer['paper'])))
        kagit.setFixedHeight(40)
        deneme = QPushButton("Deneme fişi yazdır")
        deneme.setFixedHeight(36)

        def test_print():
            printing.save_printer_settings(yazici.currentData(), kagit.currentData())
            sample = {'no': 'A0', 'type': 'takeaway', 'tableName': '', 'openedAt': pos_now(), 'discount': None,
                      'payments': [], 'items': [{'name': 'Deneme ürünü', 'qty': 1, 'unitPrice': 1000, 'options': [],
                                                 'status': 'active', 'state': 'sent'}]}
            kind, where = printing.print_html(printing.bill_html(sample), "Deneme fişi")
            ToastNotification(self, "Deneme fişi yazıcıya gönderildi." if kind == 'printer'
                              else f"PDF kaydedildi: {where}", "success" if kind == 'printer' else "info")
        deneme.clicked.connect(test_print)
        pl.addRow("Bağlı Yazıcı:", yazici)
        pl.addRow("Kağıt Boyutu:", kagit)
        pl.addRow("", deneme)
        yazici_not = QLabel("Yazıcı seçimi yalnızca bu bilgisayar için geçerlidir. Windows'a sürücüsü kurulu her yazıcı "
                            "(80/58 mm termal ya da A4) kullanılabilir. Fişlerin mali değeri yoktur.")
        yazici_not.setWordWrap(True)
        yazici_not.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        pl.addRow(yazici_not)

        self.modules_panel = ModulesPanel(self.user)
        tabs.addTab(genel, "Genel Ayarlar")
        tabs.addTab(self.modules_panel, "Modüller")
        tabs.addTab(prnt, "Yazıcı Ayarları")
        
        ly.addWidget(tabs, 1)
        
        conf_path = "config.json"
        
        if os.path.exists(conf_path):
            try:
                with open(conf_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    tema.setCurrentIndex(cfg.get("tema", 0))
            except Exception: pass
        
        act_ly = QHBoxLayout()
        act_ly.addStretch()
        sv_btn = QPushButton(f"{ICONS['save']} Ayarları Kaydet")
        sv_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary']}; color: white; font-weight: bold;
                border-radius: 8px; padding: 12px 24px; font-size: 14px; border: none; }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        def save():
            # Bu bilgisayara özel ayarlar (tema, yazıcı) yerelde kalır
            cfg = {"tema": tema.currentIndex()}
            with open(conf_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            printing.save_printer_settings(yazici.currentData(), kagit.currentData())
            current = database.general_settings()
            new = (isim.text().strip(), qr_url.text().strip(), kilit.value())
            if new == (current['cafeName'], current['qrBaseUrl'], current['idleLockMinutes']):
                ToastNotification(self, "Ayarlar kaydedildi.", "success")
                return

            def saved(data):
                database.set_setting('general', data)
                self.shop_label.setText(f"  {ICONS['home']}  {data['cafeName'].upper()}")

            cloud_action(self, lambda api: api.save_general_settings(*new), "Ayarlar buluta kaydedildi.", saved)
        sv_btn.clicked.connect(save)
        act_ly.addWidget(sv_btn)
        ly.addLayout(act_ly)
        
        return page
