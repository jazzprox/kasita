import 'package:flutter_test/flutter_test.dart';
import 'package:kasita/updates/update_logic.dart';

final now = DateTime(2026, 10, 2, 17, 30);

Map<String, dynamic> release({
  String tag = 'android-0035',
  List<Map<String, dynamic>>? assets,
  String body = "## What's new\n\n- **Fix**\n",
}) => {
  'tag_name': tag,
  'draft': false,
  'prerelease': false,
  'body': body,
  'assets':
      assets ??
      [
        {
          'name': 'kasita-35.apk',
          'size': 77330311,
          'browser_download_url': 'https://github.com/jazzprox/kasita/releases/download/android-0035/kasita-35.apk',
        },
      ],
};

ReleaseInfo info(int build) => ReleaseInfo(
  build: build,
  tag: 'android-$build',
  notes: '',
  apkUrl: 'https://x/kasita-$build.apk',
  apkSize: 1,
  apkName: 'kasita-$build.apk',
);

void main() {
  test('tag and asset names give the build number', () {
    expect(buildFromTag('android-0034'), 34);
    expect(buildFromTag('android-9'), 9);
    expect(buildFromTag('android-1234'), 1234);
    expect(buildFromTag('android-12345'), 12345);
    expect(buildFromTag('v1.0'), isNull);
    expect(buildFromTag('android-'), isNull);
    expect(buildFromTag('android-0034-rc'), isNull);
    expect(buildFromAssetName('kasita-34.apk'), 34);
    expect(buildFromAssetName('kasita-0034.apk'), 34);
    expect(buildFromAssetName('kasita-34.apk.sha256'), isNull);
    expect(buildFromAssetName('app-release.apk'), isNull);
  });

  test('a GitHub release becomes ReleaseInfo', () {
    final r = ReleaseInfo.fromGitHub(release())!;
    expect(r.build, 35);
    expect(r.tag, 'android-0035');
    expect(r.apkSize, 77330311);
    expect(r.apkName, 'kasita-35.apk');
    expect(r.apkUrl, endsWith('/kasita-35.apk'));
    expect(ReleaseInfo.fromJson(r.toJson())!.toJson(), r.toJson());
  });

  test('unusable releases are ignored', () {
    expect(ReleaseInfo.fromGitHub({...release(), 'draft': true}), isNull);
    expect(ReleaseInfo.fromGitHub({...release(), 'prerelease': true}), isNull);
    expect(ReleaseInfo.fromGitHub(release(assets: [])), isNull);
    // tag and asset disagree
    expect(ReleaseInfo.fromGitHub(release(tag: 'android-0036')), isNull);
    // no size, or not https
    expect(
      ReleaseInfo.fromGitHub(
        release(
          assets: [
            {'name': 'kasita-35.apk', 'size': 0, 'browser_download_url': 'https://x/kasita-35.apk'},
            {'name': 'kasita-35.apk', 'size': 5, 'browser_download_url': 'http://x/kasita-35.apk'},
          ],
        ),
      ),
      isNull,
    );
    expect(ReleaseInfo.fromGitHub({'message': 'API rate limit exceeded'}), isNull);
  });

  test('the matching asset is picked among others', () {
    final r = ReleaseInfo.fromGitHub(
      release(
        assets: [
          {'name': 'notes.txt', 'size': 10, 'browser_download_url': 'https://x/notes.txt'},
          {'name': 'kasita-35.apk', 'size': 10, 'browser_download_url': 'https://x/kasita-35.apk'},
        ],
      ),
    )!;
    expect(r.apkName, 'kasita-35.apk');
  });

  test('a release without an android tag falls back to the asset number', () {
    expect(ReleaseInfo.fromGitHub(release(tag: 'something'))!.build, 35);
  });

  test('own build number', () {
    expect(parseOwnBuild('34'), 34);
    expect(parseOwnBuild(''), isNull);
    expect(parseOwnBuild('0'), isNull);
    expect(parseOwnBuild('abc'), isNull);
  });

  test('newer', () {
    expect(isNewer(35, 34), isTrue);
    expect(isNewer(34, 34), isFalse);
    expect(isNewer(33, 34), isFalse);
    expect(isNewer(35, null), isFalse);
  });

  test('automatic check at most every 6 hours, and only when on', () {
    expect(shouldAutoCheck(now: now, lastCheck: null, auto: true), isTrue);
    expect(shouldAutoCheck(now: now, lastCheck: null, auto: false), isFalse);
    expect(shouldAutoCheck(now: now, lastCheck: now.subtract(const Duration(hours: 5)), auto: true), isFalse);
    expect(shouldAutoCheck(now: now, lastCheck: now.subtract(const Duration(hours: 6)), auto: true), isTrue);
    // clock moved back: check rather than wait for days
    expect(shouldAutoCheck(now: now, lastCheck: now.add(const Duration(days: 2)), auto: true), isTrue);
  });

  test('offer unless that build is snoozed', () {
    expect(shouldOffer(latest: info(35), current: 34, now: now), isTrue);
    expect(shouldOffer(latest: info(34), current: 34, now: now), isFalse);
    expect(shouldOffer(latest: null, current: 34, now: now), isFalse);
    expect(shouldOffer(latest: info(35), current: null, now: now), isFalse);
    final until = now.add(const Duration(hours: 3));
    expect(shouldOffer(latest: info(35), current: 34, now: now, snoozedBuild: 35, snoozedUntil: until), isFalse);
    // snooze over
    expect(
      shouldOffer(
        latest: info(35),
        current: 34,
        now: until.add(const Duration(seconds: 1)),
        snoozedBuild: 35,
        snoozedUntil: until,
      ),
      isTrue,
    );
    // an even newer build shows straight away
    expect(shouldOffer(latest: info(36), current: 34, now: now, snoozedBuild: 35, snoozedUntil: until), isTrue);
  });

  test('size check', () {
    expect(sizeMatches(100, 100), isTrue);
    expect(sizeMatches(99, 100), isFalse);
    expect(sizeMatches(0, 0), isFalse);
  });

  test('short notes: bullet titles without Markdown, before the details', () {
    const body = '''## What's new

- **Stores: address, phone and CRIB from receipts**
- **Shopping: "cheaper elsewhere" hints**
- **See [the map](https://x)**

<details><summary>Details</summary>

- **not this**
</details>

Changes since android-0033. Built from abc123.''';
    expect(shortNotes(body), [
      'Stores: address, phone and CRIB from receipts',
      'Shopping: "cheaper elsewhere" hints',
      'See the map',
    ]);
    expect(shortNotes(body, max: 2), ['Stores: address, phone and CRIB from receipts', 'and 2 more']);
    const plain =
        "## What's new\n\nNo changes to the app or server in this build (build and tooling only).\n\nChanges since android-0033. Built from abc123.\n";
    expect(shortNotes(plain), ['No changes to the app or server in this build (build and tooling only).']);
    expect(shortNotes(''), isEmpty);
  });
}
