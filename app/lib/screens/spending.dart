import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../widgets.dart';

/// What groceries cost: priced purchases (receipts, or prices typed when buying),
/// per category and per store, for the last week / month / quarter.
class SpendingScreen extends StatefulWidget {
  const SpendingScreen({super.key});
  @override
  State<SpendingScreen> createState() => _SpendingScreenState();
}

class _SpendingScreenState extends State<SpendingScreen> {
  int _days = 30;
  Map<String, dynamic>? _s;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    setState(() => _s = null);
    try {
      final r = await s.api.spending(s.hid, _days);
      if (mounted) setState(() => _s = r);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  double _n(dynamic v) => double.tryParse('$v') ?? 0;

  Widget _bars(String title, List rows, String cur, double total) {
    final t = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
          child: Text(title, style: t.textTheme.titleMedium),
        ),
        for (final r in rows)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(child: Text('${r['name']}')),
                    Text('$cur ${_n(r['amount']).toStringAsFixed(2)}'),
                  ],
                ),
                const SizedBox(height: 4),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: total == 0 ? 0 : _n(r['amount']) / total,
                    minHeight: 8,
                    backgroundColor: t.colorScheme.surfaceContainerHighest,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = _s;
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Spending')),
      body: ListView(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: SegmentedButton<int>(
              segments: const [
                ButtonSegment(value: 7, label: Text('7 days')),
                ButtonSegment(value: 30, label: Text('30 days')),
                ButtonSegment(value: 90, label: Text('90 days')),
              ],
              selected: {_days},
              onSelectionChanged: (d) {
                _days = d.first;
                _load();
              },
            ),
          ),
          if (s == null)
            const Padding(
              padding: EdgeInsets.all(40),
              child: Center(child: CircularProgressIndicator()),
            )
          else if ((s['purchases'] ?? 0) == 0)
            const EmptyState(
              icon: Icons.receipt_long_outlined,
              title: 'No prices yet',
              message: 'Scan a receipt, or add the price when you tap Bought, and spending shows up here.',
            )
          else ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 20, 16, 0),
              child: Text('${s['currency']} ${_n(s['total']).toStringAsFixed(2)}', style: t.textTheme.displaySmall),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text('${s['purchases']} priced items in the last $_days days', style: t.textTheme.bodySmall),
            ),
            _bars('By category', s['by_category'] as List, s['currency'], _n(s['total'])),
            _bars('By store', s['by_store'] as List, s['currency'], _n(s['total'])),
            const SizedBox(height: 24),
          ],
        ],
      ),
    );
  }
}
