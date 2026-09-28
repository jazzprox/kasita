import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  final int status;
  final String message;
  ApiException(this.status, this.message);
  @override
  String toString() => message;
}

/// Talks to a Kasita server. Keeps the refresh token in secure storage and
/// quietly swaps it for a new access token when a request comes back 401.
class Api {
  static const _storage = FlutterSecureStorage();
  static const defaultServer = 'https://kasita.jazzproxy.com';

  String server = defaultServer;
  String? _access;
  String? _refresh;
  void Function()? onSignedOut;

  bool get signedIn => _refresh != null;

  Future<void> load({String? sameOriginServer}) async {
    server = await _storage.read(key: 'server') ?? sameOriginServer ?? defaultServer;
    _refresh = await _storage.read(key: 'refresh');
  }

  Uri _u(String path, [Map<String, String>? q]) =>
      Uri.parse('${server.replaceAll(RegExp(r'/+$'), '')}$path').replace(queryParameters: q);

  Future<void> _saveTokens(Map<String, dynamic> t) async {
    _access = t['access_token'];
    _refresh = t['refresh_token'];
    await _storage.write(key: 'refresh', value: _refresh);
    await _storage.write(key: 'server', value: server);
  }

  Future<void> login(String email, String password) async {
    final r = await http.post(
      _u('/api/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'email': email, 'password': password, 'device': 'kasita-app'}),
    );
    await _saveTokens(_decode(r));
  }

  Future<void> acceptInvite({
    required String token,
    required String email,
    String? name,
    required String password,
  }) async {
    final r = await http.post(
      _u('/api/auth/accept-invite'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'token': token, 'email': email, 'name': name, 'password': password}),
    );
    await _saveTokens(_decode(r));
  }

  /// Signs out every other device; this one continues with the fresh session returned.
  Future<void> changePassword(String current, String next) async {
    final t = await post('/api/auth/change-password', {
      'current_password': current,
      'new_password': next,
      'device': 'kasita-app',
    });
    await _saveTokens(Map<String, dynamic>.from(t));
  }

  Future<void> logout() async {
    final refresh = _refresh;
    _access = null;
    _refresh = null;
    await _storage.delete(key: 'refresh');
    if (refresh != null) {
      try {
        await http.post(
          _u('/api/auth/logout'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'refresh_token': refresh}),
        );
      } catch (_) {}
    }
  }

  Future<bool> _renew() async {
    if (_refresh == null) return false;
    final r = await http.post(
      _u('/api/auth/refresh'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'refresh_token': _refresh}),
    );
    if (r.statusCode != 200) {
      await logout();
      onSignedOut?.call();
      return false;
    }
    await _saveTokens(jsonDecode(r.body));
    return true;
  }

  dynamic _decode(http.Response r) {
    if (r.statusCode == 204) return null;
    final body = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    if (r.statusCode >= 400) {
      final detail = body is Map ? body['detail'] : null;
      final msg = detail is String
          ? detail
          : (detail is List && detail.isNotEmpty ? detail.first['msg'] : 'Error ${r.statusCode}');
      throw ApiException(r.statusCode, msg.toString());
    }
    return body;
  }

  final _http = http.Client();

  Future<dynamic> _send(String method, String path, {Object? body, Map<String, String>? query}) async {
    Future<http.Response> go() async {
      final req = http.Request(method, _u(path, query));
      req.headers['Content-Type'] = 'application/json';
      if (_access != null) req.headers['Authorization'] = 'Bearer $_access';
      if (body != null) req.body = jsonEncode(body);
      return http.Response.fromStream(await _http.send(req));
    }

    if (_access == null && !await _renew()) throw ApiException(401, 'Signed out');
    var r = await go();
    if (r.statusCode == 401 && await _renew()) r = await go();
    return _decode(r);
  }

  /// Multipart upload of one file under the form field `file`.
  /// Multipart upload: every file goes under the form field `file` (several = parts, in order).
  Future<dynamic> upload(String path, List<(Uint8List, String)> files) async {
    Future<http.Response> go() async {
      final req = http.MultipartRequest('POST', _u(path));
      if (_access != null) req.headers['Authorization'] = 'Bearer $_access';
      for (final (bytes, name) in files) {
        req.files.add(http.MultipartFile.fromBytes('file', bytes, filename: name));
      }
      return http.Response.fromStream(await _http.send(req));
    }

    if (_access == null && !await _renew()) throw ApiException(401, 'Signed out');
    var r = await go();
    if (r.statusCode == 401 && await _renew()) r = await go();
    return _decode(r);
  }

  /// Raw bytes of an authenticated resource (receipt photos).
  Future<Uint8List> bytes(String path) async {
    Future<http.Response> go() =>
        _http.get(_u(path), headers: {if (_access != null) 'Authorization': 'Bearer $_access'});
    if (_access == null && !await _renew()) throw ApiException(401, 'Signed out');
    var r = await go();
    if (r.statusCode == 401 && await _renew()) r = await go();
    if (r.statusCode >= 400) _decode(r);
    return r.bodyBytes;
  }

  Future<dynamic> get(String p, [Map<String, String>? q]) => _send('GET', p, query: q);
  Future<dynamic> post(String p, [Object? b]) => _send('POST', p, body: b ?? {});
  Future<dynamic> patch(String p, Object b) => _send('PATCH', p, body: b);
  Future<dynamic> delete(String p) => _send('DELETE', p);

  // --- typed helpers ------------------------------------------------------
  Future<List<Household>> households() async =>
      (await get('/api/households') as List).map((e) => Household.fromJson(e)).toList();
  Future<Household> createHousehold(String name) async =>
      Household.fromJson(await post('/api/households', {'name': name}));

  String _h(String hid) => '/api/households/$hid';

  Future<List<Location>> locations(String hid) async =>
      (await get('${_h(hid)}/locations') as List).map((e) => Location.fromJson(e)).toList();
  Future<List<Store>> stores(String hid) async =>
      (await get('${_h(hid)}/stores') as List).map((e) => Store.fromJson(e)).toList();
  Future<Store> addStore(String hid, String name) async =>
      Store.fromJson(await post('${_h(hid)}/stores', {'name': name}));

  Future<List<StockProduct>> stock(String hid) async =>
      (await get('${_h(hid)}/stock') as List).map((e) => StockProduct.fromJson(e)).toList();
  Future<List<Product>> products(String hid, {String? q}) async =>
      (await get('${_h(hid)}/products', q == null || q.isEmpty ? null : {'q': q}) as List)
          .map((e) => Product.fromJson(e))
          .toList();
  Future<Product> product(String hid, String pid) async => Product.fromJson(await get('${_h(hid)}/products/$pid'));
  Future<Product> createProduct(String hid, Map<String, dynamic> body) async =>
      Product.fromJson(await post('${_h(hid)}/products', body));
  Future<Product> updateProduct(String hid, String pid, Map<String, dynamic> body) async =>
      Product.fromJson(await patch('${_h(hid)}/products/$pid', body));
  Future<List<PricePoint>> prices(String hid, String pid) async =>
      (await get('${_h(hid)}/products/$pid/prices') as List).map((e) => PricePoint.fromJson(e)).toList();
  Future<List<String>> categories(String hid) async => List<String>.from(await get('${_h(hid)}/categories'));
  Future<Product> addBarcode(String hid, String pid, String code) async =>
      Product.fromJson(await post('${_h(hid)}/products/$pid/barcodes?barcode=${Uri.encodeQueryComponent(code)}'));
  Future<BarcodeResult> barcode(String hid, String code) async =>
      BarcodeResult.fromJson(await get('${_h(hid)}/barcodes/${Uri.encodeComponent(code)}'));

  Future<void> purchase(String hid, Map<String, dynamic> body) => post('${_h(hid)}/stock/purchase', body);
  Future<Map<String, dynamic>> consume(String hid, String pid, double qty, {bool spoiled = false}) async =>
      Map<String, dynamic>.from(
        await post('${_h(hid)}/stock/consume', {'product_id': pid, 'quantity': qty, 'spoiled': spoiled}),
      );
  Future<void> openPack(String hid, String pid) => post('${_h(hid)}/stock/open', {'product_id': pid});

  Future<List<ShoppingItem>> shopping(String hid, {bool includeDone = false}) async =>
      (await get('${_h(hid)}/shopping', includeDone ? {'include_done': 'true'} : null) as List)
          .map((e) => ShoppingItem.fromJson(e))
          .toList();
  Future<void> addShopping(String hid, {String? name, String? productId, double quantity = 1}) =>
      post('${_h(hid)}/shopping', {'name': name, 'product_id': productId, 'quantity': quantity});
  Future<void> setShoppingDone(String hid, String id, bool done) => patch('${_h(hid)}/shopping/$id', {'done': done});
  Future<void> deleteShopping(String hid, String id) => delete('${_h(hid)}/shopping/$id');
  Future<void> clearDone(String hid) => post('${_h(hid)}/shopping/clear-done');
  Future<void> refill(String hid) => post('${_h(hid)}/shopping/refill');

  Future<List<Member>> members(String hid) async =>
      (await get('${_h(hid)}/members') as List).map((e) => Member.fromJson(e)).toList();
  Future<Map<String, dynamic>> createInvite(String hid) async =>
      Map<String, dynamic>.from(await post('${_h(hid)}/invites'));

  // --- receipts -----------------------------------------------------------
  Future<List<Receipt>> receipts(String hid) async =>
      (await get('${_h(hid)}/receipts') as List).map((e) => Receipt.fromJson(e)).toList();
  Future<Receipt> receipt(String hid, String id) async => Receipt.fromJson(await get('${_h(hid)}/receipts/$id'));

  /// One photo, or the parts of a long receipt from top to bottom.
  Future<Receipt> uploadReceipt(String hid, List<(Uint8List, String)> parts) async =>
      Receipt.fromJson(await upload('${_h(hid)}/receipts', parts));
  Future<Uint8List> receiptImage(String hid, String id) => bytes('${_h(hid)}/receipts/$id/image');
  Future<Receipt> reparseReceipt(String hid, String id) async =>
      Receipt.fromJson(await post('${_h(hid)}/receipts/$id/parse'));
  Future<Receipt> updateReceipt(String hid, String id, Map<String, dynamic> body) async =>
      Receipt.fromJson(await patch('${_h(hid)}/receipts/$id', body));
  Future<void> updateReceiptLine(String hid, String id, String lineId, Map<String, dynamic> body) =>
      patch('${_h(hid)}/receipts/$id/lines/$lineId', body);
  Future<void> addReceiptLine(String hid, String id, Map<String, dynamic> body) =>
      post('${_h(hid)}/receipts/$id/lines', body);
  Future<void> deleteReceiptLine(String hid, String id, String lineId) =>
      delete('${_h(hid)}/receipts/$id/lines/$lineId');
  Future<Map<String, dynamic>> confirmReceipt(String hid, String id, {String? locationId}) async =>
      Map<String, dynamic>.from(await post('${_h(hid)}/receipts/$id/confirm', {'location_id': locationId}));
  Future<void> deleteReceipt(String hid, String id) => delete('${_h(hid)}/receipts/$id');

  // --- ChatGPT (reads receipts) --------------------------------------------
  String _gpt(String hid) => '${_h(hid)}/integrations/chatgpt';
  Future<ChatGPTStatus> chatgpt(String hid) async => ChatGPTStatus.fromJson(await get(_gpt(hid)));
  Future<ChatGPTStatus> chatgptConnect(String hid) async => ChatGPTStatus.fromJson(await post('${_gpt(hid)}/connect'));
  Future<ChatGPTStatus> chatgptPoll(String hid) async => ChatGPTStatus.fromJson(await post('${_gpt(hid)}/poll'));
  Future<List<String>> chatgptModels(String hid) async => List<String>.from(await get('${_gpt(hid)}/models'));
  Future<ChatGPTStatus> chatgptSetModel(String hid, String model) async =>
      ChatGPTStatus.fromJson(await patch(_gpt(hid), {'model': model}));
  Future<void> chatgptDisconnect(String hid) => delete(_gpt(hid));

  // --- Securo (finance app) ------------------------------------------------
  String _sec(String hid) => '${_h(hid)}/integrations/securo';
  Future<Map<String, dynamic>> securo(String hid) async => Map<String, dynamic>.from(await get(_sec(hid)));
  Future<Map<String, dynamic>> securoConnect(String hid, String url, String email, String password) async =>
      Map<String, dynamic>.from(await post(_sec(hid), {'url': url, 'email': email, 'password': password}));
  Future<void> securoDisconnect(String hid) => delete(_sec(hid));
  Future<List<SecuroPayment>> securoCandidates(String hid, String receiptId) async =>
      (await get('${_h(hid)}/receipts/$receiptId/securo-candidates') as List)
          .map((e) => SecuroPayment.fromJson(e))
          .toList();
  Future<Receipt> securoLink(String hid, String receiptId, String txId, {bool photo = true, bool note = true}) async =>
      Receipt.fromJson(
        await post('${_h(hid)}/receipts/$receiptId/securo-link', {
          'transaction_id': txId,
          'attach_photo': photo,
          'add_note': note,
        }),
      );
  Future<Receipt> securoUnlink(String hid, String receiptId) async =>
      Receipt.fromJson(await delete('${_h(hid)}/receipts/$receiptId/securo-link'));
}
