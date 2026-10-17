import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../logic.dart';
import '../models.dart';
import '../state.dart';
import 'common.dart';
import 'menu.dart';

class HomeTab extends StatefulWidget {
  final VoidCallback onLogin;
  final VoidCallback onMenu;
  const HomeTab({super.key, required this.onLogin, required this.onMenu});

  @override
  State<HomeTab> createState() => _HomeTabState();
}

class _HomeTabState extends State<HomeTab> {
  Future<List<PastOrder>>? _orders;
  String? _loadedFor;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (s.signedIn && _loadedFor != s.customerId) {
      _loadedFor = s.customerId;
      _orders = s.repo.myOrders().catchError((_) => <PastOrder>[]);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final t = Theme.of(context).textTheme;
    final now = s.clock();
    final live = s.campaigns.where((c) => isLive(c, now, tier: s.customer?.tier)).toList();
    final later = s.campaigns.where((c) => !live.contains(c)).toList();
    final c = s.customer;
    return SafeArea(
      child: RefreshIndicator(
        onRefresh: () async => setState(() => _orders = s.repo.myOrders()),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
          children: [
            Row(children: [
              Expanded(
                child: Text(c != null ? '${greeting(now)} ${c.name.split(' ').first} 👋' : greeting(now),
                    style: t.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
              ),
              const BrandLogo(size: 40),
            ]),
            const SizedBox(height: 16),
            if (c != null) ...[
              if (isBirthdayWeek(c.birthDate, now))
                Card(
                  color: const Color(0xFFFFF1D6),
                  child: ListTile(
                    leading: const Text('🎂', style: TextStyle(fontSize: 28)),
                    title: const Text('Doğum günün kutlu olsun!'),
                    subtitle: Text(s.loyalty.birthdayReward ? 'Bu hafta gelirsen bir içecek bizden.' : 'Seni bekliyoruz.'),
                  ),
                ),
              if (isBirthdayWeek(c.birthDate, now)) const SizedBox(height: 12),
              LoyaltyCard(onShowQr: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const QrScreen()))),
            ] else
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Her kahvede damga kazan', style: t.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    Text('${s.loyalty.stampsForReward} damgada bir içecek bizden. Telefon numaranla giriş yap, kartın hazır.'),
                    const SizedBox(height: 12),
                    FilledButton(onPressed: widget.onLogin, child: const Text('Giriş yap / Üye ol')),
                  ]),
                ),
              ),
            if (c != null)
              FutureBuilder<List<PastOrder>>(
                future: _orders,
                builder: (context, snap) {
                  final last = (snap.data ?? const <PastOrder>[]).firstOrNull;
                  if (last == null) return const SizedBox.shrink();
                  return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    const SectionTitle('Her zamankinden'),
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.replay),
                        title: Text(last.items.map((i) => '${i.qty}× ${i.name}').join(', ')),
                        subtitle: Text('${dateLabel(last.businessDay)} · ${formatTl(last.total)}'),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: widget.onMenu,
                      ),
                    ),
                  ]);
                },
              ),
            if (live.isNotEmpty) ...[
              const SectionTitle('Şu an geçerli'),
              for (final k in live) _CampaignCard(k, active: true),
            ],
            if (later.isNotEmpty) ...[
              const SectionTitle('Kampanyalar'),
              for (final k in later) _CampaignCard(k, active: false),
            ],
            const SectionTitle('Kafe'),
            _InfoCard(info: s.info),
          ],
        ),
      ),
    );
  }
}

class _CampaignCard extends StatelessWidget {
  final Campaign c;
  final bool active;
  const _CampaignCard(this.c, {required this.active});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        color: active ? s.brand.accent.withValues(alpha: 0.18) : null,
        child: ListTile(
          leading: Text(c.type == 'double_stamps' ? '☕☕' : '🏷', style: const TextStyle(fontSize: 24)),
          title: Text(c.name, style: const TextStyle(fontWeight: FontWeight.bold)),
          subtitle: Text([
            campaignSummary(c),
            scheduleText(c),
            if (c.audience == 'members') 'üyelere',
            if (c.audience == 'silver') 'Gümüş ve Altın üyelere',
            if (c.audience == 'gold') 'Altın üyelere',
            if (c.description.isNotEmpty) c.description,
          ].join(' · ')),
          trailing: active ? const Chip(label: Text('Şimdi')) : null,
        ),
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  final AppInfo info;
  const _InfoCard({required this.info});

  @override
  Widget build(BuildContext context) {
    final rows = [
      if (info.hours.isNotEmpty) (Icons.schedule, info.hours),
      if (info.address.isNotEmpty) (Icons.place_outlined, info.address),
      if (info.phone.isNotEmpty) (Icons.phone_outlined, info.phone),
      if (info.instagram.isNotEmpty) (Icons.alternate_email, info.instagram),
    ];
    if (rows.isEmpty) return const SizedBox.shrink();
    return Card(
      child: Column(children: [for (final (icon, text) in rows) ListTile(dense: true, leading: Icon(icon), title: Text(text))]),
    );
  }
}

/// Kasada okutulan QR: 60 sn geçerli, kendiliğinden yenilenir
class QrScreen extends StatefulWidget {
  const QrScreen({super.key});

  @override
  State<QrScreen> createState() => _QrScreenState();
}

class _QrScreenState extends State<QrScreen> {
  LoyaltyQr? _qr;
  String? _error;
  Timer? _timer;
  int _left = 0;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  Future<void> _load() async {
    try {
      final qr = await AppScope.read(context).repo.loyaltyQr();
      if (!mounted) return;
      setState(() {
        _qr = qr;
        _error = null;
        _left = 60; // sunucu 60 sn geçerli verir; telefonun saati yanlış olsa da geri sayım doğru kalır
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  void _tick() {
    if (_qr == null) return;
    final left = _left - 1;
    if (left <= 5) {
      _qr = null;
      _load();
    } else {
      setState(() => _left = left);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = s.customer;
    return Scaffold(
      appBar: AppBar(title: const Text('QR\'ım')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(c?.name ?? '', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 4),
            Text('Kasada okutun: damga ve ödül kartına işlenir.', textAlign: TextAlign.center),
            const SizedBox(height: 24),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
              child: _qr == null
                  ? SizedBox(
                      width: 240,
                      height: 240,
                      child: Center(child: _error != null ? Text(_error!, textAlign: TextAlign.center) : const CircularProgressIndicator()))
                  : QrImageView(key: const Key('qr'), data: _qr!.qr, size: 240, backgroundColor: Colors.white),
            ),
            const SizedBox(height: 16),
            if (_qr != null) Text('$_left sn sonra yenilenir', style: const TextStyle(color: Colors.black54)),
            if (_error != null) TextButton(onPressed: _load, child: const Text('Tekrar dene')),
            const SizedBox(height: 8),
            if (s.usableRewards.isNotEmpty)
              Text('🎁 ${s.usableRewards.length} ödülün var — kasiyere "ödülümü kullan" demen yeterli.', textAlign: TextAlign.center),
          ]),
        ),
      ),
    );
  }
}

/// Ana sayfadan menüye ürün açmak için (her zamankinden)
void openProduct(BuildContext context, Product p) =>
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProductScreen(product: p)));
