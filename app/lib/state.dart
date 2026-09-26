import 'package:flutter/foundation.dart';

import 'api.dart';
import 'models.dart';

/// App-wide state: who's signed in, which household is active, and the
/// household's reference data (locations, stores) that most screens need.
class AppState extends ChangeNotifier {
  final Api api = Api();
  bool ready = false;
  List<Household> households = [];
  Household? household;
  List<Location> locations = [];
  List<Store> stores = [];

  /// Bumped whenever stock or the shopping list changes, so open screens reload.
  int revision = 0;

  String get hid => household!.id;

  Future<void> start() async {
    // The web app is served by the Kasita server itself, so its own origin is the server.
    await api.load(sameOriginServer: kIsWeb ? Uri.base.origin : null);
    api.onSignedOut = () {
      household = null;
      notifyListeners();
    };
    if (api.signedIn) {
      try {
        await loadHouseholds();
      } catch (_) {
        // offline or signed out: the sign-in screen shows
      }
    }
    ready = true;
    notifyListeners();
  }

  Future<void> loadHouseholds() async {
    households = await api.households();
    if (households.isNotEmpty) {
      final keep = households.where((h) => h.id == household?.id);
      await selectHousehold(keep.isNotEmpty ? keep.first : households.first);
    } else {
      household = null;
      notifyListeners();
    }
  }

  Future<void> selectHousehold(Household h) async {
    household = h;
    locations = await api.locations(h.id);
    stores = await api.stores(h.id);
    revision++;
    notifyListeners();
  }

  Future<void> reloadStores() async {
    stores = await api.stores(hid);
    notifyListeners();
  }

  void changed() {
    revision++;
    notifyListeners();
  }

  Future<void> signOut() async {
    await api.logout();
    households = [];
    household = null;
    notifyListeners();
  }

  String locationName(String? id) =>
      locations.where((l) => l.id == id).map((l) => l.name).firstOrNull ?? '';
  String storeName(String? id) => stores.where((s) => s.id == id).map((s) => s.name).firstOrNull ?? '';
}
