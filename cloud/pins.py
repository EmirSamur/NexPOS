"""
PIN özetleme. Sunucudaki hashPin (Node crypto.scryptSync) ile aynı parametreleri
kullanır; PIN özetleri sunucuda üretilir, terminal yalnızca doğrular.
"""
import hashlib
import hmac
import re


def is_valid_pin(pin):
    if not isinstance(pin, str) or not re.fullmatch(r'\d{6}', pin):
        return False
    if len(set(pin)) == 1:
        return False
    if pin in '0123456789' or pin in '9876543210':
        return False
    return True


def verify_pin(pin, record):
    """record: staffPins dokümanı {algo, salt, hash, n, r, p}"""
    if not record or record.get('algo') != 'scrypt' or not isinstance(pin, str):
        return False
    try:
        computed = hashlib.scrypt(
            pin.encode(),
            salt=bytes.fromhex(record['salt']),
            n=int(record.get('n', 16384)),
            r=int(record.get('r', 8)),
            p=int(record.get('p', 1)),
            dklen=32,
        )
        return hmac.compare_digest(computed.hex(), record['hash'])
    except (KeyError, ValueError):
        return False
