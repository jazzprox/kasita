import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../main.dart';
import '../nearby/nearby.dart';
import '../widgets.dart';
import 'stores.dart';

/// Where you shop: a pin per store, bigger where you spend more. OpenStreetMap tiles.
class StoreMapScreen extends StatefulWidget {
  const StoreMapScreen({super.key});
  @override
  State<StoreMapScreen> createState() => _StoreMapScreenState();
}

class _StoreMapScreenState extends State<StoreMapScreen> {
  static const _curacao = LatLng(12.17, -68.98);
  final _map = MapController();
  List<Map<String, dynamic>>? _stores;
  String? _placing; // store id waiting for a tap on the map
  (double, double)? _home; // for the travel stat

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    try {
      final rows = await s.api.storeMap(s.hid);
      final home = await s.api.home(s.hid);
      if (mounted) {
        setState(() {
          _stores = rows;
          _home = home;
        });
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  static double? _d(dynamic v) => v == null ? null : double.tryParse('$v');

  List<Map<String, dynamic>> get _located => [
    for (final x in _stores ?? const <Map<String, dynamic>>[])
      if (x['lat'] != null && x['lon'] != null) x,
  ];

  Future<void> _place(String storeId, LatLng at) async {
    final s = Kasita.read(context);
    setState(() => _placing = null);
    try {
      await s.api.updateStore(s.hid, storeId, {'lat': at.latitude, 'lon': at.longitude});
      await s.reloadStores();
      refreshNearby(s.api, s.hid, s.stores); // store reminders follow the pin
      await _load();
      if (mounted) toast(context, 'Pin placed');
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  /// Long-press: which store is here?
  Future<void> _longPress(LatLng at) async {
    final rows = [...?_stores]..sort((a, b) => (a['lat'] == null ? 0 : 1).compareTo(b['lat'] == null ? 0 : 1));
    final id = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            ListTile(
              leading: const Icon(Icons.home_outlined),
              title: const Text('Home is here'),
              subtitle: const Text('Only for the "how far do you travel" stat'),
              onTap: () => Navigator.pop(c, '#home'),
            ),
            if (_home != null)
              ListTile(
                leading: const Icon(Icons.close),
                title: const Text('Remove home'),
                onTap: () => Navigator.pop(c, '#nohome'),
              ),
            const Divider(),
            const ListTile(title: Text('Which store is here?')),
            for (final x in rows)
              ListTile(
                leading: Icon(x['lat'] == null ? Icons.add_location_alt_outlined : Icons.edit_location_alt_outlined),
                title: Text('${x['name']}'),
                subtitle: Text(x['lat'] == null ? 'Not on the map yet' : 'Move its pin here'),
                onTap: () => Navigator.pop(c, x['id'] as String),
              ),
          ],
        ),
      ),
    );
    if (!mounted) return;
    if (id == '#home' || id == '#nohome') {
      final s = Kasita.read(context);
      try {
        await s.api.setHome(s.hid, id == '#home' ? at.latitude : null, id == '#home' ? at.longitude : null);
        if (mounted) setState(() => _home = id == '#home' ? (at.latitude, at.longitude) : null);
      } on ApiException catch (e) {
        if (mounted) toast(context, e.message, error: true);
      }
    } else if (id != null) {
      await _place(id, at);
    }
  }

  Future<void> _showStore(Map<String, dynamic> x) async {
    final s = Kasita.read(context);
    final cur = s.household!.currency;
    final action = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (c) => _StoreSheet(store: x, currency: cur),
    );
    if (!mounted || action == null) return;
    if (action == 'move') {
      setState(() => _placing = x['id'] as String);
    } else if (action == 'edit') {
      final st = s.stores.where((e) => e.id == x['id']).firstOrNull ?? await s.api.store(s.hid, x['id'] as String);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute(builder: (_) => StoreEditScreen(store: st)));
      await _load();
    }
  }

  Future<void> _unlocated() async {
    final s = Kasita.read(context);
    final rows = [
      for (final x in _stores ?? const <Map<String, dynamic>>[])
        if (x['lat'] == null) x,
    ];
    final pick = await showModalBottomSheet<(String, String)>(
      context: context,
      showDragHandle: true,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(
              title: Text('Not on the map yet'),
              subtitle: Text('Look a store up by its address, or long-press the map where it is.'),
            ),
            for (final x in rows)
              ListTile(
                title: Text('${x['name']}'),
                subtitle: Text(x['address'] == null ? 'No address' : '${x['address']}'),
                trailing: Wrap(
                  children: [
                    IconButton(
                      tooltip: 'Look it up on the map',
                      icon: const Icon(Icons.travel_explore),
                      onPressed: () => Navigator.pop(c, ('find', x['id'] as String)),
                    ),
                    IconButton(
                      tooltip: 'Place it by hand',
                      icon: const Icon(Icons.add_location_alt_outlined),
                      onPressed: () => Navigator.pop(c, ('place', x['id'] as String)),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
    if (pick == null || !mounted) return;
    final (what, id) = pick;
    if (what == 'place') {
      setState(() => _placing = id);
      return;
    }
    try {
      final st = await s.api.geocodeStore(s.hid, id);
      await s.reloadStores();
      await _load();
      if (!mounted) return;
      if (st.located) {
        _map.move(LatLng(st.lat!, st.lon!), 16);
        toast(context, 'Found ${st.name}');
      } else {
        toast(context, 'Not found on OpenStreetMap. Long-press the map where it is.');
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final located = _located;
    final unlocated = (_stores?.length ?? 0) - located.length;
    final maxSpent = located.map((x) => _d(x['total']) ?? 0).fold<double>(0, math.max);
    final placingName = _stores?.where((x) => x['id'] == _placing).map((x) => x['name']).firstOrNull;
    final points = [for (final x in located) LatLng(_d(x['lat'])!, _d(x['lon'])!)];
    return Scaffold(
      appBar: AppBar(title: const Text('Map')),
      body: _stores == null
          ? const Center(child: CircularProgressIndicator())
          : Stack(
              children: [
                FlutterMap(
                  mapController: _map,
                  options: MapOptions(
                    initialCenter: _curacao,
                    initialZoom: 11,
                    initialCameraFit: points.length >= 2
                        ? CameraFit.coordinates(coordinates: points, padding: const EdgeInsets.all(48), maxZoom: 16)
                        : null,
                    onTap: (_, at) {
                      if (_placing != null) _place(_placing!, at);
                    },
                    onLongPress: (_, at) => _placing != null ? _place(_placing!, at) : _longPress(at),
                  ),
                  children: [
                    TileLayer(
                      urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'cw.jazzproxy.kasita',
                      maxNativeZoom: 19,
                    ),
                    MarkerLayer(
                      markers: [
                        if (_home != null)
                          Marker(
                            point: LatLng(_home!.$1, _home!.$2),
                            width: 34,
                            height: 34,
                            child: Tooltip(
                              message: 'Home',
                              child: Icon(Icons.home, color: cs.secondary, size: 34),
                            ),
                          ),
                        for (final x in located)
                          () {
                            final spent = _d(x['total']) ?? 0;
                            final double size = 28 + 36 * (maxSpent > 0 ? math.sqrt(spent / maxSpent) : 0.0);
                            return Marker(
                              point: LatLng(_d(x['lat'])!, _d(x['lon'])!),
                              width: size,
                              height: size,
                              child: GestureDetector(
                                onTap: () => _showStore(x),
                                child: Tooltip(
                                  message: '${x['name']}',
                                  child: Container(
                                    decoration: BoxDecoration(
                                      color: (x['id'] == _placing ? cs.tertiary : cs.primary).withValues(alpha: 0.8),
                                      shape: BoxShape.circle,
                                      border: Border.all(color: cs.onPrimary, width: 2),
                                    ),
                                    child: Icon(Icons.storefront, color: cs.onPrimary, size: size * 0.5),
                                  ),
                                ),
                              ),
                            );
                          }(),
                      ],
                    ),
                    RichAttributionWidget(
                      attributions: [
                        TextSourceAttribution(
                          'OpenStreetMap contributors',
                          onTap: () => launchUrl(Uri.parse('https://openstreetmap.org/copyright')),
                        ),
                      ],
                    ),
                  ],
                ),
                Positioned(
                  left: 12,
                  right: 12,
                  top: 12,
                  child: placingName != null
                      ? Card(
                          child: ListTile(
                            leading: const Icon(Icons.touch_app_outlined),
                            title: Text('Tap the map where $placingName is'),
                            trailing: TextButton(
                              onPressed: () => setState(() => _placing = null),
                              child: const Text('Cancel'),
                            ),
                          ),
                        )
                      : located.isEmpty
                      ? const Card(
                          child: ListTile(
                            leading: Icon(Icons.info_outline),
                            title: Text('No store on the map yet'),
                            subtitle: Text(
                              'Stores are found from the address on their receipts. Long-press the map to place one.',
                            ),
                          ),
                        )
                      : const SizedBox.shrink(),
                ),
                if (unlocated > 0 && _placing == null)
                  Positioned(
                    left: 12,
                    bottom: 12 + MediaQuery.viewPaddingOf(context).bottom,
                    child: ActionChip(
                      avatar: const Icon(Icons.wrong_location_outlined, size: 18),
                      label: Text('$unlocated not on the map'),
                      onPressed: _unlocated,
                    ),
                  ),
              ],
            ),
    );
  }
}

/// Tap a pin: visits, spending, average basket and what you buy there.
class _StoreSheet extends StatefulWidget {
  final Map<String, dynamic> store;
  final String currency;
  const _StoreSheet({required this.store, required this.currency});
  @override
  State<_StoreSheet> createState() => _StoreSheetState();
}

class _StoreSheetState extends State<_StoreSheet> {
  Map<String, dynamic>? _sum;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final s = Kasita.read(context);
      try {
        final sum = await s.api.storeSummary(s.hid, widget.store['id'] as String);
        if (mounted) setState(() => _sum = sum);
      } catch (_) {
        if (mounted) setState(() => _sum = const {});
      }
    });
  }

  String _money(dynamic v) => '${widget.currency} ${(double.tryParse('$v') ?? 0).toStringAsFixed(2)}';

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final x = widget.store;
    final sum = _sum;
    final visits = (sum?['visits'] as num?)?.toInt() ?? 0;
    final last = DateTime.tryParse('${sum?['last_visit']}');
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${x['name']}', style: t.textTheme.titleLarge),
            if (x['address'] != null) Text('${x['address']}', style: TextStyle(color: t.colorScheme.onSurfaceVariant)),
            const SizedBox(height: 12),
            if (sum == null)
              const LinearProgressIndicator()
            else if (visits == 0)
              const Text('No booked receipts from here yet.')
            else ...[
              Wrap(
                spacing: 24,
                runSpacing: 8,
                children: [
                  _Stat('Visits', '$visits'),
                  _Stat('Spent', _money(sum['total'])),
                  if (sum['average'] != null) _Stat('Average basket', _money(sum['average'])),
                  if (last != null) _Stat('Last visit', dateFmtYear.format(last)),
                ],
              ),
              if ((sum['top_items'] as List?)?.isNotEmpty ?? false) ...[
                const SizedBox(height: 16),
                Text('What you buy here', style: t.textTheme.titleSmall),
                for (final it in sum['top_items'] as List)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('${it['name']}'),
                    trailing: Text('${it['times']}× · ${_money(it['spent'])}'),
                  ),
              ],
            ],
            const SizedBox(height: 12),
            Row(
              children: [
                OutlinedButton.icon(
                  onPressed: () => Navigator.pop(context, 'move'),
                  icon: const Icon(Icons.edit_location_alt_outlined),
                  label: const Text('Move pin'),
                ),
                const SizedBox(width: 12),
                OutlinedButton.icon(
                  onPressed: () => Navigator.pop(context, 'edit'),
                  icon: const Icon(Icons.edit_outlined),
                  label: const Text('Edit store'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  final String label, value;
  const _Stat(this.label, this.value);
  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: t.textTheme.labelSmall?.copyWith(color: t.colorScheme.onSurfaceVariant)),
        Text(value, style: t.textTheme.titleMedium),
      ],
    );
  }
}
