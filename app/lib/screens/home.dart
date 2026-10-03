import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:home_widget/home_widget.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';
import 'package:quick_actions/quick_actions.dart';

import 'pantry.dart';
import 'pantry_pass.dart';
import 'receipts.dart';
import '../api.dart';
import '../home_widget_sync.dart';
import '../main.dart';
import '../spoken_list.dart';
import '../updates/update_ui.dart';
import '../updates/updater.dart';
import '../widgets.dart';
import 'products.dart';
import 'scan.dart';
import 'settings.dart';
import 'shopping.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;
  StreamSubscription<List<SharedMediaFile>>? _shareSub;
  StreamSubscription<Uri?>? _widgetSub;
  AppLifecycleListener? _lifecycle;

  @override
  void dispose() {
    _shareSub?.cancel();
    _widgetSub?.cancel();
    _lifecycle?.dispose();
    super.dispose();
  }

  Future<void> _shared(List<SharedMediaFile> files) async {
    if (!mounted || files.isEmpty) return;
    final s = Kasita.read(context);
    final images = files.where((f) => f.type == SharedMediaType.image).toList();
    final texts = files.where((f) => f.type == SharedMediaType.text || f.type == SharedMediaType.url).toList();
    try {
      if (images.isNotEmpty) {
        final parts = [for (final f in images) (await File(f.path).readAsBytes(), f.path.split('/').last)];
        final receipt = await s.api.uploadReceipt(s.hid, parts);
        if (!mounted) return;
        await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ReceiptReviewScreen(receiptId: receipt.id)));
      } else if (texts.isNotEmpty) {
        final items = parseSpokenList(texts.map((t) => t.path).join(', ').replaceAll('\n', ', '));
        for (final (qty, name) in items) {
          await s.api.addShopping(s.hid, name: name, quantity: qty);
        }
        s.changed();
        if (!mounted) return;
        setState(() => _tab = 1);
        toast(context, 'Added ${items.length} to the shopping list');
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  /// Long-press the app icon: Pantry pass, Scan receipt, Shopping list.
  @override
  void initState() {
    super.initState();
    if (kIsWeb) return;
    const actions = QuickActions();
    actions.initialize((type) {
      if (!mounted) return;
      switch (type) {
        case 'shopping':
          setState(() => _tab = 1);
        case 'pass':
          Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PantryPassScreen()));
        case 'receipt':
          scanReceipt(context);
      }
    });
    // the widget's + and title open the shopping list
    void fromWidget(Uri? uri) {
      if (mounted && uri?.host == 'shopping') setState(() => _tab = 1);
    }

    HomeWidget.initiallyLaunchedFromHomeWidget().then(fromWidget).catchError((_) {});
    _widgetSub = HomeWidget.widgetClicked.listen(fromWidget);
    // Share -> Kasita: photos become a receipt, text goes on the shopping list
    ReceiveSharingIntent.instance.getInitialMedia().then((files) {
      if (files.isNotEmpty) WidgetsBinding.instance.addPostFrameCallback((_) => _shared(files));
      ReceiveSharingIntent.instance.reset();
    });
    _shareSub = ReceiveSharingIntent.instance.getMediaStream().listen(_shared);
    final st = Kasita.read(context);
    ensureWidgetKey(st.api, st.hid);
    // a new build on GitHub? at start, then on resume at most every 6 hours
    if (updatesSupported) {
      updater.start();
      _lifecycle = AppLifecycleListener(onResume: updater.maybeCheck);
    }
    actions.setShortcutItems(const [
      ShortcutItem(type: 'pass', localizedTitle: 'Pantry pass'),
      ShortcutItem(type: 'receipt', localizedTitle: 'Scan receipt'),
      ShortcutItem(type: 'shopping', localizedTitle: 'Shopping list'),
    ]);
  }

  static const _destinations = [
    (Icons.kitchen_outlined, Icons.kitchen, 'Pantry'),
    (Icons.shopping_cart_outlined, Icons.shopping_cart, 'Shopping'),
    (Icons.qr_code_scanner, Icons.qr_code_scanner, 'Scan'),
    (Icons.inventory_2_outlined, Icons.inventory_2, 'Products'),
    (Icons.settings_outlined, Icons.settings, 'More'),
  ];

  Widget _page() => switch (_tab) {
    0 => const PantryScreen(),
    1 => const ShoppingScreen(),
    2 => ScanScreen(active: _tab == 2),
    3 => const ProductsScreen(),
    _ => const SettingsScreen(),
  };

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    if (wide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: _tab,
              onDestinationSelected: (i) => setState(() => _tab = i),
              labelType: NavigationRailLabelType.all,
              leading: Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.asset('assets/brand/kasita.png', width: 36, height: 36),
                ),
              ),
              destinations: [
                for (final d in _destinations)
                  NavigationRailDestination(icon: Icon(d.$1), selectedIcon: Icon(d.$2), label: Text(d.$3)),
              ],
            ),
            const VerticalDivider(width: 1),
            Expanded(
              child: Column(
                children: [
                  Expanded(child: _page()),
                  const SafeArea(top: false, child: UpdateBanner()),
                ],
              ),
            ),
          ],
        ),
      );
    }
    return Scaffold(
      body: _page(),
      bottomNavigationBar: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const UpdateBanner(),
          NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            destinations: [
              for (final d in _destinations)
                NavigationDestination(icon: Icon(d.$1), selectedIcon: Icon(d.$2), label: d.$3),
            ],
          ),
        ],
      ),
    );
  }
}
