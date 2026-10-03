import 'dart:math' as math;

import 'package:flutter/material.dart' hide Text;

import 'models.dart';
import 'i18n.dart';

/// What one product cost over time: a line per store, by the day it was bought.
/// Drawn by hand (no chart package): a few dozen points at most.
class PriceChart extends StatelessWidget {
  final List<PricePoint> prices; // any order
  final String currency;
  const PriceChart({super.key, required this.prices, required this.currency});

  static const _palette = [
    Color(0xFF2E7D5B), // herb green (the app's own)
    Color(0xFFE0922F),
    Color(0xFF3F6FB5),
    Color(0xFFB5475B),
    Color(0xFF7A5BB5),
    Color(0xFF4F8A8B),
  ];

  /// Store name -> its points, oldest first; stores with the most purchases get the first colours.
  Map<String, List<PricePoint>> get _series {
    final by = <String, List<PricePoint>>{};
    for (final p in prices) {
      by.putIfAbsent(p.storeName ?? 'Unknown store', () => []).add(p);
    }
    for (final l in by.values) {
      l.sort((a, b) => a.on.compareTo(b.on));
    }
    final keys = by.keys.toList()..sort((a, b) => by[b]!.length.compareTo(by[a]!.length));
    return {for (final k in keys) k: by[k]!};
  }

  /// "Up 12% at Goisco since 3 Mar" for the store with the longest history (null when flat or too short).
  static String? trend(List<PricePoint> prices) {
    final by = <String, List<PricePoint>>{};
    for (final p in prices) {
      by.putIfAbsent(p.storeName ?? '', () => []).add(p);
    }
    final best = by.entries.where((e) => e.value.length >= 2).toList()
      ..sort((a, b) => b.value.length.compareTo(a.value.length));
    if (best.isEmpty) return null;
    final l = best.first.value..sort((a, b) => a.on.compareTo(b.on));
    final first = l.first.unitPrice, last = l.last.unitPrice;
    if (first <= 0) return null;
    final pct = ((last - first) / first * 100).round();
    if (pct == 0) return 'Same price at ${best.first.key} since ${LDateFormat('d MMM').format(l.first.on)}';
    return '${pct > 0 ? 'Up' : 'Down'} ${pct.abs()}% at ${best.first.key} since ${LDateFormat('d MMM').format(l.first.on)}';
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final series = _series;
    final colors = {
      for (final (i, k) in series.keys.indexed) k: _palette[i % _palette.length],
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          height: 170,
          width: double.infinity,
          child: CustomPaint(
            painter: _ChartPainter(
              series: series,
              colors: colors,
              currency: currency,
              text: t.textTheme.labelSmall!.copyWith(color: t.colorScheme.onSurfaceVariant),
              grid: t.colorScheme.outlineVariant,
              surface: t.colorScheme.surface,
            ),
          ),
        ),
        if (series.length > 1)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Wrap(
              spacing: 12,
              runSpacing: 4,
              children: [
                for (final k in series.keys)
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(color: colors[k], shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 4),
                      Text(k, style: t.textTheme.labelSmall),
                    ],
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

class _ChartPainter extends CustomPainter {
  final Map<String, List<PricePoint>> series;
  final Map<String, Color> colors;
  final String currency;
  final TextStyle text;
  final Color grid, surface;
  _ChartPainter({
    required this.series,
    required this.colors,
    required this.currency,
    required this.text,
    required this.grid,
    required this.surface,
  });

  TextPainter _label(String s) => TextPainter(text: TextSpan(text: s, style: text), textDirection: TextDirection.ltr)
    ..layout();

  @override
  void paint(Canvas canvas, Size size) {
    final all = [for (final l in series.values) ...l];
    if (all.isEmpty) return;
    var lo = all.map((p) => p.unitPrice).reduce(math.min);
    var hi = all.map((p) => p.unitPrice).reduce(math.max);
    if (hi - lo < 0.01) {
      lo -= 0.5;
      hi += 0.5;
    }
    final pad = (hi - lo) * 0.12;
    lo = math.max(0, lo - pad);
    hi += pad;
    final t0 = all.map((p) => p.on.millisecondsSinceEpoch).reduce(math.min).toDouble();
    var t1 = all.map((p) => p.on.millisecondsSinceEpoch).reduce(math.max).toDouble();
    if (t1 - t0 < 1) t1 = t0 + const Duration(days: 1).inMilliseconds;

    final hiLabel = _label(hi.toStringAsFixed(2)), loLabel = _label(lo.toStringAsFixed(2));
    final left = math.max(hiLabel.width, loLabel.width) + 8;
    const top = 6.0, bottomPad = 18.0;
    final w = size.width - left - 8, h = size.height - top - bottomPad;
    double x(DateTime d) => left + (d.millisecondsSinceEpoch - t0) / (t1 - t0) * w;
    double y(double v) => top + (1 - (v - lo) / (hi - lo)) * h;

    final gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    for (final v in [lo, (lo + hi) / 2, hi]) {
      canvas.drawLine(Offset(left, y(v)), Offset(left + w, y(v)), gridPaint);
    }
    hiLabel.paint(canvas, Offset(left - hiLabel.width - 6, y(hi) - hiLabel.height / 2));
    loLabel.paint(canvas, Offset(left - loLabel.width - 6, y(lo) - loLabel.height / 2));

    final fmt = LDateFormat(DateTime.fromMillisecondsSinceEpoch(t0.toInt()).year ==
            DateTime.fromMillisecondsSinceEpoch(t1.toInt()).year
        ? 'd MMM'
        : 'MMM yy');
    final a = _label(fmt.format(DateTime.fromMillisecondsSinceEpoch(t0.toInt())));
    final b = _label(fmt.format(DateTime.fromMillisecondsSinceEpoch(t1.toInt())));
    a.paint(canvas, Offset(left, size.height - a.height));
    if (t1 - t0 > const Duration(days: 1).inMilliseconds) {
      b.paint(canvas, Offset(left + w - b.width, size.height - b.height));
    }

    for (final e in series.entries) {
      final c = colors[e.key]!;
      final pts = [for (final p in e.value) Offset(x(p.on), y(p.unitPrice))];
      if (pts.length > 1) {
        // a step line: the price held until the next time it was seen
        final path = Path()..moveTo(pts.first.dx, pts.first.dy);
        for (var i = 1; i < pts.length; i++) {
          path
            ..lineTo(pts[i].dx, pts[i - 1].dy)
            ..lineTo(pts[i].dx, pts[i].dy);
        }
        canvas.drawPath(
          path,
          Paint()
            ..color = c
            ..strokeWidth = 2
            ..style = PaintingStyle.stroke,
        );
      }
      for (final p in pts) {
        canvas.drawCircle(p, 4, Paint()..color = surface);
        canvas.drawCircle(p, 3, Paint()..color = c);
      }
    }
  }

  @override
  bool shouldRepaint(_ChartPainter old) => old.series != series || old.text != text;
}
