import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api.dart';
import '../main.dart';
import '../widgets.dart';

/// Who did what in the household: bought, used, opened, put on the list, scanned a receipt.
class ActivityScreen extends StatefulWidget {
  const ActivityScreen({super.key});
  @override
  State<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends State<ActivityScreen> {
  List<Map<String, dynamic>>? _feed;
  static final _when = DateFormat('d MMM, HH:mm');

  static const _icons = {
    'purchase': Icons.add_shopping_cart,
    'consume': Icons.remove_circle_outline,
    'spoil': Icons.delete_outline,
    'open': Icons.lock_open,
    'list': Icons.playlist_add,
    'receipt': Icons.receipt_long_outlined,
  };

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    try {
      final f = await s.api.activity(s.hid);
      if (mounted) setState(() => _feed = f);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final feed = _feed;
    return Scaffold(
      appBar: AppBar(title: const Text('Activity')),
      body: feed == null
          ? const Center(child: CircularProgressIndicator())
          : feed.isEmpty
          ? const EmptyState(
              icon: Icons.history,
              title: 'Nothing yet',
              message: 'Buying, using and scanning shows up here.',
            )
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                children: [
                  for (final a in feed)
                    ListTile(
                      leading: Icon(_icons[a['kind']] ?? Icons.circle_outlined),
                      title: Text('${a['who'] ?? 'Someone'} ${a['text']}'),
                      subtitle: Text(_when.format(DateTime.parse(a['at']).toLocal())),
                    ),
                ],
              ),
            ),
    );
  }
}
