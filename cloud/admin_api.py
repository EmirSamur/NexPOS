"""
Yönetim panelinin buluta doğrudan yazdığı işlemler (internet gerektirir).

Bu işlemler terminal hesabıyla değil, panele giren yöneticinin/müdürün kendi
Firebase hesabıyla yapılır; böylece sunucu kimin ne yaptığını bilir ve yetkisini
kontrol eder.
"""
import json
import uuid
from urllib.parse import quote

from cloud.firebase_client import ApiError


class AdminApi:
    def __init__(self, client, session):
        self.client = client
        self.session = session

    def _call(self, name, data):
        self.session = self.client.ensure_fresh(self.session)
        return self.client.call(name, data, self.session)

    def create_staff(self, name, role, pin, phone=None, email=None, password=None):
        data = {'action': 'create', 'name': name, 'role': role, 'pin': pin, 'phone': phone}
        if email:
            data['email'] = email
            data['password'] = password
        return self._call('manageStaff', data)

    def update_staff(self, staff_id, name, role, phone=None, email=None, password=None):
        data = {'action': 'update', 'staffId': staff_id, 'name': name, 'role': role, 'phone': phone}
        if email:
            data['email'] = email
        if password:
            data['password'] = password
        return self._call('manageStaff', data)

    def set_pin(self, staff_id, pin):
        return self._call('manageStaff', {'action': 'setPin', 'staffId': staff_id, 'pin': pin})

    def set_active(self, staff_id, active):
        return self._call('manageStaff', {'action': 'setActive', 'staffId': staff_id, 'active': active})

    def save_permissions(self, roles):
        return self._call('savePermissions', {'roles': roles})

    def list_terminals(self):
        self.session = self.client.ensure_fresh(self.session)
        return self.client.list_docs('terminals', self.session)

    def revoke_terminal(self, terminal_id):
        return self._call('revokeTerminal', {'terminalId': terminal_id})

    # ---------------------------------------------------------------- menü
    def save_category(self, data, category_id=None):
        return self._call('saveCategory', {**data, **({'id': category_id} if category_id else {})})

    def delete_category(self, category_id):
        return self._call('deleteCategory', {'id': category_id})

    def save_product(self, data, product_id=None):
        return self._call('saveProduct', {**data, **({'id': product_id} if product_id else {})})

    def delete_product(self, product_id):
        return self._call('deleteProduct', {'id': product_id})

    def save_option_group(self, data, group_id=None):
        return self._call('saveOptionGroup', {**data, **({'id': group_id} if group_id else {})})

    def delete_option_group(self, group_id):
        return self._call('deleteOptionGroup', {'id': group_id})

    def reorder(self, kind, ids):
        return self._call('reorderMenu', {'kind': kind, 'ids': ids})

    def bulk_prices(self, category_ids, rule, include_options, dry_run):
        return self._call('bulkUpdatePrices', {'categoryIds': category_ids, 'rule': rule,
                                               'includeOptions': include_options, 'dryRun': dry_run})

    def import_menu(self, categories, products):
        return self._call('importMenu', {'categories': categories, 'products': products})

    # --------------------------------------------------------- salon planı
    def save_area(self, name, area_id=None):
        return self._call('saveArea', {'name': name, **({'id': area_id} if area_id else {})})

    def delete_area(self, area_id):
        return self._call('deleteArea', {'id': area_id})

    def save_floor_plan(self, area_id, expected_version, tables, fixtures, removed_table_ids=()):
        return self._call('saveFloorPlan', {'areaId': area_id, 'expectedVersion': expected_version,
                                            'tables': tables, 'fixtures': fixtures,
                                            'removedTableIds': list(removed_table_ids)})

    def rotate_table_qr(self, table_ids):
        return self._call('rotateTableQr', {'tableIds': list(table_ids)})

    def import_floor(self, areas):
        return self._call('importFloor', {'areas': areas})

    def save_general_settings(self, cafe_name, qr_base_url, idle_lock_minutes):
        return self._call('saveGeneralSettings', {'cafeName': cafe_name, 'qrBaseUrl': qr_base_url,
                                                  'idleLockMinutes': idle_lock_minutes})

    def create_kds_pairing_code(self, name=None):
        """Mutfak ekranı için 10 dakika geçerli 6 haneli eşleme kodu: {'code', 'expiresInMinutes'}"""
        return self._call('createKdsPairingCode', {'name': name} if name else {})

    # --- Stok (8. ekran)
    def save_ingredient(self, data, ingredient_id=None):
        return self._call('saveIngredient', {**data, **({'id': ingredient_id} if ingredient_id else {})})

    def delete_ingredient(self, ingredient_id):
        return self._call('deleteIngredient', {'id': ingredient_id})

    def save_supplier(self, data, supplier_id=None):
        return self._call('saveSupplier', {**data, **({'id': supplier_id} if supplier_id else {})})

    def delete_supplier(self, supplier_id):
        return self._call('deleteSupplier', {'id': supplier_id})

    def save_purchase_order(self, data, order_id=None):
        return self._call('savePurchaseOrder', {**data, **({'id': order_id} if order_id else {})})

    def cancel_purchase_order(self, order_id):
        return self._call('cancelPurchaseOrder', {'id': order_id})

    # --- Vardiya (9. ekran)
    def save_shift_plans(self, cells):
        return self._call('saveShiftPlans', {'cells': cells})

    def publish_shift_week(self, week_start):
        return self._call('publishShiftWeek', {'weekStart': week_start})

    def save_wages(self, wages):
        """wages: {staffId: kuruş/saat ya da None} — yalnızca yönetici."""
        return self._call('saveWages', {'wages': wages})

    def get_wages(self):
        """{staffId: kuruş/saat} — yalnızca yönetici okuyabilir (terminal önbelleğine inmez)."""
        self.session = self.client.ensure_fresh(self.session)
        return {doc_id: d.get('hourlyRate') for doc_id, d in self.client.list_docs('staffWages', self.session)}

    # ------------------------------------------------------------ müşteri ve sadakat (10. ekran)
    def save_customer(self, data, customer_id=None):
        return self._call('saveCustomer', {**data, **({'id': customer_id} if customer_id else {})})

    def delete_customer(self, customer_id):
        return self._call('deleteCustomer', {'id': customer_id})

    def export_customer(self, customer_id):
        return self._call('exportCustomer', {'id': customer_id})

    def save_loyalty_settings(self, data):
        return self._call('saveLoyaltySettings', data)

    def save_campaign(self, data, campaign_id=None):
        return self._call('saveCampaign', {**data, **({'id': campaign_id} if campaign_id else {})})

    def delete_campaign(self, campaign_id):
        return self._call('deleteCampaign', {'id': campaign_id})

    def save_notification(self, data):
        return self._call('saveNotification', data)

    def import_stock(self, ingredients, recipes, option_effects):
        return self._call('importStock', {'ingredients': ingredients, 'recipes': recipes,
                                          'optionEffects': option_effects})

    def save_modules(self, data):
        """settings/modules (yalnızca yönetici). Kaydedilen (doğrulanmış) ayarı döndürür."""
        return self._call('saveModules', data)

    def upload_product_image(self, data, content_type='image/jpeg'):
        """Fotoğrafı Storage'a yükler ve herkese açık indirme adresini döndürür."""
        self.session = self.client.ensure_fresh(self.session)
        cfg = self.client.config
        ext = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}[content_type]
        name = f'products/{uuid.uuid4().hex}/photo.{ext}'
        # Firebase SDK'larının kullandığı multipart biçimi: içerik tipi meta veride gider, böylece
        # Storage kuralları (yalnızca görsel) doğru değerlendirilir. Basit "media" yüklemede
        # contentType kurala ulaşmaz ve istek reddedilir.
        boundary = uuid.uuid4().hex
        meta = json.dumps({'name': name, 'contentType': content_type})
        body = (f'--{boundary}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n{meta}\r\n'
                f'--{boundary}\r\nContent-Type: {content_type}\r\n\r\n').encode() + data + \
            f'\r\n--{boundary}--'.encode()
        r = self.client._request(
            'POST', cfg.storage_base, params={'name': name}, data=body,
            headers={'Authorization': f'Firebase {self.session.id_token}',
                     'Content-Type': f'multipart/related; boundary={boundary}',
                     'X-Goog-Upload-Protocol': 'multipart'})
        if r.status_code not in (200, 201):
            raise ApiError('permission-denied' if r.status_code == 403 else 'internal',
                           f'Fotoğraf yüklenemedi (HTTP {r.status_code}).')
        return f"{cfg.storage_base}/{quote(name, safe='')}?alt=media"


__all__ = ['AdminApi', 'ApiError']
