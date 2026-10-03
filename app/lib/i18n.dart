import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' as m;
import 'package:flutter/material.dart' show StatelessWidget, TextAlign, TextOverflow, TextStyle, Widget, BuildContext;
import 'package:flutter/services.dart' show rootBundle;
import 'package:intl/date_symbol_data_local.dart';
import 'package:intl/intl.dart';

import 'prefs.dart';

/// Languages the app speaks. English is the source language: its texts ARE the keys.
const supportedLangs = {'en': 'English', 'nl': 'Nederlands', 'pap': 'Papiamentu'};

/// The current language; changing it rebuilds the whole app (see KasitaApp).
final ValueNotifier<String> appLang = ValueNotifier('en');

Map<String, String> _table = {};
List<_Template> _templates = [];
final Map<String, String> _cache = {};

/// A text with holes, e.g. "Added {} to the shopping list". Interpolated Dart strings such as
/// 'Added ${p.name} to the shopping list' have the same shape at run time, so they are matched, not listed.
class _Template {
  final RegExp pattern;
  final String target;
  final int literal; // characters outside the holes: the longer, the more specific
  _Template(String key, this.target)
    : pattern = RegExp('^${key.split('{}').map(RegExp.escape).join('(.+?)')}\$', dotAll: true),
      literal = key.replaceAll('{}', '').length;
}

/// Load the saved (or device) language and its texts. Call once before runApp.
Future<void> initI18n() async {
  var lang = await loadPref('lang', '');
  if (!supportedLangs.containsKey(lang)) {
    lang = PlatformDispatcher.instance.locale.languageCode == 'nl' ? 'nl' : 'en';
  }
  await _load(lang);
}

Future<void> setLang(String lang) async {
  if (!supportedLangs.containsKey(lang)) return;
  await savePref('lang', lang);
  await _load(lang);
}

Future<void> _load(String lang) async {
  _cache.clear();
  _table = {};
  _templates = [];
  if (lang != 'en') {
    try {
      final raw = jsonDecode(await rootBundle.loadString('assets/i18n/$lang.json')) as Map<String, dynamic>;
      installTable(raw.map((k, v) => MapEntry(k, '$v')));
    } catch (_) {
      // a missing file just means English
    }
  }
  if (lang == 'nl') {
    try {
      await initializeDateFormatting('nl');
    } catch (_) {}
  }
  appLang.value = lang;
}

/// Install translations directly (used by [_load] and by tests).
@visibleForTesting
void installTable(Map<String, String> table) {
  _cache.clear();
  _table = {};
  _templates = [];
  table.forEach((k, v) {
    if (k.contains('{}')) {
      _templates.add(_Template(k, v));
    } else {
      _table[k] = v;
    }
  });
  _templates.sort((a, b) => b.literal.compareTo(a.literal));
}

/// Translate [s] into the current language; unknown texts come back unchanged.
String tr(String s) {
  if (_table.isEmpty && _templates.isEmpty) return s;
  final hit = _cache[s];
  if (hit != null) return hit;
  var out = _table[s];
  if (out == null) {
    for (final t in _templates) {
      final m = t.pattern.firstMatch(s);
      if (m == null) continue;
      var n = 0;
      // {1}, {2}... in a translation reorder the holes; plain {} fills them in order
      out = t.target.replaceAllMapped(RegExp(r'\{(\d*)\}'), (h) {
        final i = h[1]!.isEmpty ? n++ : int.parse(h[1]!) - 1;
        final piece = i < m.groupCount ? m.group(i + 1)! : '';
        return _table[piece] ?? piece; // a hole holding a known word ("pcs", "today") is translated too
      });
      break;
    }
  }
  out ??= s;
  if (_cache.length > 4000) _cache.clear(); // names typed by people also pass through here
  return _cache[s] = out;
}

/// Drop-in for Flutter's Text that translates its string: screens import this instead (`hide Text`).
class Text extends StatelessWidget {
  final String data;
  final TextStyle? style;
  final TextAlign? textAlign;
  final int? maxLines;
  final TextOverflow? overflow;
  const Text(this.data, {super.key, this.style, this.textAlign, this.maxLines, this.overflow});

  @override
  Widget build(BuildContext context) =>
      m.Text(tr(data), style: style, textAlign: textAlign, maxLines: maxLines, overflow: overflow);
}

// --- dates ---------------------------------------------------------------------------------
const _papMonths = {
  'January': 'yanüari', 'February': 'febrüari', 'March': 'mart', 'April': 'aprel', 'May': 'mei', 'June': 'yüni',
  'July': 'yüli', 'August': 'ougùstùs', 'September': 'sèptèmber', 'October': 'òktober', 'November': 'novèmber',
  'December': 'desèmber',
  'Jan': 'yan', 'Feb': 'feb', 'Mar': 'mar', 'Apr': 'apr', 'Jun': 'yün', 'Jul': 'yül', 'Aug': 'oug', 'Sep': 'sèp',
  'Oct': 'òkt', 'Nov': 'nov', 'Dec': 'des',
  'Monday': 'djaluna', 'Tuesday': 'djamars', 'Wednesday': 'djarason', 'Thursday': 'djaweps', 'Friday': 'djabièrnè',
  'Saturday': 'djasabra', 'Sunday': 'djadumingu',
  'Mon': 'Lun', 'Tue': 'Mar', 'Wed': 'Ras', 'Thu': 'Wep', 'Fri': 'Bièr', 'Sat': 'Sab', 'Sun': 'Dum',
};
final _papWords = RegExp('\\b(${_papMonths.keys.join('|')})\\b');

/// DateFormat that follows the app language: Dutch through intl, Papiamentu by renaming English month
/// and weekday names (intl has no Papiamentu).
class LDateFormat {
  final String pattern;
  const LDateFormat(this.pattern);

  String format(DateTime d) {
    final lang = appLang.value;
    if (lang == 'nl') {
      try {
        return DateFormat(pattern, 'nl').format(d);
      } catch (_) {}
    }
    final s = DateFormat(pattern).format(d); // English is built into intl: no locale data to load
    return lang == 'pap' ? s.replaceAllMapped(_papWords, (w) => _papMonths[w[0]!]!) : s;
  }
}
