import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';

/// Create or edit a product. When created from a scan, the barcode and
/// whatever the product databases knew come in as [prefill].
class ProductFormScreen extends StatefulWidget {
  final Product? product;
  final BarcodeResult? prefill;
  const ProductFormScreen({super.key, this.product, this.prefill});
  @override
  State<ProductFormScreen> createState() => _ProductFormScreenState();
}

class _ProductFormScreenState extends State<ProductFormScreen> {
  final _form = GlobalKey<FormState>();
  late final _name = TextEditingController(text: widget.product?.name ?? widget.prefill?.name ?? '');
  late final _brand = TextEditingController(
    text: widget.product?.brand ?? widget.prefill?.brand ?? widget.prefill?.brandHint ?? '',
  );
  late final _category = TextEditingController(text: widget.product?.category ?? widget.prefill?.category ?? '');
  List<String> _categories = const [];
  late final _unit = TextEditingController(
    text: widget.product?.unit ?? (widget.prefill?.variable == true ? 'kg' : 'pcs'),
  );
  // pack size, shown in the friendliest unit (1500 ml -> 1.5 l)
  late String _sizeUnit = _initialSizeUnit();
  late final _size = TextEditingController(text: _initialSize());

  String _initialSizeUnit() {
    final p = widget.product;
    if (p?.sizeAmount == null) return 'g';
    if (p!.sizeUnit == 'g') return p.sizeAmount! >= 1000 ? 'kg' : 'g';
    if (p.sizeUnit == 'ml') return p.sizeAmount! >= 1000 ? 'l' : 'ml';
    return 'pcs';
  }

  String _initialSize() {
    final a = widget.product?.sizeAmount;
    if (a == null) return '';
    final v = (_sizeUnit == 'kg' || _sizeUnit == 'l') ? a / 1000 : a;
    return v == v.roundToDouble() ? v.toStringAsFixed(0) : '$v';
  }
  late final _min = TextEditingController(text: widget.product == null ? '0' : fmtQty(widget.product!.minStock));
  late final _shelf = TextEditingController(text: widget.product?.shelfLifeDays?.toString() ?? '');
  late final _openDays = TextEditingController(text: widget.product?.openDays?.toString() ?? '');
  late String? _location = widget.product?.defaultLocationId;
  bool _busy = false;

  bool get _editing => widget.product != null;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final s = Kasita.read(context);
      try {
        final c = await s.api.categories(s.hid);
        if (mounted) setState(() => _categories = c);
      } catch (_) {
        // the field still accepts free text without the list
      }
    });
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    final s = Kasita.read(context);
    setState(() => _busy = true);
    final body = <String, dynamic>{
      'name': _name.text.trim(),
      'brand': _brand.text.trim().isEmpty ? null : _brand.text.trim(),
      'category': _category.text.trim().isEmpty ? null : _category.text.trim(),
      'unit': _unit.text.trim().isEmpty ? 'pcs' : _unit.text.trim(),
      'min_stock': _min.text.trim().isEmpty ? '0' : _min.text.trim().replaceAll(',', '.'),
      'shelf_life_days': int.tryParse(_shelf.text.trim()),
      'open_days': int.tryParse(_openDays.text.trim()),
      'default_location_id': _location,
    };
    final size = double.tryParse(_size.text.trim().replaceAll(',', '.'));
    if (size != null && size > 0) {
      body['size_amount'] = (_sizeUnit == 'kg' || _sizeUnit == 'l') ? size * 1000 : size;
      body['size_unit'] = switch (_sizeUnit) {
        'kg' || 'g' => 'g',
        'l' || 'ml' => 'ml',
        _ => 'pcs',
      };
    }
    try {
      final Product saved;
      if (_editing) {
        saved = await s.api.updateProduct(s.hid, widget.product!.id, body);
      } else {
        body['image_url'] = widget.prefill?.imageUrl;
        body['barcodes'] = [if (widget.prefill != null) widget.prefill!.barcode];
        saved = await s.api.createProduct(s.hid, body);
      }
      s.changed();
      if (mounted) Navigator.pop(context, saved);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    final pre = widget.prefill;
    return Scaffold(
      appBar: AppBar(title: Text(_editing ? 'Edit product' : 'New product')),
      body: Form(
        key: _form,
        child: ListView(
          padding: navBarSafe(context, const EdgeInsets.all(16)),
          children: [
            if (pre != null)
              Card(
                child: ListTile(
                  leading: ProductThumb(pre.imageUrl),
                  title: Text('Barcode ${pre.barcode}'),
                  subtitle: Text(
                    pre.found
                        ? 'Found in ${pre.source}${pre.quantityText == null ? "" : " · ${pre.quantityText}"}'
                        : 'Not in any product database: name it once and Kasita remembers it.',
                  ),
                ),
              ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _name,
              autofocus: pre != null && !pre.found,
              textCapitalization: TextCapitalization.sentences,
              validator: (v) => (v == null || v.trim().isEmpty) ? 'Give it a name' : null,
              decoration: const InputDecoration(labelText: 'Name', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _brand,
              decoration: const InputDecoration(labelText: 'Brand', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            LayoutBuilder(
              builder: (context, box) => DropdownMenu<String>(
                controller: _category,
                width: box.maxWidth,
                label: const Text('Category'),
                helperText: widget.prefill?.category != null && !_editing
                    ? 'Suggested from the product; change it if needed'
                    : null,
                enableFilter: false,
                requestFocusOnTap: true,
                dropdownMenuEntries: [for (final c in _categories) DropdownMenuEntry(value: c, label: c)],
                onSelected: (c) => _category.text = c ?? '',
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _unit,
                    decoration: const InputDecoration(
                      labelText: 'Counted in (pcs, pack, kg)',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextFormField(
                    controller: _min,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(
                      labelText: 'Keep at least',
                      helperText: 'Below this: onto the list',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: TextFormField(
                    controller: _size,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(
                      labelText: 'Pack size',
                      helperText: 'For prices per kg / litre (empty: read from the barcode)',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: DropdownButtonFormField<String>(
                    initialValue: _sizeUnit,
                    decoration: const InputDecoration(border: OutlineInputBorder()),
                    items: [
                      for (final u in const ['g', 'kg', 'ml', 'l', 'pcs']) DropdownMenuItem(value: u, child: Text(u)),
                    ],
                    onChanged: (v) => setState(() => _sizeUnit = v ?? 'g'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _shelf,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Usually keeps for (days)',
                helperText: 'Pre-fills the best-before date when you buy it',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _openDays,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Keeps once opened (days)',
                helperText: 'Tapping Opened sets its date to this many days from then (milk 5, salsa 14)',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String?>(
              initialValue: _location,
              decoration: const InputDecoration(labelText: 'Usually stored in', border: OutlineInputBorder()),
              items: [
                const DropdownMenuItem(value: null, child: Text('—')),
                for (final l in s.locations) DropdownMenuItem(value: l.id, child: Text(l.name)),
              ],
              onChanged: (v) => setState(() => _location = v),
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _busy ? null : _save,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(_editing ? 'Save' : 'Create product'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
