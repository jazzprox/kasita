import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:quick_actions/quick_actions.dart';

import 'pantry.dart';
import 'pantry_pass.dart';
import 'receipts.dart';
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
                child: Icon(Icons.house_rounded, color: Theme.of(context).colorScheme.primary, size: 32),
              ),
              destinations: [
                for (final d in _destinations)
                  NavigationRailDestination(icon: Icon(d.$1), selectedIcon: Icon(d.$2), label: Text(d.$3)),
              ],
            ),
            const VerticalDivider(width: 1),
            Expanded(child: _page()),
          ],
        ),
      );
    }
    return Scaffold(
      body: _page(),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: [
          for (final d in _destinations) NavigationDestination(icon: Icon(d.$1), selectedIcon: Icon(d.$2), label: d.$3),
        ],
      ),
    );
  }
}
