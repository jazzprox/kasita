import 'package:flutter_test/flutter_test.dart';
import 'package:kasita/nearby/nearby_logic.dart';

final now = DateTime(2026, 10, 2, 17, 30);

NearbyCache cache({DateTime? savedAt}) => NearbyCache(
  const [
    NearbyStore('m', 'Mangusa', 12.12, -68.90),
    NearbyStore('c', 'Centrum', 12.13, -68.93),
    NearbyStore('g', 'Goisco', 12.10, -68.91),
  ],
  const [
    NearbyItem('Coffee', cheapestStoreId: 'm', usualStoreId: 'c'),
    NearbyItem('Rice', cheapestStoreId: 'm', usualStoreId: 'm'),
    NearbyItem('Milk', cheapestStoreId: 'c', usualStoreId: 'm'),
    NearbyItem('Candles'),
  ],
  savedAt ?? now.subtract(const Duration(hours: 1)),
);

const on = NearbySettings(enabled: true, quietFrom: 21 * 60, quietTo: 8 * 60, everyHours: 6);

NearbyNotice? at(String store, {NearbySettings s = on, DateTime? time, Map<String, DateTime>? last, NearbyCache? c}) =>
    decide(storeId: store, now: time ?? now, cache: c ?? cache(), settings: s, lastNotified: last ?? {});

void main() {
  test('cheapest and usual items at a store', () {
    expect(at('m')!.title, 'Near Mangusa: 3 items on your list, 2 cheapest here');
    expect(at('m')!.body, 'Coffee, Rice, Milk');
    // Coffee is cheaper at Mangusa, but you usually buy it at Centrum: still worth a mention
    expect(at('c')!.title, 'Near Centrum: 2 items on your list, 1 cheapest here');
    expect(at('c')!.body, 'Milk, Coffee');
    expect(at('g'), isNull); // nothing on the list for Goisco
  });

  test('only cheapest items', () {
    final c = NearbyCache(cache().stores, const [NearbyItem('Rice', cheapestStoreId: 'g', usualStoreId: 'g')], now);
    expect(at('g', c: c)!.title, 'Near Goisco: 1 item on your list is cheapest here');
  });

  test('only usual items', () {
    final c = NearbyCache(cache().stores, const [NearbyItem('Bread', usualStoreId: 'g')], now);
    expect(at('g', c: c)!.title, 'Near Goisco: 1 item on your list you usually buy here');
  });

  test('off, muted, unknown store, old list', () {
    expect(at('m', s: const NearbySettings()), isNull);
    expect(at('m', s: on.copyWith(mutedStores: {'m'})), isNull);
    expect(at('x'), isNull);
    expect(at('m', c: cache(savedAt: now.subtract(const Duration(days: 8)))), isNull);
    expect(decide(storeId: 'm', now: now, cache: null, settings: on, lastNotified: {}), isNull);
  });

  test('quiet hours, also across midnight', () {
    expect(at('m', time: DateTime(2026, 10, 2, 22, 0)), isNull);
    expect(at('m', time: DateTime(2026, 10, 3, 7, 59)), isNull);
    expect(at('m', time: DateTime(2026, 10, 3, 8, 0)), isNotNull);
    final day = on.copyWith(quietFrom: 12 * 60, quietTo: 14 * 60);
    expect(at('m', s: day, time: DateTime(2026, 10, 2, 13, 0)), isNull);
    expect(at('m', s: day, time: DateTime(2026, 10, 2, 22, 0)), isNotNull);
    expect(inQuietHours(now, on.copyWith(quietFrom: 0, quietTo: 0)), isFalse);
  });

  test('at most once per store every N hours', () {
    expect(at('m', last: {'m': now.subtract(const Duration(hours: 5))}), isNull);
    expect(at('m', last: {'m': now.subtract(const Duration(hours: 6))}), isNotNull);
    expect(at('c', last: {'m': now}), isNotNull); // another store is fine
  });

  test('which stores get a fence', () {
    expect(fenceStores(cache(), const NearbySettings()), isEmpty);
    final ids = fenceStores(cache(), on.copyWith(mutedStores: {'c'})).map((s) => s.id).toList();
    expect(ids, ['m', 'g']); // most useful first, muted left out
  });

  test('settings and cache survive a round trip', () {
    final s = NearbySettings.fromJson(on.copyWith(mutedStores: {'g'}, radiusMeters: 250).toJson());
    expect((s.enabled, s.radiusMeters, s.everyHours), (true, 250, 6));
    expect(s.mutedStores, {'g'});
    final c = NearbyCache.fromJson(cache().toJson());
    expect(c.items.first.cheapestStoreId, 'm');
    expect(c.stores.length, 3);
  });

  test('from the server: stores without a pin are left out', () {
    final c = NearbyCache.fromServer(
      [(id: 'm', name: 'Mangusa', lat: 12.1, lon: -68.9), (id: 'z', name: 'Nowhere', lat: null, lon: null)],
      [
        {'name': 'Coffee', 'cheapest_store_id': 'm', 'usual_store_id': null},
      ],
      now,
    );
    expect(c.stores.map((s) => s.id), ['m']);
    expect(c.items.single.cheapestStoreId, 'm');
  });
}
