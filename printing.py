"""
NexPOS - Bilgi fişi yazdırma (6. ekran)

Adisyon (ön fiş), mutfak/bar fişi ve kasa raporları (X/Z) HTML olarak hazırlanır ve
Windows'a kurulu herhangi bir yazıcıdan basılır (80 mm / 58 mm termal ya da A4). Yazıcı
seçilmemişse ya da bulunamazsa PDF olarak kaydedilir.

Yazıcı seçimi bilgisayara özeldir (sync_state: printer_name, printer_paper); buluta gitmez.

⚠️ Bu fişlerin mali değeri yoktur. Mali fiş (ÖKC / e-Arşiv) bu modülün kapsamında değildir.
"""
import html
import os
import re
from datetime import datetime

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

import database
from cloud.orders import compute_totals, line_total
from money import format_tl

PAPERS = {'80': ('80 mm termal', 72), '58': ('58 mm termal', 48), 'A4': ('A4', 180)}  # yazdırılabilir genişlik (mm)
FOOTER = "Bilgi fişidir, mali değeri yoktur."


def pdf_dir():
    """PDF fişlerin kaydedildiği klasör (veritabanının yanında)."""
    return os.path.join(os.path.dirname(database.DB_PATH), 'fisler')


def printer_settings():
    paper = database.get_sync_state('printer_paper', '80') or '80'
    return {'name': database.get_sync_state('printer_name', '') or '', 'paper': paper if paper in PAPERS else '80'}


def save_printer_settings(name, paper):
    database.set_sync_state('printer_name', name or '')
    database.set_sync_state('printer_paper', paper if paper in PAPERS else '80')


def available_printers():
    from PySide6.QtPrintSupport import QPrinterInfo
    return list(QPrinterInfo.availablePrinterNames())


# =====================================================================
# Belgeler
# =====================================================================

_CSS = """
body { font-family: 'Consolas', 'DejaVu Sans Mono', monospace; font-size: 9pt; color: #000; }
h1 { font-size: 12pt; text-align: center; margin: 0; }
h2 { font-size: 10pt; text-align: center; margin: 2px 0 6px 0; }
.c { text-align: center; } .r { text-align: right; } .muted { color: #444; } .big { font-size: 12pt; font-weight: bold; }
table { width: 100%; border-collapse: collapse; }
td { padding: 1px 0; vertical-align: top; }
hr { border: 0; border-top: 1px dashed #000; }
"""


def _e(text):
    return html.escape(str(text or ''))


def _local_time(iso, fmt='%d.%m.%Y %H:%M'):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime(fmt)
    except (TypeError, ValueError):
        return ''


def _doc(body):
    return f"<html><head><style>{_CSS}</style></head><body>{body}</body></html>"


def _row(left, right, cls=''):
    return f"<tr class='{cls}'><td>{left}</td><td class='r' align='right'>&nbsp;{right}</td></tr>"


def bill_html(order):
    """Adisyon (ön fiş): müşteriye hesabı göstermek için."""
    cafe = database.general_settings()['cafeName']
    t = compute_totals(order)
    where = f"Masa {_e(order.get('tableName'))}" if order['type'] == 'dine_in' else 'Paket'
    rows = []
    for l in order['items']:
        opts = ''.join(f"<br><span class='muted'>&nbsp;&nbsp;+ {_e(o['name'])}</span>" for o in l.get('options') or [])
        if l['status'] == 'void':
            continue
        amount = 'İKRAM' if l['status'] == 'comp' else format_tl(line_total(l))
        rows.append(_row(f"{l['qty']} × {_e(l['name'])}{opts}", amount))
    totals = [_row('Ara toplam', format_tl(t['subtotal']))]
    if t['discountAmount']:
        d = order['discount']
        label = f"İskonto (%{d['value']})" if d['type'] == 'percent' else 'İskonto'
        totals.append(_row(label, format_tl(-t['discountAmount'])))
    totals.append(_row('<b>TOPLAM</b>', f"<b>{format_tl(t['total'])}</b>", 'big'))
    if t['paid']:
        totals.append(_row('Ödenen', format_tl(t['paid'])))
        totals.append(_row('Kalan', format_tl(t['remaining'])))
    body = (f"<h1>{_e(cafe)}</h1><h2>ADİSYON</h2>"
            f"<table width='100%' cellspacing='0'>{_row(where, 'No: ' + _e(order['no']))}"
            f"{_row(_local_time(order['openedAt']), '')}</table><hr>"
            f"<table width='100%' cellspacing='0'>{''.join(rows)}</table><hr><table width='100%' cellspacing='0'>{''.join(totals)}</table><hr>"
            f"<p class='c'>{FOOTER}</p>")
    return _doc(body)


def ticket_html(ticket):
    """Mutfak / bar fişi (KDS'nin kâğıt yedeği)."""
    station = 'BAR' if ticket['station'] == 'bar' else 'MUTFAK'
    where = f"MASA {_e(ticket.get('tableName'))}" if ticket.get('type') == 'dine_in' else 'PAKET'
    lines = ''.join(
        f"<tr><td class='big'>{l['qty']} × {_e(l['name'])}"
        + ''.join(f"<br>&nbsp;&nbsp;+ {_e(o)}" for o in l.get('options') or [])
        + (f"<br>&nbsp;&nbsp;<i>Not: {_e(l['note'])}</i>" if l.get('note') else '')
        + "</td></tr>" for l in ticket['lines'])
    body = (f"<h1>{station}</h1><table width='100%' cellspacing='0'>{_row(f'<b>{where}</b>', '<b>' + _e(ticket['orderNo']) + '</b>')}"
            f"{_row(_local_time(ticket['createdAt'], '%H:%M'), '')}</table><hr><table width='100%' cellspacing='0'>{lines}</table>")
    return _doc(body)


def report_html(report):
    """Kasa raporu: X (ara) ya da Z (kapanış)."""
    from pos import PAYMENT_LABELS
    r = report
    title = 'Z RAPORU' if r['kind'] == 'Z' else 'X RAPORU (ARA)'
    rows = [_row('<b>Satış (KDV dahil)</b>', f"<b>{format_tl(r['sales']['total'])}</b>")]
    for m in ('cash', 'card', 'meal'):
        if r['sales'][m]:
            rows.append(_row(f"&nbsp;&nbsp;{PAYMENT_LABELS[m]}", format_tl(r['sales'][m])))
    rows.append(_row(f"İade ({r['refunds']['count']})", format_tl(-r['refunds']['total'])))
    rows.append(_row(f"İskonto ({r['discount']['count']} adisyon)", format_tl(-r['discount']['amount'])))
    rows.append(_row(f"İkram ({r['comps']['count']} ürün)", format_tl(r['comps']['amount'])))
    rows.append(_row(f"İptal ({r['voids']['count']} ürün)", format_tl(r['voids']['amount'])))
    if r['tips']['total']:
        rows.append(_row('Bahşiş', format_tl(r['tips']['total'])))
    for v in r['vat']:
        rows.append(_row(f"KDV %{v['rate']} (matrah dahil {format_tl(v['gross'])})", format_tl(v['vat'])))
    o = r['orders']
    rows.append(_row('Adisyon sayısı / ortalama', f"{o['count']} / {format_tl(o['average'])}"))
    if o['cancelled']:
        rows.append(_row('İptal edilen adisyon', str(o['cancelled'])))
    c = r['cash']
    cash_rows = [_row('Açılış', format_tl(c['opening'])), _row('+ Nakit satış', format_tl(c['sales'])),
                 _row('− Nakit iade', format_tl(c['refunds'])), _row('+ Kasaya giriş', format_tl(c['in'])),
                 _row('− Kasadan çıkış', format_tl(c['out'])),
                 _row('<b>Beklenen nakit</b>', f"<b>{format_tl(c['expected'])}</b>")]
    if c.get('counted') is not None:
        cash_rows.append(_row('Sayılan nakit', format_tl(c['counted'])))
        diff = f"{format_tl(c['difference'], sign=True)}"
        cash_rows.append(_row('<b>Fark</b>', f"<b>{diff}</b>"))
        if c.get('differenceReason'):
            cash_rows.append(f"<tr><td colspan=2 class='muted'>Gerekçe: {_e(c['differenceReason'])}</td></tr>")
    moves = ''.join(_row(f"{'+' if m['type'] == 'in' else '−'} {_e(m['reason'])}", format_tl(m['amount']))
                    for m in r['movements'])
    staff = ''.join(_row(_e(s['name']), format_tl(s['total'])) for s in r['staff'])
    closed = (f"<br>Kapanış {_local_time(r['closedAt'], '%H:%M')} ({_e(r['closedBy'])})" if r.get('closedAt') else '')
    body = (f"<h1>{_e(r['cafeName'])}</h1><h2>{title}</h2>"
            f"<p class='c'>Kasa {_e(r['terminalLetter'])} · {_local_time(r['openedAt'], '%d.%m.%Y')}<br>"
            f"Açılış {_local_time(r['openedAt'], '%H:%M')} ({_e(r['openedBy'])}){closed}</p><hr>"
            f"<table width='100%' cellspacing='0'>{''.join(rows)}</table><hr><b>KASA</b><table width='100%' cellspacing='0'>{''.join(cash_rows)}</table>"
            + (f"<hr><b>KASA HAREKETLERİ</b><table width='100%' cellspacing='0'>{moves}</table>" if moves else '')
            + (f"<hr><b>PERSONEL</b><table width='100%' cellspacing='0'>{staff}</table>" if staff else '')
            + f"<hr><p class='c muted'>Yazdırma: {_local_time(r['printedAt'])}<br>{FOOTER}</p>")
    return _doc(body)


# =====================================================================
# Çıktı
# =====================================================================

def _layout(paper, height_mm=297):
    if paper == 'A4':
        return QPageSize(QPageSize.A4), QMarginsF(15, 15, 15, 15)
    width = 80 if paper == '80' else 58
    return QPageSize(QSizeF(width, height_mm), QPageSize.Millimeter, f"Fiş {width}mm"), QMarginsF(4, 4, 4, 4)


def _document(html_text, paper):
    doc = QTextDocument()
    doc.setHtml(html_text)
    width_mm = PAPERS[paper][1]
    doc.setTextWidth(width_mm / 25.4 * 96)  # 96 dpi mantıksal genişlik
    return doc


def _safe_name(name):
    return re.sub(r'[^\w.-]+', '_', name, flags=re.UNICODE).strip('_') or 'fis'


def print_html(html_text, name, settings=None):
    """
    Yazıcı ayarlıysa ve bulunuyorsa ona basar → ('printer', yazıcı adı).
    Değilse PDF kaydeder → ('pdf', dosya yolu).
    """
    settings = settings or printer_settings()
    paper = settings['paper']
    doc = _document(html_text, paper)
    if settings['name']:
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
            info = QPrinterInfo.printerInfo(settings['name'])
            if not info.isNull():
                printer = QPrinter(info, QPrinter.HighResolution)
                size, margins = _layout(paper, _height_mm(doc, paper))
                printer.setPageLayout(QPageLayout(size, QPageLayout.Portrait, margins, QPageLayout.Millimeter))
                printer.setDocName(name)
                doc.print_(printer)
                return 'printer', settings['name']
        except ImportError:
            pass
    return 'pdf', save_pdf(html_text, name, paper)


def _height_mm(doc, paper):
    """Termal ruloda sayfa boyu içerik kadar olsun (fiş tek parça çıksın)."""
    if paper == 'A4':
        return 297
    return max(80, int(doc.size().height() / 96 * 25.4) + 12)


def save_pdf(html_text, name, paper=None, path=None):
    paper = paper or printer_settings()['paper']
    doc = _document(html_text, paper)
    if not path:
        os.makedirs(pdf_dir(), exist_ok=True)
        path = os.path.join(pdf_dir(), f"{datetime.now():%Y%m%d-%H%M%S}-{_safe_name(name)}.pdf")
    writer = QPdfWriter(path)
    size, margins = _layout(paper, _height_mm(doc, paper))
    writer.setPageLayout(QPageLayout(size, QPageLayout.Portrait, margins, QPageLayout.Millimeter))
    writer.setResolution(300)
    writer.setTitle(name)
    doc.print_(writer)
    return path
