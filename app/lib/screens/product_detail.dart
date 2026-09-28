import 'package:flutter/material.dart';

import '../api.dart';

import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'actions.dart';
import 'product_picker.dart';
import 'product_form.dart';

class ProductDetailScreen extends StatefulWidget {
  final String productId;
  const ProductDetailScreen({super.key, required this.productId});
  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  Product? _p;
  List<StockEntry> _entries = [];
  List<PricePoint> _prices = [];
  int _seen = -1;

  Future<void> _addBarcode() async {
    final s = Kasita.read(context);
    final code = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => ScanOneBarcodeScreen(title: 'Barcode for ${_p?.name ?? 'this product'}')),
    );
    if (code == null || code.isEmpty || !mounted) return;
    try {
      await s.api.addBarcode(s.hid, widget.productId, code);
      s.changed();
      if (mounted) toast(context, 'Barcode $code added');
      _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    final p = await s.api.product(s.hid, widget.productId);
    final stock = await s.api.stock(s.hid);
    final prices = await s.api.prices(s.hid, widget.productId);
    if (!mounted) return;
    setState(() {
      _p = p;
      _entries = stock.where((x) => x.product.id == p.id).expand((x) => x.entries).toList();
      _prices = prices;
    });
  }

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
    final s = Kasita.of(context);
    final p = _p;
    final t = Theme.of(context);
    if (p == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final cheapest = _prices.isEmpty ? null : _prices.reduce((a, b) => a.unitPrice <= b.unitPrice ? a : b);
    return Scaffold(
      appBar: AppBar(
        title: Text(p.name),
        actions: [
          IconButton(
            tooltip: 'Edit',
            icon: const Icon(Icons.edit_outlined),
            onPressed: () =>
                Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProductFormScreen(product: p))),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            children: [
              ProductThumb(p.imageUrl, size: 72),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (p.brand != null) Text(p.brand!, style: TextStyle(color: t.colorScheme.onSurfaceVariant)),
                    Text('${fmtQty(p.inStock)} ${p.unit} at home', style: t.textTheme.titleLarge),
                    if (p.minStock > 0) Text('Keep at least ${fmtQty(p.minStock)}'),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              FilledButton.icon(
                onPressed: () => showPurchaseSheet(context, p),
                icon: const Icon(Icons.add_shopping_cart),
                label: const Text('Bought'),
              ),
              FilledButton.tonalIcon(
                onPressed: p.inStock > 0 ? () => consumeOne(context, p) : null,
                icon: const Icon(Icons.remove_circle_outline),
                label: const Text('Used one'),
              ),
              OutlinedButton.icon(
                onPressed: p.inStock > 0 ? () => openOne(context, p) : null,
                icon: const Icon(Icons.lock_open),
                label: const Text('Opened'),
              ),
              OutlinedButton.icon(
                onPressed: p.inStock > 0 ? () => consumeOne(context, p, spoiled: true) : null,
                icon: const Icon(Icons.delete_outline),
                label: const Text('Threw one away'),
              ),
              OutlinedButton.icon(
                onPressed: () => addToList(context, p),
                icon: const Icon(Icons.playlist_add),
                label: const Text('To list'),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Text('At home', style: t.textTheme.titleMedium),
          if (_entries.isEmpty)
            const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Text('None right now.')),
          for (final e in _entries)
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(
                '${fmtQty(e.quantity)} ${p.unit}'
                '${e.locationId == null ? "" : " · ${s.locationName(e.locationId)}"}'
                '${e.openedAt == null ? "" : " · opened"}',
              ),
              subtitle: Text(
                'Bought ${dateFmt.format(e.purchasedAt)}'
                '${e.unitPrice == null ? "" : " · ${s.household!.currency} ${e.unitPrice!.toStringAsFixed(2)}"}',
              ),
              trailing: ExpiryChip(e.bestBefore),
            ),
          const SizedBox(height: 24),
          Text('Prices paid', style: t.textTheme.titleMedium),
          if (_prices.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text('Add a price when you buy it to start a history.'),
            ),
          if (cheapest != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                'Cheapest so far: ${s.household!.currency} ${cheapest.unitPrice.toStringAsFixed(2)}'
                '${cheapest.storeName == null ? "" : " at ${cheapest.storeName}"}',
                style: TextStyle(color: t.colorScheme.primary, fontWeight: FontWeight.w600),
              ),
            ),
          for (final pr in _prices)
            ListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: Text('${s.household!.currency} ${pr.unitPrice.toStringAsFixed(2)}'),
              subtitle: Text(pr.storeName ?? 'unknown store'),
              trailing: Text(dateFmtYear.format(pr.at.toLocal())),
            ),
          const SizedBox(height: 24),
          Row(
            children: [
              Expanded(child: Text('Barcodes', style: t.textTheme.titleMedium)),
              TextButton.icon(
                onPressed: _addBarcode,
                icon: const Icon(Icons.qr_code_scanner),
                label: const Text('Add barcode'),
              ),
            ],
          ),
          Text(
            p.barcodes.isEmpty ? 'None yet: add one so scanning finds this product.' : p.barcodes.join(', '),
            style: TextStyle(color: t.colorScheme.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}
