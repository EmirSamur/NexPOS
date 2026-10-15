"""
NexPOS - Yönetim paneli: Kullanıcılar, Yetki Matrisi ve Terminaller sayfaları.

Bu sayfalardaki değişiklikler doğrudan buluta yazılır (Cloud Functions) ve
yöneticinin kendi hesabıyla yapılır; liste ve matris ise yerel önbellekten okunur,
böylece internet yokken de görüntülenebilir.
"""
from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QFont, QColor, QRegularExpressionValidator
from styles import COLORS, FONTS, ICONS
from widgets import PageHeader, ToastNotification
from access import require_admin_api
from cloud.context import ctx
from cloud.permissions import (
    PANEL_ROLES, PERMISSIONS, ROLE_LABELS, ROLES, can_manage_role
)
from cloud.pins import is_valid_pin
from cloud.qt_sync import run_async
import database


def _button(text, primary=True):
    b = QPushButton(text)
    b.setFixedHeight(40)
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setStyleSheet(f"""
            QPushButton {{ background: {COLORS['primary']}; border: none; color: white;
                font-size: 13px; font-weight: bold; border-radius: 8px; padding: 0 18px; }}
            QPushButton:hover {{ background: {COLORS['primary_dark']}; }}
            QPushButton:disabled {{ background: {COLORS['border']}; }}
        """)
    else:
        b.setStyleSheet(f"""
            QPushButton {{ background: white; border: 1px solid {COLORS['border']}; color: {COLORS['text_primary']};
                font-size: 13px; font-weight: bold; border-radius: 8px; padding: 0 16px; }}
            QPushButton:hover {{ background: {COLORS['bg_hover']}; }}
            QPushButton:disabled {{ color: {COLORS['text_muted']}; }}
        """)
    return b


def _format_time(iso):
    if not iso:
        return '—'
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone()
        return dt.strftime('%d.%m.%Y %H:%M')
    except ValueError:
        return iso


def cloud_action(page, fn, success_message, on_success=None):
    """
    Buluta yazan bir işlemi arka planda çalıştırır, ardından önbelleği tazeler.
    fn(api) şeklinde çağrılır; api yöneticinin oturumudur.
    """
    api = require_admin_api(page, page.user)
    if not api:
        return

    def work():
        result = fn(api)
        # Değişiklik hemen bu bilgisayara da insin; olmazsa bir sonraki senkronda iner.
        try:
            if ctx.engine:
                ctx.engine.pull()
        except Exception:
            ctx.request_sync()
        return result

    def done(result):
        ToastNotification(page.window(), success_message, "success")
        if on_success:
            on_success(result)

    def failed(message):
        QMessageBox.warning(page, "İşlem yapılamadı", message)

    run_async(work, done, failed)


# =====================================================================
# Kullanıcılar
# =====================================================================

class StaffPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        ly = QVBoxLayout(self)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        hr = QHBoxLayout()
        hr.addWidget(PageHeader("Kullanıcılar", "Personel, roller ve PIN kodları. Değişiklikler buluta kaydedilir.",
                                COLORS['primary_dark'], ICONS['user']), 1)
        self.add_btn = _button(f"{ICONS['plus']} Personel Ekle")
        self.add_btn.clicked.connect(lambda: self._open_dialog(None))
        hr.addWidget(self.add_btn, 0, Qt.AlignVCenter)
        ly.addLayout(hr)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Ad Soyad", "Rol", "Telefon", "Panel E-postası", "Durum", "Son Giriş"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda _: self._edit())
        ly.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.edit_btn = _button(f"{ICONS['edit']} Düzenle", primary=False)
        self.edit_btn.clicked.connect(self._edit)
        self.pin_btn = _button("🔑 PIN Sıfırla", primary=False)
        self.pin_btn.clicked.connect(self._reset_pin)
        self.active_btn = _button("Pasife Al", primary=False)
        self.active_btn.clicked.connect(self._toggle_active)
        for b in (self.edit_btn, self.pin_btn, self.active_btn):
            actions.addWidget(b)
        actions.addStretch()
        note = QLabel("Garson, kasa, barista ve mutfak personeli yalnızca PIN ile girer. "
                      "Yönetici ve müdürün ayrıca panel e-postası olur.")
        note.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        actions.addWidget(note)
        ly.addLayout(actions)
        self.refresh()

    def refresh(self):
        self.staff = database.get_all_staff()
        self.table.setRowCount(len(self.staff))
        for i, s in enumerate(self.staff):
            name = QTableWidgetItem(s['name'])
            name.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
            self.table.setItem(i, 0, name)
            role = QTableWidgetItem(ROLE_LABELS.get(s['role'], s['role']))
            if s['role'] in PANEL_ROLES:
                role.setForeground(QColor(COLORS['primary']))
            self.table.setItem(i, 1, role)
            self.table.setItem(i, 2, QTableWidgetItem(s['phone'] or ''))
            self.table.setItem(i, 3, QTableWidgetItem(s['email'] or '—'))
            status = QTableWidgetItem("Aktif" if s['active'] else "Pasif")
            status.setForeground(QColor(COLORS['success'] if s['active'] else COLORS['text_muted']))
            self.table.setItem(i, 4, status)
            self.table.setItem(i, 5, QTableWidgetItem(_format_time(s['last_login_at'])))
        self._update_buttons()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.staff[rows[0].row()] if rows else None

    def _update_buttons(self):
        s = self._selected()
        can = bool(s) and can_manage_role(self.user.get('role'), s['role'])
        for b in (self.edit_btn, self.pin_btn, self.active_btn):
            b.setEnabled(can)
        if s:
            self.active_btn.setText("Pasife Al" if s['active'] else "Aktif Et")
        if s and s['id'] == self.user.get('cloud_id'):
            self.active_btn.setEnabled(False)

    def _edit(self):
        s = self._selected()
        if s and can_manage_role(self.user.get('role'), s['role']):
            self._open_dialog(s)

    def _open_dialog(self, staff):
        dlg = StaffDialog(self.user, staff, self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values
        if staff:
            cloud_action(self, lambda api: api.update_staff(
                staff['id'], v['name'], v['role'], v['phone'], v.get('email'), v.get('password')),
                f"{v['name']} güncellendi.", lambda _: self.refresh())
        else:
            cloud_action(self, lambda api: api.create_staff(
                v['name'], v['role'], v['pin'], v['phone'], v.get('email'), v.get('password')),
                f"{v['name']} eklendi. PIN'i ile giriş yapabilir.", lambda _: self.refresh())

    def _reset_pin(self):
        s = self._selected()
        if not s:
            return
        dlg = PinResetDialog(s['name'], self)
        if dlg.exec() == QDialog.Accepted:
            cloud_action(self, lambda api: api.set_pin(s['id'], dlg.pin),
                         f"{s['name']} için yeni PIN kaydedildi.", lambda _: self.refresh())

    def _toggle_active(self):
        s = self._selected()
        if not s:
            return
        new_state = not s['active']
        if not new_state and QMessageBox.question(
                self, "Pasife Al",
                f"{s['name']} pasife alınsın mı?\nGiriş ekranından kaldırılır, geçmiş kayıtları korunur.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        cloud_action(self, lambda api: api.set_active(s['id'], new_state),
                     f"{s['name']} {'aktif edildi' if new_state else 'pasife alındı'}.",
                     lambda _: self.refresh())


class StaffDialog(QDialog):
    def __init__(self, actor, staff=None, parent=None):
        super().__init__(parent)
        self.staff = staff
        self.values = None
        self.setWindowTitle("Personeli Düzenle" if staff else "Yeni Personel")
        self.setFixedWidth(480)
        self.setStyleSheet("QDialog { background: white; }")
        form = QFormLayout(self)
        form.setContentsMargins(32, 28, 32, 28)
        form.setSpacing(14)

        self.name = QLineEdit(staff['name'] if staff else '')
        self.name.setPlaceholderText("Örn: Ali Yılmaz")
        self.phone = QLineEdit(staff['phone'] if staff and staff['phone'] else '')
        self.phone.setPlaceholderText("5XXXXXXXXX (isteğe bağlı)")
        self.phone.setValidator(QRegularExpressionValidator(QRegularExpression(r"^5\d{0,9}$")))
        self.role = QComboBox()
        for r in ROLES:
            if can_manage_role(actor.get('role'), r):
                self.role.addItem(ROLE_LABELS[r], r)
        if staff:
            idx = self.role.findData(staff['role'])
            if idx >= 0:
                self.role.setCurrentIndex(idx)
        form.addRow("Ad Soyad:", self.name)
        form.addRow("Telefon:", self.phone)
        form.addRow("Rol:", self.role)

        self.pin = QLineEdit()
        self.pin2 = QLineEdit()
        for w in (self.pin, self.pin2):
            w.setEchoMode(QLineEdit.Password)
            w.setMaxLength(6)
            w.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d{0,6}$")))
        if not staff:
            form.addRow("PIN (6 hane):", self.pin)
            form.addRow("PIN tekrar:", self.pin2)

        self.panel_box = QFrame()
        pf = QFormLayout(self.panel_box)
        pf.setContentsMargins(0, 8, 0, 0)
        pf.setSpacing(10)
        hint = QLabel("Yönetici ve müdür panele e-posta ve şifreyle de girebilir "
                      "(menü, personel ve yetki düzenlemek için gerekir).")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        pf.addRow(hint)
        self.email = QLineEdit(staff['email'] if staff and staff['email'] else '')
        self.email.setPlaceholderText("ornek@kafe.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("En az 8 karakter" + (" (değiştirmek için doldurun)" if staff and staff['email'] else ""))
        pf.addRow("Panel e-postası:", self.email)
        pf.addRow("Panel şifresi:", self.password)
        form.addRow(self.panel_box)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; font-size: 12px; background: transparent;")
        form.addRow(self.warn)

        save = QPushButton("Kaydet")
        save.setObjectName("primaryBtn")
        save.setFixedHeight(44)
        save.clicked.connect(self._save)
        form.addRow(save)

        self.role.currentIndexChanged.connect(self._toggle_panel)
        self._toggle_panel()

    def _toggle_panel(self):
        self.panel_box.setVisible(self.role.currentData() in PANEL_ROLES)
        self.adjustSize()

    def _save(self):
        warnings = []
        name = self.name.text().strip()
        role = self.role.currentData()
        if len(name) < 2:
            warnings.append("• Ad soyad en az 2 karakter olmalı")
        phone = self.phone.text().strip() or None
        if phone and len(phone) != 10:
            warnings.append("• Telefon 5 ile başlayan 10 haneli olmalı")
        values = {'name': name, 'role': role, 'phone': phone}
        if not self.staff:
            pin = self.pin.text()
            if not is_valid_pin(pin):
                warnings.append("• PIN 6 haneli olmalı; 123456, 111111 gibi kolay PIN'ler kullanılamaz")
            elif pin != self.pin2.text():
                warnings.append("• PIN'ler eşleşmiyor")
            values['pin'] = pin
        if role in PANEL_ROLES:
            email = self.email.text().strip().lower()
            password = self.password.text()
            had_email = bool(self.staff and self.staff['email'])
            if '@' not in email:
                warnings.append("• Panel e-postası gerekli")
            if (not had_email and len(password) < 8) or (password and len(password) < 8):
                warnings.append("• Panel şifresi en az 8 karakter olmalı")
            values['email'] = email
            values['password'] = password or None
        if warnings:
            self.warn.setText("\n".join(warnings))
            return
        self.values = values
        self.accept()


class PinResetDialog(QDialog):
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.pin = None
        self.setWindowTitle("PIN Sıfırla")
        self.setFixedWidth(400)
        self.setStyleSheet("QDialog { background: white; }")
        form = QFormLayout(self)
        form.setContentsMargins(28, 24, 28, 24)
        form.setSpacing(12)
        form.addRow(QLabel(f"<b>{name}</b> için yeni PIN belirleyin."))
        self.p1, self.p2 = QLineEdit(), QLineEdit()
        for w in (self.p1, self.p2):
            w.setEchoMode(QLineEdit.Password)
            w.setMaxLength(6)
            w.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d{0,6}$")))
        form.addRow("Yeni PIN:", self.p1)
        form.addRow("Tekrar:", self.p2)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color: {COLORS['danger']}; background: transparent;")
        form.addRow(self.warn)
        ok = QPushButton("Kaydet")
        ok.setObjectName("primaryBtn")
        ok.clicked.connect(self._save)
        form.addRow(ok)

    def _save(self):
        if not is_valid_pin(self.p1.text()):
            self.warn.setText("PIN 6 haneli olmalı ve kolay tahmin edilmemeli.")
        elif self.p1.text() != self.p2.text():
            self.warn.setText("PIN'ler eşleşmiyor.")
        else:
            self.pin = self.p1.text()
            self.accept()


# =====================================================================
# Yetki matrisi
# =====================================================================

class PermissionsPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.is_owner = user.get('role') == 'owner'
        ly = QVBoxLayout(self)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        hr = QHBoxLayout()
        hr.addWidget(PageHeader("Yetkilendirme Matrisi",
                                "Rollerin işlem yetkileri. Yetkisi olmayan işlemde yetkili onayı istenir.",
                                COLORS['sidebar_bg'], ICONS['lock']), 1)
        self.save_btn = _button(f"{ICONS['save']} Yetkileri Kaydet")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(self.is_owner)
        hr.addWidget(self.save_btn, 0, Qt.AlignVCenter)
        ly.addLayout(hr)

        if not self.is_owner:
            n = QLabel("Yetki matrisini yalnızca Yönetici rolü değiştirebilir.")
            n.setStyleSheet(f"color: {COLORS['warning_dark']}; background: {COLORS['bg_warning']}; "
                            f"padding: 10px; border-radius: 8px;")
            ly.addWidget(n)

        self.table = QTableWidget(len(PERMISSIONS), len(ROLES) + 1)
        self.table.setHorizontalHeaderLabels(["Yetki"] + [ROLE_LABELS[r] for r in ROLES])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        ly.addWidget(self.table, 1)
        self.checks = {}
        self.refresh()

    def refresh(self):
        matrix = database.get_permission_matrix()
        for i, (key, label) in enumerate(PERMISSIONS):
            item = QTableWidgetItem(label)
            item.setFont(QFont(FONTS['family'], FONTS['size_sm'], QFont.Bold))
            self.table.setItem(i, 0, item)
            for j, role in enumerate(ROLES):
                cb = QCheckBox()
                cb.setChecked(bool(matrix[role][key]))
                cb.setEnabled(self.is_owner and role != 'owner')
                w = QWidget()
                l = QHBoxLayout(w)
                l.addWidget(cb)
                l.setAlignment(Qt.AlignCenter)
                l.setContentsMargins(0, 0, 0, 0)
                self.table.setCellWidget(i, j + 1, w)
                self.checks[(role, key)] = cb

    def _save(self):
        roles = {r: {k: self.checks[(r, k)].isChecked() for k, _ in PERMISSIONS} for r in ROLES}

        def saved(result):
            database.set_setting('permissions', {'roles': result['roles']})
            self.refresh()

        cloud_action(self, lambda api: api.save_permissions(roles), "Yetki matrisi kaydedildi.", saved)


# =====================================================================
# Terminaller
# =====================================================================

ONLINE_WINDOW_SECONDS = 120


class TerminalsPage(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.terminals = []
        ly = QVBoxLayout(self)
        ly.setContentsMargins(32, 24, 32, 32)
        ly.setSpacing(16)

        hr = QHBoxLayout()
        hr.addWidget(PageHeader("Terminaller", "Kafeye bağlı bilgisayarlar ve bu bilgisayarın işlem kuyruğu.",
                                COLORS['info'], ICONS['settings']), 1)
        load = _button(f"{ICONS['refresh']} Buluttan Yükle", primary=False)
        load.clicked.connect(self._load)
        hr.addWidget(load, 0, Qt.AlignVCenter)
        ly.addLayout(hr)

        # Bu bilgisayarın kuyruğu (internetsiz de görünür)
        self.local_box = QLabel()
        self.local_box.setWordWrap(True)
        self.local_box.setTextFormat(Qt.RichText)
        ly.addWidget(self.local_box)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Ad", "Harf / Tür", "Durum", "Son Görülme", "Bekleyen İşlem", "Sürüm"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        ly.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.kds_btn = _button("🍳 Mutfak Ekranı Ekle")
        self.kds_btn.setToolTip("Mutfak/bar tableti için eşleme kodu üretir (Modüller → Mutfak Ekranı açık olmalı).")
        self.kds_btn.clicked.connect(self._add_kds)
        actions.addWidget(self.kds_btn)
        self.revoke_btn = _button("⛔ Terminali / Ekranı İptal Et", primary=False)
        self.revoke_btn.clicked.connect(self._revoke)
        actions.addWidget(self.revoke_btn)
        actions.addStretch()
        hint = QLabel("Çalınan ya da kullanılmayan bilgisayarı iptal edin; bir sonraki senkronda kilitlenir.")
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        actions.addWidget(hint)
        ly.addLayout(actions)
        self.refresh_local()

    def refresh_local(self):
        self.kds_btn.setVisible(database.modules()['kds']['enabled'])
        pending, failed = database.outbox_counts()
        status = ctx.last_status
        conn = ("🟢 Çevrimiçi" if status and status.online else "🟠 Çevrimdışı")
        last = status.last_sync if status and status.last_sync else database.get_sync_state('last_sync', '—')
        name = f"{ctx.creds.name} ({ctx.creds.letter})" if ctx.creds else "—"
        html = (f"<b>Bu bilgisayar:</b> {name} &nbsp;·&nbsp; {conn} &nbsp;·&nbsp; Son senkron: {last} "
                f"&nbsp;·&nbsp; Bekleyen işlem: <b>{pending}</b>")
        if failed:
            html += f" &nbsp;·&nbsp; <span style='color:{COLORS['danger']}'><b>Hatalı işlem: {failed}</b></span>"
            for op in database.get_failed_ops()[:5]:
                html += f"<br>&nbsp;&nbsp;• {op['op']} ({op['created_at'][:16]}): {op['last_error']}"
        self.local_box.setText(html)
        self.local_box.setStyleSheet(f"background: white; border: 1px solid {COLORS['border_light']}; "
                                     f"border-radius: 10px; padding: 14px;")

    def _load(self):
        self.refresh_local()
        api = require_admin_api(self, self.user)
        if not api:
            return
        run_async(api.list_terminals, self._show_terminals,
                  lambda m: QMessageBox.warning(self, "Yüklenemedi", m))

    def _show_terminals(self, docs):
        self.terminals = sorted(docs, key=lambda d: (d[1].get('kind') == 'kds', d[1].get('letter') or '', d[1].get('name', '')))
        self.table.setRowCount(len(self.terminals))
        now = datetime.now(timezone.utc)
        for i, (tid, t) in enumerate(self.terminals):
            mine = ctx.creds and tid == ctx.creds.terminal_id
            self.table.setItem(i, 0, QTableWidgetItem(t.get('name', '') + ("  (bu bilgisayar)" if mine else "")))
            kind = (f"Mutfak ekranı · {KDS_STATIONS.get(t.get('station'), '')}" if t.get('kind') == 'kds'
                    else t.get('letter', ''))
            self.table.setItem(i, 1, QTableWidgetItem(kind))
            seen = t.get('lastSeenAt')
            if t.get('revoked'):
                state, color = "İptal edildi", COLORS['text_muted']
            else:
                try:
                    age = (now - datetime.fromisoformat(seen.replace('Z', '+00:00'))).total_seconds()
                except (AttributeError, ValueError):
                    age = None
                online = age is not None and age < ONLINE_WINDOW_SECONDS
                state, color = ("🟢 Çevrimiçi", COLORS['success']) if online else ("🟠 Çevrimdışı", COLORS['warning_dark'])
            st = QTableWidgetItem(state)
            st.setForeground(QColor(color))
            self.table.setItem(i, 2, st)
            self.table.setItem(i, 3, QTableWidgetItem(_format_time(seen)))
            self.table.setItem(i, 4, QTableWidgetItem(str(t.get('pendingOps', 0))))
            self.table.setItem(i, 5, QTableWidgetItem(t.get('appVersion') or ''))

    def _add_kds(self):
        def show(result):
            KdsCodeDialog(result['code'], result['expiresInMinutes'], self).exec()
            self._load()
        cloud_action(self, lambda api: api.create_kds_pairing_code(), "Eşleme kodu üretildi.", show)

    def _revoke(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Terminal seçin", "Önce 'Buluttan Yükle' ile listeyi getirip bir terminal seçin.")
            return
        tid, t = self.terminals[rows[0].row()]
        if t.get('revoked'):
            return
        mine = ctx.creds and tid == ctx.creds.terminal_id
        warn = ("\n\nDİKKAT: Bu, şu an kullandığınız bilgisayar. İptal edilince NexPOS kilitlenir ve "
                "yeniden bağlanması gerekir.") if mine else ""
        if QMessageBox.question(self, "Terminali İptal Et",
                                f"{t.get('name')} ({t.get('letter') or 'mutfak ekranı'}) iptal edilsin mi?{warn}",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        cloud_action(self, lambda api: api.revoke_terminal(tid), f"{t.get('name')} iptal edildi.",
                     lambda _: self._load())


KDS_STATIONS = {'kitchen': 'Mutfak', 'bar': 'Bar', 'all': 'Mutfak + Bar'}


def kds_url():
    """Mutfak ekranının adresi: QR adresiyle aynı alan adı, /mutfak yolu."""
    from urllib.parse import urlsplit
    from qr_print import default_base_url
    base = database.general_settings()['qrBaseUrl'] or (default_base_url(ctx.config.project_id) if ctx.config else '')
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}/mutfak" if parts.netloc else "/mutfak"


class KdsCodeDialog(QDialog):
    """Eşleme kodu: tablette adres açılır, kod girilir, istasyon seçilir."""

    def __init__(self, code, minutes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mutfak Ekranı Ekle")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumWidth(460)
        ly = QVBoxLayout(self)
        ly.setContentsMargins(28, 24, 28, 24)
        ly.setSpacing(12)
        steps = QLabel(f"1. Mutfaktaki tablette şu adresi açın:<br><b style='font-size:15px'>{kds_url()}</b><br><br>"
                       "2. Aşağıdaki kodu girin ve istasyonu (Mutfak / Bar / İkisi) seçin.")
        steps.setTextFormat(Qt.RichText)
        steps.setTextInteractionFlags(Qt.TextSelectableByMouse)
        steps.setWordWrap(True)
        ly.addWidget(steps)
        big = QLabel(" ".join(code))
        big.setAlignment(Qt.AlignCenter)
        big.setFont(QFont("Consolas", 40, QFont.Bold))
        big.setTextInteractionFlags(Qt.TextSelectableByMouse)
        big.setStyleSheet(f"color: {COLORS['primary']}; background: {COLORS['primary_bg']}; border-radius: 12px; padding: 14px;")
        ly.addWidget(big)
        note = QLabel(f"Kod {minutes} dakika geçerlidir ve bir kez kullanılır. Tablet, bu listede ayrı bir satır olarak "
                      "görünür ve buradan iptal edilebilir.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
        ly.addWidget(note)
        ok = _button("Tamam")
        ok.clicked.connect(self.accept)
        ly.addWidget(ok)
