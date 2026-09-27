import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'chatgpt.dart';
import 'receipts.dart';
import 'securo.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  List<Member>? _members;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _loadMembers();
  }

  Future<void> _loadMembers() async {
    final s = Kasita.read(context);
    final m = await s.api.members(s.hid);
    if (mounted) setState(() => _members = m);
  }

  Future<void> _invite() async {
    final s = Kasita.read(context);
    try {
      final inv = await s.api.createInvite(s.hid);
      final url = inv['url'] as String;
      await Clipboard.setData(ClipboardData(text: url));
      if (!mounted) return;
      await showDialog(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Invite link copied'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Send this link to the person you want to add. It works once and expires in 7 days.'),
              const SizedBox(height: 12),
              SelectableText(url, style: const TextStyle(fontSize: 12)),
            ],
          ),
          actions: [FilledButton(onPressed: () => Navigator.pop(c), child: const Text('Done'))],
        ),
      );
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    final h = s.household!;
    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.house_outlined),
            title: Text(h.name),
            subtitle: Text('Household · prices in ${h.currency}'),
            trailing: s.households.length > 1 ? const Icon(Icons.swap_horiz) : null,
            onTap: s.households.length > 1
                ? () => showModalBottomSheet(
                    context: context,
                    builder: (c) => SafeArea(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          for (final other in s.households)
                            ListTile(
                              title: Text(other.name),
                              trailing: other.id == h.id ? const Icon(Icons.check) : null,
                              onTap: () {
                                Navigator.pop(c);
                                s.selectHousehold(other);
                              },
                            ),
                        ],
                      ),
                    ),
                  )
                : null,
          ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.receipt_long_outlined),
            title: const Text('Receipts'),
            subtitle: const Text('Photograph a receipt to fill the pantry with prices'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ReceiptsScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.auto_awesome_outlined),
            title: const Text('ChatGPT'),
            subtitle: const Text('Reads receipts with your ChatGPT subscription'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ChatGPTScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.account_balance_wallet_outlined),
            title: const Text('Securo'),
            subtitle: const Text('Link receipts to card payments'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SecuroScreen())),
          ),
          const Divider(),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text('Members', style: Theme.of(context).textTheme.titleSmall),
          ),
          for (final m in _members ?? const <Member>[])
            ListTile(
              leading: CircleAvatar(child: Text(m.name.isEmpty ? '?' : m.name[0].toUpperCase())),
              title: Text(m.name),
              subtitle: Text(m.email),
              trailing: m.role == 'owner' ? const Chip(label: Text('owner')) : null,
            ),
          if (h.isOwner)
            ListTile(
              leading: const Icon(Icons.person_add_alt),
              title: const Text('Invite someone'),
              subtitle: const Text('Creates a one-time link'),
              onTap: _invite,
            ),
          const Divider(),
          ListTile(leading: const Icon(Icons.dns_outlined), title: const Text('Server'), subtitle: Text(s.api.server)),
          ListTile(
            leading: const Icon(Icons.logout),
            title: const Text('Sign out'),
            onTap: () async {
              final ok = await showDialog<bool>(
                context: context,
                builder: (c) => AlertDialog(
                  title: const Text('Sign out?'),
                  actions: [
                    TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
                    FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Sign out')),
                  ],
                ),
              );
              if (ok == true) await s.signOut();
            },
          ),
        ],
      ),
    );
  }
}
