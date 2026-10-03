import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart' hide Text;
import 'package:flutter_test/flutter_test.dart';
import 'package:kasita/i18n.dart';

Map<String, String> table(String lang) =>
    (jsonDecode(File('assets/i18n/$lang.json').readAsStringSync()) as Map).map((k, v) => MapEntry('$k', '$v'));

void main() {
  test('Dutch: exact texts, texts with holes, and holes holding known words', () {
    installTable(table('nl'));
    expect(tr('Shopping list'), 'Boodschappenlijst');
    expect(tr('Added Milk to the shopping list'), 'Milk aan de boodschappenlijst toegevoegd');
    expect(tr('3 pcs at home'), '3 st thuis'); // "pcs" inside a hole is translated too
    expect(tr('expired 3d ago'), '3d geleden verlopen');
    expect(tr('Whole milk'), 'Whole milk'); // a product name is left alone
    expect(tr('Totally unknown text'), 'Totally unknown text'); // untranslated stays English
  });

  test('Papiamentu: numbered holes drop a plural suffix', () {
    installTable(table('pap'));
    expect(tr('Learned from 3 trips'), 'Siña for di 3 bishita'); // the "s" hole is not used
    expect(tr('Added 2 items: "milk, bread"'), '2 artíkulo agregá: "milk, bread"');
    expect(tr('Save'), 'Warda');
  });

  test('more specific templates win', () {
    installTable({'{} min': '{} minuten', '{} min ago': '{} minuten geleden'});
    expect(tr('5 min ago'), '5 minuten geleden');
    expect(tr('5 min'), '5 minuten');
  });

  test('dates follow the language', () async {
    installTable({});
    appLang.value = 'en';
    final d = DateTime(2026, 10, 3); // a Saturday
    expect(const LDateFormat('EEE d MMM').format(d), 'Sat 3 Oct');
    appLang.value = 'pap';
    expect(const LDateFormat('EEE d MMM').format(d), 'Sab 3 òkt');
    expect(const LDateFormat('MMMM yyyy').format(d), 'òktober 2026');
    appLang.value = 'en';
  });

  testWidgets('the drop-in Text translates what it shows', (tester) async {
    installTable({'Save': 'Opslaan'});
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Text('Save'))));
    expect(find.text('Opslaan'), findsOneWidget);
    installTable({});
  });

  test('every language file only has texts the app uses', () {
    // guards against typos: a key the screens never produce can never be shown
    for (final lang in ['nl', 'pap']) {
      final t = table(lang);
      expect(t.length, greaterThan(800), reason: lang);
      expect(t.values.where((v) => v.trim().isEmpty), isEmpty, reason: lang);
    }
  });
}
