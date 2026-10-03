import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:kasita/api.dart';
import 'package:kasita/models.dart';
import 'package:kasita/offline_shopping.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// A server that can be switched off, recording what reached it.
class FakeApi extends Api {
  bool online = true;
  final log = <String>[];
  final items = <String, ShoppingItem>{};
  int _n = 0;

  void _check() {
    if (!online) throw const SocketException('no signal');
  }

  @override
  Future<void> addShopping(String hid, {String? name, String? productId, double quantity = 1}) async {
    _check();
    final id = 'srv-${_n++}';
    items[id] = ShoppingItem.fromJson({'id': id, 'name': name, 'quantity': quantity, 'done': false});
    log.add('add $name');
  }

  final ticks = <String, (DateTime, String?)>{};

  @override
  Future<void> setShoppingDone(String hid, String id, bool done, {DateTime? at, String? storeId}) async {
    _check();
    if (!items.containsKey(id)) throw ApiException(404, 'Item not found');
    items[id] = items[id]!.copyWith(done: done);
    log.add('done $id $done');
    if (at != null) ticks[id] = (at, storeId);
  }

  @override
  Future<void> deleteShopping(String hid, String id) async {
    _check();
    items.remove(id);
    log.add('delete $id');
  }

  @override
  Future<List<ShoppingItem>> shopping(String hid, {bool includeDone = false}) async {
    _check();
    return items.values.where((i) => includeDone || !i.done).toList();
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('changes made offline reach the server in order once back online', () async {
    final api = FakeApi();
    await api.addShopping('h', name: 'milk');
    final off = OfflineShopping(api, 'h');
    await off.save(await api.shopping('h', includeDone: true));

    api.online = false;
    await off.enqueue({'op': 'done', 'id': 'srv-0', 'done': true}); // ticked milk in the store
    await off.enqueue({'op': 'add', 'id': 'local-1', 'name': 'bread', 'quantity': 1});
    await off.enqueue({'op': 'done', 'id': 'local-1', 'done': true}); // folded into the add
    await off.enqueue({'op': 'add', 'id': 'local-2', 'name': 'oops', 'quantity': 1});
    await off.enqueue({'op': 'delete', 'id': 'local-2'}); // cancels the add: never sent
    expect(await off.pendingCount(), 2);
    expect(await off.flush(), isFalse); // still offline: nothing lost
    expect(await off.pendingCount(), 2);
    expect((await off.cached())!.single.name, 'milk'); // the saved copy is still there

    api.online = true;
    expect(await off.flush(), isTrue);
    expect(api.log, ['add milk', 'done srv-0 true', 'add bread', 'done srv-1 true']);
    expect(api.items.values.every((i) => i.done), isTrue);
  });

  test('an offline tick reaches the server with its own time and store', () async {
    final api = FakeApi();
    await api.addShopping('h', name: 'milk');
    final off = OfflineShopping(api, 'h');
    api.online = false;
    final at = DateTime.utc(2026, 10, 3, 14, 5);
    await off.enqueue({'op': 'done', 'id': 'srv-0', 'done': true, 'at': at.toIso8601String(), 'store_id': 'goisco'});
    await off.enqueue({'op': 'add', 'id': 'local-1', 'name': 'bread', 'quantity': 1});
    await off.enqueue({'op': 'done', 'id': 'local-1', 'done': true, 'at': at.add(const Duration(minutes: 2)).toIso8601String()});
    api.online = true;
    expect(await off.flush(), isTrue);
    expect(api.ticks['srv-0'], (at, 'goisco'));
    expect(api.ticks['srv-1']!.$1, at.add(const Duration(minutes: 2))); // the folded add keeps its tick time
  });

  test('a change the server rejects is dropped, not retried forever', () async {
    final api = FakeApi();
    final off = OfflineShopping(api, 'h');
    await off.enqueue({'op': 'done', 'id': 'gone-on-another-phone', 'done': true});
    expect(await off.flush(), isTrue);
    expect(await off.pendingCount(), 0);
  });
}
