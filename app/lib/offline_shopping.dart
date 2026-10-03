import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'models.dart';

/// The shopping list must work in the supermarket, where the signal is bad.
///
/// Every successful load is saved on the phone. When the server can't be
/// reached, the saved list is shown and each change (tick, add, delete) is
/// applied locally and queued; [flush] replays the queue in order once the
/// server answers again. Items added offline carry a temporary "local-" id.
class OfflineShopping {
  final Api api;
  final String hid;
  OfflineShopping(this.api, this.hid);

  String get _listKey => 'shopping.list.$hid';
  String get _queueKey => 'shopping.queue.$hid';

  /// A network failure, as opposed to the server saying no (ApiException).
  static bool isOffline(Object e) => e is! ApiException;

  Future<List<ShoppingItem>?> cached() async {
    final p = await SharedPreferences.getInstance();
    final raw = p.getString(_listKey);
    if (raw == null) return null;
    return [for (final j in jsonDecode(raw) as List) ShoppingItem.fromJson(Map<String, dynamic>.from(j))];
  }

  Future<void> save(List<ShoppingItem> items) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_listKey, jsonEncode([for (final i in items) i.toJson()]));
  }

  Future<List<Map<String, dynamic>>> _queue() async {
    final p = await SharedPreferences.getInstance();
    final raw = p.getString(_queueKey);
    return raw == null ? [] : [for (final j in jsonDecode(raw) as List) Map<String, dynamic>.from(j)];
  }

  Future<void> _setQueue(List<Map<String, dynamic>> q) async {
    final p = await SharedPreferences.getInstance();
    if (q.isEmpty) {
      await p.remove(_queueKey);
    } else {
      await p.setString(_queueKey, jsonEncode(q));
    }
  }

  Future<int> pendingCount() async => (await _queue()).length;

  /// When a queued tick really happened (so the store walk is learned in the right order).
  static DateTime? _at(Map<String, dynamic> op) => op['at'] == null ? null : DateTime.tryParse(op['at'] as String);

  /// Queue a change. Changes to an item that only exists locally are folded
  /// into its queued "add" instead of being sent separately.
  Future<void> enqueue(Map<String, dynamic> op) async {
    final q = await _queue();
    final id = op['id'] as String?;
    if (id != null && id.startsWith('local-')) {
      final add = q.indexWhere((o) => o['op'] == 'add' && o['id'] == id);
      if (add >= 0) {
        if (op['op'] == 'delete') {
          q.removeAt(add);
        } else if (op['op'] == 'done') {
          q[add] = {...q[add], 'done': op['done'], 'at': op['at'], 'store_id': op['store_id']};
        }
        await _setQueue(q);
        return;
      }
    }
    q.add(op);
    await _setQueue(q);
  }

  /// Send queued changes in order. Stops at the first network failure (still
  /// offline) and keeps the rest; a change the server rejects is dropped.
  /// Returns true when the queue is empty afterwards.
  Future<bool> flush() async {
    final q = await _queue();
    while (q.isNotEmpty) {
      final op = q.first;
      try {
        switch (op['op']) {
          case 'add':
            await api.addShopping(hid, name: op['name'], quantity: (op['quantity'] as num).toDouble());
            if (op['done'] == true) {
              // the server gave it a new id; find it and tick it
              final items = await api.shopping(hid);
              final match = items.where((i) => i.name == op['name'] && !i.done).lastOrNull;
              if (match != null) {
                await api.setShoppingDone(hid, match.id, true, at: _at(op), storeId: op['store_id']);
              }
            }
          case 'done':
            await api.setShoppingDone(hid, op['id'], op['done'] == true, at: _at(op), storeId: op['store_id']);
          case 'delete':
            await api.deleteShopping(hid, op['id']);
        }
      } catch (e) {
        if (isOffline(e)) {
          await _setQueue(q);
          return false;
        }
        // rejected (e.g. the item was deleted on another phone): drop this change
      }
      q.removeAt(0);
      await _setQueue(q);
    }
    return true;
  }
}
