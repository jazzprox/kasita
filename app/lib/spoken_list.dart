/// "milk, two breads and dish soap" -> [(1, milk), (2, breads), (1, dish soap)].
///
/// Speech recognition gives one sentence; this splits it on commas and the
/// word 'and' (English, Spanish, Dutch, Papiamentu) and reads a leading
/// number word as the quantity.
library;

const _numbers = {
  // English
  'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
  'nine': 9, 'ten': 10, 'twelve': 12, 'dozen': 12, 'a dozen': 12, 'couple': 2, 'a couple of': 2, 'a couple': 2,
  // Spanish / Papiamentu
  'un': 1, 'una': 1, 'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'kuater': 4, 'cinco': 5, 'sinku': 5,
  'seis': 6, 'siete': 7, 'shete': 7, 'ocho': 8, 'ochu': 8, 'diez': 10, 'dies': 10,
  // Dutch
  'een': 1, 'één': 1, 'twee': 2, 'drie': 3, 'vier': 4, 'vijf': 5, 'zes': 6, 'zeven': 7, 'acht': 8, 'tien': 10,
};

List<(double, String)> parseSpokenList(String text) {
  final parts = text
      .toLowerCase()
      .split(RegExp(r',|;|\band\b|\by\b|\ben\b|\bi\b|\bplus\b'))
      .map((p) => p.trim())
      .where((p) => p.isNotEmpty);
  final out = <(double, String)>[];
  for (final p in parts) {
    var qty = 1.0;
    var name = p;
    final digits = RegExp(r'^(\d+(?:[.,]\d+)?)\s*x?\s+(.+)$').firstMatch(p);
    if (digits != null) {
      qty = double.parse(digits.group(1)!.replaceAll(',', '.'));
      name = digits.group(2)!;
    } else {
      // longest number phrase first ("a couple of" before "a")
      for (final w in (_numbers.keys.toList()..sort((a, b) => b.length.compareTo(a.length)))) {
        if (name.startsWith('$w ')) {
          qty = _numbers[w]!.toDouble();
          name = name.substring(w.length).trim();
          break;
        }
      }
    }
    name = name.replaceFirst(RegExp(r'^(of|de|di|van)\s+'), '').trim();
    if (name.isNotEmpty) out.add((qty, name));
  }
  return out;
}
