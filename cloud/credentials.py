"""
Terminal kimlik bilgisinin saklanması.

Terminal eşlendiğinde alınan refresh token bu bilgisayarın NexPOS'a ait kalıcı
anahtarıdır. Windows'ta Kimlik Bilgisi Yöneticisi'nde (keyring) saklanır; keyring
kullanılamayan ortamlarda (geliştirme, Linux sunucu) exe'nin yanındaki
terminal.json dosyasına yazılır.
"""
import json
import os
from dataclasses import asdict, dataclass

from cloud.config import app_dir

SERVICE = 'NexPOS'
KEY = 'terminal'
FILE_PATH = os.path.join(app_dir(), 'terminal.json')


@dataclass
class TerminalCredentials:
    terminal_id: str
    letter: str
    name: str
    uid: str
    refresh_token: str
    project_id: str


def _keyring():
    if os.environ.get('NEXPOS_NO_KEYRING') == '1':
        return None
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def load():
    kr = _keyring()
    raw = None
    if kr:
        try:
            raw = kr.get_password(SERVICE, KEY)
        except Exception:
            raw = None
    if raw is None and os.path.exists(FILE_PATH):
        with open(FILE_PATH, encoding='utf-8') as f:
            raw = f.read()
    if not raw:
        return None
    try:
        return TerminalCredentials(**json.loads(raw))
    except (TypeError, ValueError):
        return None


def save(creds):
    raw = json.dumps(asdict(creds))
    kr = _keyring()
    if kr:
        try:
            kr.set_password(SERVICE, KEY, raw)
            return
        except Exception:
            pass
    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(raw)
    try:
        os.chmod(FILE_PATH, 0o600)
    except OSError:
        pass


def clear():
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(SERVICE, KEY)
        except Exception:
            pass
    if os.path.exists(FILE_PATH):
        os.remove(FILE_PATH)
