import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../nutri.dart';
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
  Map<String, dynamic>? _month;
  List<Map<String, dynamic>> _rises = [];
  Map<String, dynamic>? _health;

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
      final m = await s.api.month(s.hid);
      final rises = await s.api.priceChanges(s.hid, _days);
      Map<String, dynamic>? health;
      try {
        health = await s.api.nutrition(s.hid, _days);
      } catch (_) {}
      if (mounted) {
        setState(() {
          _s = r;
          _month = m;
          _rises = rises;
          _health = health;
        });
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  double _n(dynamic v) => double.tryParse('$v') ?? 0;

  Future<void> _setBudget() async {
    final s = Kasita.read(context);
    final ctl = TextEditingController(text: _month?['budget'] == null ? '' : _n(_month!['budget']).toStringAsFixed(0));
    final v = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Monthly grocery budget'),
        content: TextField(
          controller: ctl,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(
            prefixText: '${s.household!.currency} ',
            helperText: 'Empty = no budget. Alerts at 80% and 100%.',
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, ctl.text.trim()), child: const Text('Save')),
        ],
      ),
    );
    if (v == null) return;
    try {
      await s.api.updateHousehold(s.hid, {'grocery_budget': double.tryParse(v.replaceAll(',', '.')) ?? 0});
      await s.loadHouseholds();
      _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Widget _monthCard() {
    final t = Theme.of(context);
    final m = _month!;
    final cur = m['currency'];
    final spent = _n(m['spent']);
    final budget = m['budget'] == null ? null : _n(m['budget']);
    final owner = Kasita.read(context).household!.isOwner;
    return Card(
      margin: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: InkWell(
        onTap: owner ? _setBudget : null,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('This month', style: t.textTheme.labelLarge),
              const SizedBox(height: 4),
              Text(
                budget == null
                    ? '$cur ${spent.toStringAsFixed(2)}'
                    : '$cur ${spent.toStringAsFixed(2)} of ${budget.toStringAsFixed(0)}',
                style: t.textTheme.titleLarge,
              ),
              if (budget != null) ...[
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: budget == 0 ? 0 : (spent / budget).clamp(0, 1).toDouble(),
                    minHeight: 10,
                    color: spent >= budget
                        ? t.colorScheme.error
                        : (spent >= 0.8 * budget ? Colors.orange.shade700 : null),
                  ),
                ),
              ],
              if (owner)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    budget == null ? 'Tap to set a monthly budget' : 'Tap to change the budget',
                    style: t.textTheme.bodySmall,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  /// Basket health: what share of the rated spending went on each Nutri-Score grade.
  Widget _healthCard(Map<String, dynamic> h, String cur) {
    final t = Theme.of(context);
    final grades = [for (final g in h['by_grade'] as List) if (g['grade'] != 'unrated') g];
    final top = h['top_d_e'] as List;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 4),
          child: Text('Basket health', style: t.textTheme.titleMedium),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Text(
            'Nutri-Score of what you bought (${h['rated_pct']}% of spending has a score; '
            'only barcoded food can be rated)',
            style: t.textTheme.bodySmall,
          ),
        ),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: SizedBox(
              height: 22,
              child: Row(
                children: [
                  for (final g in grades)
                    if ((g['pct'] ?? 0) > 0)
                      Expanded(
                        flex: g['pct'] as int,
                        child: Container(
                          color: NutriScoreBadge.colors[g['grade']],
                          alignment: Alignment.center,
                          child: (g['pct'] as int) >= 8
                              ? Text(
                                  '${(g['grade'] as String).toUpperCase()} ${g['pct']}%',
                                  style: TextStyle(
                                    color: g['grade'] == 'c' ? Colors.black87 : Colors.white,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w700,
                                  ),
                                )
                              : null,
                        ),
                      ),
                ],
              ),
            ),
          ),
        ),
        if (h['ultra_processed_pct'] != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text('Ultra-processed (NOVA 4): ${h['ultra_processed_pct']}% of what has a NOVA group'),
          ),
        if (top.isNotEmpty) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Text('Biggest D / E buys', style: t.textTheme.labelLarge),
          ),
          for (final x in top)
            ListTile(
              dense: true,
              leading: NutriScoreBadge(x['nutriscore'] as String, size: 22),
              title: Text('${x['name']}'),
              subtitle: x['sugars'] == null ? null : Text('sugar ${x['sugars']} g per 100'),
              trailing: Text('$cur ${_n(x['amount']).toStringAsFixed(2)}'),
            ),
        ],
      ],
    );
  }

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
          if (_month != null) _monthCard(),
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
            if (_health != null && (_health!['rated_pct'] ?? 0) > 0) _healthCard(_health!, s['currency']),
            if (_rises.isNotEmpty) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 20, 16, 4),
                child: Text('Went up', style: t.textTheme.titleMedium),
              ),
              for (final r in _rises)
                ListTile(
                  dense: true,
                  leading: Icon(Icons.trending_up, color: Colors.orange.shade800),
                  title: Text('${r['product']} at ${r['store']}'),
                  trailing: Text(
                    '${_n(r['before']).toStringAsFixed(2)} → ${_n(r['now']).toStringAsFixed(2)} (+${r['pct']}%)',
                  ),
                ),
            ],
            const SizedBox(height: 24),
          ],
        ],
      ),
    );
  }
}
