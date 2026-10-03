import 'package:flutter/material.dart' hide Text;
import 'package:flutter/services.dart';

import '../api.dart';
import '../main.dart';
import '../widgets.dart';
import '../i18n.dart';

/// Connect AI agents (OpenClaw, Hermes, Claude...) to Kasita through its MCP server:
/// a key per agent, the address, and a ready-made command to copy.
class AgentsScreen extends StatefulWidget {
  const AgentsScreen({super.key});
  @override
  State<AgentsScreen> createState() => _AgentsScreenState();
}

class _AgentsScreenState extends State<AgentsScreen> {
  List<Map<String, dynamic>>? _keys;

  String get _url => '${Kasita.read(context).api.server.replaceAll(RegExp(r'/+$'), '')}/mcp';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    try {
      final k = await s.api.apiKeys(s.hid);
      if (mounted) setState(() => _keys = k.where((x) => x['name'] != 'Home-screen widget').toList());
    } on ApiException {
      if (mounted) setState(() => _keys = []); // only the owner sees the household's keys
    }
  }

  Future<void> _copy(String text, String what) async {
    try {
      await Clipboard.setData(ClipboardData(text: text));
      if (mounted) toast(context, '$what copied');
    } catch (_) {}
  }

  Future<void> _create() async {
    final s = Kasita.read(context);
    final name = TextEditingController(text: 'AI agent');
    var readOnly = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('New key for an agent'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: name, decoration: InputDecoration(labelText: tr('Which agent'))),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: readOnly,
                onChanged: s.household!.isOwner ? (v) => set(() => readOnly = v) : null,
                title: const Text('Read only'),
                subtitle: const Text('Can look at the pantry and list, never change them'),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Create')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final k = await s.api.createApiKey(s.hid, name.text.trim().isEmpty ? 'AI agent' : name.text.trim(),
          readOnly: readOnly || !s.household!.isOwner);
      if (!mounted) return;
      final key = k['key'] as String;
      final command = 'claude mcp add --transport http kasita $_url --header "Authorization: Bearer $key"';
      await showDialog(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Key created'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Copy it now: Kasita shows it only once.'),
                const SizedBox(height: 8),
                SelectableText(key, style: const TextStyle(fontFamily: 'monospace')),
                const SizedBox(height: 12),
                const Text('Claude Code:'),
                SelectableText(command, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => _copy(command, 'Command'), child: const Text('Copy command')),
            FilledButton(onPressed: () => _copy(key, 'Key'), child: const Text('Copy key')),
          ],
        ),
      );
      _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final s = Kasita.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('AI agents')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _create,
        icon: const Icon(Icons.key),
        label: const Text('New key'),
      ),
      body: ListView(
        padding: navBarSafe(context, const EdgeInsets.all(16)),
        children: [
          Text(
            'Agents that speak MCP (OpenClaw, Hermes, Claude, n8n…) can check the pantry, read the list, '
            'add and tick off items, and see spending and prices.',
            style: t.textTheme.bodyMedium,
          ),
          const SizedBox(height: 16),
          Text('Address', style: t.textTheme.labelLarge),
          Row(
            children: [
              Expanded(child: SelectableText(_url, style: const TextStyle(fontFamily: 'monospace'))),
              IconButton(icon: const Icon(Icons.copy), onPressed: () => _copy(_url, 'Address')),
            ],
          ),
          Text(
            'Transport: Streamable HTTP. Header: Authorization: Bearer <key>',
            style: t.textTheme.bodySmall,
          ),
          const SizedBox(height: 20),
          Text('Keys', style: t.textTheme.titleMedium),
          if (_keys == null)
            const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()))
          else if (_keys!.isEmpty)
            const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Text('None yet: tap New key.'))
          else
            for (final k in _keys!)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(k['read_only'] == true ? Icons.visibility_outlined : Icons.key),
                title: Text('${k['name']}'),
                subtitle: Text(
                  '${k['prefix']}… · ${k['read_only'] == true ? 'read only' : 'can change things'}'
                  '${k['last_used_at'] == null ? ' · never used' : ' · used ${dateFmt.format(DateTime.parse(k['last_used_at']).toLocal())}'}',
                ),
                trailing: s.household!.isOwner
                    ? IconButton(
                        tooltip: tr('Revoke'),
                        icon: const Icon(Icons.delete_outline),
                        onPressed: () async {
                          await s.api.deleteApiKey(s.hid, k['id'] as String);
                          _load();
                        },
                      )
                    : null,
              ),
        ],
      ),
    );
  }
}
