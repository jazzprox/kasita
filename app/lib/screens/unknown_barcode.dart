import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'product_form.dart';
import 'product_picker.dart';

/// A barcode the household doesn't know yet: attach it to one of your products
/// (e.g. something that came from a receipt), or create a new product.
/// Returns the product, or null when the person cancelled or skipped.
Future<Product?> productForUnknownBarcode(BuildContext context, BarcodeResult r, {String skipLabel = 'Cancel'}) async {
  final choice = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    builder: (sheet) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ListTile(
            title: Text(r.name ?? 'Barcode ${r.barcode}', style: Theme.of(context).textTheme.titleMedium),
            subtitle: Text(r.found ? 'New to your household' : 'Not in any product database'),
          ),
          ListTile(
            leading: const Icon(Icons.link),
            title: const Text("It's one of my products"),
            subtitle: const Text('Attach this barcode to it, e.g. something added from a receipt'),
            onTap: () => Navigator.pop(sheet, 'link'),
          ),
          ListTile(
            leading: const Icon(Icons.add),
            title: const Text('New product'),
            onTap: () => Navigator.pop(sheet, 'new'),
          ),
          ListTile(leading: const Icon(Icons.close), title: Text(skipLabel), onTap: () => Navigator.pop(sheet)),
        ],
      ),
    ),
  );
  if (!context.mounted || choice == null) return null;
  if (choice == 'new') {
    return Navigator.of(context).push<Product>(MaterialPageRoute(builder: (_) => ProductFormScreen(prefill: r)));
  }
  final s = Kasita.read(context);
  final picked = await Navigator.of(context).push<Product>(
    MaterialPageRoute(
      builder: (_) => ProductPicker(
        title: 'Attach ${r.barcode} to…',
        hint: r.name == null ? 'Search your products' : 'Search (scanned: ${r.name})',
        barcodeLessFirst: true,
        emptyText: 'No match. Go back and choose New product.',
      ),
    ),
  );
  if (picked == null || !context.mounted) return null;
  try {
    final updated = await s.api.addBarcode(s.hid, picked.id, r.barcode);
    s.changed();
    if (context.mounted) toast(context, 'Barcode attached to ${updated.name}');
    return updated;
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
    return null;
  }
}
