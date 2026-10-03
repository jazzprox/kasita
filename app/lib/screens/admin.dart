import 'package:flutter/material.dart' hide Text;
import 'package:flutter/services.dart';

import '../api.dart';
import '../main.dart';
import '../widgets.dart';
import '../i18n.dart';

/// Server admin: every user and household on this Kasita (admins only).
class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});
  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  Map<String, dynamic>? _overview;
  List<Map<String, dynamic>>? _users, _homes;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final api = Kasita.read(context).api;
    try {
      final o = await api.adminOverview();
      final u = await api.adminUsers();
      final h = await api.adminHouseholds();
      if (mounted) {
        setState(() {
          _overview = o;
          _users = u;
          _homes = h;
          _error = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  String _ago(dynamic iso) {
    final d = iso == null ? null : DateTime.tryParse('$iso')?.toLocal();
    if (d == null) return 'never';
    final m = DateTime.now().difference(d).inMinutes;
    if (m < 2) return 'just now';
    if (m < 60) return '$m min ago';
    if (m < 60 * 24) return '${m ~/ 60} h ago';
    if (m < 60 * 24 * 14) return '${m ~/ (60 * 24)} days ago';
    return dateFmtYear.format(d);
  }

  String _mb(dynamic b) => b == null ? '—' : '${((b as num) / 1e6).toStringAsFixed(b < 1e7 ? 1 : 0)} MB';

  Future<void> _userActions(Map<String, dynamic> u) async {
    final api = Kasita.read(context).api;
    final pick = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(title: Text('${u['name']}'), subtitle: Text('${u['email']}')),
            ListTile(
              leading: const Icon(Icons.password),
              title: const Text('Reset password'),
              subtitle: const Text('Makes a temporary password and signs them out everywhere'),
              onTap: () => Navigator.pop(c, 'reset'),
            ),
            ListTile(
              leading: const Icon(Icons.logout),
              title: const Text('Sign out everywhere'),
              subtitle: Text('${u['sessions']} active session${u['sessions'] == 1 ? '' : 's'}'),
              onTap: () => Navigator.pop(c, 'signout'),
            ),
            ListTile(
              leading: Icon(u['is_admin'] == true ? Icons.remove_moderator_outlined : Icons.add_moderator_outlined),
              title: Text(u['is_admin'] == true ? 'Remove admin' : 'Make admin'),
              onTap: () => Navigator.pop(c, 'admin'),
            ),
          ],
        ),
      ),
    );
    if (pick == null || !mounted) return;
    try {
      if (pick == 'reset') {
        final temp = await api.adminResetPassword(u['id']);
        if (!mounted) return;
        await showDialog(
          context: context,
          builder: (c) => AlertDialog(
            title: const Text('Temporary password'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Give this to ${u['name']}. They sign in with it and change it under More.'),
                const SizedBox(height: 12),
                SelectableText(temp, style: const TextStyle(fontFamily: 'monospace', fontSize: 18)),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () async {
                  try {
                    await Clipboard.setData(ClipboardData(text: temp));
                  } catch (_) {}
                },
                child: const Text('Copy'),
              ),
              FilledButton(onPressed: () => Navigator.pop(c), child: const Text('Done')),
            ],
          ),
        );
      } else if (pick == 'signout') {
        final n = await api.adminSignOut(u['id']);
        if (mounted) toast(context, 'Signed out of $n session${n == 1 ? '' : 's'}');
      } else {
        await api.adminSetAdmin(u['id'], u['is_admin'] != true);
      }
      _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Widget _stat(String label, String value) {
    final t = Theme.of(context);
    return SizedBox(
      width: 104,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(value, style: t.textTheme.titleLarge),
          Text(label, style: t.textTheme.bodySmall),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final o = _overview;
    return Scaffold(
      appBar: AppBar(title: const Text('Server admin')),
      body: _error != null
          ? EmptyState(icon: Icons.lock_outline, title: 'Not available', message: _error!)
          : o == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: navBarSafe(context, const EdgeInsets.all(16)),
                children: [
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      _stat('users', '${o['users']}'),
                      _stat('active this week', '${o['active_this_week']}'),
                      _stat('households', '${o['households']}'),
                      _stat('products', '${o['products']}'),
                      _stat('receipts', '${o['receipts']}'),
                      _stat('bills', '${o['bills']}'),
                      _stat('photos', _mb(o['uploads_bytes'])),
                      _stat('database', _mb(o['database_bytes'])),
                    ],
                  ),
                  const SizedBox(height: 20),
                  Text('Users', style: t.textTheme.titleMedium),
                  for (final u in _users!)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: CircleAvatar(child: Text('${u['name']}'.isEmpty ? '?' : '${u['name']}'[0].toUpperCase())),
                      title: Text('${u['name']}${u['is_admin'] == true ? '  · admin' : ''}'),
                      subtitle: Text(
                        '${u['email']}\n'
                        '${[for (final h in u['households'] as List) '${h['name']} (${h['role']})'].join(', ')}\n'
                        'Seen ${_ago(u['last_seen'])} · ${u['sessions']} session${u['sessions'] == 1 ? '' : 's'}'
                        '${(u['api_keys'] ?? 0) > 0 ? ' · ${u['api_keys']} API key${u['api_keys'] == 1 ? '' : 's'}' : ''}',
                      ),
                      isThreeLine: true,
                      trailing: const Icon(Icons.more_vert),
                      onTap: () => _userActions(u),
                    ),
                  const SizedBox(height: 16),
                  Text('Households', style: t.textTheme.titleMedium),
                  for (final h in _homes!)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.home_outlined),
                      title: Text('${h['name']} (${h['currency']})'),
                      subtitle: Text(
                        '${[for (final m in h['members'] as List) '${m['name']}${m['role'] == 'owner' ? ' ★' : ''}'].join(', ')}\n'
                        '${h['products']} products · ${h['in_stock']} batches at home · ${h['receipts']} receipts'
                        '${(h['connected'] as List).isEmpty ? '' : ' · ${(h['connected'] as List).join(', ')}'}\n'
                        'Last activity ${_ago(h['last_activity'])}'
                        '${(h['open_invites'] ?? 0) > 0 ? ' · ${h['open_invites']} open invite(s)' : ''}',
                      ),
                      isThreeLine: true,
                    ),
                ],
              ),
            ),
    );
  }
}
