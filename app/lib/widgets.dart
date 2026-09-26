import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

final dateFmt = DateFormat('d MMM');
final dateFmtYear = DateFormat('d MMM yyyy');

int daysUntil(DateTime d) {
  final today = DateUtils.dateOnly(DateTime.now());
  return DateUtils.dateOnly(d).difference(today).inDays;
}

/// "expired 2d ago" / "today" / "in 3 days" / "12 Oct", coloured by urgency.
class ExpiryChip extends StatelessWidget {
  final DateTime? date;
  const ExpiryChip(this.date, {super.key});

  @override
  Widget build(BuildContext context) {
    if (date == null) return const SizedBox.shrink();
    final cs = Theme.of(context).colorScheme;
    final d = daysUntil(date!);
    final (label, color) = switch (d) {
      < 0 => ('expired ${-d}d ago', cs.error),
      0 => ('today', cs.error),
      1 => ('tomorrow', Colors.orange.shade800),
      <= 5 => ('in $d days', Colors.orange.shade800),
      _ => (dateFmt.format(date!), cs.onSurfaceVariant),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}

class ProductThumb extends StatelessWidget {
  final String? url;
  final double size;
  const ProductThumb(this.url, {super.key, this.size = 44});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final fallback = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
      child: Icon(Icons.inventory_2_outlined, color: cs.onSurfaceVariant, size: size * 0.5),
    );
    if (url == null || url!.isEmpty) return fallback;
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Image.network(url!, width: size, height: size, fit: BoxFit.cover, errorBuilder: (_, _, _) => fallback),
    );
  }
}

void toast(BuildContext context, String msg, {bool error = false}) {
  final cs = Theme.of(context).colorScheme;
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: error ? cs.error : null, behavior: SnackBarBehavior.floating),
    );
}

class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title, message;
  const EmptyState({super.key, required this.icon, required this.title, required this.message});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 56, color: t.colorScheme.outline),
            const SizedBox(height: 12),
            Text(title, style: t.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(color: t.colorScheme.onSurfaceVariant),
            ),
          ],
        ),
      ),
    );
  }
}
