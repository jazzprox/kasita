import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../widgets.dart';

/// Light, fun numbers about how you shop, from booked receipts.
class FunStatsScreen extends StatefulWidget {
  const FunStatsScreen({super.key});
  @override
  State<FunStatsScreen> createState() => _FunStatsScreenState();
}

class _FunStatsScreenState extends State<FunStatsScreen> {
  Map<String, dynamic>? _s;
  int _days = 365;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    try {
      final st = await s.api.funStats(s.hid, days: _days);
      if (mounted) setState(() => _s = st);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  static const _kindNames = {'supermarket': 'Supermarkets', 'minimarket': 'Minimarkets', 'other': 'Other'};

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final s = _s;
    final cur = Kasita.of(context).household!.currency;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Fun stats'),
        actions: [
          PopupMenuButton<int>(
            tooltip: 'Period',
            icon: const Icon(Icons.date_range_outlined),
            onSelected: (d) {
              setState(() {
                _days = d;
                _s = null;
              });
              _load();
            },
            itemBuilder: (_) => [
              for (final (d, label) in const [(30, 'Last 30 days'), (90, 'Last 3 months'), (365, 'Last year')])
                CheckedPopupMenuItem(value: d, checked: d == _days, child: Text(label)),
            ],
          ),
        ],
      ),
      body: s == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: navBarSafe(context, const EdgeInsets.fromLTRB(16, 8, 16, 16)),
                children: [
                  for (final h in (s['headlines'] as List? ?? const []))
                    Card(
                      child: ListTile(leading: const Icon(Icons.auto_awesome_outlined), title: Text('$h')),
                    ),
                  if ((s['trips'] ?? 0) > 0) ...[
                    const SizedBox(height: 16),
                    Text('Trips per weekday', style: t.textTheme.titleSmall),
                    const SizedBox(height: 8),
                    _Bars([
                      for (final d in s['weekdays'] as List)
                        ('${d['day']}'.substring(0, 2), (d['trips'] as num).toDouble()),
                    ]),
                    if (s['hours'] != null) ...[
                      const SizedBox(height: 16),
                      Text('Trips per hour of the day', style: t.textTheme.titleSmall),
                      const SizedBox(height: 8),
                      _Bars([
                        for (final h in (s['hours'] as List).where((h) => h['hour'] >= 6 && h['hour'] <= 23))
                          (h['hour'] % 3 == 0 ? '${h['hour']}' : '', (h['trips'] as num).toDouble()),
                      ]),
                    ],
                    const SizedBox(height: 16),
                    Text('Where the money goes', style: t.textTheme.titleSmall),
                    for (final k in s['by_kind'] as List)
                      if ((k['share'] as num) > 0)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${_kindNames[k['kind']] ?? k['kind']}: $cur '
                                '${(double.tryParse('${k['total']}') ?? 0).toStringAsFixed(2)} '
                                '(${((k['share'] as num) * 100).round()}%)',
                              ),
                              const SizedBox(height: 4),
                              LinearProgressIndicator(value: (k['share'] as num).toDouble(), minHeight: 8),
                            ],
                          ),
                        ),
                    const SizedBox(height: 8),
                    Text(
                      'Is a store in the wrong group? Change its kind in More → Stores.',
                      style: TextStyle(color: t.colorScheme.onSurfaceVariant, fontSize: 12),
                    ),
                    if (s['travel'] == null) ...[
                      const SizedBox(height: 16),
                      Card(
                        child: ListTile(
                          leading: const Icon(Icons.home_outlined),
                          title: const Text('How far do you travel?'),
                          subtitle: const Text('Long-press your home on the Map (More → Map) to see.'),
                        ),
                      ),
                    ],
                  ],
                ],
              ),
            ),
    );
  }
}

/// A tiny bar chart: label under each bar, the count on top.
class _Bars extends StatelessWidget {
  final List<(String, double)> data;
  const _Bars(this.data);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final max = data.fold<double>(0, (m, d) => d.$2 > m ? d.$2 : m);
    return SizedBox(
      height: 120,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final (label, v) in data)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    if (v > 0) Text(v.toStringAsFixed(0), style: const TextStyle(fontSize: 10)),
                    Container(
                      height: max == 0 ? 0 : 80 * v / max,
                      decoration: BoxDecoration(
                        color: v == max && v > 0 ? cs.primary : cs.primaryContainer,
                        borderRadius: const BorderRadius.vertical(top: Radius.circular(3)),
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(label, style: const TextStyle(fontSize: 10), maxLines: 1, overflow: TextOverflow.clip),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
