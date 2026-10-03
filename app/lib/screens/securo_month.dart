import 'package:flutter/material.dart' hide Text;
import 'package:intl/intl.dart';

import '../api.dart';
import '../main.dart';
import '../widgets.dart';
import 'receipts.dart';
import '../i18n.dart';

/// A month of groceries from both sides: what Securo says was paid (its Groceries
/// category, plus payments a receipt is linked to) and what Kasita's receipts say was
/// in the bags. Shows which payments have no receipt, and links a matching one in a tap.
class SecuroMonthScreen extends StatefulWidget {
  const SecuroMonthScreen({super.key});
  @override
  State<SecuroMonthScreen> createState() => _SecuroMonthScreenState();
}

class _SecuroMonthScreenState extends State<SecuroMonthScreen> {
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);
  Map<String, dynamic>? _r;
  String? _error;
  final Set<String> _linking = {};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  String get _key => DateFormat('yyyy-MM').format(_month);

  Future<void> _load() async {
    final s = Kasita.read(context);
    setState(() {
      _r = null;
      _error = null;
    });
    try {
      final r = await s.api.securoGroceries(s.hid, month: _key);
      if (mounted) setState(() => _r = r);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  void _shift(int months) {
    final next = DateTime(_month.year, _month.month + months);
    if (next.isAfter(DateTime.now())) return;
    setState(() => _month = next);
    _load();
  }

  double _n(dynamic v) => double.tryParse('$v') ?? 0;

  Future<void> _link(Map p) async {
    final s = Kasita.read(context);
    final id = p['id'] as String;
    setState(() => _linking.add(id));
    try {
      await s.api.securoLink(s.hid, p['suggested_receipt_id'] as String, id);
      if (mounted) toast(context, 'Linked: the receipt photo and its items are on the payment in Securo');
      await _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _linking.remove(id));
    }
  }

  void _openReceipt(String id) => Navigator.of(
    context,
  ).push(MaterialPageRoute(builder: (_) => ReceiptReviewScreen(receiptId: id))).then((_) => _load());

  Widget _bar(double value, Color? color) => ClipRRect(
    borderRadius: BorderRadius.circular(4),
    child: LinearProgressIndicator(
      value: value.clamp(0, 1).toDouble(),
      minHeight: 10,
      color: color,
      backgroundColor: Theme.of(context).colorScheme.surfaceContainerHighest,
    ),
  );

  Widget _summary(Map<String, dynamic> r) {
    final t = Theme.of(context);
    final cur = r['currency'];
    final total = _n(r['securo_total']);
    final covered = _n(r['with_receipt']);
    final budget = r['securo_budget'] != null
        ? _n(r['securo_budget']['amount'])
        : (r['kasita_budget'] == null ? null : _n(r['kasita_budget']));
    return Card(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Paid for groceries (Securo)', style: t.textTheme.labelLarge),
            const SizedBox(height: 4),
            Text(
              budget == null
                  ? '$cur ${total.toStringAsFixed(2)}'
                  : '$cur ${total.toStringAsFixed(2)} of ${budget.toStringAsFixed(0)}',
              style: t.textTheme.headlineSmall,
            ),
            if (budget != null && budget > 0) ...[
              const SizedBox(height: 8),
              _bar(total / budget, total >= budget ? t.colorScheme.error : null),
              const SizedBox(height: 2),
              Text(
                r['securo_budget'] != null ? 'Budget from Securo' : 'Budget from Kasita',
                style: t.textTheme.bodySmall,
              ),
            ],
            const SizedBox(height: 14),
            Text(
              r['coverage_pct'] == null
                  ? 'No grocery payments this month'
                  : 'Receipts cover ${r['coverage_pct']}%: $cur ${covered.toStringAsFixed(2)}',
              style: t.textTheme.labelLarge,
            ),
            if (r['coverage_pct'] != null) ...[const SizedBox(height: 6), _bar(total == 0 ? 0 : covered / total, null)],
            const SizedBox(height: 6),
            Text(
              'Only payments with a receipt say what was in the bag.',
              style: t.textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }

  Widget _payment(Map p, String cur) {
    final t = Theme.of(context);
    final linked = p['receipt_id'] != null;
    final suggested = p['suggested_receipt_id'] != null;
    final day = DateTime.tryParse('${p['date']}');
    final amount = '${p['currency']} ${_n(p['amount']).toStringAsFixed(2)}';
    return ListTile(
      leading: Icon(
        linked ? Icons.receipt_long : Icons.credit_card,
        color: linked ? t.colorScheme.primary : t.colorScheme.outline,
      ),
      title: Text('${p['description'] ?? 'Payment'}'),
      subtitle: Text(
        [
          if (day != null) LDateFormat('EEE d MMM').format(day),
          amount,
          if (p['category'] != null && p['category'] != 'Groceries') 'in ${p['category']}',
          if (!linked && !suggested) 'no receipt',
        ].join(' · '),
      ),
      trailing: linked
          ? const Icon(Icons.chevron_right)
          : suggested
          ? (_linking.contains(p['id'])
                ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                : FilledButton.tonal(onPressed: () => _link(p), child: const Text('Link receipt')))
          : null,
      onTap: linked
          ? () => _openReceipt(p['receipt_id'] as String)
          : suggested
          ? () => _openReceipt(p['suggested_receipt_id'] as String)
          : null,
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final r = _r;
    final cur = r?['currency'] ?? '';
    final atNow = _month.year == DateTime.now().year && _month.month == DateTime.now().month;
    final cats = (r?['by_category'] as List?) ?? const [];
    final catTotal = cats.fold<double>(0, (a, c) => a + _n(c['amount']));
    return Scaffold(
      appBar: AppBar(title: const Text('Groceries in Securo')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(onPressed: () => _shift(-1), icon: const Icon(Icons.chevron_left)),
                SizedBox(
                  width: 160,
                  child: Text(
                    LDateFormat('MMMM yyyy').format(_month),
                    textAlign: TextAlign.center,
                    style: t.textTheme.titleMedium,
                  ),
                ),
                IconButton(onPressed: atNow ? null : () => _shift(1), icon: const Icon(Icons.chevron_right)),
              ],
            ),
            if (_error != null)
              EmptyState(icon: Icons.link_off, title: 'Securo did not answer', message: _error!)
            else if (r == null)
              const Padding(
                padding: EdgeInsets.all(40),
                child: Center(child: CircularProgressIndicator()),
              )
            else ...[
              if (r['category_found'] == false)
                const Padding(
                  padding: EdgeInsets.fromLTRB(16, 8, 16, 0),
                  child: Text('Securo has no "Groceries" category, so only payments linked to a receipt show here.'),
                ),
              _summary(r),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 20, 16, 4),
                child: Text('Payments', style: t.textTheme.titleMedium),
              ),
              if ((r['payments'] as List).isEmpty)
                const Padding(padding: EdgeInsets.symmetric(horizontal: 16), child: Text('None this month.')),
              for (final p in r['payments'] as List) _payment(p as Map, cur),
              if ((r['unlinked_receipts'] as List).isNotEmpty) ...[
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 20, 16, 4),
                  child: Text('Receipts not linked to a payment', style: t.textTheme.titleMedium),
                ),
                for (final x in r['unlinked_receipts'] as List)
                  ListTile(
                    leading: const Icon(Icons.receipt_outlined),
                    title: Text('${x['store'] ?? 'Receipt'}'),
                    subtitle: Text(
                      [
                        if (DateTime.tryParse('${x['date']}') case final d?) LDateFormat('EEE d MMM').format(d),
                        if (x['total'] != null) '$cur ${_n(x['total']).toStringAsFixed(2)}',
                      ].join(' · '),
                    ),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => _openReceipt(x['id'] as String),
                  ),
              ],
              if (cats.isNotEmpty) ...[
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 20, 16, 4),
                  child: Text('In the bags (from ${r['receipts']} receipts)', style: t.textTheme.titleMedium),
                ),
                for (final c in cats)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(
                          children: [
                            Expanded(child: Text('${c['name']}')),
                            Text('$cur ${_n(c['amount']).toStringAsFixed(2)}'),
                          ],
                        ),
                        const SizedBox(height: 4),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(4),
                          child: LinearProgressIndicator(
                            value: catTotal == 0 ? 0 : _n(c['amount']) / catTotal,
                            minHeight: 8,
                            backgroundColor: t.colorScheme.surfaceContainerHighest,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
              const SizedBox(height: 24),
            ],
          ],
        ),
      ),
    );
  }
}
