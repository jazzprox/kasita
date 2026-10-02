import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'receipts.dart' show money;
import 'securo.dart';

/// Utility bills (Aqualectra, Selikor, Flow...): photograph them, ChatGPT reads
/// what each service costs, then tick the bills that were paid together and
/// book them on that payment in Securo (photos, Utilities, a breakdown note),
/// or record the payment there when it was cash or never showed up.
class BillsScreen extends StatefulWidget {
  const BillsScreen({super.key});
  @override
  State<BillsScreen> createState() => _BillsScreenState();
}

class _BillsScreenState extends State<BillsScreen> {
  List<Bill>? _bills;
  final _picked = <String>{};
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
      final bills = await s.api.bills(s.hid);
      if (!mounted) return;
      setState(() {
        _bills = bills;
        _picked.removeWhere((id) => !bills.any((b) => b.id == id && b.ready));
      });
      _poll?.cancel();
      if (bills.any((b) => b.reading)) _poll = Timer(const Duration(seconds: 2), _load);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  List<Bill> get _selection => [
    for (final b in _bills ?? const <Bill>[])
      if (_picked.contains(b.id)) b,
  ];

  double get _selectedTotal => _selection.fold(0, (n, b) => n + (b.total ?? 0));

  Future<void> _add() async {
    final how = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.add_a_photo_outlined),
              title: const Text('Photograph it'),
              subtitle: const Text('The bill, or the payment receipts; several in one go is fine'),
              onTap: () => Navigator.pop(c, 'photo'),
            ),
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Type it in'),
              subtitle: const Text('No paper: who you paid and how much'),
              onTap: () => Navigator.pop(c, 'hand'),
            ),
          ],
        ),
      ),
    );
    if (!mounted) return;
    if (how == 'photo') await _addPhoto();
    if (how == 'hand') await _addByHand();
  }

  Future<void> _addByHand() async {
    final s = Kasita.read(context);
    final biller = TextEditingController();
    final amount = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Add a bill'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: biller,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Who you paid', hintText: 'Aqualectra, Flow…'),
            ),
            TextField(
              controller: amount,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Amount'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Add')),
        ],
      ),
    );
    final value = double.tryParse(amount.text.trim().replaceAll(',', '.'));
    if (ok != true || !mounted) return;
    if (value == null) {
      toast(context, 'The amount is not a number', error: true);
      return;
    }
    try {
      final b = await s.api.addBillByHand(s.hid, {
        if (biller.text.trim().isNotEmpty) 'biller': biller.text.trim(),
        'total': value.toStringAsFixed(2),
      });
      if (mounted) await _open(b); // services, dates and so on, if wanted
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _addPhoto() async {
    final s = Kasita.read(context);
    final pages = await _capture(context);
    if (pages == null || !mounted) return;
    try {
      final b = await s.api.uploadBill(s.hid, pages);
      if (!mounted) return;
      setState(() => _bills = [b, ...?_bills]);
      _poll?.cancel();
      _poll = Timer(const Duration(seconds: 2), _load);
      final again = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Bill added'),
          content: const Text('ChatGPT is reading it. Paid more bills at once? Photograph the next one now.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('That was all')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Next bill')),
          ],
        ),
      );
      if (again == true && mounted) await _addPhoto();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _rowAction(Bill b, String action) async {
    final s = Kasita.read(context);
    try {
      switch (action) {
        case 'edit':
          await _open(b);
          return;
        case 'retake':
          if (await retakeBill(context, b) == null) return;
        case 'reread':
          await s.api.reparseBill(s.hid, b.id);
        case 'unlink':
          await s.api.unlinkBill(s.hid, b.id);
        case 'delete':
          if (!await deleteBill(context, b)) return;
      }
      _picked.remove(b.id);
      if (mounted) await _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _open(Bill b) async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => BillScreen(billId: b.id)));
    if (mounted) _load();
  }

  Future<void> _findPayment() async {
    final s = Kasita.read(context);
    final bills = _selection;
    setState(() => _busy = true);
    List<SecuroPayment> found;
    try {
      found = await s.api.billPayments(s.hid, [for (final b in bills) b.id]);
    } on ApiException catch (e) {
      if (mounted) _securoProblem(e.message);
      return;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (!mounted) return;
    final exact = found.any((p) => p.score > 0);
    final choice = await showModalBottomSheet<Object>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (c) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.of(c).size.height * 0.75),
          child: ListView(
            shrinkWrap: true,
            children: [
              ListTile(
                title: Text('Payment of ${money(_selectedTotal)}'),
                subtitle: Text(
                  found.isEmpty
                      ? 'Securo has no payment of that amount since these bills came in.'
                      : exact
                      ? 'Tap the payment these ${bills.length == 1 ? 'bill was' : '${bills.length} bills were'} paid with.'
                      : 'No payment of exactly that amount. These look like bill payments; tap one if it is it.',
                ),
              ),
              for (final p in found)
                ListTile(
                  leading: Icon(p.score > 0 ? Icons.check_circle_outline : Icons.help_outline),
                  title: Text(p.description ?? 'Payment'),
                  subtitle: Text(
                    [
                      if (p.date != null) dateFmtYear.format(p.date!),
                      if (p.notes != null) p.notes!,
                      if (p.attachmentCount > 0) '${p.attachmentCount} attachment(s)',
                    ].join(' · '),
                  ),
                  trailing: Text('${p.currency ?? ''} ${money(p.amount)}'),
                  onTap: () => Navigator.pop(c, p),
                ),
              ListTile(
                leading: const Icon(Icons.add_card_outlined),
                title: const Text('Not there: record the payment'),
                subtitle: const Text('Paid cash, or the payment never came into Securo'),
                onTap: () => Navigator.pop(c, 'record'),
              ),
            ],
          ),
        ),
      ),
    );
    if (!mounted) return;
    if (choice is SecuroPayment) await _link(bills, choice);
    if (choice == 'record') await _record();
  }

  Future<void> _link(List<Bill> bills, SecuroPayment p) async {
    final s = Kasita.read(context);
    var photos = true, category = true, note = true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: Text('Book on ${p.description ?? 'this payment'}?'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: photos,
                onChanged: (v) => set(() => photos = v ?? true),
                title: Text(bills.length == 1 ? 'Attach the bill photo' : 'Attach all ${bills.length} bill photos'),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: category,
                onChanged: (v) => set(() => category = v ?? true),
                title: const Text('Put it in Utilities'),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: note,
                onChanged: (v) => set(() => note = v ?? true),
                title: const Text('Add what each bill was to its note'),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Book')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    try {
      final r = await s.api.linkBills(
        s.hid,
        [for (final b in bills) b.id],
        p.id,
        photos: photos,
        category: category,
        note: note,
      );
      _booked(r);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _record() async {
    final s = Kasita.read(context);
    final bills = _selection;
    setState(() => _busy = true);
    List<SecuroAccount> accounts;
    try {
      accounts = await s.api.securoAccounts(s.hid);
    } on ApiException catch (e) {
      if (mounted) _securoProblem(e.message);
      return;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (!mounted || accounts.isEmpty) return;
    final billers = bills.map((b) => b.biller).whereType<String>().toSet().join(', ');
    final what = TextEditingController(text: billers.isEmpty ? 'Bills' : billers);
    var account = accounts.first;
    var day = DateTime.now();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: Text('Record ${money(_selectedTotal)} in Securo'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<SecuroAccount>(
                initialValue: account,
                decoration: const InputDecoration(labelText: 'Paid from'),
                items: [
                  for (final a in accounts)
                    DropdownMenuItem(value: a, child: Text('${a.name}${a.currency == null ? '' : ' (${a.currency})'}')),
                ],
                onChanged: (a) => set(() => account = a ?? account),
              ),
              TextField(
                controller: what,
                decoration: const InputDecoration(labelText: 'Description'),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.event_outlined),
                title: Text('Paid on ${dateFmtYear.format(day)}'),
                onTap: () async {
                  final d = await showDatePicker(
                    context: c,
                    initialDate: day,
                    firstDate: DateTime.now().subtract(const Duration(days: 365)),
                    lastDate: DateTime.now(),
                  );
                  if (d != null) set(() => day = d);
                },
              ),
              Text(
                'Goes in Utilities with the bill photos and a breakdown note.',
                style: Theme.of(c).textTheme.bodySmall,
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Record')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    try {
      _booked(
        await s.api.recordBills(s.hid, [for (final b in bills) b.id], account.id, day, description: what.text.trim()),
      );
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _booked(Map<String, dynamic> r) {
    if (!mounted) return;
    final skipped = List<String>.from(r['skipped'] ?? const []);
    toast(context, skipped.isEmpty ? 'Booked in Securo' : 'Booked in Securo. ${skipped.join('. ')}');
    _picked.clear();
    _load();
  }

  void _securoProblem(String message) {
    showDialog<void>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Securo'),
        content: Text(message),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Close')),
          if (message.contains('not connected') || message.contains('expired'))
            FilledButton(
              onPressed: () {
                Navigator.pop(c);
                Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SecuroScreen()));
              },
              child: const Text('Connect Securo'),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final bills = _bills;
    final open = bills?.where((b) => !b.booked).toList() ?? const <Bill>[];
    final booked = bills?.where((b) => b.booked).toList() ?? const <Bill>[];
    return Scaffold(
      appBar: AppBar(title: const Text('Bills')),
      floatingActionButton: _picked.isEmpty
          ? FloatingActionButton.extended(onPressed: _add, icon: const Icon(Icons.add), label: const Text('Add bill'))
          : null,
      bottomNavigationBar: _picked.isEmpty
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      '${_picked.length} bill${_picked.length == 1 ? '' : 's'} · ${money(_selectedTotal)}',
                      style: t.textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: FilledButton.icon(
                            onPressed: _busy ? null : _findPayment,
                            icon: _busy
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(strokeWidth: 2),
                                  )
                                : const Icon(Icons.search),
                            label: const Text('Find payment'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: _busy ? null : _record,
                            icon: const Icon(Icons.add_card_outlined),
                            label: const Text('Record it'),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
      body: bills == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: navBarSafe(context, const EdgeInsets.only(bottom: 96)),
                children: [
                  if (bills.isEmpty)
                    const Padding(
                      padding: EdgeInsets.all(24),
                      child: Text(
                        'Photograph each bill you paid (water and electricity, garbage, internet...). '
                        'ChatGPT reads what each one costs. Then tick the bills you paid together and '
                        'Kasita finds that payment in Securo, attaches the photos and notes the breakdown.',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  if (open.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Text('Tick the bills paid together', style: t.textTheme.titleSmall),
                    ),
                  for (final b in open) _row(b),
                  if (booked.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 20, 16, 4),
                      child: Text('Booked in Securo', style: t.textTheme.titleSmall),
                    ),
                  for (final b in booked) _row(b),
                ],
              ),
            ),
    );
  }

  Widget _row(Bill b) {
    final t = Theme.of(context);
    final subtitle = b.reading
        ? 'ChatGPT is reading it…'
        : b.status == 'failed'
        ? (b.error ?? 'Could not read it. Tap to fill it in.')
        : [
            if (b.services.isNotEmpty) b.services,
            if (b.period != null) b.period!,
            if (b.dueDate != null && !b.booked) 'due ${dateFmt.format(b.dueDate!)}',
          ].join(' · ');
    final tile = ListTile(
      leading: b.booked
          ? Icon(Icons.check_circle, color: t.colorScheme.primary)
          : b.reading
          ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
          : Checkbox(
              value: _picked.contains(b.id),
              onChanged: b.ready ? (v) => setState(() => v == true ? _picked.add(b.id) : _picked.remove(b.id)) : null,
            ),
      title: Text(b.biller ?? (b.reading ? 'New bill' : 'Bill')),
      subtitle: Text(
        subtitle.isEmpty ? dateFmtYear.format(b.billDate ?? b.createdAt) : subtitle,
        style: b.status == 'failed' ? TextStyle(color: t.colorScheme.error) : null,
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(b.total == null ? '' : '${b.currency ?? ''} ${money(b.total)}'),
          PopupMenuButton<String>(
            tooltip: 'Edit, retake, delete',
            onSelected: (v) => _rowAction(b, v),
            itemBuilder: (_) => billActions(b),
          ),
        ],
      ),
      contentPadding: const EdgeInsets.only(left: 16, right: 4),
      onTap: () => _open(b),
    );
    return Dismissible(
      key: ValueKey(b.id),
      direction: DismissDirection.endToStart,
      background: Container(
        color: t.colorScheme.errorContainer,
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 24),
        child: Icon(Icons.delete_outline, color: t.colorScheme.onErrorContainer),
      ),
      confirmDismiss: (_) => deleteBill(context, b),
      onDismissed: (_) => setState(() {
        _picked.remove(b.id);
        _bills?.removeWhere((x) => x.id == b.id);
      }),
      child: tile,
    );
  }
}

/// The same actions everywhere a bill shows: the list row menu and the bill screen.
List<PopupMenuEntry<String>> billActions(Bill b, {bool edit = true}) => [
  if (edit)
    const PopupMenuItem(
      value: 'edit',
      child: ListTile(leading: Icon(Icons.edit_outlined), title: Text('Edit')),
    ),
  if (!b.booked)
    PopupMenuItem(
      value: 'retake',
      child: ListTile(
        leading: const Icon(Icons.add_a_photo_outlined),
        title: Text(b.hasPhoto ? 'Retake photos' : 'Add photos'),
      ),
    ),
  if (!b.booked && b.hasPhoto && !b.reading)
    const PopupMenuItem(
      value: 'reread',
      child: ListTile(leading: Icon(Icons.refresh), title: Text('Read again')),
    ),
  if (b.booked)
    const PopupMenuItem(
      value: 'unlink',
      child: ListTile(leading: Icon(Icons.link_off), title: Text('Unlink from Securo')),
    ),
  const PopupMenuItem(
    value: 'delete',
    child: ListTile(leading: Icon(Icons.delete_outline), title: Text('Delete')),
  ),
];

/// Start over: new photos replace the old ones and ChatGPT reads the bill from scratch.
Future<Bill?> retakeBill(BuildContext context, Bill b) async {
  final s = Kasita.read(context);
  final pages = await _capture(context);
  if (pages == null || pages.isEmpty || !context.mounted) return null;
  return s.api.replaceBillPhotos(s.hid, b.id, pages);
}

/// Asks first; true when it is gone.
Future<bool> deleteBill(BuildContext context, Bill b) async {
  final s = Kasita.read(context);
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text('Delete ${b.biller ?? 'this bill'}?'),
      content: Text(b.booked ? 'Only from Kasita: what was booked in Securo stays there.' : 'The photos go too.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Delete')),
      ],
    ),
  );
  if (ok != true || !context.mounted) return false;
  try {
    await s.api.deleteBill(s.hid, b.id);
    return true;
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
    return false;
  }
}

/// Camera or gallery; a bill with several pages is photographed page by page.
Future<List<(Uint8List, String)>?> _capture(BuildContext context) async {
  final pages = <(Uint8List, String)>[];
  while (true) {
    final src = await showModalBottomSheet<Object>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (pages.isNotEmpty)
              ListTile(
                leading: CircleAvatar(child: Text('${pages.length}')),
                title: Text(pages.length == 1 ? '1 photo added' : '${pages.length} photos added'),
                subtitle: const Text(
                  'Another page, or another receipt paid at the same time? Add it here. The card slip may be included; it is not counted twice.',
                ),
              ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: Text(pages.isEmpty ? 'Take a photo' : 'Add another photo'),
              onTap: () => Navigator.pop(c, ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: Text(pages.isEmpty ? 'Choose a photo or screenshot' : 'Another photo from the gallery'),
              onTap: () => Navigator.pop(c, ImageSource.gallery),
            ),
            if (pages.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                child: FilledButton.icon(
                  onPressed: () => Navigator.pop(c, 'done'),
                  icon: const Icon(Icons.check),
                  label: const Text('Done, read it'),
                ),
              ),
          ],
        ),
      ),
    );
    if (!context.mounted) return null;
    if (src == 'done') return pages;
    if (src == null) return pages.isEmpty ? null : pages;
    final XFile? file;
    try {
      file = await ImagePicker().pickImage(source: src as ImageSource, maxWidth: 2200, imageQuality: 88);
    } catch (e) {
      if (context.mounted) toast(context, 'Could not open the camera: $e', error: true);
      return null;
    }
    if (file == null) {
      if (pages.isEmpty) return null;
      continue;
    }
    pages.add((await file.readAsBytes(), file.name));
    if (pages.length >= 8 || !context.mounted) return pages;
  }
}

/// One bill: the photo, and what ChatGPT read, to check and correct.
class BillScreen extends StatefulWidget {
  final String billId;
  const BillScreen({super.key, required this.billId});
  @override
  State<BillScreen> createState() => _BillScreenState();
}

class _BillScreenState extends State<BillScreen> {
  Bill? _b;
  Uint8List? _photo;
  Timer? _poll;
  final _biller = TextEditingController();
  final _total = TextEditingController();
  final _period = TextEditingController();
  final _account = TextEditingController();
  List<(TextEditingController, TextEditingController)> _lines = [];
  DateTime? _billDate, _dueDate;
  bool _dirty = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await _load();
      if (!mounted) return;
      final s = Kasita.read(context);
      try {
        final p = await s.api.billImage(s.hid, widget.billId);
        if (mounted) setState(() => _photo = p);
      } catch (_) {}
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    for (final c in [_biller, _total, _period, _account]) {
      c.dispose();
    }
    for (final (a, b) in _lines) {
      a.dispose();
      b.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    final b = await s.api.bill(s.hid, widget.billId);
    if (!mounted) return;
    _fill(b);
    _poll?.cancel();
    if (b.reading) _poll = Timer(const Duration(seconds: 2), _load);
  }

  void _fill(Bill b) {
    for (final (a, c) in _lines) {
      a.dispose();
      c.dispose();
    }
    setState(() {
      _b = b;
      _biller.text = b.biller ?? '';
      _total.text = b.total == null ? '' : b.total!.toStringAsFixed(2);
      _period.text = b.period ?? '';
      _account.text = b.accountRef ?? '';
      _lines = [
        for (final l in b.lines)
          (TextEditingController(text: l.service), TextEditingController(text: l.amount.toStringAsFixed(2))),
      ];
      _billDate = b.billDate;
      _dueDate = b.dueDate;
      _dirty = false;
    });
  }

  double? _parse(String v) => double.tryParse(v.trim().replaceAll(',', '.'));

  double get _linesSum => _lines.fold(0, (n, l) => n + (_parse(l.$2.text) ?? 0));

  Future<void> _save() async {
    final s = Kasita.read(context);
    final total = _parse(_total.text);
    if (_total.text.trim().isNotEmpty && total == null) {
      toast(context, 'The amount is not a number', error: true);
      return;
    }
    String? day(DateTime? d) => d?.toIso8601String().substring(0, 10);
    try {
      final b = await s.api.updateBill(s.hid, widget.billId, {
        'biller': _biller.text.trim().isEmpty ? null : _biller.text.trim(),
        'total': total?.toStringAsFixed(2),
        'period': _period.text.trim().isEmpty ? null : _period.text.trim(),
        'account_ref': _account.text.trim().isEmpty ? null : _account.text.trim(),
        'bill_date': day(_billDate),
        'due_date': day(_dueDate),
        'lines': [
          for (final (svc, amt) in _lines)
            if (svc.text.trim().isNotEmpty && _parse(amt.text) != null)
              BillLine(svc.text.trim(), _parse(amt.text)!).toJson(),
        ],
      });
      _fill(b);
      if (mounted) toast(context, 'Saved');
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _pickDate(bool due) async {
    final d = await showDatePicker(
      context: context,
      initialDate: (due ? _dueDate : _billDate) ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(const Duration(days: 120)),
    );
    if (d == null) return;
    setState(() {
      due ? _dueDate = d : _billDate = d;
      _dirty = true;
    });
  }

  Future<void> _menu(String action) async {
    final s = Kasita.read(context);
    final b = _b;
    if (b == null) return;
    try {
      switch (action) {
        case 'retake':
          final fresh = await retakeBill(context, b);
          if (fresh == null || !mounted) return;
          _fill(fresh);
          setState(() => _photo = null);
          _poll = Timer(const Duration(seconds: 2), _load);
          final p = await s.api.billImage(s.hid, widget.billId);
          if (mounted) setState(() => _photo = p);
        case 'reread':
          _fill(await s.api.reparseBill(s.hid, widget.billId));
          _poll = Timer(const Duration(seconds: 2), _load);
        case 'unlink':
          _fill(await s.api.unlinkBill(s.hid, widget.billId));
          if (mounted) toast(context, 'Unlinked here. The photo and note stay in Securo.');
        case 'delete':
          if (await deleteBill(context, b) && mounted) Navigator.pop(context);
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final b = _b;
    final t = Theme.of(context);
    final total = _parse(_total.text);
    final mismatch = _lines.isNotEmpty && total != null && (_linesSum - total).abs() > 0.009;
    void changed(_) => setState(() => _dirty = true);
    return Scaffold(
      appBar: AppBar(
        title: Text(b?.biller ?? 'Bill'),
        actions: [
          if (b != null) PopupMenuButton<String>(onSelected: _menu, itemBuilder: (_) => billActions(b, edit: false)),
        ],
      ),
      floatingActionButton: _dirty
          ? FloatingActionButton.extended(onPressed: _save, icon: const Icon(Icons.check), label: const Text('Save'))
          : null,
      body: b == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: navBarSafe(context, const EdgeInsets.fromLTRB(16, 8, 16, 96)),
              children: [
                if (_photo != null)
                  GestureDetector(
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => Scaffold(
                          appBar: AppBar(),
                          body: InteractiveViewer(maxScale: 6, child: Center(child: Image.memory(_photo!))),
                        ),
                      ),
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: SizedBox(height: 180, child: Image.memory(_photo!, fit: BoxFit.cover)),
                    ),
                  ),
                const SizedBox(height: 12),
                if (b.reading)
                  const ListTile(
                    leading: SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2)),
                    title: Text('ChatGPT is reading the bill…'),
                  ),
                if (b.status == 'failed')
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Text(
                      '${b.error ?? 'Could not read it.'} Fill it in below, or read it again from the menu.',
                      style: TextStyle(color: t.colorScheme.error),
                    ),
                  ),
                if (b.booked)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.check_circle, color: t.colorScheme.primary),
                    title: const Text('Booked in Securo'),
                  ),
                TextField(
                  controller: _biller,
                  decoration: const InputDecoration(labelText: 'Biller'),
                  onChanged: changed,
                ),
                TextField(
                  controller: _total,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(
                    labelText: 'Amount paid',
                    suffixText: b.currency,
                    helperText: 'What you paid for this bill; change it if you paid a different amount',
                  ),
                  onChanged: changed,
                ),
                const SizedBox(height: 16),
                Text('Per service', style: t.textTheme.titleSmall),
                for (final (i, (svc, amt)) in _lines.indexed)
                  Row(
                    children: [
                      Expanded(
                        flex: 3,
                        child: TextField(controller: svc, onChanged: changed),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        flex: 2,
                        child: TextField(
                          controller: amt,
                          keyboardType: const TextInputType.numberWithOptions(decimal: true),
                          textAlign: TextAlign.end,
                          onChanged: changed,
                        ),
                      ),
                      IconButton(
                        tooltip: 'Remove',
                        icon: const Icon(Icons.close),
                        onPressed: () => setState(() {
                          _lines.removeAt(i);
                          _dirty = true;
                        }),
                      ),
                    ],
                  ),
                if (mismatch)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      'The services add up to ${money(_linesSum)}, not ${money(total)}. '
                      'The Securo note then shows only the total for this bill.',
                      style: t.textTheme.bodySmall?.copyWith(color: t.colorScheme.error),
                    ),
                  ),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: () => setState(() {
                      _lines.add((TextEditingController(), TextEditingController()));
                      _dirty = true;
                    }),
                    icon: const Icon(Icons.add),
                    label: const Text('Add a service'),
                  ),
                ),
                TextField(
                  controller: _period,
                  decoration: const InputDecoration(labelText: 'Period'),
                  onChanged: changed,
                ),
                TextField(
                  controller: _account,
                  decoration: const InputDecoration(labelText: 'Customer / account number'),
                  onChanged: changed,
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.event_outlined),
                  title: Text(_billDate == null ? 'Bill date' : 'Bill date ${dateFmtYear.format(_billDate!)}'),
                  onTap: () => _pickDate(false),
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.event_busy_outlined),
                  title: Text(_dueDate == null ? 'Due date' : 'Due ${dateFmtYear.format(_dueDate!)}'),
                  onTap: () => _pickDate(true),
                ),
                const Divider(height: 32),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    if (!b.booked)
                      OutlinedButton.icon(
                        onPressed: () => _menu('retake'),
                        icon: const Icon(Icons.add_a_photo_outlined),
                        label: Text(b.hasPhoto ? 'Retake photos' : 'Add photos'),
                      ),
                    if (!b.booked && b.hasPhoto && !b.reading)
                      OutlinedButton.icon(
                        onPressed: () => _menu('reread'),
                        icon: const Icon(Icons.refresh),
                        label: const Text('Read again'),
                      ),
                    if (b.booked)
                      OutlinedButton.icon(
                        onPressed: () => _menu('unlink'),
                        icon: const Icon(Icons.link_off),
                        label: const Text('Unlink from Securo'),
                      ),
                    OutlinedButton.icon(
                      onPressed: () => _menu('delete'),
                      icon: Icon(Icons.delete_outline, color: t.colorScheme.error),
                      label: Text('Delete', style: TextStyle(color: t.colorScheme.error)),
                    ),
                  ],
                ),
              ],
            ),
    );
  }
}
