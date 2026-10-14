import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NEXPOS_NO_KEYRING'] = '1'

import pytest  # noqa: E402

import database  # noqa: E402
from cloud import credentials  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Her test için boş bir yerel veritabanı."""
    monkeypatch.setattr(database, 'DB_PATH', str(tmp_path / 'nexpos.db'))
    monkeypatch.setattr(credentials, 'FILE_PATH', str(tmp_path / 'terminal.json'))
    database.init_database()
    return database
