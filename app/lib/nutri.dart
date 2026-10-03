import 'package:flutter/material.dart';

/// Open Food Facts' Nutri-Score letter (a..e) as the familiar coloured badge.
class NutriScoreBadge extends StatelessWidget {
  final String grade;
  final double size;
  const NutriScoreBadge(this.grade, {super.key, this.size = 28});

  static const colors = {
    'a': Color(0xFF038141),
    'b': Color(0xFF85BB2F),
    'c': Color(0xFFFECB02),
    'd': Color(0xFFEE8100),
    'e': Color(0xFFE63E11),
  };

  @override
  Widget build(BuildContext context) {
    final c = colors[grade] ?? Colors.grey;
    return Tooltip(
      message: 'Nutri-Score ${grade.toUpperCase()} (A best, E worst)',
      child: Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(size / 4)),
        child: Text(
          grade.toUpperCase(),
          style: TextStyle(
            color: grade == 'c' ? Colors.black87 : Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: size * 0.55,
          ),
        ),
      ),
    );
  }
}

/// NOVA group: 1 unprocessed .. 4 ultra-processed.
String novaText(int nova) => switch (nova) {
  1 => 'NOVA 1 · unprocessed',
  2 => 'NOVA 2 · cooking ingredient',
  3 => 'NOVA 3 · processed',
  _ => 'NOVA 4 · ultra-processed',
};

/// "per 100 g: 42 kcal · sugar 10.6 g · salt 0 g"
String nutrientsText(Map<String, dynamic> n, {bool liquid = false}) {
  String g(String k, String label) => n[k] == null ? '' : '$label ${n[k]} g';
  final parts = [
    if (n['kcal'] != null) '${(n['kcal'] as num).round()} kcal',
    g('sugars', 'sugar'),
    g('fat', 'fat'),
    g('salt', 'salt'),
    g('protein', 'protein'),
  ].where((x) => x.isNotEmpty);
  return 'per 100 ${liquid ? 'ml' : 'g'}: ${parts.join(' · ')}';
}
