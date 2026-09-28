import 'package:shared_preferences/shared_preferences.dart';

/// Small remembered choices (sort orders...). Never fails: a missing or broken store gives the default.
Future<String> loadPref(String key, String fallback) async {
  try {
    return (await SharedPreferences.getInstance()).getString(key) ?? fallback;
  } catch (_) {
    return fallback;
  }
}

Future<void> savePref(String key, String value) async {
  try {
    await (await SharedPreferences.getInstance()).setString(key, value);
  } catch (_) {}
}
