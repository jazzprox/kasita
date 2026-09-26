// Plain data classes mirroring the server's JSON. Decimals arrive as strings.

double _num(dynamic v) => v == null ? 0 : (v is num ? v.toDouble() : double.tryParse(v.toString()) ?? 0);
double? _numOrNull(dynamic v) => v == null ? null : _num(v);
DateTime? _date(dynamic v) => v == null ? null : DateTime.tryParse(v.toString());

String fmtQty(double q) => q == q.roundToDouble() ? q.toInt().toString() : q.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '');

class Household {
  final String id, name, currency;
  final String? role;
  Household.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        name = j['name'],
        currency = j['currency'],
        role = j['role'];
  bool get isOwner => role == 'owner';
}

class Location {
  final String id, name;
  final bool isFreezer;
  Location.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        name = j['name'],
        isFreezer = j['is_freezer'] ?? false;
}

class Store {
  final String id, name;
  Store.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        name = j['name'];
}

class Product {
  final String id, name, unit;
  final String? brand, category, imageUrl, defaultLocationId, notes;
  final double minStock, inStock;
  final int? shelfLifeDays;
  final List<String> barcodes;
  final DateTime? nextBestBefore;

  Product.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        name = j['name'],
        unit = j['unit'] ?? 'pcs',
        brand = j['brand'],
        category = j['category'],
        imageUrl = j['image_url'],
        defaultLocationId = j['default_location_id'],
        notes = j['notes'],
        minStock = _num(j['min_stock']),
        inStock = _num(j['in_stock']),
        shelfLifeDays = j['shelf_life_days'],
        barcodes = List<String>.from(j['barcodes'] ?? const []),
        nextBestBefore = _date(j['next_best_before']);
}

class StockEntry {
  final String id;
  final double quantity;
  final DateTime? bestBefore, openedAt;
  final DateTime purchasedAt;
  final double? unitPrice;
  final String? locationId, storeId;
  StockEntry.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        quantity = _num(j['quantity']),
        bestBefore = _date(j['best_before']),
        openedAt = _date(j['opened_at']),
        purchasedAt = _date(j['purchased_at']) ?? DateTime.now(),
        unitPrice = _numOrNull(j['unit_price']),
        locationId = j['location_id'],
        storeId = j['store_id'];
}

class StockProduct {
  final Product product;
  final double total;
  final List<StockEntry> entries;
  StockProduct.fromJson(Map<String, dynamic> j)
      : product = Product.fromJson(j['product']),
        total = _num(j['total']),
        entries = (j['entries'] as List).map((e) => StockEntry.fromJson(e)).toList();
}

class ShoppingItem {
  final String id, name;
  final String? productId, note;
  final double quantity;
  final bool auto, done;
  ShoppingItem.fromJson(Map<String, dynamic> j)
      : id = j['id'],
        name = j['name'],
        productId = j['product_id'],
        note = j['note'],
        quantity = _num(j['quantity']),
        auto = j['auto'] ?? false,
        done = j['done'] ?? false;
}

class BarcodeResult {
  final String barcode;
  final Product? product;
  final bool found;
  final String? source, name, brand, quantityText, imageUrl, categories;
  BarcodeResult.fromJson(Map<String, dynamic> j)
      : barcode = j['barcode'],
        product = j['product'] == null ? null : Product.fromJson(j['product']),
        found = j['found'] ?? false,
        source = j['source'],
        name = j['name'],
        brand = j['brand'],
        quantityText = j['quantity_text'],
        imageUrl = j['image_url'],
        categories = j['categories'];
}

class PricePoint {
  final DateTime at;
  final double unitPrice, quantity;
  final String? storeName;
  PricePoint.fromJson(Map<String, dynamic> j)
      : at = _date(j['at']) ?? DateTime.now(),
        unitPrice = _num(j['unit_price']),
        quantity = _num(j['quantity']),
        storeName = j['store_name'];
}

class Member {
  final String userId, name, email, role;
  Member.fromJson(Map<String, dynamic> j)
      : userId = j['user_id'],
        name = j['name'],
        email = j['email'],
        role = j['role'];
}
