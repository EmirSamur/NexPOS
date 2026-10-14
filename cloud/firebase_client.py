"""
Firebase REST istemcisi.

Masaüstü uygulamasında Admin SDK kullanılamaz (servis hesabı anahtarı bilgisayarda
durursa tüm veritabanı açığa çıkar). Bu yüzden NexPOS, Firebase'e normal bir istemci
gibi bağlanır: Auth REST ile kimlik token'ı alır, Firestore'u REST ile okur ve
Cloud Functions'ı HTTPS ile çağırır. Güvenlik kuralları her istekte uygulanır.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

TIMEOUT = 10  # saniye


class OfflineError(Exception):
    """Sunucuya ulaşılamadı (internet yok, zaman aşımı)."""


class ApiError(Exception):
    """Sunucu isteği reddetti. code: 'permission-denied', 'invalid-argument' gibi."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Session:
    uid: str
    id_token: str
    refresh_token: str
    expires_at: float
    email: str = ''

    @property
    def expired(self):
        # Süresi dolmadan bir dakika önce yenilenir.
        return time.time() > self.expires_at - 60


# Firebase Auth hata kodlarının Türkçe karşılıkları.
AUTH_ERRORS = {
    'EMAIL_NOT_FOUND': 'E-posta veya şifre hatalı.',
    'INVALID_PASSWORD': 'E-posta veya şifre hatalı.',
    'INVALID_LOGIN_CREDENTIALS': 'E-posta veya şifre hatalı.',
    'USER_DISABLED': 'Bu hesap devre dışı bırakılmış.',
    'TOO_MANY_ATTEMPTS_TRY_LATER': 'Çok fazla deneme yapıldı. Biraz sonra tekrar deneyin.',
    'TOKEN_EXPIRED': 'Oturumun süresi doldu.',
    'INVALID_REFRESH_TOKEN': 'Oturum geçersiz.',
    'USER_NOT_FOUND': 'Hesap bulunamadı.',
}

# Callable fonksiyonların döndürdüğü durum kodları → firebase-functions kodları.
CALLABLE_STATUS = {
    'INVALID_ARGUMENT': 'invalid-argument',
    'PERMISSION_DENIED': 'permission-denied',
    'UNAUTHENTICATED': 'unauthenticated',
    'NOT_FOUND': 'not-found',
    'ALREADY_EXISTS': 'already-exists',
    'FAILED_PRECONDITION': 'failed-precondition',
    'RESOURCE_EXHAUSTED': 'resource-exhausted',
    'ABORTED': 'aborted',
    'OUT_OF_RANGE': 'out-of-range',
    'UNIMPLEMENTED': 'unimplemented',
    'DEADLINE_EXCEEDED': 'deadline-exceeded',
    'CANCELLED': 'cancelled',
    'DATA_LOSS': 'data-loss',
    'INTERNAL': 'internal',
    'UNAVAILABLE': 'unavailable',
}


class FirebaseClient:
    def __init__(self, config, http=None):
        self.config = config
        self.http = http or requests.Session()

    # ------------------------------------------------------------------ HTTP
    def _request(self, method, url, **kwargs):
        try:
            return self.http.request(method, url, timeout=TIMEOUT, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            raise OfflineError(str(e)) from e

    # ------------------------------------------------------------------ Auth
    def _session_from_auth(self, data):
        return Session(
            uid=data.get('localId') or data.get('user_id'),
            id_token=data.get('idToken') or data.get('id_token'),
            refresh_token=data.get('refreshToken') or data.get('refresh_token'),
            expires_at=time.time() + int(data.get('expiresIn') or data.get('expires_in') or 3600),
            email=data.get('email', ''),
        )

    def _auth_post(self, url, payload):
        r = self._request('POST', url, params={'key': self.config.api_key}, json=payload)
        data = r.json() if r.content else {}
        if r.status_code != 200:
            raw = (data.get('error') or {}).get('message', 'UNKNOWN')
            key = raw.split(' ')[0].split(':')[0]
            raise ApiError('auth/' + key.lower(), AUTH_ERRORS.get(key, f'Giriş başarısız ({raw}).'))
        return data

    def sign_in_with_password(self, email, password):
        data = self._auth_post(
            f'{self.config.auth_base}/accounts:signInWithPassword',
            {'email': email, 'password': password, 'returnSecureToken': True},
        )
        return self._session_from_auth(data)

    def sign_in_with_custom_token(self, token):
        data = self._auth_post(
            f'{self.config.auth_base}/accounts:signInWithCustomToken',
            {'token': token, 'returnSecureToken': True},
        )
        session = self._session_from_auth(data)
        if not session.uid:
            session.uid = self.lookup_uid(session.id_token)
        return session

    def lookup_uid(self, id_token):
        data = self._auth_post(f'{self.config.auth_base}/accounts:lookup', {'idToken': id_token})
        return data['users'][0]['localId']

    def refresh(self, refresh_token):
        r = self._request(
            'POST', f'{self.config.token_base}/token',
            params={'key': self.config.api_key},
            data={'grant_type': 'refresh_token', 'refresh_token': refresh_token},
        )
        data = r.json() if r.content else {}
        if r.status_code != 200:
            raw = (data.get('error') or {}).get('message', 'UNKNOWN')
            key = raw.split(' ')[0].split(':')[0]
            raise ApiError('auth/' + key.lower(), AUTH_ERRORS.get(key, f'Oturum yenilenemedi ({raw}).'))
        return self._session_from_auth(data)

    def ensure_fresh(self, session):
        """Süresi dolmak üzereyse yenilenmiş yeni bir oturum döndürür."""
        if session.expired:
            fresh = self.refresh(session.refresh_token)
            fresh.email = session.email
            return fresh
        return session

    # ------------------------------------------------------------- Functions
    def call(self, name, data, session):
        headers = {'Authorization': f'Bearer {session.id_token}'} if session else {}
        r = self._request('POST', self.config.function_url(name), json={'data': data}, headers=headers)
        try:
            body = r.json()
        except ValueError:
            raise ApiError('internal', f'Sunucu yanıtı okunamadı (HTTP {r.status_code}).')
        if 'error' in body:
            err = body['error']
            code = CALLABLE_STATUS.get(err.get('status'), 'internal')
            raise ApiError(code, err.get('message') or 'Sunucu isteği reddetti.')
        return body.get('result')

    # ------------------------------------------------------------- Firestore
    def _fs_headers(self, session):
        return {'Authorization': f'Bearer {session.id_token}'}

    def _fs_error(self, r):
        try:
            err = r.json()
            err = err[0]['error'] if isinstance(err, list) else err['error']
            status = err.get('status', '')
        except (ValueError, KeyError, IndexError, TypeError):
            status, err = '', {}
        code = CALLABLE_STATUS.get(status, 'internal')
        return ApiError(code, err.get('message') or f'Firestore hatası (HTTP {r.status_code}).')

    def get_doc(self, path, session):
        r = self._request('GET', f'{self.config.firestore_base}/{path}', headers=self._fs_headers(session))
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise self._fs_error(r)
        return decode_document(r.json())

    def list_docs(self, collection, session):
        """Koleksiyondaki tüm dokümanları sayfa sayfa getirir: [(id, dict)]"""
        docs, page_token = [], None
        while True:
            params = {'pageSize': 300}
            if page_token:
                params['pageToken'] = page_token
            r = self._request('GET', f'{self.config.firestore_base}/{collection}',
                              headers=self._fs_headers(session), params=params)
            if r.status_code != 200:
                raise self._fs_error(r)
            body = r.json()
            docs.extend(decode_document(d) for d in body.get('documents', []))
            page_token = body.get('nextPageToken')
            if not page_token:
                return docs

    def query_updated_since(self, collection, since_iso, session):
        """updatedAt > since olan dokümanlar (delta senkron). since None ise hepsi."""
        if not since_iso:
            return self.list_docs(collection, session)
        query = {
            'structuredQuery': {
                'from': [{'collectionId': collection}],
                'where': {'fieldFilter': {
                    'field': {'fieldPath': 'updatedAt'},
                    'op': 'GREATER_THAN',
                    'value': {'timestampValue': since_iso},
                }},
                'orderBy': [{'field': {'fieldPath': 'updatedAt'}, 'direction': 'ASCENDING'}],
            }
        }
        r = self._request('POST', f'{self.config.firestore_base}:runQuery',
                          headers=self._fs_headers(session), json=query)
        if r.status_code != 200:
            raise self._fs_error(r)
        return [decode_document(row['document']) for row in r.json() if 'document' in row]


# ---------------------------------------------------------------------------
# Firestore REST değer dönüşümü
# ---------------------------------------------------------------------------

def decode_value(v):
    if 'nullValue' in v:
        return None
    if 'booleanValue' in v:
        return v['booleanValue']
    if 'integerValue' in v:
        return int(v['integerValue'])
    if 'doubleValue' in v:
        return float(v['doubleValue'])
    if 'stringValue' in v:
        return v['stringValue']
    if 'timestampValue' in v:
        return v['timestampValue']  # ISO metin olarak tutulur (SQLite'a yazılabilir)
    if 'mapValue' in v:
        return {k: decode_value(x) for k, x in v['mapValue'].get('fields', {}).items()}
    if 'arrayValue' in v:
        return [decode_value(x) for x in v['arrayValue'].get('values', [])]
    if 'referenceValue' in v:
        return v['referenceValue']
    if 'bytesValue' in v:
        return v['bytesValue']
    if 'geoPointValue' in v:
        return v['geoPointValue']
    return None


def decode_document(doc):
    doc_id = doc['name'].rsplit('/', 1)[-1]
    fields = {k: decode_value(v) for k, v in doc.get('fields', {}).items()}
    return doc_id, fields


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
