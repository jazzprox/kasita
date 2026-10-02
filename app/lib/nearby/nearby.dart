// "You're near <store>" reminders. Android only: on the web (and anywhere else) every call is a
// no-op and [nearbySupported] is false, so the screens simply hide the feature.
export 'nearby_logic.dart';
export 'nearby_stub.dart' if (dart.library.io) 'nearby_android.dart';
