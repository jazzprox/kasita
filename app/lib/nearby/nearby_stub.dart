// Web build: no geofences, no notifications. Same functions as nearby_android.dart.
import '../api.dart';
import '../models.dart';
import 'nearby_logic.dart';

bool get nearbySupported => false;

Future<NearbySettings> loadNearbySettings() async => const NearbySettings();

Future<String?> enableNearby() async => 'Only available in the Android app';

Future<void> saveNearbySettings(NearbySettings settings) async {}

Future<void> refreshNearby(Api api, String hid, List<Store> stores, {List<Map<String, dynamic>>? prices}) async {}

Future<void> disableNearby() async {}
