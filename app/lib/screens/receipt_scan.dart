import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'product_picker.dart';
import 'unknown_barcode.dart';

/// Small shops print departments ("COMESTIBELS 7.99"), not products: scanning the pack says what a
/// line really was. A barcode the household knows is linked; one a product database knows becomes a
/// product without a form; an unknown one goes through the usual "what is this?" choices first.
/// Returns null when the person backed out.
Future<ReceiptScanResult?> scanToReceipt(BuildContext context, String receiptId, String code, {String? lineId}) async {
  final s = Kasita.read(context);
  var res = await s.api.scanForReceipt(s.hid, receiptId, lineId: lineId, barcode: code);
  if (res.status != 'unknown' || res.lookup == null) return res;
  if (!context.mounted) return null;
  final product = await productForUnknownBarcode(context, res.lookup!, skipLabel: 'Skip this one');
  if (product == null || !context.mounted) return null;
  res = await s.api.scanForReceipt(s.hid, receiptId, lineId: lineId, productId: product.id);
  s.changed();
  return res;
}

/// Scan one pack for this line. True when the line changed.
Future<bool> scanReceiptLine(BuildContext context, String receiptId, ReceiptLine line) async {
  final code = await Navigator.of(context)
      .push<String>(MaterialPageRoute(builder: (_) => ScanOneBarcodeScreen(title: 'Scan: ${line.rawText}')));
  if (code == null || code.isEmpty || !context.mounted) return false;
  try {
    final res = await scanToReceipt(context, receiptId, code, lineId: line.id);
    if (res == null || !context.mounted) return false;
    Kasita.read(context).changed();
    toast(
      context,
      '${line.rawText} is ${res.product?.name ?? 'linked'}${res.status == 'created' ? ' (new product)' : ''}',
    );
    return true;
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
    return false;
  }
}

/// Pick a spending category (Kasita's list plus the household's own).
Future<String?> pickCategory(BuildContext context, String? current) async {
  final s = Kasita.read(context);
  List<String> cats;
  try {
    cats = await s.api.categories(s.hid);
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
    return null;
  }
  if (!context.mounted) return null;
  return showDialog<String>(
    context: context,
    builder: (c) => SimpleDialog(
      title: const Text('Count it as'),
      children: [
        for (final cat in cats)
          SimpleDialogOption(
            onPressed: () => Navigator.pop(c, cat),
            child: Row(
              children: [
                Expanded(child: Text(cat)),
                if (cat == current) const Icon(Icons.check, size: 18),
              ],
            ),
          ),
      ],
    ),
  );
}

enum LineAction { changed, edit }

/// Quick ways to settle a line without opening the editor: scan the pack, spending only, pick a
/// product, or skip it. [withScan] false in Scan them all (the camera is already running).
Future<LineAction?> receiptLineActions(
  BuildContext context,
  String receiptId,
  ReceiptLine line, {
  bool withScan = true,
  bool withEdit = true,
}) async {
  final s = Kasita.read(context);
  final cat = line.spendingCategory ?? line.suggestedCategory ?? 'Other';
  final choice = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    builder: (c) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ListTile(
            title: Text(line.rawText, style: Theme.of(context).textTheme.titleMedium),
            subtitle: Text(
              line.department
                  ? 'A shop department, not a product. Scan the pack to say what it was.'
                  : (line.name ?? ''),
            ),
          ),
          if (withScan)
            ListTile(
              leading: const Icon(Icons.qr_code_scanner),
              title: const Text('Scan the pack'),
              subtitle: const Text('Links the product, or makes it from the barcode'),
              onTap: () => Navigator.pop(c, 'scan'),
            ),
          ListTile(
            leading: const Icon(Icons.payments_outlined),
            title: Text('Spending only · $cat'),
            subtitle: const Text('Counts in spending, nothing goes in the pantry'),
            onTap: () => Navigator.pop(c, 'spend'),
            trailing: TextButton(onPressed: () => Navigator.pop(c, 'spend-other'), child: const Text('Other')),
          ),
          ListTile(
            leading: const Icon(Icons.inventory_2_outlined),
            title: const Text('Choose a product'),
            onTap: () => Navigator.pop(c, 'pick'),
          ),
          ListTile(
            leading: const Icon(Icons.remove_circle_outline),
            title: const Text('Skip it'),
            subtitle: const Text('Not counted anywhere (bag, deposit…)'),
            onTap: () => Navigator.pop(c, 'skip'),
          ),
          if (withEdit)
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Edit the line'),
              onTap: () => Navigator.pop(c, 'edit'),
            ),
        ],
      ),
    ),
  );
  if (choice == null || !context.mounted) return null;
  if (choice == 'edit') return LineAction.edit;
  if (choice == 'scan') return await scanReceiptLine(context, receiptId, line) ? LineAction.changed : null;
  Map<String, dynamic> body;
  switch (choice) {
    case 'spend':
      body = {'spending_only': true, 'spending_category': cat};
    case 'spend-other':
      final other = await pickCategory(context, cat);
      if (other == null) return null;
      body = {'spending_only': true, 'spending_category': other};
    case 'pick':
      final p = await Navigator.of(context).push<Product>(
        MaterialPageRoute(builder: (_) => ProductPicker(hint: 'Search products (receipt: ${line.rawText})')),
      );
      if (p == null) return null;
      body = {'product_id': p.id};
    default:
      body = {'skip': true};
  }
  try {
    await s.api.updateReceiptLine(s.hid, receiptId, line.id, body);
    return LineAction.changed;
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
    return null;
  }
}

/// Scan every pack from the bag in one go. Each scan finds (or makes) the product and the server
/// puts it on the open line it fits best: the price paid last time, the department, the twin of the
/// line the same pack just landed on. Wrong line? Move it or undo it with one tap.
class ReceiptScanAllScreen extends StatefulWidget {
  final String receiptId;
  const ReceiptScanAllScreen({super.key, required this.receiptId});
  @override
  State<ReceiptScanAllScreen> createState() => _ReceiptScanAllScreenState();
}

class _Linked {
  final String lineId;
  final Product product;
  final String? reason;
  _Linked(this.lineId, this.product, this.reason);
}

class _ReceiptScanAllScreenState extends State<ReceiptScanAllScreen> {
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
  Receipt? _r;
  final _linked = <_Linked>[]; // what this pass linked, newest last
  String? _candidate; // first sighting of a code; it counts on the second identical read
  String? _lastCode;
  DateTime _lastAt = DateTime(2000);
  bool _busy = false;
  String? _flash;

  static const _repeatGap = Duration(milliseconds: 2500);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    try {
      final r = await s.api.receipt(s.hid, widget.receiptId);
      if (mounted) setState(() => _r = r);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  ReceiptLine? _lineById(String id) => _r?.lines?.where((l) => l.id == id).firstOrNull;

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
      var res = await s.api.scanForReceipt(s.hid, widget.receiptId, barcode: code);
      if (res.status == 'unknown' && res.lookup != null) {
        await _controller.stop();
        if (!mounted) return;
        final product = await productForUnknownBarcode(context, res.lookup!, skipLabel: 'Skip this one');
        if (!mounted) return;
        await _controller.start();
        _lastAt = DateTime.now(); // don't re-read the same pack the moment the camera is back
        if (product == null) return;
        res = await s.api.scanForReceipt(s.hid, widget.receiptId, productId: product.id);
      }
      final line = res.line;
      String flash;
      if (line == null) {
        flash = 'No open line left for ${res.product?.name ?? 'this'}';
        HapticFeedback.heavyImpact();
      } else {
        _linked.add(_Linked(line.id, res.product!, res.reason));
        flash = '${res.product!.name} → ${line.rawText} ${_money(line.lineTotal)}';
        HapticFeedback.mediumImpact();
      }
      s.changed();
      if (mounted) {
        setState(() {
          _r = res.receipt;
          _flash = flash;
        });
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _guard(Future<void> Function() fn) async {
    setState(() => _busy = true);
    try {
      await fn();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _undo(_Linked x) => _guard(() async {
    final s = Kasita.read(context);
    await s.api.updateReceiptLine(s.hid, widget.receiptId, x.lineId, {'clear_product': true});
    _linked.remove(x);
    await _load();
    if (mounted) setState(() => _flash = 'Undone: ${x.product.name}');
  });

  Future<void> _move(_Linked x) async {
    final open = (_r?.lines ?? const <ReceiptLine>[]).where((l) => l.open && l.id != x.lineId).toList();
    if (open.isEmpty) {
      toast(context, 'No other open line to move it to');
      return;
    }
    final to = await showModalBottomSheet<ReceiptLine>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            ListTile(title: Text('Move ${x.product.name} to…', style: Theme.of(context).textTheme.titleMedium)),
            for (final l in open)
              ListTile(
                title: Text(l.rawText),
                subtitle: l.name == null || l.name == l.rawText ? null : Text(l.name!),
                trailing: Text(_money(l.lineTotal)),
                onTap: () => Navigator.pop(c, l),
              ),
          ],
        ),
      ),
    );
    if (to == null || !mounted) return;
    await _guard(() async {
      final s = Kasita.read(context);
      final r = await s.api.moveReceiptLink(s.hid, widget.receiptId, x.lineId, to.id);
      final i = _linked.indexOf(x);
      if (i >= 0) _linked[i] = _Linked(to.id, x.product, 'moved by you');
      if (mounted) {
        setState(() {
          _r = r;
          _flash = '${x.product.name} → ${to.rawText} ${_money(to.lineTotal)}';
        });
      }
    });
  }

  Future<void> _resolveOpen(ReceiptLine l) async {
    await _controller.stop();
    if (!mounted) return;
    final done = await receiptLineActions(context, widget.receiptId, l, withScan: false, withEdit: false);
    if (!mounted) return;
    await _controller.start();
    _lastAt = DateTime.now();
    if (done == LineAction.changed) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final r = _r;
    final open = (r?.lines ?? const <ReceiptLine>[]).where((l) => l.open).toList();
    final linked = _linked.reversed.where((x) => _lineById(x.lineId)?.productId == x.product.id).toList();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Scan them all'),
        actions: [
          IconButton(
            tooltip: 'Torch',
            icon: const Icon(Icons.flashlight_on_outlined),
            onPressed: () => _controller.toggleTorch(),
          ),
        ],
      ),
      body: Column(
        children: [
          SizedBox(
            height: 220,
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
                      border: Border.all(color: Colors.white, width: 3),
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
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
                if (_busy) const Center(child: CircularProgressIndicator()),
              ],
            ),
          ),
          Expanded(
            child: r == null
                ? const Center(child: CircularProgressIndicator())
                : ListView(
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
                        child: Text(
                          open.isEmpty
                              ? 'Every line is settled.'
                              : 'Scan each pack from the bag. Kasita puts it on the line it fits best. '
                                    'Tap an open line to settle it without scanning.',
                          style: t.textTheme.bodySmall,
                        ),
                      ),
                      for (final x in linked) _linkedTile(x, t),
                      if (open.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                          child: Text('Still open (${open.length})', style: t.textTheme.titleSmall),
                        ),
                      for (final l in open)
                        ListTile(
                          dense: true,
                          leading: Icon(
                            l.department ? Icons.qr_code_scanner : Icons.help_outline,
                            color: Colors.orange.shade800,
                          ),
                          title: Text(l.rawText),
                          subtitle: Text(
                            [
                              if (l.department) 'department',
                              if (l.matchedBy == 'guess' && l.productName != null) '${l.productName}?',
                              if (!l.department && l.name != null && l.name != l.rawText) l.name!,
                            ].join(' · '),
                          ),
                          trailing: Text(_money(l.lineTotal), style: t.textTheme.bodyLarge),
                          onTap: _busy ? null : () => _resolveOpen(l),
                        ),
                    ],
                  ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
              child: FilledButton.icon(
                onPressed: () => Navigator.pop(context, true),
                icon: const Icon(Icons.check),
                label: const Text('Done'),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _linkedTile(_Linked x, ThemeData t) {
    final l = _lineById(x.lineId);
    return ListTile(
      leading: ProductThumb(x.product.imageUrl),
      title: Text(x.product.name),
      subtitle: Text(
        [if (l != null) '${l.rawText} ${_money(l.lineTotal)}', if (x.reason != null) x.reason!].join(' · '),
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: 'Move to another line',
            icon: const Icon(Icons.swap_vert),
            onPressed: _busy ? null : () => _move(x),
          ),
          IconButton(tooltip: 'Undo', icon: const Icon(Icons.undo), onPressed: _busy ? null : () => _undo(x)),
        ],
      ),
    );
  }
}

String _money(double? v) => v == null ? '' : v.toStringAsFixed(2);
