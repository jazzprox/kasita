import 'package:flutter/foundation.dart';
import 'package:home_widget/home_widget.dart';

import 'models.dart';

/// Keep the Android home-screen widget in step with the app: the open shopping
/// list and what to use soon. The widget shows what the app last saw, so it is
/// refreshed whenever the shopping list or the pantry loads.
bool get _supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

Future<void> syncShoppingWidget(List<ShoppingItem> items) async {
  if (!_supported) return;
  final open = items.where((i) => !i.done).toList();
  try {
    await HomeWidget.saveWidgetData<String>('shopping_title', 'Shopping list (${open.length})');
    await HomeWidget.saveWidgetData<String>(
      'shopping',
      open.isEmpty ? 'Nothing to buy' : open.take(8).map((i) => '• ${i.name}').join('\n'),
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
