// Android: OS geofences (native_geofence, low battery: the phone's location service watches
// the fences, Kasita is only woken when one is entered) and a local notification.
import 'dart:convert';
import 'dart:io';
import 'dart:ui';

import 'package:flutter/widgets.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:home_widget/home_widget.dart';
import 'package:http/http.dart' as http;
import 'package:native_geofence/native_geofence.dart' as ng;
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api.dart';
import '../models.dart';
import 'nearby_logic.dart';

bool get nearbySupported => Platform.isAndroid;

const _kSettings = 'nearby.settings';
const _kCache = 'nearby.cache';
const _kLast = 'nearby.last';
const _fencePrefix = 'kasita-store-';

// SharedPreferencesAsync has no in-memory cache, so the app and the background
// geofence isolate always see each other's writes.
final _prefs = SharedPreferencesAsync();

Future<Map<String, dynamic>?> _readJson(String key) async {
  try {
    final s = await _prefs.getString(key);
    return s == null ? null : Map<String, dynamic>.from(jsonDecode(s));
  } catch (_) {
    return null;
  }
}

Future<void> _writeJson(String key, Object value) async {
  try {
    await _prefs.setString(key, jsonEncode(value));
  } catch (_) {}
}

Future<NearbySettings> loadNearbySettings() async {
  final j = await _readJson(_kSettings);
  return j == null ? const NearbySettings() : NearbySettings.fromJson(j);
}

Future<NearbyCache?> _loadCache() async {
  final j = await _readJson(_kCache);
  return j == null ? null : NearbyCache.fromJson(j);
}

/// Ask for what the reminders need: notifications, location, and location "all the time"
/// (Android only wakes an app for a geofence with background location). Null = all granted,
/// else what is missing, in plain words.
Future<String?> enableNearby() async {
  if (!nearbySupported) return 'Only available in the Android app';
  await Permission.notification.request();
  final fine = await Permission.locationWhenInUse.request();
  if (!fine.isGranted) return 'Kasita needs location permission to know when you are near a store.';
  final always = await Permission.locationAlways.request();
  if (!always.isGranted) {
    return 'Choose "Allow all the time" for Kasita\'s location in Android settings: without it, '
        'Android does not tell Kasita when you reach a store.';
  }
  if (!await Permission.notification.isGranted) {
    return 'Notifications are off for Kasita, so the reminders cannot show.';
  }
  return null;
}

Future<void> saveNearbySettings(NearbySettings settings) async {
  await _writeJson(_kSettings, settings.toJson());
  await _syncFences(settings, await _loadCache());
}

/// Save what the phone needs when a fence fires (stores with a pin, the open list and where each
/// item is cheapest / usually bought), then put the fences in place. Call whenever the app has
/// a fresh shopping list. Does nothing unless the reminders are on.
Future<void> refreshNearby(Api api, String hid, List<Store> stores, {List<Map<String, dynamic>>? prices}) async {
  if (!nearbySupported) return;
  final settings = await loadNearbySettings();
  if (!settings.enabled) return;
  try {
    prices ??= [
      for (final x in await api.get('/api/households/$hid/shopping/prices') as List) Map<String, dynamic>.from(x),
    ];
  } catch (_) {
    return; // offline: keep the last cache
  }
  final cache = NearbyCache.fromServer(
    [for (final s in stores) (id: s.id, name: s.name, lat: s.lat, lon: s.lon)],
    prices,
    DateTime.now(),
  );
  await _writeJson(_kCache, cache.toJson());
  await _syncFences(settings, cache);
}

Future<void> disableNearby() async {
  final settings = await loadNearbySettings();
  await _writeJson(_kSettings, settings.copyWith(enabled: false).toJson());
  try {
    await ng.NativeGeofenceManager.instance.initialize();
    await ng.NativeGeofenceManager.instance.removeAllGeofences();
  } catch (_) {}
}

Future<void> _syncFences(NearbySettings settings, NearbyCache? cache) async {
  if (!nearbySupported) return;
  try {
    final m = ng.NativeGeofenceManager.instance;
    await m.initialize();
    final want = {
      for (final s in cache == null ? const <NearbyStore>[] : fenceStores(cache, settings)) '$_fencePrefix${s.id}': s,
    };
    final have = await m.getRegisteredGeofences();
    for (final f in have) {
      final w = want[f.id];
      final same =
          w != null &&
          f.radiusMeters == settings.radiusMeters.toDouble() &&
          (f.location.latitude - w.lat).abs() < 1e-6 &&
          (f.location.longitude - w.lon).abs() < 1e-6;
      if (same) {
        want.remove(f.id);
      } else if (f.id.startsWith(_fencePrefix)) {
        await m.removeGeofenceById(f.id);
      }
    }
    if (want.isNotEmpty && !await Permission.locationAlways.isGranted) return;
    for (final e in want.entries) {
      await m.createGeofence(
        ng.Geofence(
          id: e.key,
          location: ng.Location(latitude: e.value.lat, longitude: e.value.lon),
          radiusMeters: settings.radiusMeters.toDouble(),
          triggers: {ng.GeofenceEvent.enter},
          iosSettings: const ng.IosGeofenceSettings(initialTrigger: false),
          androidSettings: const ng.AndroidGeofenceSettings(
            initialTriggers: {},
            // a few minutes late is fine, and much kinder to the battery
            notificationResponsiveness: Duration(minutes: 2),
          ),
        ),
        nearbyFenceEntered,
      );
    }
  } catch (e) {
    debugPrint('nearby: could not set geofences: $e');
  }
}

/// A fresh list straight from the server, with the home-screen widget's read-only key (no sign-in
/// needed, never changes anything). Short timeout: the phone gives a geofence callback little time.
Future<NearbyCache?> _fetchFresh() async {
  try {
    final key = await HomeWidget.getWidgetData<String>('kasita_key');
    final server = await HomeWidget.getWidgetData<String>('kasita_server');
    final hid = await HomeWidget.getWidgetData<String>('kasita_hid');
    if (key == null || key.isEmpty || server == null || hid == null) return null;
    final base = '${server.replaceAll(RegExp(r'/+$'), '')}/api/households/$hid';
    Future<List> get(String path) async {
      final r = await http
          .get(Uri.parse('$base$path'), headers: {'X-Api-Key': key})
          .timeout(const Duration(seconds: 8));
      if (r.statusCode != 200) throw Exception('HTTP ${r.statusCode}');
      return jsonDecode(utf8.decode(r.bodyBytes)) as List;
    }

    final results = await Future.wait([get('/stores'), get('/shopping/prices')]);
    final stores = [for (final s in results[0]) Store.fromJson(Map<String, dynamic>.from(s))];
    return NearbyCache.fromServer(
      [for (final s in stores) (id: s.id, name: s.name, lat: s.lat, lon: s.lon)],
      [for (final p in results[1]) Map<String, dynamic>.from(p)],
      DateTime.now(),
    );
  } catch (_) {
    return null;
  }
}

/// Android woke Kasita: the phone entered the fence around one or more stores.
@pragma('vm:entry-point')
Future<void> nearbyFenceEntered(ng.GeofenceCallbackParams params) async {
  WidgetsFlutterBinding.ensureInitialized();
  DartPluginRegistrant.ensureInitialized();
  if (params.event != ng.GeofenceEvent.enter) return;
  final settings = await loadNearbySettings();
  if (!settings.enabled) return;
  var cache = await _fetchFresh();
  if (cache != null) {
    await _writeJson(_kCache, cache.toJson());
  } else {
    cache = await _loadCache();
  }
  final lastJson = await _readJson(_kLast) ?? {};
  final last = <String, DateTime>{
    for (final e in lastJson.entries)
      if (DateTime.tryParse('${e.value}') != null) e.key: DateTime.parse('${e.value}'),
  };
  final now = DateTime.now();
  final notes = <NearbyNotice>[];
  for (final f in params.geofences) {
    if (!f.id.startsWith(_fencePrefix)) continue;
    final notice = decide(
      storeId: f.id.substring(_fencePrefix.length),
      now: now,
      cache: cache,
      settings: settings,
      lastNotified: last,
    );
    if (notice != null) notes.add(notice);
  }
  if (notes.isEmpty) return;
  final plugin = FlutterLocalNotificationsPlugin();
  await plugin.initialize(
    settings: const InitializationSettings(android: AndroidInitializationSettings('@mipmap/ic_launcher')),
  );
  for (final n in notes) {
    await plugin.show(
      id: n.storeId.hashCode & 0x7fffffff,
      title: n.title,
      body: n.body,
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails(
          'nearby',
          'Near a store',
          channelDescription: 'When you are near a store where items on your list are cheapest',
        ),
      ),
    );
    last[n.storeId] = now;
  }
  await _writeJson(_kLast, {for (final e in last.entries) e.key: e.value.toIso8601String()});
}
