import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'chatgpt.dart';

final _money = NumberFormat('#,##0.00');
String money(double? v) => v == null ? '—' : _money.format(v);

/// Take or pick a receipt photo, upload it and open the review screen.
Future<void> scanReceipt(BuildContext context, {ImageSource? source}) async {
  final s = Kasita.read(context);
  source ??= await showModalBottomSheet<ImageSource>(
    context: context,
    showDragHandle: true,
    builder: (c) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ListTile(
            leading: const Icon(Icons.photo_camera_outlined),
            title: const Text('Take a photo'),
            subtitle: const Text('Flat, well lit, the whole receipt in view'),
            onTap: () => Navigator.pop(c, ImageSource.camera),
          ),
          ListTile(
            leading: const Icon(Icons.photo_library_outlined),
            title: const Text('Choose a photo'),
            onTap: () => Navigator.pop(c, ImageSource.gallery),
          ),
        ],
      ),
    ),
  );
  if (source == null) return;
  final XFile? file;
  try {
    file = await ImagePicker().pickImage(source: source, maxWidth: 2400, maxHeight: 2400, imageQuality: 88);
  } catch (e) {
    if (context.mounted) toast(context, 'Could not open the camera: $e', error: true);
    return;
  }
  if (file == null || !context.mounted) return;
  try {
    final receipt = await s.api.uploadReceipt(s.hid, await file.readAsBytes(), file.name);
    if (!context.mounted) return;
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ReceiptReviewScreen(receiptId: receipt.id)));
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
  }
}

class ReceiptsScreen extends StatefulWidget {
  const ReceiptsScreen({super.key});
  @override
  State<ReceiptsScreen> createState() => _ReceiptsScreenState();
}

class _ReceiptsScreenState extends State<ReceiptsScreen> {
  List<Receipt>? _list;
  ChatGPTStatus? _gpt;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    final list = await s.api.receipts(s.hid);
    ChatGPTStatus? gpt;
    try {
      gpt = await s.api.chatgpt(s.hid);
    } catch (_) {}
    if (mounted) {
      setState(() {
        _list = list;
        _gpt = gpt;
      });
    }
  }

  Future<void> _new() async {
    await scanReceipt(context);
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final list = _list;
    return Scaffold(
      appBar: AppBar(title: const Text('Receipts')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _new,
        icon: const Icon(Icons.receipt_long),
        label: const Text('Scan receipt'),
      ),
      body: list == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                children: [
                  if (_gpt != null && !_gpt!.connected)
                    Card(
                      margin: const EdgeInsets.all(12),
                      child: ListTile(
                        leading: const Icon(Icons.auto_awesome),
                        title: const Text('Connect ChatGPT to read receipts'),
                        subtitle: const Text('Uses your ChatGPT subscription, no API key'),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () async {
                          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ChatGPTScreen()));
                          if (mounted) _load();
                        },
                      ),
                    ),
                  if (list.isEmpty)
                    const EmptyState(
                      icon: Icons.receipt_long_outlined,
                      title: 'No receipts yet',
                      message: 'Photograph a grocery receipt: every line goes into the pantry with its price.',
                    ),
                  for (final r in list)
                    ListTile(
                      leading: _StatusIcon(r.status),
                      title: Text(r.storeName ?? (r.reading ? 'Reading…' : 'Receipt')),
                      subtitle: Text(
                        [
                          dateFmtYear.format(r.purchasedOn ?? r.createdAt),
                          if (r.lineCount > 0) '${r.lineCount} lines',
                          if (r.status == 'parsed') 'to review',
                          if (r.status == 'failed') 'could not read',
                        ].join(' · '),
                      ),
                      trailing: Text(r.total == null ? '' : '${r.currency ?? ''} ${money(r.total)}'),
                      onTap: () async {
                        await Navigator.of(context)
                            .push(MaterialPageRoute(builder: (_) => ReceiptReviewScreen(receiptId: r.id)));
                        if (mounted) _load();
                      },
                    ),
                  const SizedBox(height: 96),
                ],
              ),
            ),
    );
  }
}

class _StatusIcon extends StatelessWidget {
  final String status;
  const _StatusIcon(this.status);
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return switch (status) {
      'new' => const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2)),
      'parsed' => Icon(Icons.rate_review_outlined, color: Colors.orange.shade800),
      'confirmed' => Icon(Icons.check_circle, color: cs.primary),
      _ => Icon(Icons.error_outline, color: cs.error),
    };
  }
}

class ReceiptReviewScreen extends StatefulWidget {
  final String receiptId;
  const ReceiptReviewScreen({super.key, required this.receiptId});
  @override
  State<ReceiptReviewScreen> createState() => _ReceiptReviewScreenState();
}

class _ReceiptReviewScreenState extends State<ReceiptReviewScreen> {
  Receipt? _r;
  Uint8List? _photo;
  Timer? _poll;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _load();
      _loadPhoto();
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    try {
      final r = await s.api.receipt(s.hid, widget.receiptId);
      if (!mounted) return;
      setState(() => _r = r);
      _poll?.cancel();
      if (r.reading) _poll = Timer(const Duration(seconds: 2), _load);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _loadPhoto() async {
    final s = Kasita.read(context);
    try {
      final b = await s.api.receiptImage(s.hid, widget.receiptId);
      if (mounted) setState(() => _photo = b);
    } catch (_) {}
  }

  Future<void> _run(Future<void> Function() fn) async {
    setState(() => _busy = true);
    try {
      await fn();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reread() => _run(() async {
    final s = Kasita.read(context);
    await s.api.reparseReceipt(s.hid, widget.receiptId);
    await _load();
  });

  Future<void> _confirm() => _run(() async {
    final s = Kasita.read(context);
    final r = _r!;
    final unmatched = r.lines!.where((l) => !l.skip && l.productId == null).length;
    if (unmatched > 0) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Create new products?'),
          content: Text(
            '$unmatched line${unmatched == 1 ? '' : 's'} are not linked to a product yet. '
            'Kasita will create ${unmatched == 1 ? 'a product' : 'products'} named as shown. '
            'Skip lines that are not groceries.',
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Back')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Create and add')),
          ],
        ),
      );
      if (ok != true) return;
    }
    final res = await s.api.confirmReceipt(s.hid, r.id);
    s.changed();
    await s.reloadStores();
    if (!mounted) return;
    toast(context, 'Added ${res['added']} item${res['added'] == 1 ? '' : 's'} to the pantry');
    Navigator.pop(context);
  });

  Future<void> _delete() async {
    final s = Kasita.read(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Delete this receipt?'),
        content: Text(
          _r?.status == 'confirmed'
              ? 'The photo and lines are removed. What was added to the pantry stays.'
              : 'The photo and lines are removed.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Delete')),
        ],
      ),
    );
    if (ok != true) return;
    await s.api.deleteReceipt(s.hid, widget.receiptId);
    if (mounted) Navigator.pop(context);
  }

  void _showPhoto() {
    if (_photo == null) return;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => Scaffold(
          appBar: AppBar(title: const Text('Receipt')),
          body: InteractiveViewer(maxScale: 6, child: Center(child: Image.memory(_photo!))),
        ),
      ),
    );
  }

  Future<void> _pickStore() async {
    final s = Kasita.read(context);
    final r = _r!;
    final chosen = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            if (r.storeName != null && !s.stores.any((st) => st.name.toLowerCase() == r.storeName!.toLowerCase()))
              ListTile(
                leading: const Icon(Icons.add_business_outlined),
                title: Text('New store "${r.storeName}"'),
                subtitle: const Text('Created when you add the items'),
                onTap: () => Navigator.pop(c, ''),
              ),
            for (final st in s.stores)
              ListTile(
                title: Text(st.name),
                trailing: st.id == r.storeId ? const Icon(Icons.check) : null,
                onTap: () => Navigator.pop(c, st.id),
              ),
          ],
        ),
      ),
    );
    if (chosen == null) return;
    await _run(() async {
      await s.api.updateReceipt(s.hid, r.id, {'store_id': chosen.isEmpty ? null : chosen});
      await _load();
    });
  }

  Future<void> _pickDate() async {
    final s = Kasita.read(context);
    final r = _r!;
    final d = await showDatePicker(
      context: context,
      initialDate: r.purchasedOn ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (d == null) return;
    await _run(() async {
      await s.api.updateReceipt(s.hid, r.id, {'purchased_on': DateFormat('yyyy-MM-dd').format(d)});
      await _load();
    });
  }

  Future<void> _editLine(ReceiptLine? line) async {
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _LineEditor(receiptId: widget.receiptId, line: line),
    );
    if (changed == true) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    final r = _r;
    final t = Theme.of(context);
    final editable = r != null && r.status != 'confirmed';
    return Scaffold(
      appBar: AppBar(
        title: const Text('Receipt'),
        actions: [
          if (r != null && editable && !r.reading)
            IconButton(tooltip: 'Read again', icon: const Icon(Icons.refresh), onPressed: _busy ? null : _reread),
          if (r != null) IconButton(tooltip: 'Delete', icon: const Icon(Icons.delete_outline), onPressed: _delete),
        ],
      ),
      bottomNavigationBar: r != null && r.status == 'parsed'
          ? SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: FilledButton.icon(
                  onPressed: _busy ? null : _confirm,
                  icon: const Icon(Icons.kitchen),
                  label: Text('Add ${r.lines!.where((l) => !l.skip).length} items to the pantry'),
                ),
              ),
            )
          : null,
      body: r == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                // header: photo + store/date/total
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      GestureDetector(
                        onTap: _showPhoto,
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: Container(
                            width: 72,
                            height: 110,
                            color: t.colorScheme.surfaceContainerHighest,
                            child: _photo == null
                                ? const Icon(Icons.receipt_long_outlined)
                                : Image.memory(_photo!, fit: BoxFit.cover),
                          ),
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            InkWell(
                              onTap: editable && !r.reading ? _pickStore : null,
                              child: Text(
                                s.stores.where((st) => st.id == r.storeId).firstOrNull?.name ??
                                    r.storeName ??
                                    (r.reading ? 'Reading…' : 'Which store?'),
                                style: t.textTheme.titleLarge,
                              ),
                            ),
                            InkWell(
                              onTap: editable && !r.reading ? _pickDate : null,
                              child: Padding(
                                padding: const EdgeInsets.symmetric(vertical: 4),
                                child: Text(dateFmtYear.format(r.purchasedOn ?? r.createdAt)),
                              ),
                            ),
                            if (r.total != null)
                              Text('Total ${r.currency ?? ''} ${money(r.total)}', style: t.textTheme.titleMedium),
                            if (r.total != null && r.linesTotal != null && (r.total! - r.linesTotal!).abs() > 0.05)
                              Text(
                                'Lines add up to ${money(r.linesTotal)}: a line may be missing or misread',
                                style: TextStyle(color: Colors.orange.shade800, fontSize: 12),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                if (r.reading)
                  const Padding(
                    padding: EdgeInsets.all(24),
                    child: Column(
                      children: [
                        CircularProgressIndicator(),
                        SizedBox(height: 16),
                        Text('ChatGPT is reading the receipt. This takes up to a minute.', textAlign: TextAlign.center),
                      ],
                    ),
                  ),
                if (r.status == 'failed')
                  Card(
                    margin: const EdgeInsets.symmetric(horizontal: 16),
                    color: t.colorScheme.errorContainer,
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(r.error ?? 'Could not read this receipt'),
                          const SizedBox(height: 8),
                          Wrap(
                            spacing: 8,
                            children: [
                              if ((r.error ?? '').contains('not connected') || (r.error ?? '').contains('sign-in'))
                                FilledButton(
                                  onPressed: () async {
                                    await Navigator.of(context)
                                        .push(MaterialPageRoute(builder: (_) => const ChatGPTScreen()));
                                    if (mounted) _reread();
                                  },
                                  child: const Text('Connect ChatGPT'),
                                ),
                              OutlinedButton(onPressed: _busy ? null : _reread, child: const Text('Try again')),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                if (r.status == 'confirmed')
                  ListTile(
                    leading: Icon(Icons.check_circle, color: t.colorScheme.primary),
                    title: const Text('Added to the pantry'),
                  ),
                if (r.status == 'parsed')
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                    child: Text(
                      'Check the lines: tap one to link it to a product or skip it. '
                      'Kasita remembers your choices for the next receipt from this store.',
                      style: t.textTheme.bodySmall,
                    ),
                  ),
                for (final l in r.lines ?? const <ReceiptLine>[])
                  _LineTile(line: l, onTap: editable ? () => _editLine(l) : null),
                if (editable && !r.reading && r.status == 'parsed')
                  ListTile(
                    leading: const Icon(Icons.add),
                    title: const Text('Add a line the AI missed'),
                    onTap: () => _editLine(null),
                  ),
                const SizedBox(height: 24),
              ],
            ),
    );
  }
}

class _LineTile extends StatelessWidget {
  final ReceiptLine line;
  final VoidCallback? onTap;
  const _LineTile({required this.line, this.onTap});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final l = line;
    final (icon, color, note) = l.skip
        ? (Icons.remove_circle_outline, t.colorScheme.outline, 'skipped')
        : switch (l.matchedBy) {
            'alias' => (Icons.check_circle_outline, t.colorScheme.primary, l.productName ?? ''),
            'user' => (Icons.check_circle_outline, t.colorScheme.primary, l.productName ?? ''),
            'guess' => (Icons.help_outline, Colors.orange.shade800, '${l.productName}? check'),
            _ => (Icons.add_circle_outline, t.colorScheme.tertiary, 'new product'),
          };
    return ListTile(
      onTap: onTap,
      leading: Icon(icon, color: color),
      title: Text(
        l.label,
        style: l.skip ? TextStyle(decoration: TextDecoration.lineThrough, color: t.colorScheme.outline) : null,
      ),
      subtitle: Text('${l.rawText}  ·  $note', maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(money(l.lineTotal), style: t.textTheme.bodyLarge),
          if (l.quantity != 1) Text('${fmtQty(l.quantity)} × ${money(l.unitPrice)}', style: t.textTheme.bodySmall),
        ],
      ),
    );
  }
}

/// Edit one receipt line: which product it is, amount and price, or skip it.
class _LineEditor extends StatefulWidget {
  final String receiptId;
  final ReceiptLine? line; // null = add a new line
  const _LineEditor({required this.receiptId, this.line});
  @override
  State<_LineEditor> createState() => _LineEditorState();
}

class _LineEditorState extends State<_LineEditor> {
  late final _name = TextEditingController(text: widget.line?.label ?? '');
  late final _qty = TextEditingController(text: fmtQty(widget.line?.quantity ?? 1));
  late final _total = TextEditingController(
    text: widget.line?.lineTotal == null ? '' : widget.line!.lineTotal!.toStringAsFixed(2),
  );
  late String? _productId = widget.line?.productId;
  late String? _productName = widget.line?.productName;
  late bool _skip = widget.line?.skip ?? false;
  bool _busy = false;

  double? _n(String v) => double.tryParse(v.replaceAll(',', '.').trim());

  Future<void> _chooseProduct() async {
    final picked = await Navigator.of(context)
        .push<Product>(MaterialPageRoute(builder: (_) => _ProductPicker(initialQuery: _name.text)));
    if (picked != null) {
      setState(() {
        _productId = picked.id;
        _productName = picked.name;
      });
    }
  }

  Future<void> _save() async {
    final s = Kasita.read(context);
    final qty = _n(_qty.text) ?? 1;
    final total = _n(_total.text);
    setState(() => _busy = true);
    try {
      if (widget.line == null) {
        await s.api.addReceiptLine(s.hid, widget.receiptId, {
          'raw_text': _name.text.trim(),
          'name': _name.text.trim(),
          'quantity': qty,
          'line_total': total,
          'unit_price': total == null ? null : double.parse((total / qty).toStringAsFixed(2)),
          'product_id': _productId,
          'skip': _skip,
        });
      } else {
        await s.api.updateReceiptLine(s.hid, widget.receiptId, widget.line!.id, {
          'name': _name.text.trim().isEmpty ? null : _name.text.trim(),
          'quantity': qty,
          'line_total': total,
          'unit_price': total == null ? null : double.parse((total / qty).toStringAsFixed(2)),
          'skip': _skip,
          if (_productId != null && _productId != widget.line!.productId) 'product_id': _productId,
          if (_productId == null && widget.line!.productId != null) 'clear_product': true,
        });
      }
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final s = Kasita.read(context);
    await s.api.deleteReceiptLine(s.hid, widget.receiptId, widget.line!.id);
    if (mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    final line = widget.line;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.viewInsetsOf(context).bottom + 20),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (line != null) Text('On the receipt: ${line.rawText}', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 8),
            TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'Name', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _qty,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Quantity', border: OutlineInputBorder()),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextField(
                    controller: _total,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Line total', border: OutlineInputBorder()),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.inventory_2_outlined),
              title: Text(_productName ?? 'New product'),
              subtitle: Text(
                _productId == null
                    ? 'Created from the name above when you add the receipt'
                    : 'This line is this product',
              ),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (_productId != null)
                    IconButton(
                      tooltip: 'Make it a new product',
                      icon: const Icon(Icons.close),
                      onPressed: () => setState(() {
                        _productId = null;
                        _productName = null;
                      }),
                    ),
                  TextButton(onPressed: _chooseProduct, child: const Text('Choose')),
                ],
              ),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Skip this line'),
              subtitle: const Text('Not something to keep in stock (bag, deposit, non-grocery)'),
              value: _skip,
              onChanged: (v) => setState(() => _skip = v),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                if (line != null)
                  TextButton.icon(
                    onPressed: _busy ? null : _delete,
                    icon: const Icon(Icons.delete_outline),
                    label: const Text('Remove'),
                  ),
                const Spacer(),
                FilledButton(
                  onPressed: _busy || _name.text.trim().isEmpty && line == null ? null : _save,
                  child: const Text('Save'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ProductPicker extends StatefulWidget {
  final String initialQuery;
  const _ProductPicker({required this.initialQuery});
  @override
  State<_ProductPicker> createState() => _ProductPickerState();
}

class _ProductPickerState extends State<_ProductPicker> {
  List<Product>? _all;
  String _q = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final s = Kasita.read(context);
      final all = await s.api.products(s.hid);
      if (mounted) setState(() => _all = all);
    });
  }

  @override
  Widget build(BuildContext context) {
    final q = _q.toLowerCase();
    final list = (_all ?? [])
        .where((p) => q.isEmpty || '${p.name} ${p.brand ?? ''}'.toLowerCase().contains(q))
        .toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Which product?')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: SearchBar(
              hintText: 'Search products (receipt: ${widget.initialQuery})',
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
                          subtitle: Text([p.brand, p.category].whereType<String>().join(' · ')),
                          onTap: () => Navigator.pop(context, p),
                        ),
                      if (list.isEmpty)
                        const Padding(
                          padding: EdgeInsets.all(24),
                          child: Text('No match. Go back and leave it as a new product.', textAlign: TextAlign.center),
                        ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}
