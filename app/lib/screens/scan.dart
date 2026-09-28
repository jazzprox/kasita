import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'actions.dart';
import 'product_detail.dart';
import 'unknown_barcode.dart';
import 'receipts.dart';

class ScanScreen extends StatefulWidget {
  final bool active;
  const ScanScreen({super.key, required this.active});
  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  final _controller = MobileScannerController(
    formats: const [
      BarcodeFormat.ean13,
      BarcodeFormat.ean8,
      BarcodeFormat.upcA,
      BarcodeFormat.upcE,
      BarcodeFormat.code128,
    ],
    // every frame, not "only new codes": a code must be read twice in a row
    // before it counts, so one misread frame (curved, shiny packs) can't get through
    detectionSpeed: DetectionSpeed.normal,
    detectionTimeoutMs: 150,
  );
  String? _candidate;
  final _manual = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _handle(String code) async {
    if (_busy) return;
    setState(() => _busy = true);
    await _controller.stop();
    if (!mounted) return;
    final s = Kasita.read(context);
    try {
      final r = await s.api.barcode(s.hid, code);
      if (mounted) await _showResult(r);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } catch (e) {
      if (mounted) toast(context, 'Lookup failed: $e', error: true);
    } finally {
      if (mounted) {
        setState(() => _busy = false);
        await _controller.start();
      }
    }
  }

  Future<void> _showResult(BarcodeResult r) async {
    var product = r.product;
    if (product == null) {
      // new to this household: one of your products (e.g. from a receipt) or a new one?
      product = await productForUnknownBarcode(context, r);
      if (product == null || !mounted) return;
    }
    final p = product;
    await showModalBottomSheet(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: ProductThumb(p.imageUrl, size: 56),
                title: Text(p.name, style: Theme.of(context).textTheme.titleMedium),
                subtitle: Text('${fmtQty(p.inStock)} ${p.unit} at home'),
                trailing: ExpiryChip(p.nextBestBefore),
              ),
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: () async {
                  Navigator.pop(sheet);
                  await showPurchaseSheet(context, p);
                },
                icon: const Icon(Icons.add_shopping_cart),
                label: const Text('Bought'),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.tonalIcon(
                      onPressed: p.inStock > 0
                          ? () {
                              Navigator.pop(sheet);
                              consumeOne(context, p);
                            }
                          : null,
                      icon: const Icon(Icons.remove_circle_outline),
                      label: const Text('Used one'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: p.inStock > 0
                          ? () {
                              Navigator.pop(sheet);
                              openOne(context, p);
                            }
                          : null,
                      icon: const Icon(Icons.lock_open),
                      label: const Text('Opened'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () {
                        Navigator.pop(sheet);
                        addToList(context, p);
                      },
                      icon: const Icon(Icons.playlist_add),
                      label: const Text('To list'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextButton(
                      onPressed: () {
                        Navigator.pop(sheet);
                        Navigator.of(context)
                            .push(MaterialPageRoute(builder: (_) => ProductDetailScreen(productId: p.id)));
                      },
                      child: const Text('Details'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Scan'),
        actions: [
          TextButton.icon(
            onPressed: () async {
              await _controller.stop();
              if (!context.mounted) return;
              await Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ReceiptsScreen()));
              if (mounted) await _controller.start();
            },
            icon: const Icon(Icons.receipt_long),
            label: const Text('Receipt'),
          ),
          IconButton(
            tooltip: 'Torch',
            icon: const Icon(Icons.flashlight_on_outlined),
            onPressed: () => _controller.toggleTorch(),
          ),
        ],
      ),
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
                    if (code == null || _busy) return;
                    if (code == _candidate) {
                      _candidate = null;
                      _handle(code);
                    } else {
                      _candidate = code; // first sighting: wait for a second identical read
                    }
                  },
                  errorBuilder: (context, error) => Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        'Camera unavailable (${error.errorCode.name}). Type the barcode below instead.',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                ),
                // aiming frame
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
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _manual,
              keyboardType: TextInputType.number,
              onSubmitted: (v) => v.trim().isEmpty ? null : _handle(v.trim()),
              decoration: InputDecoration(
                hintText: 'Or type the barcode number',
                border: const OutlineInputBorder(),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.search),
                  onPressed: () => _manual.text.trim().isEmpty ? null : _handle(_manual.text.trim()),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
