// Saf hesaplar: para, telefon, iş günü, kampanya geçerliliği ve ürün kartındaki kampanya etiketi.
// Kampanya kuralları sunucudaki src/campaigns.js ve NexPOS'taki campaigns_logic.py ile aynıdır
// (uygulama yalnızca gösterir; indirimi kasa hesaplar).
import 'models.dart';

/// 9500 → '95,00 ₺', 125000 → '1.250,00 ₺'
String formatTl(int kurus) {
  final neg = kurus < 0;
  final abs = kurus.abs();
  final lira = (abs ~/ 100).toString();
  final buf = StringBuffer();
  for (var i = 0; i < lira.length; i++) {
    if (i > 0 && (lira.length - i) % 3 == 0) buf.write('.');
    buf.write(lira[i]);
  }
  return '${neg ? '-' : ''}$buf,${(abs % 100).toString().padLeft(2, '0')} ₺';
}

/// '0532 123 45 67', '5321234567', '+90 532…' → '+905321234567' (Firebase telefon girişi için); geçersizse null
String? toE164(String text) {
  var d = text.replaceAll(RegExp(r'\D'), '');
  if (d.length == 12 && d.startsWith('90')) d = d.substring(2);
  if (d.length == 11 && d.startsWith('0')) d = d.substring(1);
  return RegExp(r'^[2-5]\d{9}$').hasMatch(d) ? '+90$d' : null;
}

/// İş günü 05:00'te döner (kasayla aynı)
String businessDay(DateTime now) {
  final d = now.subtract(const Duration(hours: 5));
  return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}

int _minutes(String hm) => int.parse(hm.substring(0, 2)) * 60 + int.parse(hm.substring(3, 5));

/// Kampanya bu an (yerel saat) ve bu müşteri seviyesi için geçerli mi? (campaigns.js isLive ile aynı)
bool isLive(Campaign c, DateTime now, {String? tier}) {
  final day = '${now.year.toString().padLeft(4, '0')}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
  if (c.startDate != null && day.compareTo(c.startDate!) < 0) return false;
  if (c.endDate != null && day.compareTo(c.endDate!) > 0) return false;
  final weekday = now.weekday; // 1 = Pazartesi
  final m = now.hour * 60 + now.minute;
  if (c.from != null && c.to != null) {
    final f = _minutes(c.from!);
    final t = _minutes(c.to!);
    bool dayOk;
    if (f < t) {
      if (m < f || m >= t) return false;
      dayOk = c.days.contains(weekday);
    } else if (m >= f) {
      dayOk = c.days.contains(weekday);
    } else if (m < t) {
      dayOk = c.days.contains(((weekday + 5) % 7) + 1);
    } else {
      return false;
    }
    if (!dayOk) return false;
  } else if (!c.days.contains(weekday)) {
    return false;
  }
  switch (c.audience) {
    case 'all':
      return true;
    case 'members':
      return tier != null;
    case 'silver':
      return tier == 'silver' || tier == 'gold';
    default:
      return tier == 'gold';
  }
}

bool _applies(Campaign c, Product p) {
  if (c.categoryIds.isEmpty && c.productIds.isEmpty) return true;
  return c.productIds.contains(p.id) || c.categoryIds.contains(p.categoryId);
}

int _halfUp(int x, int pct) => (x * pct + 50) ~/ 100;

/// Ürün kartında gösterilecek kampanya: (etiket, indirimli fiyat ya da null). Şu an geçerli kampanyalardan
/// bu ürüne en çok indirim vereni; X. ürün ve menü için yalnızca etiket.
({String label, int? price})? productPromo(Product p, List<Campaign> campaigns, DateTime now, {String? tier}) {
  ({String label, int? price})? best;
  var bestOff = 0;
  for (final c in campaigns.where((c) => isLive(c, now, tier: tier))) {
    if ((c.type == 'percent' || c.type == 'amount') && _applies(c, p)) {
      final off = c.type == 'percent' ? _halfUp(p.price, c.value) : (c.value < p.price ? c.value : p.price);
      if (off > bestOff) {
        bestOff = off;
        best = (label: c.name, price: p.price - off);
      }
    } else if (best == null && c.type == 'nth' && _applies(c, p)) {
      best = (label: c.value >= 100 ? '${c.nthQty} al ${c.nthQty! - 1} öde' : '${c.nthQty}. ürün %${c.value}', price: null);
    } else if (best == null && c.type == 'bundle' && c.bundleProductIds.contains(p.id)) {
      best = (label: '${c.name}: ${formatTl(c.bundlePrice ?? 0)}', price: null);
    }
  }
  return best;
}

const _weekdays = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];

/// 'Hafta içi 14:00–17:00'
String scheduleText(Campaign c) {
  final days = [...c.days]..sort();
  String d;
  if (days.length == 7) {
    d = 'Her gün';
  } else if (days.join(',') == '1,2,3,4,5') {
    d = 'Hafta içi';
  } else if (days.join(',') == '6,7') {
    d = 'Hafta sonu';
  } else {
    d = days.map((x) => _weekdays[x - 1]).join(', ');
  }
  if (c.from != null) d += ' ${c.from}–${c.to}';
  return d;
}

/// Kampanyanın kısa anlatımı: '%20 indirim', '2. ürün %50', 'Menü 120,00 ₺', '2× damga'
String campaignSummary(Campaign c) {
  switch (c.type) {
    case 'percent':
      return '%${c.value} indirim';
    case 'amount':
      return '${formatTl(c.value)} indirim';
    case 'nth':
      return c.value >= 100 ? '${c.nthQty} al ${c.nthQty! - 1} öde' : '${c.nthQty}. ürün %${c.value}';
    case 'bundle':
      return 'Menü ${formatTl(c.bundlePrice ?? 0)}';
    default:
      return '${c.stampMultiplier}× damga';
  }
}

/// Doğum günü haftası (±3 gün; 29 Şubat artık olmayan yılda 28'i) — loyalty.js ile aynı
bool isBirthdayWeek(String? birthDate, DateTime today) {
  if (birthDate == null || !RegExp(r'^\d{2}-\d{2}$').hasMatch(birthDate)) return false;
  final day = DateTime.utc(today.year, today.month, today.day);
  for (final y in [today.year - 1, today.year, today.year + 1]) {
    var md = birthDate;
    final leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
    if (md == '02-29' && !leap) md = '02-28';
    final b = DateTime.utc(y, int.parse(md.substring(0, 2)), int.parse(md.substring(3)));
    if (day.difference(b).inDays.abs() <= 3) return true;
  }
  return false;
}

const months = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

/// '10-18' → '18 Ekim'
String birthdayLabel(String? md) {
  if (md == null || md.length != 5) return '';
  return '${int.parse(md.substring(3))} ${months[int.parse(md.substring(0, 2)) - 1]}';
}

/// '2026-12-15' → '15 Aralık'
String dateLabel(String ymd) {
  if (ymd.length != 10) return ymd;
  return '${int.parse(ymd.substring(8))} ${months[int.parse(ymd.substring(5, 7)) - 1]}';
}

String greeting(DateTime now) => now.hour >= 5 && now.hour < 12
    ? 'Günaydın'
    : now.hour < 18
        ? 'İyi günler'
        : 'İyi akşamlar';
