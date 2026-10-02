import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';

/// The shops this household buys from. Receipts fill in their address, phone and CRIB.
class StoresScreen extends StatelessWidget {
  const StoresScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Stores')),
      body: s.stores.isEmpty
          ? const EmptyState(
              icon: Icons.storefront_outlined,
              title: 'No stores yet',
              message: 'Each receipt you book adds its store here, with its address and phone.',
            )
          : RefreshIndicator(
              onRefresh: s.reloadStores,
              child: ListView(
                children: [
                  for (final st in s.stores)
                    ListTile(
                      leading: Icon(st.located ? Icons.location_on_outlined : Icons.storefront_outlined),
                      title: Text(st.name),
                      subtitle: st.address == null && st.phone == null
                          ? null
                          : Text([st.address, st.phone].whereType<String>().join(' · ')),
                      onTap: () =>
                          Navigator.of(context).push(MaterialPageRoute(builder: (_) => StoreEditScreen(store: st))),
                    ),
                ],
              ),
            ),
    );
  }
}

/// Edit a store's profile. What you type here is never overwritten by later receipts.
class StoreEditScreen extends StatefulWidget {
  final Store store;
  const StoreEditScreen({super.key, required this.store});
  @override
  State<StoreEditScreen> createState() => _StoreEditScreenState();
}

class _StoreEditScreenState extends State<StoreEditScreen> {
  final _form = GlobalKey<FormState>();
  late final _name = TextEditingController(text: widget.store.name);
  late final _address = TextEditingController(text: widget.store.address ?? '');
  late final _phone = TextEditingController(text: widget.store.phone ?? '');
  late final _crib = TextEditingController(text: widget.store.crib ?? '');
  late final _payee = TextEditingController(text: widget.store.payeeMatch ?? '');
  bool _busy = false;

  String? _t(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    final s = Kasita.read(context);
    setState(() => _busy = true);
    try {
      await s.api.updateStore(s.hid, widget.store.id, {
        'name': _name.text.trim(),
        'address': _t(_address),
        'phone': _t(_phone),
        'crib': _t(_crib),
        'payee_match': _t(_payee),
      });
      await s.reloadStores();
      if (mounted) Navigator.pop(context);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _field(TextEditingController c, String label, {String? help, TextInputType? keyboard}) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextFormField(
      controller: c,
      keyboardType: keyboard,
      decoration: InputDecoration(labelText: label, helperText: help, border: const OutlineInputBorder()),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final st = widget.store;
    return Scaffold(
      appBar: AppBar(title: const Text('Store')),
      body: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                validator: (v) => (v == null || v.trim().isEmpty) ? 'Give it a name' : null,
                decoration: const InputDecoration(labelText: 'Name', border: OutlineInputBorder()),
              ),
            ),
            _field(_address, 'Address', help: 'Street first, then the number: Cas Coraweg 78'),
            _field(_phone, 'Phone', keyboard: TextInputType.phone),
            _field(
              _crib,
              'CRIB number',
              help: 'Tax number printed on the receipt. Recognises this store even when the name is misread.',
              keyboard: TextInputType.number,
            ),
            _field(_payee, 'Shows on card payments as', help: 'For linking receipts in Securo, e.g. MANGUSA'),
            if (st.located)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.location_on_outlined),
                title: Text(st.locationSource == 'manual' ? 'Placed on the map by hand' : 'Found on the map'),
                subtitle: Text('${st.lat!.toStringAsFixed(5)}, ${st.lon!.toStringAsFixed(5)}'),
              ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _busy ? null : _save,
              child: const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: Text('Save')),
            ),
          ],
        ),
      ),
    );
  }
}
