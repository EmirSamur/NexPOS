import 'package:flutter/material.dart';

import '../logic.dart';
import '../models.dart';
import '../state.dart';
import 'common.dart';
import 'quiz.dart';

const _favorites = '__fav__';

class MenuTab extends StatefulWidget {
  const MenuTab({super.key});

  @override
  State<MenuTab> createState() => _MenuTabState();
}

class _MenuTabState extends State<MenuTab> {
  String? _category;
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final menu = s.menu;
    if (!s.menuLoaded) return const Center(child: CircularProgressIndicator());
    final cats = menu.categories.where((c) => menu.productsOf(c.id).isNotEmpty).toList();
    final selected = _category ?? (cats.isNotEmpty ? cats.first.id : null);
    List<Product> products;
    if (_query.isNotEmpty) {
      final q = _query.toLowerCase();
      products = menu.products.where((p) => p.name.toLowerCase().contains(q) || p.description.toLowerCase().contains(q)).toList();
    } else if (selected == _favorites) {
      products = menu.products.where((p) => s.favorites.contains(p.id)).toList();
    } else {
      products = selected == null ? const [] : menu.productsOf(selected);
    }
    return SafeArea(
      child: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: TextField(
            key: const Key('search'),
            decoration: InputDecoration(
              hintText: 'Menüde ara',
              prefixIcon: const Icon(Icons.search),
              filled: true,
              fillColor: Colors.white,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
            ),
            onChanged: (v) => setState(() => _query = v.trim()),
          ),
        ),
        if (_query.isEmpty)
          SizedBox(
            height: 52,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: ActionChip(
                    label: const Text('✨ Bana öner'),
                    onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const QuizScreen())),
                  ),
                ),
                if (s.favorites.isNotEmpty)
                  _chip(context, '♥ Favoriler', selected == _favorites, () => setState(() => _category = _favorites)),
                for (final c in cats) _chip(context, c.name, selected == c.id, () => setState(() => _category = c.id)),
              ],
            ),
          ),
        Expanded(
          child: products.isEmpty
              ? Center(child: Text(_query.isNotEmpty ? 'Sonuç yok.' : 'Bu kategoride ürün yok.'))
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                  itemCount: products.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (_, i) => ProductTile(product: products[i]),
                ),
        ),
      ]),
    );
  }

  Widget _chip(BuildContext context, String label, bool on, VoidCallback onTap) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: ChoiceChip(label: Text(label), selected: on, onSelected: (_) => onTap()),
      );
}

class ProductTile extends StatelessWidget {
  final Product product;
  const ProductTile({super.key, required this.product});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final p = product;
    final promo = productPromo(p, s.campaigns, s.clock(), tier: s.customer?.tier);
    final fav = s.favorites.contains(p.id);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProductScreen(product: p))),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            Opacity(opacity: p.soldOut ? 0.4 : 1, child: ProductImage(p, size: 72)),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(p.name, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                if (p.description.isNotEmpty)
                  Text(p.description, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.black54)),
                const SizedBox(height: 6),
                Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  if (promo?.price != null) ...[
                    Text(formatTl(promo!.price!), style: TextStyle(fontWeight: FontWeight.bold, color: s.brand.primary)),
                    Text(formatTl(p.price),
                        style: const TextStyle(decoration: TextDecoration.lineThrough, color: Colors.black45, fontSize: 12)),
                  ] else
                    Text(formatTl(p.price), style: TextStyle(fontWeight: FontWeight.bold, color: s.brand.primary)),
                  if (p.soldOut) const Text('Tükendi', style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.bold)),
                ]),
                if (promo != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text('🏷 ${promo.label}', style: TextStyle(color: s.brand.primary, fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
              ]),
            ),
            IconButton(
              tooltip: fav ? 'Favorilerden çıkar' : 'Favorilere ekle',
              icon: Icon(fav ? Icons.favorite : Icons.favorite_border, color: fav ? Colors.redAccent : null),
              onPressed: () => s.toggleFavorite(p.id),
            ),
          ]),
        ),
      ),
    );
  }
}

/// Ürün detayı: fotoğraf, açıklama, seçenekler, alerjen, kalori, kafein; sipariş açıksa sepete ekleme.
class ProductScreen extends StatefulWidget {
  final Product product;
  const ProductScreen({super.key, required this.product});

  @override
  State<ProductScreen> createState() => _ProductScreenState();
}

class _ProductScreenState extends State<ProductScreen> {
  final _picked = <String, List<String>>{}; // grup → seçenek kimlikleri
  int _qty = 1;
  final _note = TextEditingController();
  bool _defaultsSet = false;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  void _toggle(OptionGroup g, OptionItem o) {
    setState(() {
      final list = _picked.putIfAbsent(g.id, () => []);
      if (list.contains(o.id)) {
        if (g.multi || !g.required) list.remove(o.id);
      } else if (g.multi) {
        if (list.length < g.max) list.add(o.id);
      } else {
        list
          ..clear()
          ..add(o.id);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final p = s.menu.product(widget.product.id) ?? widget.product; // tükendi gibi değişiklikler canlı
    final t = Theme.of(context).textTheme;
    final promo = productPromo(p, s.campaigns, s.clock(), tier: s.customer?.tier);
    final groups = p.optionGroupIds.map((id) => s.menu.optionGroups[id]).whereType<OptionGroup>().toList();
    final fav = s.favorites.contains(p.id);
    final ordering = s.canOrder;
    // Zorunlu tek seçimli gruplarda ilk uygun seçenek hazır seçili gelir
    if (ordering && !_defaultsSet) {
      _defaultsSet = true;
      for (final g in groups) {
        final first = g.options.where((o) => o.available).firstOrNull;
        if (!g.multi && g.min > 0 && first != null) _picked[g.id] = [first.id];
      }
    }
    final picks = [
      for (final g in groups)
        for (final id in _picked[g.id] ?? const <String>[])
          if (g.options.where((o) => o.id == id).firstOrNull case final o?) PickedOption(g.id, o),
    ];
    final problem = groups.map((g) => optionProblem(g, (_picked[g.id] ?? const []).length)).whereType<String>().firstOrNull;
    final item = CartItem(p, options: picks, qty: _qty, note: _note.text.trim());
    final soldOutOption = picks.any((x) => !x.option.available);
    return Scaffold(
      appBar: AppBar(
        title: Text(p.name),
        actions: [
          IconButton(
            icon: Icon(fav ? Icons.favorite : Icons.favorite_border, color: fav ? Colors.redAccent : null),
            onPressed: () => s.toggleFavorite(p.id),
          ),
        ],
      ),
      bottomNavigationBar: !ordering
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: Row(children: [
                  IconButton.outlined(
                    tooltip: 'Azalt',
                    onPressed: _qty > 1 ? () => setState(() => _qty--) : null,
                    icon: const Icon(Icons.remove),
                  ),
                  Padding(padding: const EdgeInsets.symmetric(horizontal: 12), child: Text('$_qty', style: t.titleLarge)),
                  IconButton.outlined(
                    tooltip: 'Artır',
                    onPressed: _qty < 20 ? () => setState(() => _qty++) : null,
                    icon: const Icon(Icons.add),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton(
                      key: const Key('addToCart'),
                      onPressed: p.soldOut || problem != null || soldOutOption
                          ? null
                          : () {
                              s.addItem(item); // alttaki sepet çubuğu görünür
                              Navigator.of(context).pop();
                            },
                      child: Text(p.soldOut ? 'Tükendi' : (problem ?? 'Sepete ekle · ${formatTl(item.total)}')),
                    ),
                  ),
                ]),
              ),
            ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Center(child: ProductImage(p, size: 200)),
          const SizedBox(height: 16),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: Text(p.name, style: t.headlineSmall?.copyWith(fontWeight: FontWeight.bold))),
            const SizedBox(width: 12),
            Text(formatTl(promo?.price ?? p.price), style: t.titleLarge?.copyWith(color: s.brand.primary, fontWeight: FontWeight.bold)),
          ]),
          if (promo != null) Text('🏷 ${promo.label}', style: TextStyle(color: s.brand.primary)),
          if (p.soldOut)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text('Şu an tükendi', style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.bold)),
            ),
          if (p.description.isNotEmpty) ...[const SizedBox(height: 10), Text(p.description, style: t.bodyLarge)],
          if (s.menu.earnsStamp(p)) ...[
            const SizedBox(height: 10),
            const Text('☕ Bu ürün sadakat kartına damga kazandırır.'),
          ],
          for (final g in groups) ...[
            SectionTitle(g.name,
                trailing: Text(g.min > 0 ? 'zorunlu' : (g.multi ? 'en fazla ${g.max}' : 'isteğe bağlı'),
                    style: const TextStyle(color: Colors.black54))),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final o in g.options)
                ordering
                    ? FilterChip(
                        label: Text(o.priceDelta == 0 ? o.name : '${o.name} (+${formatTl(o.priceDelta)})'),
                        selected: (_picked[g.id] ?? const []).contains(o.id),
                        showCheckmark: g.multi,
                        onSelected: o.available ? (_) => _toggle(g, o) : null,
                        avatar: o.available ? null : const Icon(Icons.block, size: 16),
                      )
                    : Chip(
                        label: Text(o.priceDelta == 0 ? o.name : '${o.name} (+${formatTl(o.priceDelta)})'),
                        backgroundColor: o.available ? null : Colors.black12,
                        avatar: o.available ? null : const Icon(Icons.block, size: 16),
                      ),
            ]),
          ],
          if (ordering) ...[
            const SectionTitle('Not'),
            TextField(
              controller: _note,
              maxLength: 120,
              decoration: const InputDecoration(hintText: 'Örn. az şekerli', border: OutlineInputBorder()),
              onChanged: (_) => setState(() {}),
            ),
          ],
          if (p.allergens.isNotEmpty || p.calories != null || p.caffeineMg != null) ...[
            const SectionTitle('Besin bilgisi'),
            if (p.allergens.isNotEmpty)
              Wrap(spacing: 8, children: [
                for (final a in p.allergens) Chip(avatar: const Icon(Icons.warning_amber, size: 16), label: Text(allergenLabels[a] ?? a)),
              ]),
            if (p.calories != null) ListTile(dense: true, contentPadding: EdgeInsets.zero, leading: const Icon(Icons.local_fire_department_outlined), title: Text('${p.calories} kcal')),
            if (p.caffeineMg != null) ListTile(dense: true, contentPadding: EdgeInsets.zero, leading: const Icon(Icons.bolt), title: Text('${p.caffeineMg} mg kafein')),
          ],
        ],
      ),
    );
  }
}
