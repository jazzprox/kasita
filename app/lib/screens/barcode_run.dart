import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../api.dart';

import '../main.dart';
import '../models.dart';
import '../widgets.dart';

/// Tag every product that has no barcode yet, in one pass.
///
/// Adding a barcode per product means opening it, scrolling to the bottom,
/// tapping Add barcode, scanning, and going back — about five taps each, and
/// sixteen products off one receipt is eighty taps. This keeps the CAMERA
/// still and moves the PRODUCT: scan, it attaches and advances, scan the next
/// item. Putting the shopping away becomes one continuous pass.
///
/// The list is fetched once and worked through in order. A product is only
/// ever removed from the queue by being tagged or skipped, so a failed scan
/// leaves you on the same item rather than silently losing it.
class BarcodeRunScreen extends StatefulWidget {
  const BarcodeRunScreen({super.key});
  @override
  State<BarcodeRunScreen> createState() => _BarcodeRunScreenState();
}

class _BarcodeRunScreenState extends State<BarcodeRunScreen> {
  final _controller = MobileScannerController(
    /* The same formats and timing as the single-scan screen, so a barcode
       that reads there reads here. */
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
  final _manual = TextEditingController();

  List<Product> _queue = [];
  int _at = 0;
  int _tagged = 0;
  bool _loading = true;
  bool _busy = false;
  String? _error;

  /// The last raw read, for the two-identical-reads rule below.
  String? _candidate;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _controller.dispose();
    _manual.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    try {
      final all = await s.api.products(s.hid);
      if (!mounted) return;
      setState(() {
        _queue = all.where((p) => p.barcodes.isEmpty).toList();
        _loading = false;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() { _error = e.message; _loading = false; });
    }
  }

  Product? get _current => _at < _queue.length ? _queue[_at] : null;

  /// Attach [code] to the product in front of us, then advance.
  ///
  /// The server fills in photo, brand and category from the public databases
  /// where the product has none — so a receipt-made product usually gains a
  /// picture here too, without overwriting anything typed by hand.
  Future<void> _attach(String raw) async {
    final code = raw.trim();
    final p = _current;
    if (_busy || code.isEmpty || p == null) return;
    setState(() => _busy = true);
    final s = Kasita.read(context);
    try {
      await s.api.addBarcode(s.hid, p.id, code);
      s.changed();
      if (!mounted) return;
      _manual.clear();
      setState(() {
        _tagged += 1;
        _at += 1;
        _busy = false;
        _candidate = null;
      });
      toast(context, '${p.name} → $code');
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() { _busy = false; _candidate = null; });
      /*
       * 409 means this code already belongs to another product, and receipt
       * import really does produce near-duplicates ("Pineapple chunks"
       * twice off one receipt). Retrying the same tin can never succeed, so
       * the honest offer is to move on rather than a red toast the reader
       * has to interpret.
       */
      if (e.status == 409) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(
            content: Text('$code is already on another product'),
            behavior: SnackBarBehavior.floating,
            action: SnackBarAction(label: 'Skip this one', onPressed: _skip),
            duration: const Duration(seconds: 6),
          ));
        return;
      }
      /* Anything else — a bad number, the network — leaves you on the SAME
         product, because advancing would quietly lose it. */
      toast(context, e.message, error: true);
    }
  }

  void _skip() {
    if (_current == null) return;
    setState(() { _at += 1; _candidate = null; });
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final p = _current;
    final left = _queue.length - _at;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Tag barcodes'),
        actions: [
          if (!_loading && _queue.isNotEmpty)
            Center(child: Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Text('$_tagged tagged', style: t.textTheme.labelLarge),
            )),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(_error!)))
              : p == null
                  ? _done(t)
                  : _run(t, p, left),
    );
  }

  /// Nothing left — either everything is tagged or there was nothing to do.
  Widget _done(ThemeData t) => Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(_tagged > 0 ? Icons.check_circle_outline : Icons.qr_code_2,
                  size: 56, color: t.colorScheme.primary),
              const SizedBox(height: 16),
              Text(
                _queue.isEmpty
                    ? 'Every product already has a barcode.'
                    : _tagged == 0
                        ? 'Nothing tagged this time.'
                        : '$_tagged product${_tagged == 1 ? '' : 's'} tagged.',
                style: t.textTheme.titleMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 20),
              FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Done')),
            ],
          ),
        ),
      );

  Widget _run(ThemeData t, Product p, int left) => Column(
        children: [
          /* WHAT AM I SCANNING? The product name sits above the viewfinder,
             not below it, because that is where the eye already is when the
             phone is held over a tin. */
          Container(
            width: double.infinity,
            color: t.colorScheme.surfaceContainerHighest,
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Scan the item for', style: t.textTheme.labelMedium),
                const SizedBox(height: 2),
                Text(p.name, style: t.textTheme.titleLarge),
                if (p.brand != null && p.brand!.isNotEmpty)
                  Text(p.brand!, style: t.textTheme.bodySmall),
                const SizedBox(height: 6),
                Text('$left to go', style: t.textTheme.labelSmall),
              ],
            ),
          ),
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: [
                MobileScanner(
                  controller: _controller,
                  onDetect: (capture) {
                    if (_busy) return;
                    final code = capture.barcodes.map((b) => b.rawValue).whereType<String>().firstOrNull;
                    if (code == null) return;
                    /* TWO IDENTICAL READS before it counts — the same rule the
                       single scanner uses. One frame of a half-seen barcode is
                       how a wrong code gets attached to the wrong product, and
                       here that would also advance the queue past it. */
                    if (code == _candidate) {
                      _attach(code);
                    } else {
                      _candidate = code;
                    }
                  },
                  errorBuilder: (context, error) => const Center(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Text('Camera unavailable. Type the barcode below instead.',
                          textAlign: TextAlign.center),
                    ),
                  ),
                ),
                Center(
                  child: Container(
                    width: 260,
                    height: 150,
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.white, width: 3),
                      borderRadius: BorderRadius.circular(16),
                    ),
                  ),
                ),
                if (_busy) const Center(child: CircularProgressIndicator()),
              ],
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _manual,
                      keyboardType: TextInputType.number,
                      onSubmitted: _attach,
                      decoration: const InputDecoration(
                        hintText: 'Or type the number',
                        border: OutlineInputBorder(),
                        isDense: true,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  /* SKIP is as important as scan: an item with no barcode on it
                     at all (loose veg, something decanted) would otherwise stop
                     the whole run. */
                  TextButton(onPressed: _busy ? null : _skip, child: const Text('Skip')),
                ],
              ),
            ),
          ),
        ],
      );
}
