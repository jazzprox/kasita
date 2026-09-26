import 'package:flutter/material.dart';

import 'pantry.dart';
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
