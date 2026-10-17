import 'package:flutter/material.dart';

import '../logic.dart';
import '../models.dart';
import '../state.dart';
import 'common.dart';

class ProfileTab extends StatefulWidget {
  final VoidCallback onLogin;
  const ProfileTab({super.key, required this.onLogin});

  @override
  State<ProfileTab> createState() => _ProfileTabState();
}

class _ProfileTabState extends State<ProfileTab> {
  Future<List<PastOrder>>? _orders;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (s.signedIn) _orders ??= s.repo.myOrders().catchError((_) => <PastOrder>[]);
  }

  Future<void> _edit() async {
    final s = AppScope.read(context);
    final c = s.customer!;
    final name = TextEditingController(text: c.name);
    String? birth = c.birthDate;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Bilgilerim'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(key: const Key('editName'), controller: name, maxLength: 60, decoration: const InputDecoration(labelText: 'Ad')),
            const SizedBox(height: 8),
            BirthdayPicker(value: birth, onChanged: (v) => setLocal(() => birth = v)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Kaydet')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await s.updateProfile(name: name.text.trim(), birthDate: birth, clearBirthDate: birth == null);
      if (mounted) showMessage(context, 'Kaydedildi.');
    } catch (e) {
      if (mounted) showMessage(context, e);
    }
  }

  Future<void> _consent(bool v) async {
    try {
      await AppScope.read(context).updateProfile(marketingConsent: v);
    } catch (e) {
      if (mounted) showMessage(context, e);
    }
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Hesabı sil'),
        content: const Text('Adın, telefonun ve doğum günün silinecek; damgaların ve kullanılmamış ödüllerin kaybolacak. '
            'Bu işlem geri alınamaz.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Vazgeç')),
          FilledButton(
            key: const Key('confirmDelete'),
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Hesabımı sil'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await AppScope.read(context).deleteAccount();
    } catch (e) {
      if (mounted) showMessage(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = s.customer;
    if (!s.signedIn || c == null) {
      return SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const BrandLogo(),
              const SizedBox(height: 16),
              const Text('Kartını ve siparişlerini görmek için giriş yap.'),
              const SizedBox(height: 16),
              FilledButton(onPressed: widget.onLogin, child: const Text('Giriş yap / Üye ol')),
              TextButton(onPressed: () => showKvkk(context), child: const Text('Kişisel verilerin korunması')),
            ]),
          ),
        ),
      );
    }
    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
        children: [
          Text(c.name, style: t.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
          Text('${c.phoneMasked} · ${s.loyalty.tier(c.tier).name} · ${c.visitCount} ziyaret',
              style: const TextStyle(color: Colors.black54)),
          const SectionTitle('Bilgilerim'),
          Card(
            child: Column(children: [
              ListTile(
                leading: const Icon(Icons.person_outline),
                title: const Text('Ad ve doğum günü'),
                subtitle: Text([c.name, if (c.birthDate != null) birthdayLabel(c.birthDate)].join(' · ')),
                trailing: const Icon(Icons.edit_outlined),
                onTap: _edit,
              ),
              SwitchListTile(
                key: const Key('profileConsent'),
                secondary: const Icon(Icons.notifications_outlined),
                title: const Text('Kampanya bildirimleri'),
                subtitle: const Text('Sipariş durumu bildirimleri her zaman gelir.'),
                value: c.marketingConsent,
                onChanged: _consent,
              ),
              SwitchListTile(
                key: const Key('pushToggle'),
                secondary: const Icon(Icons.phone_iphone),
                title: const Text('Telefon bildirimleri'),
                subtitle: Text(s.pushEnabled ? 'Açık: siparişin hazır olunca haber veririz.'
                    : 'Kapalı: açmak için izin verin (telefon ayarlarından da kapatılabilir).'),
                value: s.pushEnabled,
                onChanged: s.pushEnabled
                    ? null
                    : (_) async {
                        final on = await s.turnOnPush();
                        if (!on && context.mounted) showMessage(context, 'Bildirim izni verilmedi.');
                      },
              ),
            ]),
          ),
          SectionTitle('Ödüllerim', trailing: Text('${s.usableRewards.length}')),
          if (s.usableRewards.isEmpty)
            Card(
              child: ListTile(
                leading: const Text('🎁', style: TextStyle(fontSize: 24)),
                title: Text('${s.loyalty.stampsForReward - c.stamps} damga sonra ilk ödülün gelir.'),
              ),
            )
          else
            Card(
              child: Column(children: [
                for (final r in s.usableRewards)
                  ListTile(
                    leading: const Text('🎁', style: TextStyle(fontSize: 24)),
                    title: Text(r.label),
                    subtitle: Text('${dateLabel(r.expiresAt)} tarihine kadar · en fazla ${formatTl(s.loyalty.rewardMaxValue)}'),
                  ),
              ]),
            ),
          const SectionTitle('Geçmiş siparişler'),
          FutureBuilder<List<PastOrder>>(
            future: _orders,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
              }
              final orders = snap.data ?? const [];
              if (orders.isEmpty) return const Card(child: ListTile(title: Text('Henüz sipariş yok.')));
              return Card(
                child: Column(children: [
                  for (final o in orders)
                    ListTile(
                      title: Text(o.items.map((i) => '${i.qty}× ${i.name}').join(', ')),
                      subtitle: Text('${dateLabel(o.businessDay)} · ${formatTl(o.total)}${o.stamps > 0 ? ' · +${o.stamps} damga' : ''}'),
                    ),
                ]),
              );
            },
          ),
          const SectionTitle('Hesap'),
          Card(
            child: Column(children: [
              ListTile(leading: const Icon(Icons.privacy_tip_outlined), title: const Text('Kişisel verilerin korunması'), onTap: () => showKvkk(context)),
              ListTile(leading: const Icon(Icons.logout), title: const Text('Çıkış yap'), onTap: s.signOut),
              ListTile(
                key: const Key('deleteAccount'),
                leading: const Icon(Icons.delete_outline, color: Colors.red),
                title: const Text('Hesabımı sil', style: TextStyle(color: Colors.red)),
                onTap: _delete,
              ),
            ]),
          ),
        ],
      ),
    );
  }
}
