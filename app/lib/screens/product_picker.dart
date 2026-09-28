import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../main.dart';
import '../models.dart';
import '../widgets.dart';

/// Pick one of the household's products. With [barcodeLessFirst], products that
/// have no barcode yet (typically created from a receipt) are listed on top.
class ProductPicker extends StatefulWidget {
  final String title;
  final String? hint;
  final bool barcodeLessFirst;
  final String emptyText;
  const ProductPicker({
    super.key,
    this.title = 'Which product?',
    this.hint,
    this.barcodeLessFirst = false,
    this.emptyText = 'No match. Go back and leave it as a new product.',
  });
  @override
  State<ProductPicker> createState() => _ProductPickerState();
}

class _ProductPickerState extends State<ProductPicker> {
  List<Product>? _all;
  String _q = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final s = Kasita.read(context);
      final all = await s.api.products(s.hid);
      if (widget.barcodeLessFirst) {
        all.sort((a, b) => (a.barcodes.isEmpty ? 0 : 1) - (b.barcodes.isEmpty ? 0 : 1));
      }
      if (mounted) setState(() => _all = all);
    });
  }

  @override
  Widget build(BuildContext context) {
    final q = _q.toLowerCase();
    final list = (_all ?? [])
        .where((p) => q.isEmpty || '${p.name} ${p.brand ?? ''}'.toLowerCase().contains(q))
        .toList();
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: SearchBar(
              hintText: widget.hint ?? 'Search products',
              leading: const Icon(Icons.search),
              autoFocus: true,
              onChanged: (v) => setState(() => _q = v),
            ),
          ),
          Expanded(
            child: _all == null
                ? const Center(child: CircularProgressIndicator())
                : ListView(
                    children: [
                      for (final p in list)
                        ListTile(
                          leading: ProductThumb(p.imageUrl),
                          title: Text(p.name),
                          subtitle: Text(
                            [
                              p.brand,
                              p.category,
                              if (widget.barcodeLessFirst) p.barcodes.isEmpty ? 'no barcode yet' : 'has a barcode',
                            ].whereType<String>().join(' · '),
                          ),
                          trailing: widget.barcodeLessFirst && p.barcodes.isEmpty
                              ? Icon(Icons.qr_code_2, color: t.colorScheme.primary)
                              : null,
                          onTap: () => Navigator.pop(context, p),
                        ),
                      if (list.isEmpty)
                        Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(widget.emptyText, textAlign: TextAlign.center),
                        ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

/// Scan (or type) one barcode and return it. Same double-read rule as the Scan tab.
class ScanOneBarcodeScreen extends StatefulWidget {
  final String title;
  const ScanOneBarcodeScreen({super.key, this.title = 'Scan the barcode'});
  @override
  State<ScanOneBarcodeScreen> createState() => _ScanOneBarcodeScreenState();
}

class _ScanOneBarcodeScreenState extends State<ScanOneBarcodeScreen> {
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
  final _manual = TextEditingController();
  String? _candidate;
  bool _done = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _finish(String code) {
    if (_done) return;
    _done = true;
    Navigator.pop(context, code.trim());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Column(
        children: [
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: [
                MobileScanner(
                  controller: _controller,
                  onDetect: (capture) {
                    final code = capture.barcodes.map((b) => b.rawValue).whereType<String>().firstOrNull;
                    if (code == null) return;
                    if (code == _candidate) {
                      _finish(code);
                    } else {
                      _candidate = code;
                    }
                  },
                  errorBuilder: (context, error) => const Center(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Text('Camera unavailable. Type the barcode below instead.', textAlign: TextAlign.center),
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
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _manual,
              keyboardType: TextInputType.number,
              onSubmitted: (v) => v.trim().isEmpty ? null : _finish(v),
              decoration: InputDecoration(
                hintText: 'Or type the barcode number',
                border: const OutlineInputBorder(),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.check),
                  onPressed: () => _manual.text.trim().isEmpty ? null : _finish(_manual.text),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
