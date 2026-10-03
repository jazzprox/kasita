import 'package:flutter/material.dart' hide Text;
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'actions.dart';
import 'unknown_barcode.dart';
import '../i18n.dart';

enum PassMode { add, use }

/// One running line of the pass: a product and the stock events this pass made for it.
class _Tally {
  final Product product;
  final List<(int, String)> events = []; // (+1 or -1, stock event ids) per step, newest last, for undo
  final List<String> batches = []; // batches this pass added (newest last): the date button dates the last
  _Tally(this.product);
  int get added => events.where((e) => e.$1 > 0).length;
  int get used => events.where((e) => e.$1 < 0).length;
}

/// Scan what's already at home (or what's gone) in one continuous pass:
/// every scan adds one to the pantry, or uses one up, with no questions in between.
/// The camera keeps running; the list below shows what this pass did, with + and −.
class PantryPassScreen extends StatefulWidget {
  const PantryPassScreen({super.key});
  @override
  State<PantryPassScreen> createState() => _PantryPassScreenState();
}

class _PantryPassScreenState extends State<PantryPassScreen> {
  final _controller = MobileScannerController(
    formats: const [
      BarcodeFormat.ean13,
      BarcodeFormat.ean8,
      BarcodeFormat.upcA,
      BarcodeFormat.upcE,
      BarcodeFormat.code128,
    ],
    detectionSpeed: DetectionSpeed.normal,
    detectionTimeoutMs: 150,
  );
  PassMode _mode = PassMode.add;
  final _tallies = <String, _Tally>{}; // by product id, in scan order
  String? _candidate; // first sighting of a code; it counts on the second identical read
  String? _lastCode; // the code just handled: ignored for a moment so holding it still doesn't repeat
  DateTime _lastAt = DateTime(2000);
  bool _busy = false;
  String? _flash; // the last action, shown over the camera

  static const _repeatGap = Duration(milliseconds: 2500);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onCode(String code) {
    if (_busy) return;
    if (code == _lastCode && DateTime.now().difference(_lastAt) < _repeatGap) return;
    if (code != _candidate) {
      _candidate = code; // wait for a second identical read (misreads happen on shiny packs)
      return;
    }
    _candidate = null;
    _lastCode = code;
    _lastAt = DateTime.now();
    _scan(code);
  }

  Future<void> _scan(String code) async {
    final s = Kasita.read(context);
    setState(() => _busy = true);
    try {
      final r = await s.api.barcode(s.hid, code);
      var product = r.product;
      if (product == null) {
        await _controller.stop();
        if (!mounted) return;
        product = await productForUnknownBarcode(context, r, skipLabel: 'Skip this one');
        if (!mounted) return;
        await _controller.start();
        _lastAt = DateTime.now(); // don't re-read the same pack the moment the camera is back
        if (product == null) return;
      }
      await _step(product, _mode == PassMode.add ? 1 : -1);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// +1 adds a batch of one; -1 uses one up. Records the event so − can undo it.
  Future<void> _step(Product p, int dir) async {
    final s = Kasita.read(context);
    final tally = _tallies.putIfAbsent(p.id, () => _Tally(p));
    String flash;
    if (dir > 0) {
      final entry = await s.api.purchaseEntry(s.hid, {'product_id': p.id, 'quantity': 1});
      if (entry['event_id'] != null) tally.events.add((1, entry['event_id'] as String));
      tally.batches.add(entry['id'] as String);
      flash = '+1 ${p.name}';
    } else {
      final res = await s.api.consume(s.hid, p.id, 1);
      final ids = List<String>.from(res['event_ids'] ?? const []);
      if (ids.isEmpty) {
        flash = 'No ${p.name} left at home';
      } else {
        tally.events.add((-1, ids.join(',')));
        flash = '−1 ${p.name}';
      }
    }
    HapticFeedback.mediumImpact();
    s.changed();
    if (mounted) setState(() => _flash = flash);
  }

  /// Read the printed date off the pack and put it on the batch this pass just added.
  Future<void> _dateLast(_Tally t) async {
    final s = Kasita.read(context);
    await _controller.stop();
    if (!mounted) return;
    final d = await dateFromPhoto(context);
    if (mounted) await _controller.start();
    if (d == null || !mounted) return;
    try {
      await s.api.patchEntry(s.hid, t.batches.last, {'best_before': d.toIso8601String().substring(0, 10)});
      s.changed();
      if (mounted) setState(() => _flash = '${t.product.name}: best before ${dateFmtYear.format(d)}');
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  /// The minus button: take back the last thing this pass did to that product.
  Future<void> _undo(_Tally t) async {
    if (t.events.isEmpty) return;
    final s = Kasita.read(context);
    try {
      await s.api.undoStock(s.hid, t.events.last.$2.split(','));
      t.events.removeLast();
      s.changed();
      if (mounted) setState(() => _flash = 'Undone: ${t.product.name}');
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final adding = _mode == PassMode.add;
    final rows = _tallies.values.where((x) => x.events.isNotEmpty).toList().reversed.toList();
    final total = rows.fold<int>(0, (n, x) => n + x.events.length);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pantry pass'),
        actions: [
          IconButton(
            tooltip: tr('Torch'),
            icon: const Icon(Icons.flashlight_on_outlined),
            onPressed: () => _controller.toggleTorch(),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: SegmentedButton<PassMode>(
              segments: const [
                ButtonSegment(value: PassMode.add, icon: Icon(Icons.add), label: Text('Add to pantry')),
                ButtonSegment(value: PassMode.use, icon: Icon(Icons.remove), label: Text('Use up')),
              ],
              selected: {_mode},
              onSelectionChanged: (m) => setState(() => _mode = m.first),
            ),
          ),
          SizedBox(
            height: 240,
            child: Stack(
              fit: StackFit.expand,
              children: [
                MobileScanner(
                  controller: _controller,
                  onDetect: (capture) {
                    final code = capture.barcodes.map((b) => b.rawValue).whereType<String>().firstOrNull;
                    if (code != null) _onCode(code);
                  },
                  errorBuilder: (context, error) => const Center(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Text('Camera unavailable', textAlign: TextAlign.center),
                    ),
                  ),
                ),
                Center(
                  child: Container(
                    width: 240,
                    height: 130,
                    decoration: BoxDecoration(
                      border: Border.all(color: adding ? Colors.white : Colors.orangeAccent, width: 3),
                      borderRadius: BorderRadius.circular(16),
                    ),
                  ),
                ),
                if (_flash != null)
                  Positioned(
                    left: 12,
                    right: 12,
                    bottom: 10,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      decoration: BoxDecoration(color: Colors.black87, borderRadius: BorderRadius.circular(10)),
                      child: Text(
                        _flash!,
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
                if (_busy) const Center(child: CircularProgressIndicator()),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
            child: Text(
              rows.isEmpty
                  ? (adding
                        ? 'Scan each item at home. Every scan adds one. Same item twice? Scan it again or tap +.'
                        : 'Scan what is used up or thrown away. Every scan takes one out.')
                  : '$total change${total == 1 ? '' : 's'} this pass · − takes the last one back',
              style: t.textTheme.bodySmall,
            ),
          ),
          Expanded(
            child: ListView(
              children: [
                for (final x in rows)
                  ListTile(
                    leading: ProductThumb(x.product.imageUrl),
                    title: Text(x.product.name),
                    subtitle: Text(
                      [if (x.added > 0) '+${x.added} added', if (x.used > 0) '−${x.used} used'].join(' · '),
                    ),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (adding && x.batches.isNotEmpty)
                          IconButton(
                            tooltip: tr('Photo of its date'),
                            icon: const Icon(Icons.event_outlined),
                            onPressed: _busy ? null : () => _dateLast(x),
                          ),
                        IconButton(
                          tooltip: tr('Take the last one back'),
                          icon: const Icon(Icons.remove_circle_outline),
                          onPressed: _busy ? null : () => _undo(x),
                        ),
                        IconButton(
                          tooltip: adding ? 'One more' : 'Use one more',
                          icon: const Icon(Icons.add_circle_outline),
                          onPressed: _busy ? null : () => _step(x.product, adding ? 1 : -1),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
              child: FilledButton.icon(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.check),
                label: Text(rows.isEmpty ? 'Close' : 'Done'),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
