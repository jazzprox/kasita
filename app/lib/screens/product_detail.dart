import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';

import '../main.dart';
import '../nutri.dart';
import '../price_chart.dart';
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
  List<Map<String, dynamic>> _compare = const [];
  int _seen = -1;

  Future<void> _share() async {
    final s = Kasita.read(context);
    final p = _p!;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Share with Open Food Facts?'),
        content: Text(
          'Adds "${p.name}"${p.brand == null ? '' : ' (${p.brand})'}, its barcode, category'
          '${p.imageUrl == null ? '' : ' and your photo'} to the free, public Open Food Facts databases, '
          'under your account. Anyone can then find it by scanning, and anyone can improve it.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Share')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final r = await s.api.contribute(s.hid, p.id);
      if (!mounted) return;
      toast(context, 'Added to ${r['site']}. Thank you!');
      _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  /// Tap a batch: set its date (photo or calendar) or move it (into the freezer starts the frozen clock).
  Future<void> _editEntry(StockEntry e) async {
    final s = Kasita.read(context);
    final choice = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const Text('Read the date from a photo'),
              onTap: () => Navigator.pop(c, 'photo'),
            ),
            ListTile(
              leading: const Icon(Icons.event),
              title: const Text('Pick the date'),
              onTap: () => Navigator.pop(c, 'pick'),
            ),
            const Divider(),
            for (final l in s.locations)
              ListTile(
                leading: Icon(l.isFreezer ? Icons.ac_unit : Icons.kitchen_outlined),
                title: Text('Move to ${l.name}'),
                trailing: l.id == e.locationId ? const Icon(Icons.check) : null,
                onTap: () => Navigator.pop(c, 'loc:${l.id}'),
              ),
          ],
        ),
      ),
    );
    if (choice == null || !mounted) return;
    Map<String, dynamic>? body;
    if (choice == 'photo') {
      final d = await dateFromPhoto(context);
      if (d != null) body = {'best_before': d.toIso8601String().substring(0, 10)};
    } else if (choice == 'pick') {
      final now = DateTime.now();
      final d = await showDatePicker(
        context: context,
        initialDate: e.bestBefore ?? now.add(const Duration(days: 7)),
        firstDate: now.subtract(const Duration(days: 365)),
        lastDate: now.add(const Duration(days: 365 * 5)),
      );
      if (d != null) body = {'best_before': d.toIso8601String().substring(0, 10)};
    } else if (choice.startsWith('loc:')) {
      body = {'location_id': choice.substring(4)};
    }
    if (body == null || !mounted) return;
    try {
      await s.api.patchEntry(s.hid, e.id, body);
      s.changed();
      _load();
    } on ApiException catch (err) {
      if (mounted) toast(context, err.message, error: true);
    }
  }

  /// Tap the picture: take a new one, pick one, or remove it.
  Future<void> _photo() async {
    final s = Kasita.read(context);
    final p = _p!;
    final choice = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (p.photoSource == 'database')
              const ListTile(
                leading: Icon(Icons.cloud_outlined),
                title: Text('This picture came with the barcode'),
                subtitle: Text(
                  'It is the product database\'s photo. Replacing it only changes it in Kasita, '
                  'and you can put it back later.',
                ),
              ),
            if (p.canRestorePhoto)
              ListTile(
                leading: const Icon(Icons.restore),
                title: const Text('Restore the database photo'),
                onTap: () => Navigator.pop(c, 'restore'),
              ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: Text(
                p.imageUrl == null
                    ? 'Take a photo'
                    : (p.photoSource == 'database' ? 'Replace with my own photo' : 'Take a new photo'),
              ),
              subtitle: const Text('Pack on a table, front label filling the frame'),
              onTap: () => Navigator.pop(c, 'camera'),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Choose from gallery'),
              onTap: () => Navigator.pop(c, 'gallery'),
            ),
            if (p.imageUrl != null)
              ListTile(
                leading: const Icon(Icons.hide_image_outlined),
                title: const Text('Remove photo'),
                onTap: () => Navigator.pop(c, 'remove'),
              ),
          ],
        ),
      ),
    );
    if (choice == null || !mounted) return;
    try {
      if (choice == 'restore') {
        await s.api.restoreProductPhoto(s.hid, p.id);
      } else if (choice == 'remove') {
        await s.api.removeProductPhoto(s.hid, p.id);
      } else {
        final shot = await ImagePicker().pickImage(
          source: choice == 'camera' ? ImageSource.camera : ImageSource.gallery,
          maxWidth: 1600,
          imageQuality: 88,
        );
        if (shot == null || !mounted) return;
        await s.api.setProductPhoto(s.hid, p.id, await shot.readAsBytes());
      }
      s.changed();
      _load();
      if (mounted) {
        toast(context, {'remove': 'Photo removed', 'restore': 'Database photo is back'}[choice] ?? 'Photo updated');
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

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
    List<Map<String, dynamic>> compare = const [];
    try {
      compare = await s.api.compareSizes(s.hid, widget.productId);
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      _compare = compare;
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

  /// Newest price at each store (prices come newest first), cheapest marked.
  List<(String, PricePoint, bool)> _perStore() {
    final latest = <String, PricePoint>{};
    for (final pr in _prices) {
      latest.putIfAbsent(pr.storeName ?? 'Unknown store', () => pr);
    }
    if (latest.isEmpty) return [];
    final low = latest.values.map((p) => p.unitPrice).reduce((a, b) => a < b ? a : b);
    final rows = [for (final e in latest.entries) (e.key, e.value, e.value.unitPrice == low)];
    rows.sort((a, b) => a.$2.unitPrice.compareTo(b.$2.unitPrice));
    return rows;
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
        padding: navBarSafe(context, const EdgeInsets.all(16)),
        children: [
          Row(
            children: [
              GestureDetector(
                onTap: _photo,
                child: Stack(
                  children: [
                    ProductThumb(p.imageUrl, size: 72),
                    Positioned(
                      right: 2,
                      bottom: 2,
                      child: CircleAvatar(
                        radius: 12,
                        backgroundColor: t.colorScheme.primaryContainer,
                        child: Icon(
                          p.photoSource == 'database' ? Icons.cloud_outlined : Icons.photo_camera,
                          size: 14,
                          color: t.colorScheme.onPrimaryContainer,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (p.brand != null) Text(p.brand!, style: TextStyle(color: t.colorScheme.onSurfaceVariant)),
                    if (p.photoSource != null)
                      Text(
                        p.photoSource == 'database' ? 'Photo: from the product database' : 'Photo: yours',
                        style: t.textTheme.bodySmall?.copyWith(color: t.colorScheme.onSurfaceVariant),
                      ),
                    Text('${fmtQty(p.inStock)} ${p.unit} at home', style: t.textTheme.titleLarge),
                    if (p.minStock > 0) Text('Keep at least ${fmtQty(p.minStock)}'),
                    if (p.sizeText != null || p.weighed)
                      Text(
                        p.weighed ? 'Sold by weight (deli / scale label)' : 'Pack: ${p.sizeText}',
                        style: t.textTheme.bodySmall,
                      ),
                  ],
                ),
              ),
            ],
          ),
          if (p.nutriscore != null || p.nova != null || p.nutrients != null) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                if (p.nutriscore != null) ...[NutriScoreBadge(p.nutriscore!), const SizedBox(width: 10)],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (p.nova != null) Text(novaText(p.nova!), style: t.textTheme.labelLarge),
                      if (p.nutrients != null)
                        Text(
                          nutrientsText(p.nutrients!, liquid: p.sizeUnit == 'ml'),
                          style: t.textTheme.bodySmall,
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ],
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
          if (p.runsOutInDays != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                'At your usual pace this lasts about ${p.runsOutInDays!.round()} more days',
                style: TextStyle(
                  color: p.runsOutInDays! <= 7 ? Colors.orange.shade800 : t.colorScheme.onSurfaceVariant,
                ),
              ),
            ),
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
              trailing: e.frozenAt != null ? FrozenChip(e.frozenAt!) : ExpiryChip(e.bestBefore),
              onTap: () => _editEntry(e),
            ),
          const SizedBox(height: 24),
          Text('Prices paid', style: t.textTheme.titleMedium),
          if (_prices.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text('Add a price when you buy it to start a history.'),
            ),
          if (_prices.length >= 2) ...[
            const SizedBox(height: 8),
            PriceChart(prices: _prices, currency: s.household!.currency),
            if (PriceChart.trend(_prices) case final trend?)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(trend, style: t.textTheme.bodySmall),
              ),
          ],
          if (cheapest != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                'Cheapest so far: ${s.household!.currency} ${cheapest.unitPrice.toStringAsFixed(2)}'
                '${cheapest.storeName == null ? "" : " at ${cheapest.storeName}"}',
                style: TextStyle(color: t.colorScheme.primary, fontWeight: FontWeight.w600),
              ),
            ),
          if (_perStore().length > 1) ...[
            const SizedBox(height: 4),
            Text('Latest price per store', style: t.textTheme.labelLarge),
            for (final (store, pr, cheapest) in _perStore())
              ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                leading: Icon(
                  cheapest ? Icons.star : Icons.storefront_outlined,
                  color: cheapest ? t.colorScheme.primary : null,
                ),
                title: Text(store),
                subtitle: Text(dateFmtYear.format(pr.on)),
                trailing: Text(
                  '${s.household!.currency} ${pr.unitPrice.toStringAsFixed(2)}',
                  style: cheapest ? TextStyle(color: t.colorScheme.primary, fontWeight: FontWeight.w600) : null,
                ),
              ),
            const Divider(),
            Text('Every price paid', style: t.textTheme.labelLarge),
          ],
          for (final pr in _prices)
            ListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: Text(
                '${s.household!.currency} ${pr.unitPrice.toStringAsFixed(2)}'
                '${pr.perBase != null && !(pr.per == 'kg' && p.unit == 'kg') ? '  ·  ${pr.perBase!.toStringAsFixed(2)} per ${pr.per == 'each' ? 'piece' : pr.per}' : ''}',
              ),
              subtitle: Text(pr.storeName ?? 'unknown store'),
              trailing: Text(dateFmtYear.format(pr.on)),
            ),
          if (_compare.length > 1) ...[
            const SizedBox(height: 16),
            Text('Same kind, per ${_compare.first['per'] == 'each' ? 'piece' : _compare.first['per']}',
                style: t.textTheme.titleMedium),
            Text('Other sizes and brands you buy, cheapest first (latest price)', style: t.textTheme.bodySmall),
            for (final c in _compare)
              ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                leading: Icon(
                  c == _compare.first ? Icons.star : Icons.scale_outlined,
                  color: c == _compare.first ? t.colorScheme.primary : null,
                ),
                title: Text(
                  '${c['name']}${c['this'] == true ? ' (this one)' : ''}',
                  style: c['this'] == true ? const TextStyle(fontWeight: FontWeight.w600) : null,
                ),
                subtitle: Text('${s.household!.currency} ${double.parse('${c['price']}').toStringAsFixed(2)} at ${c['store']}'),
                trailing: Text(
                  '${double.parse('${c['per_base']}').toStringAsFixed(2)} / ${c['per'] == 'each' ? 'pc' : c['per']}',
                  style: c == _compare.first ? TextStyle(color: t.colorScheme.primary, fontWeight: FontWeight.w600) : null,
                ),
                onTap: c['this'] == true
                    ? null
                    : () => Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => ProductDetailScreen(productId: c['product_id'] as String)),
                      ),
              ),
          ],
          if (p.shareable) ...[
            const SizedBox(height: 16),
            Card(
              child: ListTile(
                leading: const Icon(Icons.volunteer_activism_outlined),
                title: const Text('Share with Open Food Facts'),
                subtitle: const Text('No database knew this barcode. Add it so the next person who scans it finds it.'),
                onTap: _share,
              ),
            ),
          ],
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
