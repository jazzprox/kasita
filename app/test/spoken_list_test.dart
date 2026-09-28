import 'package:flutter_test/flutter_test.dart';
import 'package:kasita/spoken_list.dart';

void main() {
  test('commas, and, number words', () {
    expect(parseSpokenList('milk, two breads and dish soap'), [(1.0, 'milk'), (2.0, 'breads'), (1.0, 'dish soap')]);
    expect(parseSpokenList('a dozen eggs and a couple of limes'), [(12.0, 'eggs'), (2.0, 'limes')]);
    expect(parseSpokenList('3 yogurts'), [(3.0, 'yogurts')]);
  });
  test('Spanish, Dutch, Papiamentu', () {
    expect(parseSpokenList('dos leche y pan'), [(2.0, 'leche'), (1.0, 'pan')]);
    expect(parseSpokenList('twee melk en brood'), [(2.0, 'melk'), (1.0, 'brood')]);
    expect(parseSpokenList('tres webu i lechi'), [(3.0, 'webu'), (1.0, 'lechi')]);
  });
  test('words that merely contain "and" stay whole', () {
    expect(parseSpokenList('candles and sandwich bags'), [(1.0, 'candles'), (1.0, 'sandwich bags')]);
  });
}
