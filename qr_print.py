"""
NexPOS - Masa QR etiketleri

Her masanın QR'ı: <qrBaseUrl>/<masaId>?t=<qrToken>. A4 sayfaya 2 × 3 = 6 etiket basılır.
QR matrisi segno ile üretilir ve QPainter ile vektör olarak çizilir (ek görsel kütüphanesi gerekmez).
"""
from urllib.parse import quote

import segno
from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

COLS, ROWS = 2, 3


def default_base_url(project_id):
    """Firebase Hosting'in ücretsiz adresi; ayarlardan değiştirilebilir."""
    return f"https://{project_id}.web.app/masa"


def table_qr_url(base_url, table_id, token):
    return f"{base_url.rstrip('/')}/{quote(table_id, safe='')}?t={quote(token, safe='')}"


def draw_qr(painter, rect, data):
    """QR'ı rect içine kare olarak, sessiz bölgesiyle birlikte çizer."""
    qr = segno.make(data, error='m', micro=False)
    matrix = [list(row) for row in qr.matrix]
    n = len(matrix) + 8  # 4 modül sessiz bölge her yanda
    side = min(rect.width(), rect.height())
    module = side / n
    x0 = rect.x() + (rect.width() - side) / 2 + 4 * module
    y0 = rect.y() + (rect.height() - side) / 2 + 4 * module
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#000000'))
    for r, row in enumerate(matrix):
        for c, bit in enumerate(row):
            if bit:
                painter.drawRect(QRectF(x0 + c * module, y0 + r * module, module + 0.01, module + 0.01))
    painter.restore()


def _draw_label(painter, rect, cafe_name, table_name, url):
    painter.save()
    pen = QPen(QColor('#94A3B8'))
    pen.setStyle(Qt.DashLine)
    pen.setWidthF(rect.width() / 400)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(rect)  # kesme çizgisi

    pad = rect.width() * 0.08
    inner = rect.adjusted(pad, pad, -pad, -pad)
    h = inner.height()
    painter.setPen(QColor('#0F172A'))
    f = QFont('Segoe UI')
    f.setPixelSize(int(h * 0.075))
    f.setBold(True)
    painter.setFont(f)
    painter.drawText(QRectF(inner.x(), inner.y(), inner.width(), h * 0.11), Qt.AlignCenter, cafe_name.upper())

    draw_qr(painter, QRectF(inner.x(), inner.y() + h * 0.12, inner.width(), h * 0.56), url)

    f.setPixelSize(int(h * 0.12))
    painter.setFont(f)
    painter.drawText(QRectF(inner.x(), inner.y() + h * 0.69, inner.width(), h * 0.16), Qt.AlignCenter, table_name.upper())
    f.setPixelSize(int(h * 0.05))
    f.setBold(False)
    painter.setFont(f)
    painter.setPen(QColor('#475569'))
    painter.drawText(QRectF(inner.x(), inner.y() + h * 0.86, inner.width(), h * 0.12), Qt.AlignCenter,
                     "Menü ve sipariş için okutun")
    painter.restore()


def write_qr_pdf(path, cafe_name, base_url, tables):
    """tables: [{'id', 'name', 'qrToken'}] → A4 PDF, sayfa başına 6 etiket. Sayfa sayısını döndürür."""
    writer = QPdfWriter(path)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(10, 10, 10, 10),
                                     QPageLayout.Millimeter))
    writer.setResolution(300)
    writer.setTitle(f"{cafe_name} masa QR etiketleri")
    painter = QPainter(writer)
    page = writer.pageLayout().paintRectPixels(300)
    cell_w, cell_h = page.width() / COLS, page.height() / ROWS
    pages = 0
    for i, t in enumerate(tables):
        slot = i % (COLS * ROWS)
        if slot == 0:
            if i:
                writer.newPage()
            pages += 1
        col, row = slot % COLS, slot // COLS
        rect = QRectF(col * cell_w, row * cell_h, cell_w, cell_h).adjusted(8, 8, -8, -8)
        _draw_label(painter, rect, cafe_name, t['name'], table_qr_url(base_url, t['id'], t['qrToken']))
    painter.end()
    return pages
