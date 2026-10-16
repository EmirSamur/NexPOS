"""
Senkron motoru: yerel önbellek ↔ Firebase.

Her turda (run_once):
  1. Terminal oturumunu tazeler (refresh token → kimlik token'ı).
  2. Kuyruktaki işlemleri (outbox) 50'lik paketler hâlinde syncOps'a gönderir.
  3. Buluttaki değişiklikleri çeker: personel, PIN özetleri, yetki matrisi,
     terminalin kendi kaydı (iptal edildi mi?).
  4. Canlılık sinyali (terminalHeartbeat) gönderir.

İnternet yoksa sessizce "çevrimdışı" durumu döner; ekranlar yerel veriyle çalışmaya
devam eder. Qt'ye bağımlı değildir; arayüz tarafı SyncWorker (cloud/qt_sync.py) ile
bunu arka planda çalıştırır.
"""
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import database
from cloud.firebase_client import ApiError, OfflineError, Session

APP_VERSION = '4.0.0'

# Delta senkronla çekilen koleksiyonlar ve yazıldıkları önbellek fonksiyonu.
# Sıra önemli: kategoriler ürünlerden önce iner (ürün yansıtılırken kategorisi aranır).
PULL_COLLECTIONS = {
    'staff': database.upsert_staff,
    'staffPins': database.upsert_pins,
    'categories': lambda docs: database.upsert_menu('categories', docs),
    'optionGroups': lambda docs: database.upsert_menu('optionGroups', docs),
    'products': lambda docs: database.upsert_menu('products', docs),
    'areas': lambda docs: database.upsert_floor('areas', docs),
    'tables': lambda docs: database.upsert_floor('tables', docs),
    'kitchenTickets': database.upsert_cloud_tickets,   # mutfak ekranındaki Başla / Hazır
    'ingredients': lambda docs: database.upsert_cache('ingredients', docs),   # stok (8. ekran)
}

# Yalnızca yakın geçmişi gereken koleksiyonlar (ilk senkronda tümü indirilmez)
RECENT_ONLY = {'kitchenTickets'}

# Tek doküman olarak çekilen ayarlar: settings/<ad> → settings_cache[<ad>]
PULL_SETTINGS = ('permissions', 'general', 'modules')

MENU_CHANGES = {'categories', 'optionGroups', 'products'}


@dataclass
class SyncStatus:
    online: bool = False
    pending: int = 0
    failed: int = 0
    revoked: bool = False
    last_sync: str = ''          # en son başarılı senkronun saati (SS:DD)
    error: str = ''
    changed: set = field(default_factory=set)  # bu turda değişen koleksiyonlar


class SyncEngine:
    def __init__(self, client, creds):
        self.client = client
        self.creds = creds
        self.session = None
        self._lock = threading.Lock()  # ekran ve işçi aynı anda senkron başlatmasın

    # --------------------------------------------------------------- oturum
    def _ensure_session(self):
        if self.session is None:
            self.session = Session(uid=self.creds.uid, id_token='', refresh_token=self.creds.refresh_token,
                                   expires_at=0)
        self.session = self.client.ensure_fresh(self.session)
        return self.session

    # ----------------------------------------------------------------- push
    def push(self):
        while True:
            ops = database.get_pending_ops(50)
            if not ops:
                return
            batch = [{
                'opId': o['op_id'],
                'op': o['op'],
                'payload': json.loads(o['payload']),
                'staffId': o['staff_id'],
                'createdAt': o['created_at'],
            } for o in ops]
            result = self.client.call('syncOps', {'ops': batch}, self._ensure_session())
            done, deferred = [], 0
            for r in result.get('results', []):
                status = r.get('status')
                if status in ('ok', 'duplicate'):
                    done.append(r['opId'])
                elif status == 'rejected':
                    database.fail_op(r['opId'], r.get('error') or 'Sunucu işlemi reddetti.')
                else:  # unsupported: sunucu güncellenince işlenecek
                    database.defer_op(r['opId'], 'Sunucu bu işlemi henüz desteklemiyor.')
                    deferred += 1
            database.complete_ops(done)
            # Bekletilen işlemler tekrar tekrar gönderilmesin; bir sonraki tura kalır.
            if deferred or len(ops) < 50:
                return

    # ----------------------------------------------------------------- pull
    def pull(self):
        changed = set()
        session = self._ensure_session()
        for collection, store in PULL_COLLECTIONS.items():
            key = f'pull:{collection}'
            since = database.get_sync_state(key)
            if not since and collection in RECENT_ONLY:
                # Geçmiş fişler gerekmez; ilk senkronda yalnızca son bir gün
                since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.000000Z')
            docs = self.client.query_updated_since(collection, since, session)
            if docs:
                store(docs)
                newest = max((d.get('updatedAt') or '' for _, d in docs), default='')
                if newest:
                    database.set_sync_state(key, newest)
                changed.add(collection)

        for name in PULL_SETTINGS:
            doc = self.client.get_doc(f'settings/{name}', session)
            if doc:
                _, data = doc
                if data.get('updatedAt') != (database.get_setting(name) or {}).get('updatedAt'):
                    database.set_setting(name, data)
                    changed.add(name)
        return changed

    def check_revoked(self):
        try:
            doc = self.client.get_doc(f'terminals/{self.creds.terminal_id}', self._ensure_session())
        except ApiError as e:
            return e.code in ('permission-denied', 'unauthenticated') or e.code.startswith('auth/')
        return doc is None or doc[1].get('revoked') is True

    # ------------------------------------------------------------------ tur
    def run_once(self):
        with self._lock:
            status = SyncStatus()
            try:
                self.push()
                status.changed = self.pull()
                pending, _ = database.outbox_counts()
                self.client.call('terminalHeartbeat', {'pending': pending, 'appVersion': APP_VERSION},
                                 self._ensure_session())
                status.online = True
                status.last_sync = datetime.now().strftime('%H:%M')
                database.set_sync_state('last_sync', status.last_sync)
            except OfflineError:
                status.online = False
            except ApiError as e:
                # İptal edilen terminalin token'ı yenilenemez ya da istekleri reddedilir.
                if e.code.startswith('auth/') or e.code in ('permission-denied', 'unauthenticated'):
                    status.revoked = self._safe_check_revoked(e)
                status.online = not status.revoked and not e.code.startswith('auth/')
                status.error = e.message
            status.pending, status.failed = database.outbox_counts()
            if not status.last_sync:
                status.last_sync = database.get_sync_state('last_sync', '')
            return status

    def _safe_check_revoked(self, error):
        if error.code in ('auth/user_disabled', 'auth/token_expired', 'auth/invalid_refresh_token',
                          'auth/user_not_found'):
            return True
        try:
            return self.check_revoked()
        except OfflineError:
            return False
