import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../widgets.dart';

/// Meal ideas from what is at home (soon-expiring things first), by the household's ChatGPT.
class CookScreen extends StatefulWidget {
  const CookScreen({super.key});
  @override
  State<CookScreen> createState() => _CookScreenState();
}

class _CookScreenState extends State<CookScreen> {
  final _note = TextEditingController();
  List<Map<String, dynamic>>? _ideas;
  bool _busy = false;
  final _added = <String>{};

  Future<void> _ask() async {
    final s = Kasita.read(context);
    setState(() => _busy = true);
    try {
      final r = await s.api.cook(s.hid, _note.text.trim().isEmpty ? null : _note.text.trim());
      if (!mounted) return;
      setState(() => _ideas = [for (final i in r['ideas'] as List) Map<String, dynamic>.from(i)]);
      if ((r['pantry'] ?? 0) == 0) toast(context, 'The pantry is empty: add what you have first');
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addMissing(Map<String, dynamic> idea) async {
    final s = Kasita.read(context);
    for (final m in List<String>.from(idea['missing'] ?? const [])) {
      await s.api.addShopping(s.hid, name: m);
    }
    s.changed();
    if (!mounted) return;
    setState(() => _added.add(idea['title']));
    toast(context, 'Added to the shopping list');
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('What can I cook?')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _note,
            decoration: const InputDecoration(
              labelText: 'Wishes (optional)',
              hintText: 'quick, no oven, something with rice…',
              border: OutlineInputBorder(),
            ),
            onSubmitted: (_) => _busy ? null : _ask(),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _busy ? null : _ask,
            icon: _busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.restaurant_menu),
            label: Text(_busy ? 'Thinking…' : (_ideas == null ? 'Suggest meals' : 'Suggest again')),
          ),
          const SizedBox(height: 8),
          Text('Uses what is in your pantry, soon-expiring things first.', style: t.textTheme.bodySmall),
          for (final idea in _ideas ?? const <Map<String, dynamic>>[])
            Card(
              margin: const EdgeInsets.only(top: 16),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text(idea['title'], style: t.textTheme.titleMedium)),
                        if ((idea['minutes'] ?? 0) > 0) Chip(label: Text('${idea['minutes']} min')),
                      ],
                    ),
                    if ((idea['why'] ?? '').isNotEmpty)
                      Text(idea['why'], style: TextStyle(color: t.colorScheme.primary)),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [for (final u in idea['uses'] as List) Chip(label: Text('$u'))],
                    ),
                    if ((idea['missing'] as List).isNotEmpty)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.shopping_cart_outlined),
                        title: Text('Missing: ${(idea['missing'] as List).join(', ')}'),
                        trailing: _added.contains(idea['title'])
                            ? const Icon(Icons.check)
                            : TextButton(onPressed: () => _addMissing(idea), child: const Text('Add to list')),
                      ),
                    ExpansionTile(
                      tilePadding: EdgeInsets.zero,
                      title: const Text('Steps'),
                      children: [
                        for (final (n, step) in (idea['steps'] as List).indexed)
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            dense: true,
                            leading: CircleAvatar(radius: 12, child: Text('${n + 1}')),
                            title: Text('$step'),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
