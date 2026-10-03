import 'package:flutter/material.dart' hide Text;

import '../main.dart';
import '../nearby/nearby.dart';
import '../widgets.dart';
import '../i18n.dart';

/// Settings for the "You're near a store" reminders (Android app only).
class NearbyScreen extends StatefulWidget {
  const NearbyScreen({super.key});
  @override
  State<NearbyScreen> createState() => _NearbyScreenState();
}

class _NearbyScreenState extends State<NearbyScreen> {
  NearbySettings? _s;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    loadNearbySettings().then((v) {
      if (mounted) setState(() => _s = v);
    });
  }

  Future<void> _save(NearbySettings next) async {
    setState(() => _s = next);
    await saveNearbySettings(next);
  }

  Future<void> _turnOn() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Remind me near a store'),
        content: const Text(
          'Kasita will ask for two things:\n\n'
          '• Location, "Allow all the time". Android itself watches the stores on your map and wakes '
          'Kasita when you get close; Kasita does not track you and your location is not sent anywhere.\n\n'
          '• Notifications, to show the reminder.\n\n'
          'You can switch this off again at any time.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Not now')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Continue')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    final problem = await enableNearby();
    if (!mounted) return;
    setState(() => _busy = false);
    if (problem != null) return toast(context, problem, error: true);
    final s = Kasita.read(context);
    await _save(_s!.copyWith(enabled: true));
    await refreshNearby(s.api, s.hid, s.stores);
    if (mounted) toast(context, 'On. Kasita will remind you near your stores.');
  }

  Future<void> _turnOff() async {
    await disableNearby();
    if (mounted) setState(() => _s = _s!.copyWith(enabled: false));
  }

  String _time(int minutes) =>
      MaterialLocalizations.of(context)
          .formatTimeOfDay(TimeOfDay(hour: minutes ~/ 60, minute: minutes % 60), alwaysUse24HourFormat: true);

  Future<void> _pickTime(bool from) async {
    final cur = from ? _s!.quietFrom : _s!.quietTo;
    final t = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: cur ~/ 60, minute: cur % 60),
    );
    if (t == null) return;
    final m = t.hour * 60 + t.minute;
    await _save(from ? _s!.copyWith(quietFrom: m) : _s!.copyWith(quietTo: m));
  }

  @override
  Widget build(BuildContext context) {
    final st = Kasita.of(context);
    final s = _s;
    if (!nearbySupported) {
      return Scaffold(
        appBar: AppBar(title: const Text('Near a store')),
        body: const EmptyState(
          icon: Icons.near_me_outlined,
          title: 'Only in the Android app',
          message: 'Store reminders need the phone\'s location, so they live in the Android app.',
        ),
      );
    }
    if (s == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final located = st.stores.where((x) => x.located).toList();
    final unlocated = st.stores.where((x) => !x.located).toList();
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Near a store')),
      body: ListView(
        children: [
          SwitchListTile(
            secondary: const Icon(Icons.near_me_outlined),
            title: const Text('Remind me near a store'),
            subtitle: const Text(
              'A notification when you pass a store where things on your list are cheapest, '
              'or where you usually buy them. Off unless you switch it on.',
            ),
            value: s.enabled,
            onChanged: _busy ? null : (v) => v ? _turnOn() : _turnOff(),
          ),
          if (s.enabled) ...[
            ListTile(
              leading: const Icon(Icons.radar),
              title: const Text('How near'),
              trailing: DropdownButton<int>(
                value: s.radiusMeters,
                items: [
                  for (final m in const [100, 150, 250, 400]) DropdownMenuItem(value: m, child: Text('$m m')),
                ],
                onChanged: (v) => v == null ? null : _save(s.copyWith(radiusMeters: v)),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.timer_outlined),
              title: const Text('At most once per store every'),
              trailing: DropdownButton<int>(
                value: s.everyHours,
                items: [
                  for (final h in const [2, 4, 6, 12, 24]) DropdownMenuItem(value: h, child: Text('$h hours')),
                ],
                onChanged: (v) => v == null ? null : _save(s.copyWith(everyHours: v)),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.bedtime_outlined),
              title: const Text('Quiet hours'),
              subtitle: Text(
                s.quietFrom == s.quietTo
                    ? 'None: reminders any time'
                    : 'No reminders from ${_time(s.quietFrom)} to ${_time(s.quietTo)}',
              ),
              trailing: Wrap(
                spacing: 4,
                children: [
                  TextButton(onPressed: () => _pickTime(true), child: Text(_time(s.quietFrom))),
                  TextButton(onPressed: () => _pickTime(false), child: Text(_time(s.quietTo))),
                ],
              ),
            ),
            const Divider(),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Text('Stores', style: t.textTheme.titleSmall),
            ),
            if (located.isEmpty)
              const ListTile(
                title: Text('No store has a location yet'),
                subtitle: Text('Add an address to a store, or place it on the map.'),
              ),
            for (final x in located)
              SwitchListTile(
                title: Text(x.name),
                subtitle: x.address == null ? null : Text(x.address!),
                value: !s.mutedStores.contains(x.id),
                onChanged: (on) =>
                    _save(s.copyWith(mutedStores: on ? ({...s.mutedStores}..remove(x.id)) : {...s.mutedStores, x.id})),
              ),
            if (unlocated.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                child: Text(
                  'Not on the map yet: ${unlocated.map((x) => x.name).join(', ')}. '
                  'Add their address in Stores, or place them on the map.',
                  style: TextStyle(color: t.colorScheme.onSurfaceVariant),
                ),
              ),
          ],
        ],
      ),
    );
  }
}
