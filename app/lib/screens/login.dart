import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' hide Text;

import '../api.dart';
import '../main.dart';
import '../i18n.dart';

class LoginScreen extends StatefulWidget {
  final String? inviteToken;
  const LoginScreen({super.key, this.inviteToken});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _name = TextEditingController();
  final _invite = TextEditingController();
  final _server = TextEditingController();
  late bool _joining = widget.inviteToken != null;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _invite.text = widget.inviteToken ?? '';
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_server.text.isEmpty) _server.text = Kasita.read(context).api.server;
  }

  String _tokenFrom(String text) {
    final t = text.trim();
    final i = t.indexOf('/invite/');
    return i >= 0 ? t.substring(i + '/invite/'.length) : t;
  }

  Future<void> _submit() async {
    final s = Kasita.read(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      s.api.server = _server.text.trim();
      if (_joining) {
        await s.api.acceptInvite(
          token: _tokenFrom(_invite.text),
          email: _email.text.trim(),
          name: _name.text.trim(),
          password: _password.text,
        );
      } else {
        await s.api.login(_email.text.trim(), _password.text);
      }
      await s.loadHouseholds();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Could not reach the server ($e)');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          // clear of the status bar and the system navigation bar (edge to edge)
          padding: EdgeInsets.all(24) + MediaQuery.paddingOf(context),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: AutofillGroup(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(16),
                      child: Image.asset('assets/brand/kasita.png', width: 72, height: 72),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text('Kasita', textAlign: TextAlign.center, style: t.textTheme.headlineMedium),
                  const SizedBox(height: 24),
                  SegmentedButton<bool>(
                    segments: const [
                      ButtonSegment(value: false, label: Text('Sign in')),
                      ButtonSegment(value: true, label: Text('Join with invite')),
                    ],
                    selected: {_joining},
                    onSelectionChanged: (v) => setState(() => _joining = v.first),
                  ),
                  const SizedBox(height: 16),
                  if (_joining) ...[
                    TextField(
                      controller: _invite,
                      decoration: InputDecoration(labelText: tr('Invite link or code'), border: OutlineInputBorder()),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _name,
                      textCapitalization: TextCapitalization.words,
                      decoration: InputDecoration(labelText: tr('Your name'), border: OutlineInputBorder()),
                    ),
                    const SizedBox(height: 12),
                  ],
                  TextField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.email],
                    decoration: InputDecoration(labelText: tr('Email'), border: OutlineInputBorder()),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _password,
                    obscureText: true,
                    autofillHints: [_joining ? AutofillHints.newPassword : AutofillHints.password],
                    onSubmitted: (_) => _submit(),
                    decoration: InputDecoration(
                      labelText: _joining ? 'Password (at least 10 characters)' : 'Password',
                      border: const OutlineInputBorder(),
                    ),
                  ),
                  if (!kIsWeb) ...[
                    const SizedBox(height: 12),
                    TextField(
                      controller: _server,
                      keyboardType: TextInputType.url,
                      decoration: InputDecoration(labelText: tr('Server'), border: OutlineInputBorder()),
                    ),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: TextStyle(color: t.colorScheme.error)),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      child: _busy
                          ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                          : Text(_joining ? 'Join household' : 'Sign in'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Signed in but not in any household yet (e.g. the very first start).
class NoHouseholdScreen extends StatefulWidget {
  const NoHouseholdScreen({super.key});
  @override
  State<NoHouseholdScreen> createState() => _NoHouseholdScreenState();
}

class _NoHouseholdScreenState extends State<NoHouseholdScreen> {
  final _name = TextEditingController();

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Kasita'),
        actions: [IconButton(icon: const Icon(Icons.logout), tooltip: tr('Sign out'), onPressed: s.signOut)],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('You are not in a household yet. Create one, or ask someone to send you an invite.'),
                const SizedBox(height: 16),
                TextField(
                  controller: _name,
                  decoration: InputDecoration(labelText: tr('Household name'), border: OutlineInputBorder()),
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () async {
                    if (_name.text.trim().isEmpty) return;
                    await s.api.createHousehold(_name.text.trim());
                    await s.loadHouseholds();
                  },
                  child: const Text('Create household'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
