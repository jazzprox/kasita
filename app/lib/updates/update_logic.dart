// In-app updates, the decisions only (pure Dart, unit tested): which build a GitHub release is,
// whether it is newer, when to ask GitHub again, and whether "Not now" still holds.
//
// CI tags every Android release `android-NNNN` (zero-padded) with one asset `kasita-N.apk`, and
// builds that APK with `--build-number=<run number>`, the same N. So the tag number is the
// versionCode of the APK inside, and the app compares it with its own build number.

/// How often the app asks GitHub by itself (anonymous API: 60 requests an hour per IP).
const checkEvery = Duration(hours: 6);

/// How long "Not now" hides one build.
const snoozeFor = Duration(hours: 24);

final _tagRe = RegExp(r'^android-0*(\d+)$');
final _assetRe = RegExp(r'^kasita-0*(\d+)\.apk$');

/// `android-0034` -> 34. Null for anything else.
int? buildFromTag(String tag) {
  final m = _tagRe.firstMatch(tag.trim());
  return m == null ? null : int.tryParse(m.group(1)!);
}

/// `kasita-34.apk` -> 34. Null for anything else.
int? buildFromAssetName(String name) {
  final m = _assetRe.firstMatch(name.trim());
  return m == null ? null : int.tryParse(m.group(1)!);
}

/// The latest Android release: its build number and the APK to download.
class ReleaseInfo {
  final int build;
  final String tag;
  final String notes; // release body, Markdown
  final String apkUrl;
  final int apkSize; // bytes, as GitHub reports it; the download must match
  final String apkName;

  const ReleaseInfo({
    required this.build,
    required this.tag,
    required this.notes,
    required this.apkUrl,
    required this.apkSize,
    required this.apkName,
  });

  /// From GitHub's `releases/latest` JSON. Null when it isn't a usable Android release (other tag,
  /// draft, no `kasita-N.apk` asset, or tag and asset disagree about N).
  static ReleaseInfo? fromGitHub(Map<String, dynamic> json) {
    if (json['draft'] == true || json['prerelease'] == true) return null;
    final tag = json['tag_name'];
    if (tag is! String) return null;
    final fromTag = buildFromTag(tag);
    final assets = json['assets'];
    if (assets is! List) return null;
    for (final a in assets) {
      if (a is! Map) continue;
      final name = a['name'], url = a['browser_download_url'], size = a['size'];
      if (name is! String || url is! String || size is! int || size <= 0) continue;
      final fromAsset = buildFromAssetName(name);
      if (fromAsset == null) continue;
      // the tag is the source of truth; an asset with another number is not this build
      if (fromTag != null && fromAsset != fromTag) continue;
      if (!url.startsWith('https://')) continue;
      return ReleaseInfo(
        build: fromAsset,
        tag: tag,
        notes: json['body'] is String ? json['body'] as String : '',
        apkUrl: url,
        apkSize: size,
        apkName: name,
      );
    }
    return null;
  }

  Map<String, dynamic> toJson() => {
    'build': build,
    'tag': tag,
    'notes': notes,
    'apkUrl': apkUrl,
    'apkSize': apkSize,
    'apkName': apkName,
  };

  static ReleaseInfo? fromJson(Map<String, dynamic> j) {
    try {
      return ReleaseInfo(
        build: j['build'] as int,
        tag: j['tag'] as String,
        notes: j['notes'] as String,
        apkUrl: j['apkUrl'] as String,
        apkSize: j['apkSize'] as int,
        apkName: j['apkName'] as String,
      );
    } catch (_) {
      return null;
    }
  }
}

/// The app's own build number from package_info (`"34"`). Null when unknown (then never offer).
int? parseOwnBuild(String buildNumber) {
  final n = int.tryParse(buildNumber.trim());
  return n == null || n <= 0 ? null : n;
}

bool isNewer(int latest, int? current) => current != null && latest > current;

/// Time for an automatic check? Also when the clock was moved back (last check "in the future").
bool shouldAutoCheck({required DateTime now, required DateTime? lastCheck, required bool auto}) {
  if (!auto) return false;
  if (lastCheck == null) return true;
  if (lastCheck.isAfter(now)) return true;
  return now.difference(lastCheck) >= checkEvery;
}

/// Show the "Update available" card? Not while that build is snoozed ("Not now" for 24 h).
/// A newer build than the snoozed one shows straight away.
bool shouldOffer({
  required ReleaseInfo? latest,
  required int? current,
  required DateTime now,
  int? snoozedBuild,
  DateTime? snoozedUntil,
}) {
  if (latest == null || !isNewer(latest.build, current)) return false;
  if (snoozedBuild != null && snoozedUntil != null && latest.build <= snoozedBuild && now.isBefore(snoozedUntil)) {
    return false;
  }
  return true;
}

/// The downloaded file is complete when its size is exactly what GitHub said.
bool sizeMatches(int actual, int expected) => expected > 0 && actual == expected;

/// The short "What's new" for the card: the bullet titles of the release notes (before the
/// `<details>` part), without Markdown. Falls back to the first plain lines.
List<String> shortNotes(String body, {int max = 5}) {
  final head = body.split('<details>').first;
  String clean(String l) => l
      .replaceFirst(RegExp(r'^\s*[-*]\s+'), '')
      .replaceAll(RegExp(r'\*\*|__|`'), '')
      .replaceAllMapped(RegExp(r'\[([^\]]*)\]\([^)]*\)'), (m) => m[1]!)
      .trim();
  final lines = head.split('\n');
  final bullets = [
    for (final l in lines)
      if (RegExp(r'^\s*[-*]\s+').hasMatch(l)) clean(l),
  ].where((l) => l.isNotEmpty).toList();
  final picked = bullets.isNotEmpty
      ? bullets
      : [
          for (final l in lines)
            if (l.trim().isNotEmpty && !l.trimLeft().startsWith('#') && !l.startsWith('Changes since')) clean(l),
        ].where((l) => l.isNotEmpty).toList();
  if (picked.length <= max) return picked;
  return [...picked.take(max - 1), 'and ${picked.length - max + 1} more'];
}
