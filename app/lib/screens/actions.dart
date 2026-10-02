import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';

/// Used one of something: take it out of stock, oldest-expiring first.
Future<void> consumeOne(BuildContext context, Product p, {double qty = 1, bool spoiled = false}) async {
  final s = Kasita.read(context);
  try {
    final r = await s.api.consume(s.hid, p.id, qty, spoiled: spoiled);
    s.changed();
    if (!context.mounted) return;
    final left = double.tryParse(r['remaining'].toString()) ?? 0;
    final short = double.tryParse(r['short_by'].toString()) ?? 0;
    final events = List<String>.from(r['event_ids'] ?? const []);
    if (short > 0 && events.isEmpty) {
      toast(context, 'There was no ${p.name} in stock');
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text('${spoiled ? "Threw away" : "Used"} ${p.name} · ${fmtQty(left)} left'),
          behavior: SnackBarBehavior.floating,
          action: SnackBarAction(
            label: 'Undo',
            onPressed: () async {
              try {
                await s.api.undoStock(s.hid, events);
                s.changed();
                messenger.showSnackBar(
                  SnackBar(content: Text('Put back ${p.name}'), behavior: SnackBarBehavior.floating),
                );
              } on ApiException catch (e) {
                messenger.showSnackBar(SnackBar(content: Text(e.message), behavior: SnackBarBehavior.floating));
              }
            },
          ),
        ),
      );
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
  }
}

Future<void> openOne(BuildContext context, Product p) async {
  final s = Kasita.read(context);
  try {
    await s.api.openPack(s.hid, p.id);
    s.changed();
    if (context.mounted) toast(context, 'Marked ${p.name} as opened');
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
  }
}

Future<void> addToList(BuildContext context, Product p) async {
  final s = Kasita.read(context);
  await s.api.addShopping(s.hid, productId: p.id);
  s.changed();
  if (context.mounted) toast(context, 'Added ${p.name} to the shopping list');
}

/// "I bought this": quantity, best-before date, price and store.
Future<bool> showPurchaseSheet(BuildContext context, Product p) async {
  final ok = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (sheet) => Padding(
      // above the keyboard when it is up, else above the system navigation bar
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(sheet).bottom + MediaQuery.paddingOf(sheet).bottom),
      child: _PurchaseSheet(product: p),
    ),
  );
  return ok ?? false;
}

class _PurchaseSheet extends StatefulWidget {
  final Product product;
  const _PurchaseSheet({required this.product});
  @override
  State<_PurchaseSheet> createState() => _PurchaseSheetState();
}

class _PurchaseSheetState extends State<_PurchaseSheet> {
  double _qty = 1;
  DateTime? _bestBefore;
  final _price = TextEditingController();
  String? _storeId;
  String? _locationId;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final days = widget.product.shelfLifeDays;
    if (days != null) _bestBefore = DateUtils.dateOnly(DateTime.now()).add(Duration(days: days));
    _locationId = widget.product.defaultLocationId;
  }

  Future<void> _newStore() async {
    final s = Kasita.read(context);
    final name = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('New store'),
        content: TextField(
          controller: name,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Name'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Add')),
        ],
      ),
    );
    if (ok == true && name.text.trim().isNotEmpty) {
      final store = await s.api.addStore(s.hid, name.text.trim());
      await s.reloadStores();
      setState(() => _storeId = store.id);
    }
  }

  Future<void> _save() async {
    final s = Kasita.read(context);
    setState(() => _busy = true);
    try {
      await s.api.purchase(s.hid, {
        'product_id': widget.product.id,
        'quantity': _qty,
        'best_before': _bestBefore?.toIso8601String().substring(0, 10),
        'unit_price': _price.text.trim().isEmpty ? null : _price.text.trim().replaceAll(',', '.'),
        'store_id': _storeId,
        'location_id': _locationId,
      });
      s.changed();
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Bought ${widget.product.name}', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          Row(
            children: [
              const Text('Quantity'),
              const Spacer(),
              IconButton.outlined(
                onPressed: _qty > 1 ? () => setState(() => _qty--) : null,
                icon: const Icon(Icons.remove),
              ),
              SizedBox(
                width: 48,
                child: Text(fmtQty(_qty), textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleMedium),
              ),
              IconButton.outlined(onPressed: () => setState(() => _qty++), icon: const Icon(Icons.add)),
            ],
          ),
          const SizedBox(height: 8),
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.event),
            title: Text(
              _bestBefore == null ? 'No best-before date' : 'Best before ${dateFmtYear.format(_bestBefore!)}',
            ),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  tooltip: 'Read the date from a photo',
                  icon: const Icon(Icons.photo_camera_outlined),
                  onPressed: () async {
                    final d = await dateFromPhoto(context);
                    if (d != null && mounted) setState(() => _bestBefore = d);
                  },
                ),
                if (_bestBefore != null)
                  IconButton(icon: const Icon(Icons.clear), onPressed: () => setState(() => _bestBefore = null)),
              ],
            ),
            onTap: () async {
              final now = DateTime.now();
              final d = await showDatePicker(
                context: context,
                initialDate: _bestBefore ?? now.add(const Duration(days: 7)),
                firstDate: now.subtract(const Duration(days: 30)),
                lastDate: now.add(const Duration(days: 365 * 5)),
              );
              if (d != null) setState(() => _bestBefore = d);
            },
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _price,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              labelText: 'Price each (optional)',
              prefixText: '${s.household!.currency} ',
              border: const OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String?>(
                  initialValue: _storeId,
                  decoration: const InputDecoration(labelText: 'Store', border: OutlineInputBorder()),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('—')),
                    for (final st in s.stores) DropdownMenuItem(value: st.id, child: Text(st.name)),
                  ],
                  onChanged: (v) => setState(() => _storeId = v),
                ),
              ),
              IconButton(tooltip: 'New store', onPressed: _newStore, icon: const Icon(Icons.add_business_outlined)),
            ],
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String?>(
            initialValue: _locationId,
            decoration: const InputDecoration(labelText: 'Where it goes', border: OutlineInputBorder()),
            items: [
              const DropdownMenuItem(value: null, child: Text('—')),
              for (final l in s.locations) DropdownMenuItem(value: l.id, child: Text(l.name)),
            ],
            onChanged: (v) => setState(() => _locationId = v),
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: _busy ? null : _save,
            icon: const Icon(Icons.add_shopping_cart),
            label: const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: Text('Add to pantry')),
          ),
        ],
      ),
    );
  }
}

/// Photograph the date printed on a pack; ChatGPT reads it. Null when cancelled or unreadable.
Future<DateTime?> dateFromPhoto(BuildContext context) async {
  final s = Kasita.read(context);
  final XFile? shot;
  try {
    shot = await ImagePicker().pickImage(source: ImageSource.camera, maxWidth: 1600, imageQuality: 88);
  } catch (e) {
    if (context.mounted) toast(context, 'Could not open the camera: $e', error: true);
    return null;
  }
  if (shot == null || !context.mounted) return null;
  final bytes = await shot.readAsBytes();
  if (!context.mounted) return null;
  showDialog(
    context: context,
    barrierDismissible: false,
    builder: (_) => const AlertDialog(
      content: Row(
        children: [
          CircularProgressIndicator(),
          SizedBox(width: 20),
          Expanded(child: Text('Reading the date…')),
        ],
      ),
    ),
  );
  try {
    final r = await s.api.readDate(s.hid, bytes);
    if (!context.mounted) return null;
    Navigator.of(context).pop();
    final d = r['date'] == null ? null : DateTime.tryParse(r['date']);
    if (d == null) {
      toast(context, "Couldn't read a date there. Try closer, or pick it by hand.");
    } else {
      toast(context, 'Read "${r['printed'] ?? r['date']}": ${dateFmtYear.format(d)}');
    }
    return d;
  } on ApiException catch (e) {
    if (context.mounted) {
      Navigator.of(context).pop();
      toast(context, e.message, error: true);
    }
    return null;
  }
}
