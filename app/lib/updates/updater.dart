import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'update_logic.dart';

/// In-app updates for the Android app (the web app updates itself): asks GitHub for the latest
/// release, downloads `kasita-N.apk` into the app's cache and hands it to Android's installer.
bool get updatesSupported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

final updater = Updater();

const _latestUrl = 'https://api.github.com/repos/jazzprox/kasita/releases/latest';
const _channel = MethodChannel('kasita/updates');

// remembered in shared_preferences
const _kAuto = 'updates.auto', _kLastCheck = 'updates.last_check', _kLatest = 'updates.latest';
const _kSnoozeBuild = 'updates.snooze_build', _kSnoozeUntil = 'updates.snooze_until';
const _kExplained = 'updates.install_explained';

class DownloadCancelled implements Exception {}

class Updater extends ChangeNotifier {
  bool _started = false;
  int? current; // own build number
  ReleaseInfo? latest;
  bool auto = true;
  bool checking = false;
  bool checkFailed = false;
  DateTime? _lastCheck;
  int? _snoozeBuild;
  DateTime? _snoozeUntil;

  /// 0..1 while downloading, null otherwise.
  double? progress;
  http.Client? _download;
  bool _cancelled = false;

  bool get available => latest != null && isNewer(latest!.build, current);

  /// The home-screen card: newer and not snoozed.
  bool get offer => shouldOffer(
    latest: latest,
    current: current,
    now: DateTime.now(),
    snoozedBuild: _snoozeBuild,
    snoozedUntil: _snoozeUntil,
  );

  /// On app start: own build, remembered state, then a check if it's been 6 hours.
  Future<void> start() async {
    if (!updatesSupported || _started) return;
    _started = true;
    try {
      current = parseOwnBuild((await PackageInfo.fromPlatform()).buildNumber);
      final p = await SharedPreferences.getInstance();
      auto = p.getBool(_kAuto) ?? true;
      _lastCheck = DateTime.tryParse(p.getString(_kLastCheck) ?? '');
      _snoozeBuild = p.getInt(_kSnoozeBuild);
      _snoozeUntil = DateTime.tryParse(p.getString(_kSnoozeUntil) ?? '');
      final cached = p.getString(_kLatest);
      if (cached != null) latest = ReleaseInfo.fromJson(jsonDecode(cached) as Map<String, dynamic>);
    } catch (_) {}
    notifyListeners();
    unawaited(_tidy());
    await maybeCheck();
  }

  /// After an update the installed APK only takes space in the cache (~80 MB).
  Future<void> _tidy() async {
    if (available) return;
    try {
      final dir = Directory((await _channel.invokeMethod<String>('apkDir'))!);
      for (final f in dir.listSync().whereType<File>()) {
        f.deleteSync();
      }
    } catch (_) {}
  }

  /// On start and on resume: at most once every 6 hours, and only when switched on.
  Future<void> maybeCheck() async {
    if (!_started || checking) return;
    if (shouldAutoCheck(now: DateTime.now(), lastCheck: _lastCheck, auto: auto)) await check();
  }

  /// Asks GitHub now. False when that failed (offline, rate limit...).
  Future<bool> check() async {
    if (!updatesSupported || checking) return !checkFailed;
    checking = true;
    notifyListeners();
    try {
      final r = await http
          .get(
            Uri.parse(_latestUrl),
            headers: {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
          )
          .timeout(const Duration(seconds: 20));
      if (r.statusCode != 200) throw HttpException('GitHub said ${r.statusCode}');
      final info = ReleaseInfo.fromGitHub(jsonDecode(r.body) as Map<String, dynamic>);
      if (info != null) latest = info;
      _lastCheck = DateTime.now();
      checkFailed = false;
      final p = await SharedPreferences.getInstance();
      await p.setString(_kLastCheck, _lastCheck!.toIso8601String());
      if (info != null) await p.setString(_kLatest, jsonEncode(info.toJson()));
    } catch (_) {
      checkFailed = true;
    } finally {
      checking = false;
      notifyListeners();
    }
    return !checkFailed;
  }

  Future<void> setAuto(bool on) async {
    auto = on;
    notifyListeners();
    try {
      await (await SharedPreferences.getInstance()).setBool(_kAuto, on);
    } catch (_) {}
    if (on) await maybeCheck();
  }

  /// "Not now": hide this build's card for 24 hours.
  Future<void> snooze() async {
    if (latest == null) return;
    _snoozeBuild = latest!.build;
    _snoozeUntil = DateTime.now().add(snoozeFor);
    notifyListeners();
    try {
      final p = await SharedPreferences.getInstance();
      await p.setInt(_kSnoozeBuild, _snoozeBuild!);
      await p.setString(_kSnoozeUntil, _snoozeUntil!.toIso8601String());
    } catch (_) {}
  }

  /// Downloads the APK (or reuses a complete earlier download) and returns its path.
  /// Throws [DownloadCancelled] after [cancel].
  Future<String> download() async {
    final rel = latest!;
    final dir = Directory((await _channel.invokeMethod<String>('apkDir'))!);
    final file = File('${dir.path}/kasita-${rel.build}.apk');
    // old downloads (an earlier build, half files) only take space
    for (final f in dir.listSync().whereType<File>()) {
      if (f.path != file.path) {
        try {
          f.deleteSync();
        } catch (_) {}
      }
    }
    if (file.existsSync() && sizeMatches(file.lengthSync(), rel.apkSize)) return file.path;

    final part = File('${file.path}.part');
    final client = http.Client();
    _download = client;
    _cancelled = false;
    progress = 0;
    notifyListeners();
    IOSink? sink;
    try {
      final res = await client.send(http.Request('GET', Uri.parse(rel.apkUrl)));
      if (res.statusCode != 200) throw HttpException('Download failed (${res.statusCode})');
      sink = part.openWrite();
      var got = 0;
      await for (final chunk in res.stream) {
        if (_cancelled) throw DownloadCancelled();
        sink.add(chunk);
        got += chunk.length;
        final p = (got / rel.apkSize).clamp(0.0, 1.0);
        if (p - (progress ?? 0) >= 0.01 || p == 1) {
          progress = p;
          notifyListeners();
        }
      }
      await sink.close();
      sink = null;
      if (_cancelled) throw DownloadCancelled();
      if (!sizeMatches(part.lengthSync(), rel.apkSize)) {
        throw const FileSystemException('The download is incomplete. Try again.');
      }
      part.renameSync(file.path);
      return file.path;
    } catch (e) {
      try {
        await sink?.close();
      } catch (_) {}
      try {
        if (part.existsSync()) part.deleteSync();
      } catch (_) {}
      // closing the client mid-download surfaces as a ClientException
      if (_cancelled) throw DownloadCancelled();
      rethrow;
    } finally {
      client.close();
      _download = null;
      progress = null;
      notifyListeners();
    }
  }

  void cancel() {
    _cancelled = true;
    _download?.close(); // aborts the request
  }

  bool get downloading => progress != null;

  Future<bool> canInstall() async => await _channel.invokeMethod<bool>('canInstall') ?? false;

  Future<bool> openInstallSettings() async => await _channel.invokeMethod<bool>('openInstallSettings') ?? false;

  Future<void> install(String path) => _channel.invokeMethod('install', {'path': path});

  /// Explain "Install unknown apps" only the first time.
  Future<bool> explainedInstall() async {
    try {
      final p = await SharedPreferences.getInstance();
      final was = p.getBool(_kExplained) ?? false;
      if (!was) await p.setBool(_kExplained, true);
      return was;
    } catch (_) {
      return false;
    }
  }
}
