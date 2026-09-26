import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';

/// "Sign in with ChatGPT": the household's ChatGPT subscription reads receipts.
/// The server does the sign-in (device code) and keeps the tokens; this screen
/// only shows the code and waits.
class ChatGPTScreen extends StatefulWidget {
  const ChatGPTScreen({super.key});
  @override
  State<ChatGPTScreen> createState() => _ChatGPTScreenState();
}

class _ChatGPTScreenState extends State<ChatGPTScreen> {
  ChatGPTStatus? _s;
  List<String>? _models;
  Timer? _poll;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    try {
      final st = await s.api.chatgpt(s.hid);
      if (!mounted) return;
      setState(() => _s = st);
      if (st.userCode != null) _startPolling(st.interval);
      if (st.connected && s.household!.isOwner) _loadModels();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _loadModels() async {
    final s = Kasita.read(context);
    try {
      final m = await s.api.chatgptModels(s.hid);
      if (mounted) setState(() => _models = m);
    } catch (_) {
      // the list is a nicety; the current model keeps working without it
    }
  }

  void _startPolling(int seconds) {
    _poll?.cancel();
    _poll = Timer.periodic(Duration(seconds: seconds.clamp(3, 15)), (_) async {
      final s = Kasita.read(context);
      try {
        final st = await s.api.chatgptPoll(s.hid);
        if (!mounted) return;
        setState(() => _s = st);
        if (st.connected) {
          _poll?.cancel();
          toast(context, 'ChatGPT connected');
          _loadModels();
        } else if (st.userCode == null) {
          _poll?.cancel();
        }
      } on ApiException catch (e) {
        _poll?.cancel();
        if (mounted) {
          toast(context, e.message, error: true);
          _load();
        }
      }
    });
  }

  Future<void> _connect() async {
    final s = Kasita.read(context);
    setState(() => _busy = true);
    try {
      final st = await s.api.chatgptConnect(s.hid);
      if (!mounted) return;
      setState(() => _s = st);
      _startPolling(st.interval);
      if (st.verificationUrl != null) _open(st.verificationUrl!);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _open(String url) async {
    if (_s?.userCode != null) await Clipboard.setData(ClipboardData(text: _s!.userCode!));
    await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  }

  Future<void> _disconnect() async {
    final s = Kasita.read(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Disconnect ChatGPT?'),
        content: const Text('Receipts can no longer be read until someone connects again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Disconnect')),
        ],
      ),
    );
    if (ok != true) return;
    await s.api.chatgptDisconnect(s.hid);
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    final st = _s;
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('ChatGPT')),
      body: st == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Text(
                  'Kasita uses your ChatGPT subscription to read grocery receipts. '
                  'No API key and no extra cost: it counts toward your normal ChatGPT usage.',
                  style: t.textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                if (st.connected) ...[
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.check_circle, color: t.colorScheme.primary),
                    title: Text(st.email ?? 'Connected'),
                    subtitle: Text(['ChatGPT', if (st.plan != null) st.plan!].join(' · ')),
                  ),
                  if (s.household!.isOwner) ...[
                    const SizedBox(height: 8),
                    DropdownButtonFormField<String>(
                      initialValue: st.model,
                      decoration: const InputDecoration(labelText: 'Model', border: OutlineInputBorder()),
                      items: [
                        for (final m in {...?_models, if (st.model != null) st.model!})
                          DropdownMenuItem(value: m, child: Text(m)),
                      ],
                      onChanged: (m) async {
                        if (m == null) return;
                        final updated = await s.api.chatgptSetModel(s.hid, m);
                        if (mounted) setState(() => _s = updated);
                      },
                    ),
                    const SizedBox(height: 16),
                    OutlinedButton.icon(
                      onPressed: _disconnect,
                      icon: const Icon(Icons.link_off),
                      label: const Text('Disconnect'),
                    ),
                  ],
                ] else if (st.userCode != null) ...[
                  Text('1. Open the ChatGPT sign-in page', style: t.textTheme.titleSmall),
                  const SizedBox(height: 8),
                  FilledButton.tonalIcon(
                    onPressed: () => _open(st.verificationUrl!),
                    icon: const Icon(Icons.open_in_new),
                    label: const Text('Open auth.openai.com'),
                  ),
                  const SizedBox(height: 20),
                  Text('2. Sign in and enter this code', style: t.textTheme.titleSmall),
                  const SizedBox(height: 8),
                  Center(
                    child: SelectableText(
                      st.userCode!,
                      style: t.textTheme.displaySmall?.copyWith(fontFamily: 'monospace', letterSpacing: 4),
                    ),
                  ),
                  Center(
                    child: TextButton.icon(
                      onPressed: () {
                        Clipboard.setData(ClipboardData(text: st.userCode!));
                        toast(context, 'Code copied');
                      },
                      icon: const Icon(Icons.copy, size: 18),
                      label: const Text('Copy code'),
                    ),
                  ),
                  const SizedBox(height: 20),
                  const Row(
                    children: [
                      SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                      SizedBox(width: 12),
                      Expanded(child: Text('Waiting for you to approve… this page updates by itself.')),
                    ],
                  ),
                ] else if (s.household!.isOwner)
                  FilledButton.icon(
                    onPressed: _busy ? null : _connect,
                    icon: const Icon(Icons.login),
                    label: const Text('Sign in with ChatGPT'),
                  )
                else
                  const Text('Ask the household owner to connect ChatGPT.'),
              ],
            ),
    );
  }
}
