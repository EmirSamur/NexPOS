import 'package:flutter/material.dart';

import '../logic.dart';
import '../models.dart';
import '../state.dart';

void showMessage(BuildContext context, Object message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text('$message'), behavior: SnackBarBehavior.floating));
}

/// Kafe logosu: brand.json'da logo yoksa adın baş harfi
class BrandLogo extends StatelessWidget {
  final double size;
  const BrandLogo({super.key, this.size = 72});

  @override
  Widget build(BuildContext context) {
    final b = AppScope.of(context).brand;
    if (b.logoAsset != null) return Image.asset(b.logoAsset!, width: size, height: size);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: b.primary, borderRadius: BorderRadius.circular(size / 3.2)),
      alignment: Alignment.center,
      child: Text('☕', style: TextStyle(fontSize: size * 0.45)),
    );
  }
}

/// Ürün fotoğrafı ya da sade yer tutucu
class ProductImage extends StatelessWidget {
  final Product product;
  final double size;
  const ProductImage(this.product, {super.key, this.size = 64});

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.primaryContainer;
    final fallback = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(12)),
      alignment: Alignment.center,
      child: Text(product.name.isNotEmpty ? product.name.characters.first : '☕',
          style: TextStyle(fontSize: size * 0.4, fontWeight: FontWeight.bold, color: Theme.of(context).colorScheme.onPrimaryContainer)),
    );
    if (product.imageUrl == null) return fallback;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: Image.network(product.imageUrl!, width: size, height: size, fit: BoxFit.cover,
          errorBuilder: (_, _, _) => fallback),
    );
  }
}

/// ●●●●●○○○○○ damga satırı (erişilebilir metinle)
class StampRow extends StatelessWidget {
  final int stamps;
  final int total;
  final Color color;
  const StampRow({super.key, required this.stamps, required this.total, required this.color});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '$total damgadan $stamps',
      child: Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          for (var i = 0; i < total; i++)
            Container(
              width: 24,
              height: 24,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: i < stamps ? color : Colors.transparent,
                border: Border.all(color: color, width: 2),
              ),
              alignment: Alignment.center,
              child: i < stamps ? const Text('☕', style: TextStyle(fontSize: 11)) : null,
            ),
        ],
      ),
    );
  }
}

/// Ana sayfadaki sadakat kartı
class LoyaltyCard extends StatelessWidget {
  final VoidCallback? onShowQr;
  const LoyaltyCard({super.key, this.onShowQr});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = s.customer;
    if (c == null) return const SizedBox.shrink();
    final total = s.loyalty.stampsForReward;
    final left = total - c.stamps;
    final tier = s.loyalty.tier(c.tier);
    final next = s.loyalty.nextTier(c.lifetimeStamps);
    final rewards = s.usableRewards;
    final onPrimary = Colors.white;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(22),
        gradient: LinearGradient(colors: [s.brand.primary, Color.lerp(s.brand.primary, Colors.black, 0.25)!]),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Text('Sadakat kartı', style: TextStyle(color: onPrimary.withValues(alpha: 0.8), fontWeight: FontWeight.w600)),
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: s.brand.accent, borderRadius: BorderRadius.circular(20)),
              child: Text('⭐ ${tier.name}', style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.black87)),
            ),
          ]),
          const SizedBox(height: 14),
          StampRow(stamps: c.stamps, total: total, color: s.brand.accent),
          const SizedBox(height: 12),
          Text('${c.stamps} / $total damga', style: TextStyle(color: onPrimary, fontSize: 22, fontWeight: FontWeight.bold)),
          Text(left == 1 ? 'Bir kahve sonra bir içecek bizden!' : '$left kahve sonra bir içecek bizden',
              style: TextStyle(color: onPrimary.withValues(alpha: 0.85))),
          if (rewards.isNotEmpty) ...[
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(12)),
              child: Text(
                '🎁 ${rewards.length} ödülün var · en yakını ${dateLabel(rewards.first.expiresAt)} tarihine kadar\n'
                'Kasada QR\'ını okut, ödülünü kullan.',
                style: TextStyle(color: onPrimary, fontWeight: FontWeight.w600),
              ),
            ),
          ],
          if (tier.perks.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('${tier.name} ayrıcalığı: ${tier.perks}', style: TextStyle(color: onPrimary.withValues(alpha: 0.85))),
          ],
          if (next != null) ...[
            const SizedBox(height: 4),
            Text('${next.name} seviyesine ${next.minStamps - c.lifetimeStamps} damga kaldı',
                style: TextStyle(color: onPrimary.withValues(alpha: 0.7), fontSize: 12)),
          ],
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: Colors.white, foregroundColor: s.brand.primary),
              onPressed: onShowQr,
              icon: const Icon(Icons.qr_code_2),
              label: const Text('QR\'ımı göster'),
            ),
          ),
        ],
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  final String text;
  final Widget? trailing;
  const SectionTitle(this.text, {super.key, this.trailing});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 20, 4, 8),
        child: Row(children: [
          Expanded(child: Text(text, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold))),
          ?trailing,
        ]),
      );
}

/// Gün + ay seçimi (yıl tutulmaz). value: 'MM-DD' ya da null
class BirthdayPicker extends StatelessWidget {
  final String? value;
  final ValueChanged<String?> onChanged;
  const BirthdayPicker({super.key, this.value, required this.onChanged});

  static const _daysIn = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

  @override
  Widget build(BuildContext context) {
    final month = value == null ? null : int.parse(value!.substring(0, 2));
    final day = value == null ? null : int.parse(value!.substring(3));
    String? compose(int? d, int? m) {
      if (d == null || m == null) return null;
      final dd = d > _daysIn[m - 1] ? _daysIn[m - 1] : d;
      return '${m.toString().padLeft(2, '0')}-${dd.toString().padLeft(2, '0')}';
    }

    return Row(children: [
      Expanded(
        child: DropdownButtonFormField<int>(
          key: const Key('birthDay'),
          initialValue: day,
          decoration: const InputDecoration(labelText: 'Gün', border: OutlineInputBorder()),
          items: [for (var d = 1; d <= 31; d++) DropdownMenuItem(value: d, child: Text('$d'))],
          onChanged: (d) => onChanged(compose(d, month ?? 1)),
        ),
      ),
      const SizedBox(width: 12),
      Expanded(
        flex: 2,
        child: DropdownButtonFormField<int>(
          key: const Key('birthMonth'),
          initialValue: month,
          decoration: const InputDecoration(labelText: 'Ay', border: OutlineInputBorder()),
          items: [for (var m = 1; m <= 12; m++) DropdownMenuItem(value: m, child: Text(months[m - 1]))],
          onChanged: (m) => onChanged(compose(day ?? 1, m)),
        ),
      ),
    ]);
  }
}

/// KVKK aydınlatma metni (panelden düzenlenir)
void showKvkk(BuildContext context) {
  final s = AppScope.read(context);
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.8,
      builder: (_, controller) => ListView(
        controller: controller,
        padding: const EdgeInsets.all(24),
        children: [
          Text('Kişisel verilerin korunması', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          Text(s.info.kvkkText.isNotEmpty
              ? s.info.kvkkText
              : '${s.info.cafeName.isNotEmpty ? s.info.cafeName : s.brand.appName}, sadakat programı ve sipariş için '
                  'adını, telefon numaranı ve (verirsen) doğum gününü işler. Verilerin yalnızca bu amaçla kullanılır, '
                  'üçüncü kişilerle paylaşılmaz. Profil sayfasından hesabını istediğin zaman silebilirsin.'),
        ],
      ),
    ),
  );
}
