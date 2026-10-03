import 'package:flutter/material.dart' hide Text;
import 'package:flutter/services.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../nearby/nearby.dart';
import '../updates/update_ui.dart';
import '../widgets.dart';
import 'activity.dart';
import 'admin.dart';
import 'agents.dart';
import 'bills.dart';
import 'chatgpt.dart';
import 'fun_stats.dart';
import 'map.dart';
import 'nearby.dart';
import 'receipts.dart';
import 'recipes.dart';
import 'securo.dart';
import 'securo_month.dart';
import 'spending.dart';
import 'stores.dart';
import '../i18n.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  List<Member>? _members;
  bool _isAdmin = false; // runs this Kasita server: sees everyone

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _loadMembers();
  }

  Future<void> _loadMembers() async {
    final s = Kasita.read(context);
    final m = await s.api.members(s.hid);
    if (mounted) setState(() => _members = m);
    try {
      final me = await s.api.me();
      if (mounted) setState(() => _isAdmin = me['is_admin'] == true);
    } catch (_) {}
  }

  Future<void> _invite() async {
    final s = Kasita.read(context);
    final own = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.group_add_outlined),
              title: Text('Join ${s.household!.name}'),
              subtitle: const Text('For family: they share this pantry, shopping list and receipts'),
              onTap: () => Navigator.pop(c, false),
            ),
            ListTile(
              leading: const Icon(Icons.add_home_outlined),
              title: const Text('Their own household'),
              subtitle: const Text('Kasita for themselves: a separate, empty household. They see nothing of yours.'),
              onTap: () => Navigator.pop(c, true),
            ),
          ],
        ),
      ),
    );
    if (own == null || !mounted) return;
    try {
      final inv = await s.api.createInvite(s.hid, ownHousehold: own);
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
              Text(
                inv['own_household'] == true
                    ? 'Send this link to the person. It creates their account with a household of their own. It works once and expires in 7 days.'
                    : 'Send this link to the person you want to add to ${s.household!.name}. It works once and expires in 7 days.',
              ),
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
            leading: const Icon(Icons.bolt_outlined),
            title: const Text('Bills'),
            subtitle: const Text('Photograph utility bills and book them in Securo'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const BillsScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.menu_book_outlined),
            title: const Text('Recipes'),
            subtitle: const Text('Saved meals, Cooked it'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const RecipesScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.calendar_month_outlined),
            title: const Text('Week plan'),
            subtitle: const Text("What's for dinner, and what to buy for it"),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const WeekPlanScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.history),
            title: const Text('Activity'),
            subtitle: const Text('Who bought, used and scanned what'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ActivityScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.bar_chart),
            title: const Text('Spending'),
            subtitle: const Text('What groceries cost, per category and store'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SpendingScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.fact_check_outlined),
            title: const Text('Groceries in Securo'),
            subtitle: const Text('Each month: what you paid, and which payments have a receipt'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SecuroMonthScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.map_outlined),
            title: const Text('Map'),
            subtitle: const Text('Where you shop, and what you spend there'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const StoreMapScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.emoji_events_outlined),
            title: const Text('Fun stats'),
            subtitle: const Text('Home turf, favourite days, minimarkets vs supermarkets'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const FunStatsScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.storefront_outlined),
            title: const Text('Stores'),
            subtitle: const Text('Address, phone and CRIB, filled in from receipts'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const StoresScreen())),
          ),
          if (nearbySupported)
            ListTile(
              leading: const Icon(Icons.near_me_outlined),
              title: const Text('Near a store'),
              subtitle: const Text('A reminder when you pass a store where your list is cheapest'),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const NearbyScreen())),
            ),
          ListTile(
            leading: const Icon(Icons.auto_awesome_outlined),
            title: const Text('ChatGPT'),
            subtitle: const Text('Reads receipts with your ChatGPT subscription'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ChatGPTScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.language),
            title: const Text('Language'),
            subtitle: Text(supportedLangs[appLang.value] ?? 'English'),
            onTap: () async {
              final pick = await showModalBottomSheet<String>(
                context: context,
                showDragHandle: true,
                builder: (c) => SafeArea(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      for (final e in supportedLangs.entries)
                        ListTile(
                          leading: Icon(e.key == appLang.value ? Icons.radio_button_checked : Icons.radio_button_unchecked),
                          title: Text(e.value),
                          onTap: () => Navigator.pop(c, e.key),
                        ),
                      const Padding(
                        padding: EdgeInsets.fromLTRB(16, 4, 16, 12),
                        child: Text(
                          'Texts the app does not know in your language stay in English.',
                          style: TextStyle(fontSize: 12),
                        ),
                      ),
                    ],
                  ),
                ),
              );
              if (pick != null && pick != appLang.value) await setLang(pick); // the whole app restarts in the new language
            },
          ),
          if (_isAdmin)
            ListTile(
              leading: const Icon(Icons.admin_panel_settings_outlined),
              title: const Text('Server admin'),
              subtitle: const Text('Everyone on this Kasita: users, households, sessions'),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AdminScreen())),
            ),
          ListTile(
            leading: const Icon(Icons.smart_toy_outlined),
            title: const Text('AI agents'),
            subtitle: const Text('Let OpenClaw, Hermes or Claude use Kasita (MCP)'),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AgentsScreen())),
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
              subtitle: const Text('To this household, or to a household of their own'),
              onTap: _invite,
            ),
          const Divider(),
          const UpdateSettingsTiles(),
          ListTile(leading: const Icon(Icons.dns_outlined), title: const Text('Server'), subtitle: Text(s.api.server)),
          ListTile(
            leading: const Icon(Icons.password),
            title: const Text('Change password'),
            subtitle: const Text('Signs out your other devices'),
            onTap: () => showDialog(context: context, builder: (_) => const _ChangePasswordDialog()),
          ),
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

class _ChangePasswordDialog extends StatefulWidget {
  const _ChangePasswordDialog();
  @override
  State<_ChangePasswordDialog> createState() => _ChangePasswordDialogState();
}

class _ChangePasswordDialogState extends State<_ChangePasswordDialog> {
  final _current = TextEditingController();
  final _next = TextEditingController();
  final _again = TextEditingController();
  String? _error;
  bool _busy = false;

  Future<void> _save() async {
    if (_next.text.length < 10) return setState(() => _error = 'Use at least 10 characters');
    if (_next.text != _again.text) return setState(() => _error = 'The new passwords do not match');
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await Kasita.read(context).api.changePassword(_current.text, _next.text);
      if (!mounted) return;
      Navigator.pop(context);
      toast(context, 'Password changed. Other devices were signed out.');
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Change password'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _current,
            obscureText: true,
            autofillHints: const [AutofillHints.password],
            decoration: InputDecoration(labelText: tr('Current password')),
          ),
          TextField(
            controller: _next,
            obscureText: true,
            autofillHints: const [AutofillHints.newPassword],
            decoration: InputDecoration(labelText: tr('New password'), helperText: tr('At least 10 characters')),
          ),
          TextField(
            controller: _again,
            obscureText: true,
            decoration: InputDecoration(labelText: tr('New password again')),
            onSubmitted: (_) => _busy ? null : _save(),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _save, child: const Text('Change')),
      ],
    );
  }
}
