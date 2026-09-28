import 'dart:async';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../main.dart';
import '../offline_shopping.dart';
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
  bool _offline = false; // showing the list saved on the phone
  int _pending = 0; // changes waiting to be sent
  Timer? _retry;

  OfflineShopping _store() {
    final s = Kasita.read(context);
    return OfflineShopping(s.api, s.hid);
  }

  @override
  void initState() {
    super.initState();
    // while offline, try again every 20 s so queued changes go out as soon as there is signal
    _retry = Timer.periodic(const Duration(seconds: 20), (_) {
      if (_offline && mounted) _load();
    });
  }

  @override
  void dispose() {
    _retry?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final off = _store();
    final s = Kasita.read(context);
    try {
      await off.flush();
      final items = await s.api.shopping(s.hid, includeDone: true);
      await off.save(items);
      final pending = await off.pendingCount();
      if (mounted) {
        setState(() {
          _items = items;
          _offline = false;
          _pending = pending;
        });
      }
    } catch (e) {
      if (!OfflineShopping.isOffline(e)) {
        if (mounted) toast(context, '$e', error: true);
        return;
      }
      final cached = await off.cached();
      final pending = await off.pendingCount();
      if (mounted) {
        setState(() {
          _items = _items ?? cached ?? [];
          _offline = true;
          _pending = pending;
        });
      }
    }
  }

  /// Apply a change on screen and in the phone's copy, and queue it for the server.
  Future<void> _queue(Map<String, dynamic> op, List<ShoppingItem> next) async {
    final off = _store();
    await off.enqueue(op);
    await off.save(next);
    final pending = await off.pendingCount();
    if (mounted) {
      setState(() {
        _items = next;
        _offline = true;
        _pending = pending;
      });
    }
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
    final parts = _add.text.split(',').map((p) => p.trim()).where((p) => p.isNotEmpty).toList();
    _add.clear();
    var wentOffline = false;
    for (final part in parts) {
      final m = RegExp(r'^(\d+(?:[.,]\d+)?)\s*x?\s+(.+)$', caseSensitive: false).firstMatch(part);
      final qty = m == null ? 1.0 : double.parse(m.group(1)!.replaceAll(',', '.'));
      final name = m == null ? part : m.group(2)!;
      try {
        if (_offline) throw const _Offline();
        await s.api.addShopping(s.hid, name: name, quantity: qty);
      } catch (e) {
        if (!OfflineShopping.isOffline(e)) {
          if (mounted) toast(context, '$e', error: true);
          continue;
        }
        wentOffline = true;
        final id = 'local-${DateTime.now().microsecondsSinceEpoch}';
        final item = ShoppingItem.fromJson({'id': id, 'name': name, 'quantity': qty, 'auto': false, 'done': false});
        await _queue({'op': 'add', 'id': id, 'name': name, 'quantity': qty}, [...?_items, item]);
      }
    }
    if (!wentOffline) await _load();
  }

  Future<void> _toggle(ShoppingItem i) async {
    final s = Kasita.read(context);
    final next = [for (final x in _items!) x.id == i.id ? _flip(x) : x];
    setState(() => _items = next);
    try {
      if (_offline || i.id.startsWith('local-')) throw const _Offline();
      await s.api.setShoppingDone(s.hid, i.id, !i.done);
      await _store().save(next);
    } catch (e) {
      if (OfflineShopping.isOffline(e)) {
        await _queue({'op': 'done', 'id': i.id, 'done': !i.done}, next);
      } else if (mounted) {
        toast(context, '$e', error: true);
      }
    }
  }

  Future<void> _delete(ShoppingItem i) async {
    final s = Kasita.read(context);
    final next = [
      for (final x in _items!)
        if (x.id != i.id) x,
    ];
    setState(() => _items = next);
    try {
      if (_offline || i.id.startsWith('local-')) throw const _Offline();
      await s.api.deleteShopping(s.hid, i.id);
      await _store().save(next);
    } catch (e) {
      if (OfflineShopping.isOffline(e)) {
        await _queue({'op': 'delete', 'id': i.id}, next);
      } else if (mounted) {
        toast(context, '$e', error: true);
      }
    }
  }

  ShoppingItem _flip(ShoppingItem i) => i.copyWith(done: !i.done);

  /// Store-walk order; anything else (or no category) comes last as "Other".
  static const _order = [
    'Produce',
    'Bakery',
    'Meat & fish',
    'Dairy & eggs',
    'Pantry',
    'Snacks & sweets',
    'Drinks',
    'Alcohol',
    'Frozen',
    'Personal care',
    'Household & cleaning',
    'Baby',
    'Pet',
    'Health',
  ];

  /// Open items grouped by category, groups in store-walk order.
  List<(String, List<ShoppingItem>)> _groups(List<ShoppingItem> open) {
    final by = <String, List<ShoppingItem>>{};
    for (final i in open) {
      final c = _order.contains(i.category) ? i.category! : 'Other';
      by.putIfAbsent(c, () => []).add(i);
    }
    return [
      for (final c in [..._order, 'Other'])
        if (by[c] != null) (c, by[c]!),
    ];
  }

  String _asText(List<ShoppingItem> open) {
    final lines = <String>['Shopping list'];
    for (final (cat, items) in _groups(open)) {
      lines
        ..add('')
        ..add(cat);
      for (final i in items) {
        lines.add(
          '• ${i.quantity == 1 ? '' : '${fmtQty(i.quantity)}× '}${i.name}${i.note == null ? '' : ' (${i.note})'}',
        );
      }
    }
    return lines.join('\n');
  }

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    final open = _items?.where((i) => !i.done).toList() ?? [];
    final done = _items?.where((i) => i.done).toList() ?? [];
    return Scaffold(
      appBar: AppBar(
        title: const Text('Shopping list'),
        actions: [
          if (open.isNotEmpty)
            IconButton(
              tooltip: 'Share the list (WhatsApp, messages...)',
              icon: const Icon(Icons.share_outlined),
              onPressed: () => SharePlus.instance.share(ShareParams(text: _asText(open))),
            ),
          IconButton(
            tooltip: 'Add everything that is running low',
            icon: const Icon(Icons.playlist_add),
            onPressed: () async {
              if (_offline) return toast(context, 'Needs a connection');
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
                if (_offline) return toast(context, 'Needs a connection');
                await s.api.clearDone(s.hid);
                await _load();
              },
            ),
        ],
      ),
      body: Column(
        children: [
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
          if (_offline)
            MaterialBanner(
              leading: const Icon(Icons.cloud_off),
              content: Text(
                _pending == 0
                    ? 'Offline: showing the list saved on this phone.'
                    : 'Offline: $_pending change${_pending == 1 ? '' : 's'} saved on this phone, sent when you have signal.',
              ),
              actions: [TextButton(onPressed: _load, child: const Text('Retry'))],
            ),
          Expanded(
            child: _items == null
                ? const Center(child: CircularProgressIndicator())
                : _items!.isEmpty
                ? const EmptyState(
                    icon: Icons.shopping_cart_outlined,
                    title: 'Nothing to buy',
                    message: 'Items that run low in the pantry show up here automatically.',
                  )
                : RefreshIndicator(
                    onRefresh: _load,
                    child: ListView(
                      children: [
                        for (final (cat, items) in _groups(open)) ...[
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 14, 16, 2),
                            child: Text(
                              cat,
                              style: Theme.of(context).textTheme.labelLarge
                                  ?.copyWith(color: Theme.of(context).colorScheme.primary),
                            ),
                          ),
                          for (final i in items) _tile(i),
                        ],
                        if (done.isNotEmpty) const Divider(),
                        for (final i in done) _tile(i),
                        const SizedBox(height: 80),
                      ],
                    ),
                  ),
          ),
        ],
      ),
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
        child: Icon(Icons.delete_outline, color: cs.onErrorContainer),
      ),
      onDismissed: (_) => _delete(i),
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

/// Thrown to take the offline path without trying the server (already offline, or a local-only item).
class _Offline implements Exception {
  const _Offline();
}
