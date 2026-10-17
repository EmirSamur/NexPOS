// Sipariş (11b): sepet, masaya / gel-al gönderme, sipariş durumu, masadan garson çağır / hesap iste.
import 'package:flutter/material.dart';

import '../data/repo.dart';
import '../logic.dart';
import '../models.dart';
import '../state.dart';
import 'common.dart';

/// Alt çubuktaki sepet özeti
class CartBar extends StatelessWidget {
  const CartBar({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    if (s.cart.isEmpty) return const SizedBox.shrink();
    return Material(
      color: s.brand.primary,
      child: InkWell(
        key: const Key('cartBar'),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const CartScreen())),
        child: SafeArea(
          top: false,
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
            child: Row(children: [
              const Icon(Icons.shopping_bag_outlined, color: Colors.white),
              const SizedBox(width: 10),
              Expanded(
                child: Text('Sepet · ${s.cartCount} ürün',
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
              ),
              Text(formatTl(cartTotal(s.cart)),
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
              const Icon(Icons.chevron_right, color: Colors.white),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Masadaki QR ile açıldıysa üstte: "Masa 4 · Velvet Kafe" + Garson çağır / Hesap iste
class TableBanner extends StatelessWidget {
  const TableBanner({super.key});

  Future<void> _call(BuildContext context, String kind) async {
    final s = AppScope.read(context);
    try {
      final fresh = await s.callTable(kind);
      if (!context.mounted) return;
      final what = kind == 'bill' ? 'Hesap isteğin' : 'Çağrın';
      showMessage(context, fresh ? '$what iletildi, garson geliyor.' : '$what zaten iletildi, garson geliyor.');
    } catch (e) {
      if (context.mounted) showMessage(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    if (s.tableError != null) {
      return MaterialBanner(
        content: Text(s.tableError!),
        leading: const Icon(Icons.qr_code_2),
        actions: [TextButton(onPressed: s.leaveTable, child: const Text('Tamam'))],
      );
    }
    final t = s.table;
    if (t == null) return const SizedBox.shrink();
    final name = s.ordering?.cafeName.isNotEmpty == true ? s.ordering!.cafeName : s.brand.appName;
    return Material(
      color: s.brand.accent.withValues(alpha: 0.22),
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 6),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              const Icon(Icons.table_restaurant_outlined),
              const SizedBox(width: 8),
              Expanded(
                child: Text('${t.label} · $name',
                    key: const Key('tableLabel'), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
              ),
            ]),
            if (s.ordering?.tableOrders == true)
              Row(children: [
                Expanded(
                  child: TextButton.icon(
                    onPressed: () => _call(context, 'waiter'),
                    icon: const Text('🙋'),
                    label: const Text('Garson çağır'),
                  ),
                ),
                Expanded(
                  child: TextButton.icon(
                    onPressed: () => _call(context, 'bill'),
                    icon: const Text('🧾'),
                    label: const Text('Hesap iste'),
                  ),
                ),
              ]),
          ]),
        ),
      ),
    );
  }
}

class CartScreen extends StatefulWidget {
  const CartScreen({super.key});

  @override
  State<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends State<CartScreen> {
  String? _kind; // table | pickup
  PickupChoice _pickup = const PickupChoice.asap();
  String _pickupKey = 'asap';
  final _note = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _pickTime(BuildContext context, int prep) async {
    final now = TimeOfDay.fromDateTime(DateTime.now().add(Duration(minutes: prep + 5)));
    final t = await showTimePicker(context: context, initialTime: now, helpText: 'Ne zaman geleceksin?');
    if (t == null) return;
    final n = DateTime.now();
    var at = DateTime(n.year, n.month, n.day, t.hour, t.minute);
    if (at.isBefore(n)) at = at.add(const Duration(days: 1));
    setState(() {
      _pickup = PickupChoice.at(at);
      _pickupKey = 'at';
    });
  }

  Future<void> _send(BuildContext context, String kind) async {
    final s = AppScope.read(context);
    if (!s.signedIn) {
      // Sepet korunur; girişten sonra kaldığı yerden devam eder
      showMessage(context, 'Sipariş için telefon numaranla giriş yap; sepetin saklanıyor.');
      Navigator.of(context).popUntil((r) => r.isFirst);
      s.requestLogin?.call();
      return;
    }
    setState(() => _busy = true);
    try {
      final id = await s.submitOrder(kind: kind, pickup: kind == 'pickup' ? _pickup : null, note: _note.text.trim());
      if (!context.mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => OrderStatusScreen(orderId: id)));
    } on AppError catch (e) {
      if (context.mounted) showMessage(context, e);
      await s.refreshOrdering();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final info = s.ordering;
    final t = Theme.of(context).textTheme;
    final kinds = [if (s.canOrderAtTable) 'table', if (s.canPickup) 'pickup'];
    final kind = kinds.contains(_kind) ? _kind! : (kinds.isNotEmpty ? kinds.first : null);
    final prep = info?.prepMinutes ?? 10;
    final online = info?.online ?? false;
    return Scaffold(
      appBar: AppBar(title: const Text('Sepet')),
      body: s.cart.isEmpty
          ? const Center(child: Text('Sepetin boş.'))
          : ListView(padding: const EdgeInsets.all(16), children: [
              for (final i in s.cart)
                Card(
                  margin: const EdgeInsets.only(bottom: 10),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
                    child: Row(children: [
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(i.product.name, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                          if (i.optionsText.isNotEmpty) Text(i.optionsText, style: const TextStyle(color: Colors.black54)),
                          if (i.note.isNotEmpty) Text('📝 ${i.note}', style: const TextStyle(color: Colors.black54)),
                          Text(formatTl(i.total), style: TextStyle(color: s.brand.primary, fontWeight: FontWeight.bold)),
                        ]),
                      ),
                      IconButton(
                        tooltip: i.qty == 1 ? 'Çıkar' : 'Azalt',
                        icon: Icon(i.qty == 1 ? Icons.delete_outline : Icons.remove_circle_outline),
                        onPressed: () => s.setQty(i.key, i.qty - 1),
                      ),
                      Text('${i.qty}', style: t.titleMedium),
                      IconButton(
                        tooltip: 'Artır',
                        icon: const Icon(Icons.add_circle_outline),
                        onPressed: i.qty < 20 ? () => s.setQty(i.key, i.qty + 1) : null,
                      ),
                    ]),
                  ),
                ),
              Row(children: [
                Text('Toplam', style: t.titleLarge),
                const Spacer(),
                Text(formatTl(cartTotal(s.cart)), style: t.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
              ]),
              const Text('Kampanya ve ödüllerin kasada uygulanır; ödeme kasada ya da masada.',
                  style: TextStyle(color: Colors.black54)),
              if (kinds.length > 1) ...[
                const SizedBox(height: 16),
                SegmentedButton<String>(
                  segments: [
                    ButtonSegment(value: 'table', label: Text(s.table!.label), icon: const Icon(Icons.table_restaurant_outlined)),
                    const ButtonSegment(value: 'pickup', label: Text('Gel-al'), icon: Icon(Icons.shopping_bag_outlined)),
                  ],
                  selected: {kind!},
                  onSelectionChanged: (v) => setState(() => _kind = v.first),
                ),
              ],
              if (kind == 'pickup') ...[
                const SectionTitle('Ne zaman geleceksin?'),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  ChoiceChip(
                    label: Text('Hemen (~$prep dk)'),
                    selected: _pickupKey == 'asap',
                    onSelected: (_) => setState(() {
                      _pickup = const PickupChoice.asap();
                      _pickupKey = 'asap';
                    }),
                  ),
                  for (final m in [15, 30])
                    if (m > prep)
                      ChoiceChip(
                        label: Text('$m dk sonra'),
                        selected: _pickupKey == '$m',
                        onSelected: (_) => setState(() {
                          _pickup = PickupChoice.inMinutes(m);
                          _pickupKey = '$m';
                        }),
                      ),
                  ChoiceChip(
                    label: Text(_pickupKey == 'at' && _pickup.at != null ? 'Saat: ${hm(_pickup.at!)}' : 'Saat seç'),
                    selected: _pickupKey == 'at',
                    onSelected: (_) => _pickTime(context, prep),
                  ),
                ]),
              ],
              const SizedBox(height: 12),
              TextField(
                controller: _note,
                maxLength: 200,
                decoration: InputDecoration(
                  labelText: 'Siparişe not (isteğe bağlı)',
                  hintText: kind == 'table' ? 'Örn. pencere kenarındayız' : 'Örn. kapıdan alacağım',
                  border: const OutlineInputBorder(),
                ),
              ),
              if (info?.pickupBlocked == true && kind != 'pickup')
                const Text('Gel-al siparişi hesabına kapalı; kafeyle görüşebilirsin.', style: TextStyle(color: Colors.black54)),
              const SizedBox(height: 8),
              if (kind == null || !online)
                Card(
                  color: const Color(0xFFFFF1D6),
                  child: ListTile(
                    leading: const Icon(Icons.wifi_off),
                    title: Text(kind == null ? 'Şu an uygulamadan sipariş alınmıyor.' : 'Şu an çevrimiçi sipariş alınmıyor.'),
                    subtitle: const Text('Kasaya ya da garsona sipariş verebilirsin.'),
                  ),
                )
              else
                FilledButton(
                  key: const Key('sendOrder'),
                  onPressed: _busy ? null : () => _send(context, kind),
                  child: Text(_busy
                      ? 'Gönderiliyor…'
                      : kind == 'table'
                          ? 'Siparişi gönder · ${s.table!.label}'
                          : 'Gel-al siparişini gönder'),
                ),
            ]),
    );
  }
}

const _steps = ['pending', 'accepted', 'preparing', 'ready'];

/// Siparişin canlı durumu: Gönderildi → Onaylandı → Hazırlanıyor → Hazır
class OrderStatusScreen extends StatelessWidget {
  final String orderId;
  const OrderStatusScreen({super.key, required this.orderId});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final o = s.appOrders.where((x) => x.id == orderId).firstOrNull;
    final t = Theme.of(context).textTheme;
    if (o == null) {
      return Scaffold(appBar: AppBar(title: const Text('Siparişim')), body: const Center(child: CircularProgressIndicator()));
    }
    final status = o.statusAt(s.clock());
    final failed = const ['rejected', 'expired', 'cancelled', 'no_show'].contains(status);
    final step = status == 'completed' ? _steps.length : _steps.indexOf(status);
    return Scaffold(
      appBar: AppBar(title: Text(o.place)),
      body: ListView(padding: const EdgeInsets.all(20), children: [
        Text(
          switch (status) {
            'pending' => 'Siparişin alındı ☕',
            'accepted' || 'preparing' => 'Hazırlanıyor ☕',
            'ready' => o.kind == 'pickup' ? 'Hazır 🔔 Gelip alabilirsin' : 'Hazır 🔔 Birazdan masanda',
            'completed' => 'Afiyet olsun!',
            _ => appOrderStatusLabels[status] ?? status,
          },
          key: const Key('orderHeadline'),
          style: t.headlineSmall?.copyWith(fontWeight: FontWeight.bold),
        ),
        if (o.orderNo != null) Text('Sipariş no: ${o.orderNo}', style: t.titleMedium),
        if (o.kind == 'pickup' && o.pickupAt != null) Text('Geliş saati: ${hm(o.pickupAt!)}'),
        if (status == 'pending') const Text('Kafe onayladığında hazırlanmaya başlar.', style: TextStyle(color: Colors.black54)),
        if (failed) ...[
          const SizedBox(height: 8),
          Text(
            status == 'expired'
                ? 'Kafe şu an yoğun; siparişin onaylanamadı. Kasaya ya da garsona sipariş verebilirsin.'
                : (o.reason ?? ''),
            style: const TextStyle(color: Colors.redAccent),
          ),
        ],
        const SizedBox(height: 20),
        if (!failed)
          for (var i = 0; i < _steps.length; i++)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(i <= step ? Icons.check_circle : Icons.radio_button_unchecked,
                  color: i <= step ? s.brand.primary : Colors.black26),
              title: Text(const ['Gönderildi', 'Onaylandı', 'Hazırlanıyor', 'Hazır'][i],
                  style: TextStyle(fontWeight: i == step ? FontWeight.bold : FontWeight.normal)),
            ),
        const SectionTitle('Sipariş'),
        for (final i in o.items)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            title: Text('${i.qty}× ${i.name}'),
            subtitle: i.options.isEmpty ? null : Text(i.options.join(', ')),
            trailing: Text(formatTl(i.lineTotal)),
          ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Toplam', style: TextStyle(fontWeight: FontWeight.bold)),
          trailing: Text(formatTl(o.total), style: const TextStyle(fontWeight: FontWeight.bold)),
        ),
        if (status == 'pending')
          OutlinedButton(
            onPressed: () async {
              try {
                await s.repo.cancelAppOrder(o.id);
              } catch (e) {
                if (context.mounted) showMessage(context, e);
              }
            },
            child: const Text('Siparişi geri çek'),
          ),
      ]),
    );
  }
}

/// Ana sayfada açık siparişler
class ActiveOrders extends StatelessWidget {
  const ActiveOrders({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final list = s.activeOrders;
    if (list.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const SectionTitle('Siparişlerim'),
      for (final o in list)
        Card(
          margin: const EdgeInsets.only(bottom: 10),
          color: o.status == 'ready' ? const Color(0xFFE6F4EA) : null,
          child: ListTile(
            leading: Text(o.kind == 'pickup' ? '🛍' : '🍽', style: const TextStyle(fontSize: 24)),
            title: Text('${o.place} · ${appOrderStatusLabels[o.statusAt(s.clock())]}'),
            subtitle: Text(o.itemsText, maxLines: 2, overflow: TextOverflow.ellipsis),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => OrderStatusScreen(orderId: o.id))),
          ),
        ),
    ]);
  }
}
