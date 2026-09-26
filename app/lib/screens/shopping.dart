import 'package:flutter/material.dart';

import '../main.dart';
import '../models.dart';
import '../widgets.dart';

class ShoppingScreen extends StatefulWidget {
  const ShoppingScreen({super.key});
  @override
  State<ShoppingScreen> createState() => _ShoppingScreenState();
}

class _ShoppingScreenState extends State<ShoppingScreen> {
  final _add = TextEditingController();
  List<ShoppingItem>? _items;
  int _seen = -1;

  Future<void> _load() async {
    final s = Kasita.read(context);
    final items = await s.api.shopping(s.hid, includeDone: true);
    if (mounted) setState(() => _items = items);
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

  /// "2x milk, bread, 3 eggs" adds three items.
  Future<void> _addText() async {
    final s = Kasita.read(context);
    final parts = _add.text.split(',').map((p) => p.trim()).where((p) => p.isNotEmpty);
    for (final part in parts) {
      final m = RegExp(r'^(\d+(?:[.,]\d+)?)\s*x?\s+(.+)$', caseSensitive: false).firstMatch(part);
      final qty = m == null ? 1.0 : double.parse(m.group(1)!.replaceAll(',', '.'));
      await s.api.addShopping(s.hid, name: m == null ? part : m.group(2)!, quantity: qty);
    }
    _add.clear();
    await _load();
  }

  Future<void> _toggle(ShoppingItem i) async {
    final s = Kasita.read(context);
    setState(() => _items = [for (final x in _items!) x.id == i.id ? _flip(x) : x]);
    await s.api.setShoppingDone(s.hid, i.id, !i.done);
  }

  ShoppingItem _flip(ShoppingItem i) => ShoppingItem.fromJson({
        'id': i.id, 'name': i.name, 'product_id': i.productId, 'note': i.note,
        'quantity': i.quantity, 'auto': i.auto, 'done': !i.done,
      });

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    final open = _items?.where((i) => !i.done).toList() ?? [];
    final done = _items?.where((i) => i.done).toList() ?? [];
    return Scaffold(
      appBar: AppBar(title: const Text('Shopping list'), actions: [
        IconButton(
          tooltip: 'Add everything that is running low',
          icon: const Icon(Icons.playlist_add),
          onPressed: () async {
            await s.api.refill(s.hid);
            await _load();
            if (context.mounted) toast(context, 'Added what is running low');
          },
        ),
        if (done.isNotEmpty)
          IconButton(
            tooltip: 'Remove ticked items',
            icon: const Icon(Icons.cleaning_services_outlined),
            onPressed: () async {
              await s.api.clearDone(s.hid);
              await _load();
            },
          ),
      ]),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          child: TextField(
            controller: _add,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _addText(),
            decoration: InputDecoration(
              hintText: 'Add items: 2x milk, bread',
              border: const OutlineInputBorder(),
              suffixIcon: IconButton(icon: const Icon(Icons.add), onPressed: _addText),
            ),
          ),
        ),
        Expanded(
          child: _items == null
              ? const Center(child: CircularProgressIndicator())
              : _items!.isEmpty
                  ? const EmptyState(
                      icon: Icons.shopping_cart_outlined,
                      title: 'Nothing to buy',
                      message: 'Items that run low in the pantry show up here automatically.')
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView(children: [
                        for (final i in open) _tile(i),
                        if (done.isNotEmpty) const Divider(),
                        for (final i in done) _tile(i),
                        const SizedBox(height: 80),
                      ]),
                    ),
        ),
      ]),
    );
  }

  Widget _tile(ShoppingItem i) {
    final cs = Theme.of(context).colorScheme;
    return Dismissible(
      key: ValueKey(i.id),
      direction: DismissDirection.endToStart,
      background: Container(
          color: cs.errorContainer,
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: 20),
          child: Icon(Icons.delete_outline, color: cs.onErrorContainer)),
      onDismissed: (_) async {
        final s = Kasita.read(context);
        setState(() => _items!.removeWhere((x) => x.id == i.id));
        await s.api.deleteShopping(s.hid, i.id);
      },
      child: CheckboxListTile(
        value: i.done,
        onChanged: (_) => _toggle(i),
        controlAffinity: ListTileControlAffinity.leading,
        title: Text(
          i.quantity == 1 ? i.name : '${fmtQty(i.quantity)} × ${i.name}',
          style: i.done ? TextStyle(decoration: TextDecoration.lineThrough, color: cs.outline) : null,
        ),
        subtitle: i.auto ? const Text('running low') : (i.note == null ? null : Text(i.note!)),
      ),
    );
  }
}
