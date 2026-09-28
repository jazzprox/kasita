import 'package:flutter/material.dart';

import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'barcode_run.dart';
import 'product_detail.dart';
import 'product_form.dart';

class ProductsScreen extends StatefulWidget {
  const ProductsScreen({super.key});
  @override
  State<ProductsScreen> createState() => _ProductsScreenState();
}

class _ProductsScreenState extends State<ProductsScreen> {
  List<Product>? _all;
  String _q = '';
  int _seen = -1;

  Future<void> _load() async {
    final s = Kasita.read(context);
    final all = await s.api.products(s.hid);
    if (mounted) setState(() => _all = all);
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

  /// How many products still have no barcode, for the prompt above the list.
  int get _untagged => (_all ?? []).where((p) => p.barcodes.isEmpty).length;

  @override
  Widget build(BuildContext context) {
    final q = _q.toLowerCase();
    final list = (_all ?? [])
        .where((p) => q.isEmpty || '${p.name} ${p.brand ?? ""} ${p.category ?? ""}'.toLowerCase().contains(q))
        .toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Products')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProductFormScreen())),
        icon: const Icon(Icons.add),
        label: const Text('New product'),
      ),
      body: _all == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                  child: SearchBar(
                    hintText: 'Search products',
                    leading: const Icon(Icons.search),
                    onChanged: (v) => setState(() => _q = v),
                  ),
                ),
                /*
                 * A prompt only while there is work to do.
                 *
                 * Receipt import creates products with no barcode, and
                 * tagging them one at a time is five taps each. This offers
                 * the single-pass run instead — and disappears entirely once
                 * everything is tagged, because a permanent button for an
                 * occasional job is clutter.
                 */
                if (_untagged > 0)
                  Card(
                    margin: const EdgeInsets.fromLTRB(16, 4, 16, 8),
                    child: ListTile(
                      leading: const Icon(Icons.qr_code_scanner),
                      title: Text('$_untagged product${_untagged == 1 ? '' : 's'} without a barcode'),
                      subtitle: const Text('Scan them in one pass'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () async {
                        await Navigator.of(context)
                            .push(MaterialPageRoute(builder: (_) => const BarcodeRunScreen()));
                        if (mounted) _load();
                      },
                    ),
                  ),
                if (_all!.isEmpty)
                  const EmptyState(
                    icon: Icons.inventory_2_outlined,
                    title: 'No products yet',
                    message: 'Scanning a barcode creates the product for you.',
                  ),
                for (final p in list)
                  ListTile(
                    leading: ProductThumb(p.imageUrl),
                    title: Text(p.name),
                    subtitle: Text([p.brand, p.category].whereType<String>().join(' · ')),
                    trailing: Text(p.inStock > 0 ? '${fmtQty(p.inStock)} ${p.unit}' : '—'),
                    onTap: () =>
                        Navigator.of(context)
                            .push(MaterialPageRoute(builder: (_) => ProductDetailScreen(productId: p.id))),
                  ),
                const SizedBox(height: 96),
              ],
            ),
    );
  }
}
