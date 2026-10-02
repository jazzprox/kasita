import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'receipts.dart' show money;

/// Connect Securo (the finance app) so receipts can be matched to card payments.
class SecuroScreen extends StatefulWidget {
  const SecuroScreen({super.key});
  @override
  State<SecuroScreen> createState() => _SecuroScreenState();
}

class _SecuroScreenState extends State<SecuroScreen> {
  Map<String, dynamic>? _s;
  final _url = TextEditingController(text: 'https://fin.jazzproxy.com');
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    final st = await s.api.securo(s.hid);
    if (mounted) setState(() => _s = st);
  }

  Future<void> _connect() async {
    final s = Kasita.read(context);
    setState(() => _busy = true);
    try {
      final st = await s.api.securoConnect(s.hid, _url.text.trim(), _email.text.trim(), _password.text);
      _password.clear();
      if (!mounted) return;
      setState(() => _s = st);
      toast(context, 'Securo connected');
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    final st = _s;
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Securo')),
      body: st == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: navBarSafe(context, const EdgeInsets.all(20)),
              children: [
                Text(
                  'Link receipts to the card payment in Securo: the receipt photo is attached to the payment '
                  'and its note says what you bought. Kasita only reads Securo until you link a receipt.',
                  style: t.textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                if (st['connected'] == true) ...[
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.check_circle, color: t.colorScheme.primary),
                    title: Text(st['email'] ?? 'Connected'),
                    subtitle: Text(st['url'] ?? ''),
                  ),
                  if (s.household!.isOwner)
                    OutlinedButton.icon(
                      onPressed: () async {
                        await s.api.securoDisconnect(s.hid);
                        _load();
                      },
                      icon: const Icon(Icons.link_off),
                      label: const Text('Disconnect'),
                    ),
                ] else if (s.household!.isOwner) ...[
                  TextField(
                    controller: _url,
                    decoration: const InputDecoration(labelText: 'Securo address', border: OutlineInputBorder()),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    decoration: const InputDecoration(labelText: 'Securo email', border: OutlineInputBorder()),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _password,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'Securo password',
                      helperText: 'Used once to sign in; Kasita keeps only Securo\'s access token',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _busy ? null : _connect, child: const Text('Connect Securo')),
                ] else
                  const Text('Ask the household owner to connect Securo.'),
              ],
            ),
    );
  }
}

/// On a receipt: find the matching card payment and link it.
class SecuroPaymentSection extends StatefulWidget {
  final Receipt receipt;
  final ValueChanged<Receipt> onChanged;
  const SecuroPaymentSection({super.key, required this.receipt, required this.onChanged});
  @override
  State<SecuroPaymentSection> createState() => _SecuroPaymentSectionState();
}

class _SecuroPaymentSectionState extends State<SecuroPaymentSection> {
  List<SecuroPayment>? _found;
  String? _error;
  bool _busy = false;

  Future<void> _search() async {
    final s = Kasita.read(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final c = await s.api.securoCandidates(s.hid, widget.receipt.id);
      if (mounted) setState(() => _found = c);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _link(SecuroPayment p) async {
    final s = Kasita.read(context);
    var photo = true, note = true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: Text('Link to ${p.description ?? 'this payment'}?'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: photo,
                onChanged: (v) => set(() => photo = v ?? true),
                title: const Text('Attach the receipt photo in Securo'),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: note,
                onChanged: (v) => set(() => note = v ?? true),
                title: const Text('Add what was bought to its note'),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Link')),
          ],
        ),
      ),
    );
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      final r = await s.api.securoLink(s.hid, widget.receipt.id, p.id, photo: photo, note: note);
      widget.onChanged(r);
      if (mounted) toast(context, 'Linked to the Securo payment');
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.receipt;
    final t = Theme.of(context);
    if (r.securoTransactionId != null) {
      return ListTile(
        leading: Icon(Icons.credit_card, color: t.colorScheme.primary),
        title: const Text('Linked to a card payment in Securo'),
        trailing: TextButton(
          onPressed: _busy
              ? null
              : () async {
                  final s = Kasita.read(context);
                  widget.onChanged(await s.api.securoUnlink(s.hid, r.id));
                },
          child: const Text('Unlink'),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ListTile(
          leading: const Icon(Icons.credit_card_outlined),
          title: const Text('Card payment'),
          subtitle: Text(
            _error ??
                (_found == null
                    ? 'Find this purchase in Securo'
                    : _found!.isEmpty
                    ? 'No payment of ${money(r.total)} around this date yet'
                    : 'Tap the payment that belongs to this receipt'),
          ),
          trailing: _busy
              ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
              : TextButton(onPressed: r.total == null ? null : _search, child: const Text('Find')),
        ),
        for (final p in _found ?? const <SecuroPayment>[])
          ListTile(
            contentPadding: const EdgeInsets.only(left: 72, right: 16),
            title: Text(p.description ?? 'Payment'),
            subtitle: Text(
              [
                if (p.date != null) dateFmt.format(p.date!),
                if (p.notes != null) p.notes!,
                if (p.attachmentCount > 0) '${p.attachmentCount} attachment(s)',
              ].join(' · '),
            ),
            trailing: Text('${p.currency ?? ''} ${money(p.amount)}'),
            onTap: () => _link(p),
          ),
      ],
    );
  }
}
