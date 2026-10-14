"""
Terminal eşleme: kafedeki bilgisayarı bir kez Firebase'e bağlar.

Yönetici e-posta ve şifresiyle giriş yapılır, registerTerminal fonksiyonu bu
bilgisayar için ayrı bir cihaz hesabı açar. Yöneticinin oturumu saklanmaz; yalnızca
cihaz hesabının refresh token'ı saklanır.
"""
import database
from cloud import credentials
from cloud.credentials import TerminalCredentials
from cloud.sync import APP_VERSION, SyncEngine


def pair_terminal(client, email, password, terminal_name, progress=lambda text: None):
    progress('Yönetici hesabı doğrulanıyor…')
    manager = client.sign_in_with_password(email.strip(), password)

    progress('Terminal kaydediliyor…')
    reg = client.call('registerTerminal', {'name': terminal_name.strip(), 'appVersion': APP_VERSION}, manager)

    progress('Terminal hesabına geçiliyor…')
    device = client.sign_in_with_custom_token(reg['customToken'])
    creds = TerminalCredentials(
        terminal_id=reg['terminalId'],
        letter=reg['letter'],
        name=reg['name'],
        uid=device.uid,
        refresh_token=device.refresh_token,
        project_id=client.config.project_id,
    )

    progress('Personel ve yetkiler indiriliyor…')
    database.reset_cloud_cache()
    engine = SyncEngine(client, creds)
    engine.session = device
    engine.pull()

    credentials.save(creds)
    database.set_sync_state('terminal_letter', creds.letter)
    database.set_sync_state('terminal_name', creds.name)
    return creds, engine
