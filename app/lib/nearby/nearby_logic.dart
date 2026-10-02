// "You're near <store>": which stores to watch, and whether to say something when the phone
// gets near one. Plain Dart (no Flutter, no plugins) so it can be unit tested; the Android
// glue in nearby_android.dart feeds it.

/// The user's choices. Off until they switch it on.
class NearbySettings {
  final bool enabled;
  final int radiusMeters;
  final int quietFrom, quietTo; // minutes after midnight; equal = no quiet hours
  final int everyHours; // at most one note per store per this many hours
  final Set<String> mutedStores; // store ids the user opted out of

  const NearbySettings({
    this.enabled = false,
    this.radiusMeters = 150,
    this.quietFrom = 21 * 60,
    this.quietTo = 8 * 60,
    this.everyHours = 6,
    this.mutedStores = const {},
  });

  NearbySettings copyWith({
    bool? enabled,
    int? radiusMeters,
    int? quietFrom,
    int? quietTo,
    int? everyHours,
    Set<String>? mutedStores,
  }) => NearbySettings(
    enabled: enabled ?? this.enabled,
    radiusMeters: radiusMeters ?? this.radiusMeters,
    quietFrom: quietFrom ?? this.quietFrom,
    quietTo: quietTo ?? this.quietTo,
    everyHours: everyHours ?? this.everyHours,
    mutedStores: mutedStores ?? this.mutedStores,
  );

  Map<String, dynamic> toJson() => {
    'enabled': enabled,
    'radius': radiusMeters,
    'quiet_from': quietFrom,
    'quiet_to': quietTo,
    'every_hours': everyHours,
    'muted': mutedStores.toList(),
  };

  factory NearbySettings.fromJson(Map<String, dynamic> j) => NearbySettings(
    enabled: j['enabled'] == true,
    radiusMeters: (j['radius'] as num?)?.toInt() ?? 150,
    quietFrom: (j['quiet_from'] as num?)?.toInt() ?? 21 * 60,
    quietTo: (j['quiet_to'] as num?)?.toInt() ?? 8 * 60,
    everyHours: (j['every_hours'] as num?)?.toInt() ?? 6,
    mutedStores: {...((j['muted'] as List?) ?? const []).map((e) => '$e')},
  );
}

class NearbyStore {
  final String id, name;
  final double lat, lon;
  const NearbyStore(this.id, this.name, this.lat, this.lon);
  Map<String, dynamic> toJson() => {'id': id, 'name': name, 'lat': lat, 'lon': lon};
  factory NearbyStore.fromJson(Map<String, dynamic> j) =>
      NearbyStore('${j['id']}', '${j['name']}', (j['lat'] as num).toDouble(), (j['lon'] as num).toDouble());
}

/// One open shopping-list item and where it fits.
class NearbyItem {
  final String name;
  final String? cheapestStoreId, usualStoreId;
  const NearbyItem(this.name, {this.cheapestStoreId, this.usualStoreId});
  Map<String, dynamic> toJson() => {'name': name, 'cheapest': cheapestStoreId, 'usual': usualStoreId};
  factory NearbyItem.fromJson(Map<String, dynamic> j) =>
      NearbyItem('${j['name']}', cheapestStoreId: j['cheapest'] as String?, usualStoreId: j['usual'] as String?);
}

/// What the phone last knew: the located stores and the open list with its best stores.
/// Saved whenever the app sees the list, used when a geofence fires in the background.
class NearbyCache {
  final List<NearbyStore> stores;
  final List<NearbyItem> items;
  final DateTime savedAt;
  const NearbyCache(this.stores, this.items, this.savedAt);

  Map<String, dynamic> toJson() => {
    'stores': [for (final s in stores) s.toJson()],
    'items': [for (final i in items) i.toJson()],
    'saved_at': savedAt.toIso8601String(),
  };
  factory NearbyCache.fromJson(Map<String, dynamic> j) => NearbyCache(
    [for (final s in (j['stores'] as List? ?? const [])) NearbyStore.fromJson(Map<String, dynamic>.from(s))],
    [for (final i in (j['items'] as List? ?? const [])) NearbyItem.fromJson(Map<String, dynamic>.from(i))],
    DateTime.tryParse('${j['saved_at']}') ?? DateTime.fromMillisecondsSinceEpoch(0),
  );

  /// From the server: the household's stores and GET /shopping/prices.
  factory NearbyCache.fromServer(
    List<({String id, String name, double? lat, double? lon})> stores,
    List<Map<String, dynamic>> prices,
    DateTime now,
  ) => NearbyCache(
    [
      for (final s in stores)
        if (s.lat != null && s.lon != null) NearbyStore(s.id, s.name, s.lat!, s.lon!),
    ],
    [
      for (final p in prices)
        NearbyItem(
          '${p['name']}',
          cheapestStoreId: p['cheapest_store_id'] as String?,
          usualStoreId: p['usual_store_id'] as String?,
        ),
    ],
    now,
  );
}

/// Android lets an app watch at most 100 geofences.
const maxFences = 90;

/// A list older than this is not worth a notification: it is probably out of date.
const cacheMaxAge = Duration(days: 7);

/// The stores to put a geofence around: located, not muted, at most [maxFences].
List<NearbyStore> fenceStores(NearbyCache cache, NearbySettings settings) {
  if (!settings.enabled) return const [];
  final out = [
    for (final s in cache.stores)
      if (!settings.mutedStores.contains(s.id)) s,
  ];
  // stores with something on the list first, so the cap drops the least useful ones
  int useful(NearbyStore s) => cache.items.where((i) => i.cheapestStoreId == s.id || i.usualStoreId == s.id).length;
  out.sort((a, b) => useful(b).compareTo(useful(a)));
  return out.take(maxFences).toList();
}

bool inQuietHours(DateTime now, NearbySettings s) {
  if (s.quietFrom == s.quietTo) return false;
  final m = now.hour * 60 + now.minute;
  return s.quietFrom < s.quietTo ? (m >= s.quietFrom && m < s.quietTo) : (m >= s.quietFrom || m < s.quietTo);
}

class NearbyNotice {
  final String storeId, title, body;
  const NearbyNotice(this.storeId, this.title, this.body);
  @override
  String toString() => '$title: $body';
}

String _items(int n) => n == 1 ? '1 item' : '$n items';

/// Entered the fence around [storeId]: say something, or null (and why not, for testing).
NearbyNotice? decide({
  required String storeId,
  required DateTime now,
  required NearbyCache? cache,
  required NearbySettings settings,
  required Map<String, DateTime> lastNotified,
}) {
  if (!settings.enabled || cache == null || settings.mutedStores.contains(storeId)) return null;
  if (now.difference(cache.savedAt) > cacheMaxAge) return null;
  if (inQuietHours(now, settings)) return null;
  final last = lastNotified[storeId];
  if (last != null && now.difference(last) < Duration(hours: settings.everyHours)) return null;
  final store = cache.stores.where((s) => s.id == storeId).firstOrNull;
  if (store == null) return null;
  final cheapest = cache.items.where((i) => i.cheapestStoreId == storeId).toList();
  final usual = cache.items.where((i) => i.cheapestStoreId != storeId && i.usualStoreId == storeId).toList();
  final all = [...cheapest, ...usual];
  if (all.isEmpty) return null;
  final String title;
  if (usual.isEmpty) {
    title = cheapest.length == 1
        ? 'Near ${store.name}: 1 item on your list is cheapest here'
        : 'Near ${store.name}: ${cheapest.length} items on your list are cheapest here';
  } else if (cheapest.isEmpty) {
    title = 'Near ${store.name}: ${_items(usual.length)} on your list you usually buy here';
  } else {
    title = 'Near ${store.name}: ${_items(all.length)} on your list, ${cheapest.length} cheapest here';
  }
  final names = all.map((i) => i.name).toList();
  final body = names.length <= 6 ? names.join(', ') : '${names.take(5).join(', ')} and ${names.length - 5} more';
  return NearbyNotice(storeId, title, body);
}
