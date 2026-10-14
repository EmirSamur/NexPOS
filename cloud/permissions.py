"""
Roller ve yetki matrisi.

Sunucudaki karşılığı firebase/functions/src/lib.js içindedir; tablolar değişirse
iki tarafı birlikte güncelleyin.
"""

ROLES = ['owner', 'manager', 'cashier', 'waiter', 'courier', 'barista', 'kitchen']

ROLE_LABELS = {
    'owner': 'Yönetici',
    'manager': 'Müdür',
    'cashier': 'Kasa',
    'waiter': 'Garson',
    'courier': 'Kurye',
    'barista': 'Barista',
    'kitchen': 'Mutfak',
}

# Yönetim paneline e-posta + şifre ile girebilen roller.
PANEL_ROLES = ('owner', 'manager')

# (anahtar, NexPOS yetki matrisindeki etiket)
PERMISSIONS = [
    ('openTable', 'Masa Açma/Kapatma'),
    ('voidItem', 'Sipariş İptal Edebilir'),
    ('comp', 'İkram Yapabilir'),
    ('refund', 'İade Yapabilir'),
    ('discount', 'İskonto Yapabilir'),
    ('cash', 'Kasa İşlemleri Yapabilir'),
    ('expense', 'Gider / Zayi Girebilir'),
    ('editMenu', 'Ürün / Fiyat / Masa Tanımlayabilir'),
    ('settings', 'Sistem Ayarlarına Erişebilir'),
    ('viewReports', 'Raporları Görüntüleyebilir'),
    ('manageUsers', 'Kullanıcı Tanımlayabilir'),
    ('markSoldOut', 'Tükendi İşaretleyebilir'),
]
PERMISSION_KEYS = [k for k, _ in PERMISSIONS]
PERMISSION_LABELS = dict(PERMISSIONS)


def _all(value):
    return {k: value for k in PERMISSION_KEYS}


DEFAULT_PERMISSIONS = {
    'owner': _all(True),
    'manager': {**_all(True), 'settings': False},
    'cashier': {**_all(False), 'openTable': True, 'discount': True, 'cash': True, 'expense': True,
                'markSoldOut': True},
    'waiter': {**_all(False), 'openTable': True},
    'courier': {**_all(False), 'openTable': True},
    'barista': {**_all(False), 'markSoldOut': True},
    'kitchen': {**_all(False), 'markSoldOut': True},
}


def normalize_permissions(roles):
    """Sunucudaki normalizePermissions ile aynı kurallar."""
    source = roles if isinstance(roles, dict) else {}
    result = {}
    for role in ROLES:
        given = source.get(role) if isinstance(source.get(role), dict) else {}
        result[role] = {
            k: given[k] if isinstance(given.get(k), bool) else DEFAULT_PERMISSIONS[role][k]
            for k in PERMISSION_KEYS
        }
    result['owner'] = _all(True)
    return result


def has_permission(matrix, role, permission, overrides=None):
    if role == 'owner':
        return True
    if isinstance(overrides, dict) and isinstance(overrides.get(permission), bool):
        return overrides[permission]
    roles = matrix or DEFAULT_PERMISSIONS
    return bool(roles.get(role, {}).get(permission, False))


def can_manage_role(actor_role, target_role):
    if actor_role == 'owner':
        return True
    if actor_role == 'manager':
        return target_role not in ('owner', 'manager')
    return False
