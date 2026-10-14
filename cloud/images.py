"""
Ürün fotoğrafları: yüklemeden önce küçültme ve ekranda gösterim için yerel önbellek.
"""
import hashlib
import os

import requests
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPixmap

from cloud.config import app_dir
from cloud.qt_sync import run_async

MAX_SIDE = 800
CACHE_DIR = os.path.join(app_dir(), 'image_cache')


def prepare_upload(path):
    """Görseli en uzun kenarı 800 px olacak şekilde küçültüp JPEG baytlarına çevirir."""
    img = QImage(path)
    if img.isNull():
        raise ValueError('Görsel açılamadı. JPEG, PNG ya da WEBP seçin.')
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if img.hasAlphaChannel():
        img = img.convertToFormat(QImage.Format_RGB32)
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.WriteOnly)
    img.save(dev, 'JPEG', 82)
    return bytes(buf)


def _cache_path(url):
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + '.jpg')


def cached_pixmap(url):
    path = _cache_path(url) if url else None
    if path and os.path.exists(path):
        pm = QPixmap(path)
        return None if pm.isNull() else pm
    return None


def fetch_pixmap(url, on_ready):
    """Önbellekte yoksa arka planda indirir; hazır olunca on_ready(QPixmap) çağrılır."""
    pm = cached_pixmap(url)
    if pm or not url:
        if pm:
            on_ready(pm)
        return

    def work():
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(url), 'wb') as f:
            f.write(r.content)
        return True

    run_async(work, lambda _: on_ready(cached_pixmap(url)) if cached_pixmap(url) else None, lambda _m: None)
