import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:home_widget/home_widget.dart';

import 'api.dart';
import 'models.dart';

/// Keep the Android home-screen widget in step with the app: the open shopping
/// list and what to use soon. The widget shows what the app last saw, so it is
/// refreshed whenever the shopping list or the pantry loads.
bool get _supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

Future<void> syncShoppingWidget(List<ShoppingItem> items) async {
  if (!_supported) return;
  final open = items.where((i) => !i.done).toList();
  try {
    // ticks made on the widget that haven't reached the server yet stay off its list
    final unsent = ((await HomeWidget.getWidgetData<String>('pending_ticks')) ?? '').split(',').toSet();
    final shown = open.where((i) => !unsent.contains(i.id) && !i.id.startsWith('local-')).toList();
    await HomeWidget.saveWidgetData<String>('shopping_title', 'Shopping list (${shown.length})');
    await HomeWidget.saveWidgetData<String>(
      'shopping',
      shown.isEmpty ? 'Nothing to buy' : shown.take(8).map((i) => '• ${i.name}').join('\n'),
    );
    // the tickable list (tap a row on the widget to tick it off)
    await HomeWidget.saveWidgetData<String>(
      'items_json',
      jsonEncode([
        for (final i in shown.take(60)) {'id': i.id, 'name': i.name, 'quantity': i.quantity},
      ]),
    );
    await HomeWidget.updateWidget(androidName: 'KasitaWidgetProvider');
  } catch (_) {
    // no widget on the home screen, or an older launcher: nothing to update
  }
}

Future<void> syncPantryWidget(List<StockProduct> stock) async {
  if (!_supported) return;
  final today = DateTime.now();
  final soon = stock
      .where((s) => s.product.nextBestBefore != null && s.product.nextBestBefore!.difference(today).inDays <= 2)
      .map((s) => s.product.name)
      .take(4)
      .toList();
  try {
    await HomeWidget.saveWidgetData<String>('soon', soon.isEmpty ? '' : 'Use soon: ${soon.join(', ')}');
    await HomeWidget.updateWidget(androidName: 'KasitaWidgetProvider');
  } catch (_) {}
}

/// Give the widget its own read-only key, so it can refresh itself every 30 minutes
/// without the app open. The key can look but never change anything, and lives only
/// in this app's private storage. One key per household; switching household replaces it.
Future<void> ensureWidgetKey(Api api, String hid) async {
  if (!_supported) return;
  try {
    final have = await HomeWidget.getWidgetData<String>('kasita_hid');
    final key = await HomeWidget.getWidgetData<String>('kasita_key');
    if (have == hid && key != null && key.isNotEmpty) return;
    final created = await api.createApiKey(hid, 'Home-screen widget', readOnly: true);
    await HomeWidget.saveWidgetData<String>('kasita_server', api.server);
    await HomeWidget.saveWidgetData<String>('kasita_hid', hid);
    await HomeWidget.saveWidgetData<String>('kasita_key', created['key'] as String);
    await HomeWidget.updateWidget(androidName: 'KasitaWidgetProvider');
  } catch (_) {
    // offline or not allowed: the widget keeps showing what the app last saw
  }
}

/// Signing out: the widget forgets its key and shows nothing personal.
Future<void> clearWidget() async {
  if (!_supported) return;
  try {
    for (final k in ['kasita_key', 'kasita_hid', 'kasita_server', 'items_json', 'pending_ticks']) {
      await HomeWidget.saveWidgetData<String>(k, null);
    }
    await HomeWidget.saveWidgetData<String>('shopping_title', 'Kasita');
    await HomeWidget.saveWidgetData<String>('shopping', 'Signed out');
    await HomeWidget.saveWidgetData<String>('soon', '');
    await HomeWidget.updateWidget(androidName: 'KasitaWidgetProvider');
  } catch (_) {}
}
