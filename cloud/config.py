"""
Firebase proje ayarları.

Ayarlar exe'nin (ya da main.py'nin) yanındaki nexpos_config.json dosyasından okunur:

    {
      "apiKey": "AIza...",
      "projectId": "kafe-xyz",
      "region": "europe-west1",
      "storageBucket": "kafe-xyz.firebasestorage.app"
    }

Emülatörle geliştirmek için NEXPOS_EMULATOR=1 ortam değişkeni yeterlidir; dosya gerekmez.
"""
import json
import os
import sys
from dataclasses import dataclass


def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CONFIG_PATH = os.path.join(app_dir(), 'nexpos_config.json')


@dataclass(frozen=True)
class CloudConfig:
    api_key: str
    project_id: str
    region: str = 'europe-west1'
    emulator_host: str = ''  # "127.0.0.1" ise emülatör kullanılır
    storage_bucket: str = ''

    @property
    def bucket(self):
        return self.storage_bucket or f'{self.project_id}.appspot.com'

    @property
    def storage_base(self):
        root = (f'http://{self.emulator_host}:9199' if self.emulator_host
                else 'https://firebasestorage.googleapis.com')
        return f'{root}/v0/b/{self.bucket}/o'

    @property
    def auth_base(self):
        if self.emulator_host:
            return f'http://{self.emulator_host}:9099/identitytoolkit.googleapis.com/v1'
        return 'https://identitytoolkit.googleapis.com/v1'

    @property
    def token_base(self):
        if self.emulator_host:
            return f'http://{self.emulator_host}:9099/securetoken.googleapis.com/v1'
        return 'https://securetoken.googleapis.com/v1'

    def function_url(self, name):
        if self.emulator_host:
            return f'http://{self.emulator_host}:5001/{self.project_id}/{self.region}/{name}'
        return f'https://{self.region}-{self.project_id}.cloudfunctions.net/{name}'

    @property
    def firestore_base(self):
        root = (f'http://{self.emulator_host}:8080' if self.emulator_host
                else 'https://firestore.googleapis.com')
        return f'{root}/v1/projects/{self.project_id}/databases/(default)/documents'


def load_config():
    """Ayar yoksa None döner; uygulama bu durumda kurulum uyarısı gösterir."""
    if os.environ.get('NEXPOS_EMULATOR') == '1':
        return CloudConfig(
            api_key='demo-key',
            project_id=os.environ.get('NEXPOS_PROJECT', 'demo-nexpos'),
            emulator_host=os.environ.get('NEXPOS_EMULATOR_HOST', '127.0.0.1'),
        )
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return CloudConfig(
        api_key=data['apiKey'],
        project_id=data['projectId'],
        region=data.get('region', 'europe-west1'),
        storage_bucket=data.get('storageBucket', ''),
    )
