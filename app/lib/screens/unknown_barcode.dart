import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import 'product_form.dart';
import 'product_picker.dart';

/// A barcode the household doesn't know yet: attach it to one of your products
/// (e.g. something that came from a receipt), or create a new product.
/// Returns the product, or null when the person cancelled or skipped.
Future<Product?> productForUnknownBarcode(BuildContext context, BarcodeResult r, {String skipLabel = 'Cancel'}) async {
  final choice = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    builder: (sheet) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ListTile(
            title: Text(r.name ?? 'Barcode ${r.barcode}', style: Theme.of(context).textTheme.titleMedium),
            subtitle: Text(
              r.found
                  ? 'New to your household'
                  : 'Not in any product database${r.brandHint == null ? '' : ' · probably ${r.brandHint}'}',
            ),
          ),
          if (!r.found)
            ListTile(
              leading: const Icon(Icons.travel_explore),
              title: const Text('Look it up on Google'),
              subtitle: const Text('See what it is, then come back and name it once'),
              onTap: () => launchUrl(
                Uri.https('www.google.com', '/search', {'q': r.barcode}),
                mode: LaunchMode.externalApplication,
              ),
            ),
          ListTile(
            leading: const Icon(Icons.photo_camera_outlined),
            title: const Text('Take a photo of it'),
            subtitle: const Text('ChatGPT reads the label and fills in the name for you'),
            onTap: () => Navigator.pop(sheet, 'photo'),
          ),
          ListTile(
            leading: const Icon(Icons.link),
            title: const Text("It's one of my products"),
            subtitle: const Text('Attach this barcode to it, e.g. something added from a receipt'),
            onTap: () => Navigator.pop(sheet, 'link'),
          ),
          ListTile(
            leading: const Icon(Icons.add),
            title: const Text('New product'),
            onTap: () => Navigator.pop(sheet, 'new'),
          ),
          ListTile(leading: const Icon(Icons.close), title: Text(skipLabel), onTap: () => Navigator.pop(sheet)),
        ],
      ),
    ),
  );
  if (!context.mounted || choice == null) return null;
  if (choice == 'photo') {
    final prefill = await _fromPhoto(context, r);
    if (prefill == null || !context.mounted) return null;
    return Navigator.of(context).push<Product>(MaterialPageRoute(builder: (_) => ProductFormScreen(prefill: prefill)));
  }
  if (choice == 'new') {
    return Navigator.of(context).push<Product>(MaterialPageRoute(builder: (_) => ProductFormScreen(prefill: r)));
  }
  final s = Kasita.read(context);
  final picked = await Navigator.of(context).push<Product>(
    MaterialPageRoute(
      builder: (_) => ProductPicker(
        title: 'Attach ${r.barcode} to…',
        hint: r.name == null ? 'Search your products' : 'Search (scanned: ${r.name})',
        barcodeLessFirst: true,
        emptyText: 'No match. Go back and choose New product.',
      ),
    ),
  );
  if (picked == null || !context.mounted) return null;
  try {
    final updated = await s.api.addBarcode(s.hid, picked.id, r.barcode);
    s.changed();
    if (context.mounted) toast(context, 'Barcode attached to ${updated.name}');
    return updated;
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
    return null;
  }
}

/// Photograph the pack, let ChatGPT read it, and turn the answer into a form prefill.
Future<BarcodeResult?> _fromPhoto(BuildContext context, BarcodeResult r) async {
  final s = Kasita.read(context);
  final XFile? shot;
  try {
    shot = await ImagePicker().pickImage(source: ImageSource.camera, maxWidth: 1600, imageQuality: 88);
  } catch (e) {
    if (context.mounted) toast(context, 'Could not open the camera: $e', error: true);
    return null;
  }
  if (shot == null || !context.mounted) return null;
  final bytes = await shot.readAsBytes();
  if (!context.mounted) return null;
  showDialog(
    context: context,
    barrierDismissible: false,
    builder: (_) => const AlertDialog(
      content: Row(
        children: [
          CircularProgressIndicator(),
          SizedBox(width: 20),
          Expanded(child: Text('Reading the label…')),
        ],
      ),
    ),
  );
  try {
    final got = await s.api.identifyProduct(s.hid, bytes);
    if (!context.mounted) return null;
    Navigator.of(context).pop(); // the progress dialog
    if (got['found'] != true) {
      toast(context, "Couldn't read the label. Name it yourself; the photo is kept.");
    }
    return BarcodeResult.fromJson({
      'barcode': r.barcode,
      'product': null,
      'found': got['found'] == true,
      'source': 'your photo (ChatGPT)',
      'name': got['name'],
      'brand': got['brand'],
      'quantity_text': got['quantity_text'],
      'image_url': got['image_url'],
      'category': got['category'],
    });
  } on ApiException catch (e) {
    if (context.mounted) {
      Navigator.of(context).pop();
      toast(context, e.message, error: true);
    }
    return null;
  }
}
