import 'package:flutter/material.dart';

import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import '../home_widget_sync.dart';
import 'cook.dart';
import 'pantry_pass.dart';
import 'actions.dart';
import 'product_detail.dart';

class PantryScreen extends StatefulWidget {
  const PantryScreen({super.key});
  @override
  State<PantryScreen> createState() => _PantryScreenState();
}

class _PantryScreenState extends State<PantryScreen> {
  Future<List<StockProduct>>? _future;
  int _seen = -1;
  String _q = '';

  void _load() => _future = Kasita.read(context).api.stock(Kasita.read(context).hid).then((stock) {
    syncPantryWidget(stock);
    return stock;
  });

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final rev = Kasita.of(context).revision;
    if (rev != _seen) {
      _seen = rev;
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pantry'),
        actions: [
          IconButton(
            tooltip: 'What can I cook?',
            icon: const Icon(Icons.restaurant_menu),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const CookScreen())),
          ),
          TextButton.icon(
            onPressed: () async {
              await Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PantryPassScreen()));
              if (mounted) setState(_load);
            },
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('Pantry pass'),
          ),
        ],
      ),
      body: FutureBuilder<List<StockProduct>>(
        future: _future,
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text('Could not load: ${snap.error}'));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final all = snap.data!
              .where((s) => _q.isEmpty || s.product.name.toLowerCase().contains(_q.toLowerCase()))
              .toList();
          final soon = all
              .where((s) => s.product.nextBestBefore != null && daysUntil(s.product.nextBestBefore!) <= 5)
              .toList();
          final rest = all.where((s) => !soon.contains(s)).toList();
          return RefreshIndicator(
            onRefresh: () async => setState(_load),
            child: ListView(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                  child: SearchBar(
                    hintText: 'Search pantry',
                    leading: const Icon(Icons.search),
                    onChanged: (v) => setState(() => _q = v),
                  ),
                ),
                if (snap.data!.isEmpty)
                  const EmptyState(
                    icon: Icons.kitchen_outlined,
                    title: 'Nothing in the pantry yet',
                    message: 'Scan a barcode or open Products to add what you have at home.',
                  ),
                if (soon.isNotEmpty) _header(context, 'Use soon', Icons.schedule),
                for (final s in soon) _tile(context, s),
                if (rest.isNotEmpty && soon.isNotEmpty) _header(context, 'Everything else', Icons.kitchen_outlined),
                for (final s in rest) _tile(context, s),
                const SizedBox(height: 80),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _header(BuildContext context, String text, IconData icon) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
    child: Row(
      children: [
        Icon(icon, size: 18, color: Theme.of(context).colorScheme.primary),
        const SizedBox(width: 8),
        Text(text, style: Theme.of(context).textTheme.titleSmall),
      ],
    ),
  );

  Widget _tile(BuildContext context, StockProduct s) {
    final p = s.product;
    final opened = s.entries.any((e) => e.openedAt != null);
    final frozen = s.entries.isNotEmpty && s.entries.every((e) => e.frozenAt != null);
    final frozenSince = frozen ? s.entries.map((e) => e.frozenAt!).reduce((a, b) => a.isBefore(b) ? a : b) : null;
    final runsOut = p.runsOutInDays;
    return ListTile(
      leading: ProductThumb(p.imageUrl),
      title: Text(p.name),
      subtitle: Row(
        children: [
          Text('${fmtQty(s.total)} ${p.unit}'),
          if (opened) ...[const SizedBox(width: 8), const Text('· opened')],
          if (runsOut != null && runsOut <= 7) ...[
            const SizedBox(width: 8),
            Text('· runs out in ~${runsOut.ceil()}d', style: TextStyle(color: Colors.orange.shade800)),
          ],
          if (p.minStock > 0 && s.total < p.minStock) ...[
            const SizedBox(width: 8),
            Text('· low', style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
        ],
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (frozen) FrozenChip(frozenSince!) else ExpiryChip(p.nextBestBefore),
          IconButton(
            tooltip: 'Used one',
            icon: const Icon(Icons.remove_circle_outline),
            onPressed: () => consumeOne(context, p),
          ),
        ],
      ),
      onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProductDetailScreen(productId: p.id))),
    );
  }
}
