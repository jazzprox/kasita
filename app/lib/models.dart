// Plain data classes mirroring the server's JSON. Decimals arrive as strings.

double _num(dynamic v) => v == null ? 0 : (v is num ? v.toDouble() : double.tryParse(v.toString()) ?? 0);
double? _numOrNull(dynamic v) => v == null ? null : _num(v);
DateTime? _date(dynamic v) => v == null ? null : DateTime.tryParse(v.toString());

String fmtQty(double q) =>
    q == q.roundToDouble() ? q.toInt().toString() : q.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '');

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
  Location.fromJson(Map<String, dynamic> j) : id = j['id'], name = j['name'], isFreezer = j['is_freezer'] ?? false;
}

class Store {
  final String id, name;
  Store.fromJson(Map<String, dynamic> j) : id = j['id'], name = j['name'];
}

class Product {
  final String id, name, unit;
  final String? brand, category, imageUrl, defaultLocationId, notes;
  final double minStock, inStock;
  final int? shelfLifeDays;
  final List<String> barcodes;
  final DateTime? nextBestBefore;
  final bool shareable; // a barcode no database knows: can be given to Open Food Facts
  final int? openDays; // keeps this many days once opened
  final double? runsOutInDays; // forecast from usage; null = not enough history

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
      nextBestBefore = _date(j['next_best_before']),
      shareable = j['shareable'] ?? false,
      openDays = j['open_days'],
      runsOutInDays = _numOrNull(j['runs_out_in_days']);
}

class StockEntry {
  final String id;
  final double quantity;
  final DateTime? bestBefore, openedAt, frozenAt;
  final DateTime purchasedAt;
  final double? unitPrice;
  final String? locationId, storeId;
  StockEntry.fromJson(Map<String, dynamic> j)
    : id = j['id'],
      quantity = _num(j['quantity']),
      bestBefore = _date(j['best_before']),
      openedAt = _date(j['opened_at']),
      frozenAt = _date(j['frozen_at']),
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
  final String? productId, note, category;
  final double quantity;
  final bool auto, done;
  ShoppingItem.fromJson(Map<String, dynamic> j)
    : id = j['id'],
      name = j['name'],
      productId = j['product_id'],
      note = j['note'],
      category = j['category'],
      quantity = _num(j['quantity']),
      auto = j['auto'] ?? false,
      done = j['done'] ?? false;
  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'product_id': productId,
    'note': note,
    'category': category,
    'quantity': quantity,
    'auto': auto,
    'done': done,
  };
  ShoppingItem copyWith({bool? done}) => ShoppingItem.fromJson({...toJson(), 'done': done ?? this.done});
}

class BarcodeResult {
  final String barcode;
  final Product? product;
  final bool found;
  final String? source, name, brand, quantityText, imageUrl, categories, category, brandHint;
  BarcodeResult.fromJson(Map<String, dynamic> j)
    : barcode = j['barcode'],
      product = j['product'] == null ? null : Product.fromJson(j['product']),
      found = j['found'] ?? false,
      source = j['source'],
      name = j['name'],
      brand = j['brand'],
      quantityText = j['quantity_text'],
      imageUrl = j['image_url'],
      categories = j['categories'],
      category = j['category'],
      brandHint = j['brand_hint'];
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

class ReceiptLine {
  final String id, rawText;
  final String? name, productId, productName, matchedBy;
  final double quantity;
  final double? unitPrice, lineTotal;
  final bool skip;
  ReceiptLine.fromJson(Map<String, dynamic> j)
    : id = j['id'],
      rawText = j['raw_text'],
      name = j['name'],
      productId = j['product_id'],
      productName = j['product_name'],
      matchedBy = j['matched_by'],
      quantity = _num(j['quantity']),
      unitPrice = _numOrNull(j['unit_price']),
      lineTotal = _numOrNull(j['line_total']),
      skip = j['skip'] ?? false;
  String get label => name ?? rawText;
}

class Receipt {
  final String id, status;
  final String? error, storeId, storeName, currency, securoTransactionId;
  final DateTime? purchasedOn;
  final DateTime createdAt;
  final double? total, linesTotal;
  final int lineCount;
  final List<ReceiptLine>? lines;
  Receipt.fromJson(Map<String, dynamic> j)
    : id = j['id'],
      status = j['status'],
      error = j['error'],
      storeId = j['store_id'],
      storeName = j['store_name'],
      currency = j['currency'],
      securoTransactionId = j['securo_transaction_id'],
      purchasedOn = _date(j['purchased_on']),
      createdAt = _date(j['created_at']) ?? DateTime.now(),
      total = _numOrNull(j['total']),
      linesTotal = _numOrNull(j['lines_total']),
      lineCount = j['line_count'] ?? 0,
      lines = (j['lines'] as List?)?.map((e) => ReceiptLine.fromJson(e)).toList();
  bool get reading => status == 'new';
}

class ChatGPTStatus {
  final bool connected;
  final String? email, plan, model;
  final String? userCode, verificationUrl;
  final int interval;
  ChatGPTStatus.fromJson(Map<String, dynamic> j)
    : connected = j['connected'] ?? false,
      email = j['email'],
      plan = j['plan'],
      model = j['model'],
      userCode = j['pending']?['user_code'],
      verificationUrl = j['pending']?['verification_url'],
      interval = j['pending']?['interval'] ?? 5;
}

class SecuroPayment {
  final String id;
  final String? description, currency, notes;
  final DateTime? date;
  final double amount;
  final int score, attachmentCount;
  SecuroPayment.fromJson(Map<String, dynamic> j)
    : id = j['id'],
      description = j['description'],
      currency = j['currency'],
      notes = j['notes'],
      date = _date(j['date']),
      amount = _num(j['amount']),
      score = j['score'] ?? 0,
      attachmentCount = j['attachment_count'] ?? 0;
}
