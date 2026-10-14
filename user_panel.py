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
from widgets import TableCard, OrderCard, InfoDialog, add_shadow, ToastNotification
from access import request_approval
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
        self.pages.addWidget(self._create_siparisler_page())
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
        self.tab_siparisler = QPushButton(f"{ICONS['menu_food']}  Sipariş Panosu")
        
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

    def _switch_tab(self, idx):
        self.pages.setCurrentIndex(idx)
        self.tab_bolgeler.setChecked(idx == 0)
        self.tab_siparisler.setChecked(idx == 1)
        self._update_tab_styles()
        if idx == 0:
            self._refresh_bolgeler()
        else:
            self._refresh_siparisler()

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

        # Grid
        self.user_masa_scroll = QScrollArea()
        self.user_masa_scroll.setWidgetResizable(True)
        self.user_masa_scroll.setStyleSheet("border: none; background: transparent;")
        ly.addWidget(self.user_masa_scroll, 1)

        self.current_region = None
        self._refresh_bolgeler()
        return page

    def _refresh_bolgeler(self):
        while self.region_tabs_layout.count():
            item = self.region_tabs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        regions = database.get_all_regions()
        
        # Current region kontrolü
        valid_rids = [r['id'] for r in regions]
        if self.current_region not in valid_rids and regions:
            self.current_region = regions[0]['id']

        for region in regions:
            tables = database.get_tables_by_region(region['id'])
            occ = sum(1 for t in tables if t['durum'] == 'dolu')
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

        self._load_tables(self.current_region)

    def _select_region(self, rid):
        self.current_region = rid
        self._refresh_bolgeler()

    def _load_tables(self, rid):
        if not rid:
            return
            
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
        if data.get('durum') == 'dolu':
            self._show_order_detail(data)
        else:
            self._create_order_dialog(data)

    def _show_order_detail(self, data):
        # Önce aktif siparişi bul — banner tutarı da buradan gelecek
        all_active = database.get_orders('hazirlaniyor') + database.get_orders('bekliyor')
        target_order = None
        for o in all_active:
            if o['masa_id'] == data['id']:
                target_order = o
                break

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Masa Detayı - {data['ad']}")
        dlg.setFixedSize(560, 560)
        dlg.setStyleSheet("background: white; border-radius: 16px;")

        ly = QVBoxLayout(dlg)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(0)

        # Banner — tutarı target_order'dan al, data'dan değil
        banner = QFrame()
        banner.setFixedHeight(95)
        banner.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {COLORS['primary']}, stop:1 {COLORS['primary_dark']});
            border-bottom-left-radius: 0; border-bottom-right-radius: 0;
            border-top-left-radius: 16px; border-top-right-radius: 16px;
        """)
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(28, 0, 28, 0)
        
        name_ly = QVBoxLayout()
        name_ly.setSpacing(2)
        name_ly.setAlignment(Qt.AlignVCenter)
        masa_lbl = QLabel(data['ad'])
        masa_lbl.setFont(QFont(FONTS['family'], 26, QFont.Bold))
        masa_lbl.setStyleSheet("color: white; background: transparent;")
        
        tarih_str = target_order['tarih'] if target_order else data.get('siparis_tarihi', '')
        try:
            from datetime import datetime
            dt = datetime.strptime(tarih_str, "%Y-%m-%d %H:%M")
            diff = datetime.now() - dt
            mins = int(diff.total_seconds() // 60)
            s_lbl = QLabel(f"{ICONS['dot']} {mins} dakikadır açık")
            s_lbl.setFont(QFont(FONTS['family'], FONTS['size_sm']))
            s_lbl.setStyleSheet("color: rgba(255,255,255,0.7); background: transparent;")
        except Exception:
            s_lbl = QLabel("Açılış Tarihi Bilinmiyor")
        
        name_ly.addWidget(masa_lbl)
        name_ly.addWidget(s_lbl)
        
        bl.addLayout(name_ly)
        bl.addStretch()
        
        gercek_tutar = (target_order['toplam_tutar'] if target_order else data.get('toplam_tutar')) or 0
        tutar_vl = QVBoxLayout()
        tutar_vl.setAlignment(Qt.AlignVCenter)
        tut_lbl = QLabel("Toplam Tutar")
        tut_lbl.setFont(QFont(FONTS['family'], 11))
        tut_lbl.setStyleSheet("color: rgba(255,255,255,0.7); background: transparent;")
        tut_vl = QLabel(f"₺{gercek_tutar:,.2f}")
        tut_vl.setFont(QFont(FONTS['family'], 22, QFont.Bold))
        tut_vl.setStyleSheet("color: white; background: transparent;")
        tutar_vl.addWidget(tut_lbl)
        tutar_vl.addWidget(tut_vl)
        bl.addLayout(tutar_vl)
        
        ly.addWidget(banner)

        # İçerik
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 20, 28, 20)
        cl.setSpacing(16)

        header_l = QLabel("Sipariş Özeti")
        header_l.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
        cl.addWidget(header_l)

        # Sipariş Edilenler Scroll
        items_scroll = QScrollArea()
        items_scroll.setWidgetResizable(True)
        items_scroll.setStyleSheet(f"border: 1px solid {COLORS['border_light']}; border-radius: 12px; background: {COLORS['bg_input']};")
        
        icw = QWidget()
        icw.setStyleSheet("background: transparent;")
        il = QVBoxLayout(icw)
        il.setSpacing(8)
                
        if target_order:
            items = database.get_order_items(target_order['id'])
            if items:
                for item in items:
                    ir = QFrame()
                    ir.setStyleSheet("background: white; border-radius: 8px;")
                    irl = QHBoxLayout(ir)
                    irl.setContentsMargins(12, 10, 12, 10)
                    
                    un = QLabel(item.get('urun_adi', 'Ürün'))
                    un.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
                    un.setStyleSheet(f"color: {COLORS['text_primary']};")
                    
                    a = QLabel(f"x{item.get('adet', 1)}")
                    a.setFont(QFont(FONTS['family'], FONTS['size_sm']))
                    a.setStyleSheet(f"color: {COLORS['text_secondary']};")
                    
                    p = QLabel(f"₺{(item.get('toplam') or 0):,.2f}")
                    p.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
                    p.setStyleSheet(f"color: {COLORS['primary']};")
                    
                    irl.addWidget(a)
                    irl.addSpacing(8)
                    irl.addWidget(un, 1)
                    irl.addWidget(p)
                    il.addWidget(ir)
            else:
                il.addWidget(QLabel("Masa açık ancak ürün detayı bulunamadı."))
        else:
            il.addWidget(QLabel("Bu masaya ait aktif sipariş bulunamadı."))

        il.addStretch()
        items_scroll.setWidget(icw)
        cl.addWidget(items_scroll, 1)

        # Butonlar
        close_btn = QPushButton("Kapat")
        close_btn.setObjectName("outlineBtn")
        close_btn.setFixedHeight(44)
        close_btn.clicked.connect(dlg.accept)

        transfer_btn = QPushButton(f"↔ Masa Transfer")
        transfer_btn.setObjectName("outlineBtn")
        transfer_btn.setFixedHeight(44)
        transfer_btn.setStyleSheet(transfer_btn.styleSheet() + f" color: {COLORS['info']}; border-color: {COLORS['info']};")
        transfer_btn.clicked.connect(lambda: self._transfer_table_dialog(data, target_order, dlg))

        add_btn = QPushButton(f"{ICONS['plus']} Yeni Ekle")
        add_btn.setObjectName("outlineBtn")
        add_btn.setFixedHeight(44)
        add_btn.setStyleSheet(add_btn.styleSheet() + f" color: {COLORS['warning_dark']}; border-color: {COLORS['warning_dark']};")
        add_btn.clicked.connect(lambda: [dlg.accept(), self._create_order_dialog(data)])

        pay_btn = QPushButton(f"{ICONS['money']}  Ödeme Al")
        pay_btn.setFixedHeight(52)
        pay_btn.setCursor(Qt.PointingHandCursor)
        pay_btn.setStyleSheet(f"""
            QPushButton {{
                background: #10B981;
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 15px;
                font-weight: bold;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background: #059669;
            }}
        """)
        pay_btn.clicked.connect(lambda: self._process_payment(data, target_order, dlg))

        # Üst sıra: Kapat | Masa Transfer | Yeni Ekle
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(close_btn, 1)
        top_row.addWidget(transfer_btn, 1)
        top_row.addWidget(add_btn, 1)

        cl.addLayout(top_row)
        cl.addWidget(pay_btn)

        ly.addWidget(content, 1)
        dlg.exec()

    def _transfer_table_dialog(self, from_data, target_order, parent_dlg):
        if not target_order:
            QMessageBox.warning(self, "Uyarı", "Aktif sipariş bulunamadı!")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Masa Transfer")
        dlg.setFixedSize(380, 220)
        fl = QFormLayout(dlg)
        fl.setContentsMargins(32, 28, 32, 28)
        fl.setSpacing(16)

        info = QLabel(f"'{from_data['ad']}' masasındaki siparişi\nhangi masaya taşımak istiyorsunuz?")
        info.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        fl.addRow(info)

        combo = QComboBox()
        combo.setFixedHeight(44)
        # Boş masaları listele
        for region in database.get_all_regions():
            for t in database.get_tables_by_region(region['id']):
                if t['durum'] == 'bos' and t['id'] != from_data['id']:
                    combo.addItem(f"{region['ad']} — {t['ad']}", t['id'])
        fl.addRow("Hedef Masa:", combo)

        warn = QLabel("")
        warn.setStyleSheet(f"color: {COLORS['danger']}; font-size: 12px;")
        fl.addRow(warn)

        btn = QPushButton("Taşı")
        btn.setObjectName("primaryBtn")
        btn.setFixedHeight(44)

        def do_transfer():
            to_id = combo.currentData()
            if not to_id:
                warn.setText("Boş masa bulunamadı!")
                return
            ok = database.transfer_table(from_data['id'], to_id, self.user['id'])
            if ok:
                parent_dlg.accept()
                self._refresh_bolgeler()
                ToastNotification(self, f"Sipariş {combo.currentText()} masasına taşındı.", "success")
                dlg.accept()
            else:
                warn.setText("Transfer başarısız!")

        btn.clicked.connect(do_transfer)
        fl.addRow(btn)
        dlg.exec()

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

    def _process_payment(self, m_data, o_data, dlg):
        if not o_data:
            # Aktif sipariş yok ama masa dolu — masayı direkt boşalt
            reply = QMessageBox.question(self, "Masayı Kapat",
                "Bu masaya ait aktif sipariş bulunamadı.\nMasayı yine de kapatmak istiyor musunuz?",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                conn = database.get_connection()
                conn.execute("UPDATE tables SET durum='bos', garson_id=NULL WHERE id=?", (m_data['id'],))
                conn.commit()
                conn.close()
                dlg.accept()
                self._refresh_bolgeler()
                ToastNotification(self, "Masa kapatıldı.", "success")
            return
        if not o_data:
            QMessageBox.warning(self, "Hata", "Ödenecek aktif bir sipariş bulunamadı!")
            return
            
        dlg2 = QDialog(self)
        dlg2.setWindowTitle("Ödeme Al")
        dlg2.setFixedSize(400, 300)
        
        fl = QFormLayout(dlg2)
        fl.setContentsMargins(32, 28, 32, 28)
        fl.setSpacing(16)
        
        t_lbl = QLabel(f"₺{(o_data['toplam_tutar'] or 0):,.2f}")
        t_lbl.setFont(QFont(FONTS['family'], 28, QFont.Bold))
        t_lbl.setStyleSheet(f"color: {COLORS['success']};")
        t_lbl.setAlignment(Qt.AlignCenter)
        
        combo = QComboBox()
        combo.addItems(["Nakit", "Kredi Kartı", "Cari Hesap", "Alman Usulü (Parçalı)"])
        combo.setFixedHeight(44)
        
        fl.addRow(t_lbl)
        fl.addRow(QLabel("Ödeme Yöntemi:"), combo)
        
        btn = QPushButton("Tahsil Et ve Masayı Kapat")
        btn.setObjectName("successBtn")
        btn.clicked.connect(lambda: [
            database.update_order_status(o_data['id'], 'tamamlandi'),
            QMessageBox.information(self, "Başarılı", "Tahsilat yapıldı, masa kapatıldı!"),
            dlg2.accept(),
            dlg.accept(),
            self._refresh_bolgeler()
        ])
        fl.addRow(btn)
        
        dlg2.exec()

    def _create_order_dialog(self, data):
        self._order_table_name = data['ad']
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Sipariş Oluştur - {data['ad']}")
        dlg.setFixedSize(650, 680)
        dlg.setStyleSheet("background: white; border-radius: 16px;")

        ly = QVBoxLayout(dlg)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(0)

        # Banner
        banner = QFrame()
        banner.setFixedHeight(75)
        banner.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {COLORS['primary']}, stop:1 {COLORS['primary_dark']});
            border-bottom-left-radius: 0; border-bottom-right-radius: 0;
            border-top-left-radius: 16px; border-top-right-radius: 16px;
        """)
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(28, 0, 28, 0)
        title = QLabel(f"{data['ad']} - Sipariş Girişi")
        title.setFont(QFont(FONTS['family'], FONTS['size_lg'], QFont.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        bl.addWidget(title)
        ly.addWidget(banner)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 20, 28, 20)
        cl.setSpacing(16)

        self.order_items = []
        self._order_total = 0

        # Ekleme satırı - Modern ve büyük
        add_frame = QFrame()
        add_frame.setObjectName("sepeteEkleFrame")
        add_frame.setStyleSheet(f"QFrame#sepeteEkleFrame {{ background: {COLORS['bg_input']}; border-radius: 12px; border: 1px solid {COLORS['border_light']}; }}")
        afl = QHBoxLayout(add_frame)
        afl.setContentsMargins(16, 16, 16, 16)
        afl.setSpacing(12)
        
        vl_inputs = QVBoxLayout()
        vl_inputs.setSpacing(10)

        # Ürün arama
        search_box = QLineEdit()
        search_box.setPlaceholderText("🔍 Ürün ara...")
        search_box.setFixedHeight(38)
        search_box.setStyleSheet(f"border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 0 10px; font-size: 13px;")

        cc = QComboBox()
        cc.addItem("Tüm Kategoriler", None)
        for c in database.get_all_categories():
            cc.addItem(c['ad'], c['id'])
        cc.setFixedHeight(44)

        pc = QComboBox()
        pc.setFixedHeight(44)

        all_products = database.get_products_by_category()

        def update_prods():
            pc.clear()
            txt = search_box.text().lower()
            cat = cc.currentData()
            for p in all_products:
                if cat and p['kategori_id'] != cat:
                    continue
                if txt and txt not in p['ad'].lower():
                    continue
                pc.addItem(f"{p['ad']} (₺{p['fiyat']:,.2f})", p['id'])

        cc.currentIndexChanged.connect(update_prods)
        search_box.textChanged.connect(update_prods)
        update_prods()

        vl_inputs.addWidget(search_box)
        vl_inputs.addWidget(cc)
        vl_inputs.addWidget(pc)
        afl.addLayout(vl_inputs, 1)

        vl_act = QVBoxLayout()
        vl_act.setSpacing(10)
        
        adet_frame = QFrame()
        adet_frame.setFixedHeight(44)
        adet_frame.setStyleSheet(f"background: white; border: 1px solid {COLORS['border']}; border-radius: 8px;")
        adet_layout = QHBoxLayout(adet_frame)
        adet_layout.setContentsMargins(4, 4, 4, 4)
        adet_layout.setSpacing(4)

        btn_eksi = QPushButton("-")
        btn_eksi.setFixedSize(36, 36)
        btn_eksi.setStyleSheet(f"background: {COLORS['bg_input']}; border: none; border-radius: 6px; font-weight: bold; font-size: 16px; color: {COLORS['text_dark']};")
        btn_eksi.setCursor(Qt.PointingHandCursor)
        
        lbl_adet = QLabel("1")
        lbl_adet.setAlignment(Qt.AlignCenter)
        lbl_adet.setFont(QFont(FONTS['family'], 14, QFont.Bold))
        lbl_adet.setStyleSheet("border: none; background: transparent;")
        
        btn_arti = QPushButton("+")
        btn_arti.setFixedSize(36, 36)
        btn_arti.setStyleSheet(f"background: {COLORS['bg_input']}; border: none; border-radius: 6px; font-weight: bold; font-size: 16px; color: {COLORS['text_dark']};")
        btn_arti.setCursor(Qt.PointingHandCursor)

        adet_layout.addWidget(btn_eksi)
        adet_layout.addWidget(lbl_adet, 1)
        adet_layout.addWidget(btn_arti)

        btn_eksi.clicked.connect(lambda: lbl_adet.setText(str(max(1, int(lbl_adet.text()) - 1))))
        btn_arti.clicked.connect(lambda: lbl_adet.setText(str(min(99, int(lbl_adet.text()) + 1))))

        vl_act.addWidget(adet_frame)

        add_btn = QPushButton(f"{ICONS['plus']} Sepete Ekle")
        add_btn.setStyleSheet(f"QPushButton {{ background-color: {COLORS['success']}; color: white; border: none; border-radius: 8px; font-weight: bold; font-size: 14px; }} QPushButton:hover {{ background-color: {COLORS['success_dark']}; }}")
        add_btn.setFixedHeight(44)
        vl_act.addWidget(add_btn)
        
        afl.addLayout(vl_act)
        cl.addWidget(add_frame)

        cl.addWidget(QLabel(f"<span style='font-weight:bold; font-size:16px;'>Sepet Özeti</span>"))

        # Sipariş notu alanı
        note_frame = QFrame()
        note_frame.setStyleSheet(f"QFrame {{ background: {COLORS['bg_input']}; border-radius: 10px; border: 1px solid {COLORS['border_light']}; }}")
        nfl = QHBoxLayout(note_frame)
        nfl.setContentsMargins(14, 10, 14, 10)
        note_icon = QLabel("📝")
        note_icon.setFixedWidth(24)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Sipariş notu (örn: az şekerli, allerji var...)")
        self.note_input.setStyleSheet("border: none; background: transparent; font-size: 13px;")
        nfl.addWidget(note_icon)
        nfl.addWidget(self.note_input, 1)
        cl.addWidget(note_frame)

        # Sepet scroll
        items_scroll = QScrollArea()
        items_scroll.setWidgetResizable(True)
        items_scroll.setStyleSheet(f"""
            border: 1px solid {COLORS['border']}; border-radius: 12px;
            background: {COLORS['bg_main']};
        """)
        ic = QWidget()
        ic.setStyleSheet("background: transparent;")
        self.items_layout = QVBoxLayout(ic)
        self.items_layout.setAlignment(Qt.AlignTop)
        self.items_layout.setContentsMargins(12, 12, 12, 12)
        self.items_layout.setSpacing(8)

        self.empty_msg = QLabel(f"{ICONS['menu_food']}\nHenüz ürün eklenmedi")
        self.empty_msg.setAlignment(Qt.AlignCenter)
        self.empty_msg.setFont(QFont(FONTS['family'], FONTS['size_md']))
        self.empty_msg.setStyleSheet(f"color: {COLORS['text_muted']}; padding: 30px;")
        self.items_layout.addWidget(self.empty_msg)

        items_scroll.setWidget(ic)
        cl.addWidget(items_scroll, 1)

        # Alt bar - Toplam ve Gönder
        bot_ly = QHBoxLayout()
        
        t_ly = QVBoxLayout()
        t_ly.setSpacing(2)
        tk = QLabel("Sipariş Toplamı:")
        tk.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.total_label = QLabel("₺0,00")
        self.total_label.setFont(QFont(FONTS['family'], 26, QFont.Bold))
        self.total_label.setStyleSheet(f"color: {COLORS['primary']};")

        # İskonto satırı — pill tasarımı
        iskonto_ly = QHBoxLayout()
        iskonto_ly.setSpacing(0)

        iskonto_frame = QFrame()
        iskonto_frame.setFixedHeight(56)
        iskonto_frame.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
        """)
        iskonto_inner = QHBoxLayout(iskonto_frame)
        iskonto_inner.setContentsMargins(10, 0, 10, 0)
        iskonto_inner.setSpacing(6)

        iskonto_lbl = QLabel("İskonto")
        iskonto_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent;")

        self.iskonto_input = QLineEdit("0")
        self.iskonto_input.setFixedSize(72, 34)
        self.iskonto_input.setAlignment(Qt.AlignCenter)
        self.iskonto_input.setStyleSheet(f"""
            border: none; background: white; border-radius: 5px;
            font-size: 13px; font-weight: bold; color: {COLORS['text_dark']};
        """)

        pct_lbl = QLabel("%")
        pct_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent;")

        self.iskonto_net_lbl = QLabel("")
        self.iskonto_net_lbl.setStyleSheet(f"color: {COLORS['danger']}; font-size: 12px; font-weight: bold; background: transparent;")

        iskonto_inner.addWidget(iskonto_lbl)
        iskonto_inner.addSpacing(4)
        iskonto_inner.addWidget(self.iskonto_input)
        iskonto_inner.addWidget(pct_lbl)
        iskonto_inner.addSpacing(6)
        iskonto_inner.addWidget(self.iskonto_net_lbl)

        def update_iskonto():
            try:
                pct = float(self.iskonto_input.text())
                pct = max(0, min(100, pct))
                net = self._order_total * (1 - pct / 100)
                if pct > 0:
                    self.iskonto_net_lbl.setText(f"→ ₺{net:,.2f}")
                else:
                    self.iskonto_net_lbl.setText("")
            except Exception:
                self.iskonto_net_lbl.setText("")
        self.iskonto_input.textChanged.connect(update_iskonto)

        iskonto_ly.addWidget(iskonto_frame)
        iskonto_ly.addStretch()

        t_ly.addWidget(tk)
        t_ly.addWidget(self.total_label)
        t_ly.addLayout(iskonto_ly)
        
        order_btn = QPushButton(f"{ICONS['check']} Siparişi Mutfağa Gönder")
        order_btn.setFont(QFont(FONTS['family'], 15, QFont.Bold))
        order_btn.setFixedHeight(56)
        order_btn.setMinimumWidth(320)
        order_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary']}; border: none; color: white;
                border-radius: 8px; padding: 0 24px; }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
        """)
        order_btn.setCursor(Qt.PointingHandCursor)
        order_btn.clicked.connect(lambda: self._submit_order(data['id'], dlg))
        add_shadow(order_btn, blur=15, offset_y=4, color=QColor(79, 70, 229, 60))

        bot_ly.addLayout(t_ly)
        bot_ly.addStretch()
        bot_ly.addWidget(order_btn)
        
        cl.addLayout(bot_ly)

        def add_item():
            pid = pc.currentData()
            ptext = pc.currentText()
            a = int(lbl_adet.text())
            lbl_adet.setText("1")
            if pid:
                if self.empty_msg.isVisible():
                    self.empty_msg.setVisible(False)
                self.order_items.append((pid, a))
                
                try:
                    price = float(ptext.split("₺")[1].replace(")", "").replace(",", ""))
                    t = price * a
                    self._order_total += t
                except Exception:
                    t = 0

                item_row = QFrame()
                item_row.setFixedHeight(50)
                item_row.setStyleSheet(f"background: white; border-radius: 8px; border: 1px solid {COLORS['border_light']};")
                add_shadow(item_row, blur=6, offset_y=2, color=QColor(0,0,0,5))
                irl = QHBoxLayout(item_row)
                irl.setContentsMargins(16, 0, 16, 0)
                
                parts = ptext.split(" (")
                nm = QLabel(parts[0])
                nm.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
                
                ad_lbl = QLabel(f"x{a}")
                ad_lbl.setFont(QFont(FONTS['family'], FONTS['size_md']))
                ad_lbl.setStyleSheet(f"color: {COLORS['text_muted']};")
                
                pr_btn = QLabel(f"₺{t:,.2f}")
                pr_btn.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
                pr_btn.setStyleSheet(f"color: {COLORS['primary']};")
                
                del_btn = QPushButton(ICONS['cross'])
                del_btn.setFixedSize(28,28)
                del_btn.setStyleSheet(f"background: {COLORS['bg_danger']}; color: {COLORS['danger']}; border-radius: 14px; font-weight: bold; border: none;")
                del_btn.setCursor(Qt.PointingHandCursor)

                def make_delete_handler(row_widget, item_pid, item_adet, item_tutar):
                    def _delete():
                        # UI'dan kaldır
                        row_widget.deleteLater()
                        # order_items listesinden ilk eşleşeni çıkar
                        try:
                            self.order_items.remove((item_pid, item_adet))
                        except ValueError:
                            pass
                        # Toplam tutarı düşür
                        self._order_total = max(0.0, self._order_total - item_tutar)
                        self.total_label.setText(f"₺{self._order_total:,.2f}")
                    return _delete

                del_btn.clicked.connect(make_delete_handler(item_row, pid, a, t))

                irl.addWidget(ad_lbl)
                irl.addSpacing(16)
                irl.addWidget(nm, 1)
                irl.addWidget(pr_btn)
                irl.addSpacing(12)
                irl.addWidget(del_btn)
                self.items_layout.addWidget(item_row)

                self.total_label.setText(f"₺{self._order_total:,.2f}")
                
        add_btn.clicked.connect(add_item)

        ly.addWidget(content, 1)
        dlg.exec()

    def _submit_order(self, masa_id, dlg):
        if not self.order_items:
            QMessageBox.warning(self, "Uyarı", "Sepet boş! Lütfen ürün ekleyin.")
            return
        # İskonto uygula
        try:
            pct = float(self.iskonto_input.text())
            pct = max(0, min(100, pct))
        except Exception:
            pct = 0
        if pct > 0:
            masa = getattr(self, '_order_table_name', f"Masa #{masa_id}")
            approver, _ = request_approval(self, self.user, 'discount', f"{masa} · %{pct:g} iskonto")
            if not approver:
                return
        order_id = database.create_order(masa_id, self.user['id'], self.order_items, iskonto_pct=pct)
        # Notu kaydet
        note = self.note_input.text().strip() if hasattr(self, 'note_input') else ""
        if note and order_id:
            database.add_order_note(order_id, note)
        dlg.accept()
        self._refresh_bolgeler()
        msg = f"Sipariş mutfağa iletildi!"
        if pct > 0:
            msg += f" (%{pct:.0f} iskonto uygulandı)"
        ToastNotification(self, msg, "success")

    # ==================== SİPARİŞ KANBAN PANOSU ====================
    def _create_siparisler_page(self):
        page = QWidget()
        ly = QVBoxLayout(page)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        # Üst bar
        sr = QHBoxLayout()
        self.kb_search = QLineEdit()
        self.kb_search.setPlaceholderText(f"{ICONS['search']} Sipariş kodu veya masa numarası...")
        self.kb_search.setFixedWidth(400)
        self.kb_search.setFixedHeight(44)
        self.kb_search.textChanged.connect(self._refresh_siparisler)
        sr.addWidget(self.kb_search)
        sr.addStretch()
        
        self.kb_filt = QComboBox()
        self.kb_filt.addItems(["Tümü", "Sadece Benim Siparişlerim", "Gecikenler"])
        self.kb_filt.setFixedHeight(44)
        self.kb_filt.currentIndexChanged.connect(self._refresh_siparisler)
        sr.addWidget(self.kb_filt)
        ly.addLayout(sr)

        # Kanban Board
        self.kanban_scroll = QScrollArea()
        self.kanban_scroll.setWidgetResizable(True)
        self.kanban_scroll.setStyleSheet("border: none; background: transparent;")
        ly.addWidget(self.kanban_scroll, 1)
        
        self._refresh_siparisler()
        return page

    def _refresh_siparisler(self, *args):
        cw = QWidget()
        cw.setStyleSheet("background: transparent;")
        kl = QHBoxLayout(cw)
        kl.setSpacing(24)
        kl.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        search_txt = self.kb_search.text().lower() if hasattr(self, 'kb_search') else ""
        filt_idx = self.kb_filt.currentIndex() if hasattr(self, 'kb_filt') else 0

        columns = [
            ("Mutfakta (Hazırlanıyor)", "hazirlaniyor", COLORS['bg_warning'], COLORS['warning']),
            ("Hazır (Teslim Bekliyor)", "bekliyor", COLORS['bg_success'], COLORS['success']),
        ]

        for title, status, bg, dot_color in columns:
            raw_orders = database.get_orders(status)
            orders = []
            for o in raw_orders:
                if search_txt and search_txt not in str(o.get('id', '')) and search_txt not in o.get('masa_adi', '').lower():
                    continue
                if filt_idx == 1 and o.get('garson_id') != self.user.get('id'):
                    continue
                if filt_idx == 2:
                    # Geciken: 30 dakikadan eski siparişler
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(o.get('tarih', ''), "%Y-%m-%d %H:%M")
                        if (datetime.now() - dt).total_seconds() < 1800:
                            continue
                    except Exception:
                        pass
                o['items'] = database.get_order_items(o['id'])
                orders.append(o)
            
            # Kolon Container
            col = QFrame()
            col.setFixedWidth(340)
            col.setStyleSheet(f"""
                QFrame {{ background: {bg}; border-radius: 16px;
                    border: 1px solid {COLORS['border']}; }}
            """)
            cl = QVBoxLayout(col)
            cl.setContentsMargins(16, 20, 16, 20)
            cl.setSpacing(16)

            # Başlık
            h_ly = QHBoxLayout()
            dot = QLabel(ICONS['circle'])
            dot.setStyleSheet(f"color: {dot_color}; font-size: 14px;")
            dot.setFixedWidth(20)
            
            h = QLabel(f"{title}")
            h.setFont(QFont(FONTS['family'], FONTS['size_md'], QFont.Bold))
            h.setStyleSheet(f"color: {COLORS['text_dark']};")
            
            cnt = QLabel(str(len(orders)))
            cnt.setStyleSheet(f"background: white; border-radius: 8px; padding: 2px 8px; font-weight: bold; color: {COLORS['text_primary']}; border: 1px solid {COLORS['border_light']};")
            
            h_ly.addWidget(dot)
            h_ly.addWidget(h, 1)
            h_ly.addWidget(cnt)
            cl.addLayout(h_ly)

            if not orders:
                empty = QLabel(f"<div style='text-align:center;'><br><br><span style='font-size:32px;'>{ICONS['check']}</span><br><br>Bu listeye ait sipariş yok.</div>")
                empty.setStyleSheet(f"color: {COLORS['text_muted']}; border: 2px dashed {COLORS['border']}; border-radius: 12px;")
                cl.addWidget(empty)
            else:
                for order in orders:
                    card = OrderCard(order)
                    card.status_changed.connect(self._on_order_status_changed)
                    card.detail_requested.connect(lambda data: InfoDialog("Sipariş Detayı", f"Sipariş No: #{data['id']}\nMasa: {data['masa_adi']}\n\nDetaylı ürün listesi burada görüntülenecektir.", COLORS['info'], self).exec())
                    cl.addWidget(card)

            cl.addStretch()
            kl.addWidget(col)

        kl.addStretch()
        self.kanban_scroll.setWidget(cw)

    def _on_order_status_changed(self, order_id, new_status):
        if new_status == 'iptal':
            approver, _ = request_approval(self, self.user, 'voidItem', f"Sipariş #{order_id} iptali")
            if not approver:
                return
        database.update_order_status(order_id, new_status)
        self._refresh_siparisler()
        self._refresh_bolgeler()
        msg = "iptal edildi" if new_status == 'iptal' else "tamamlandı ve teslim edildi"
        ToastNotification(self, f"Sipariş #{order_id} {msg}.", "success" if new_status != 'iptal' else "warning")
