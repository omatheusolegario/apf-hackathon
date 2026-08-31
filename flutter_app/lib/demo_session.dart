import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'app_config.dart';

class DemoSession {
  static const _key = 'demo_user_id';

  static Future<String> initialize() async {
    final prefs = await SharedPreferences.getInstance();
    var userId = prefs.getString(_key);
    userId ??=
        'demo_${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}';
    final response = await http
        .post(
          Uri.parse('${AppConfig.apiBaseUrl}/demo/session/$userId'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'name': 'Maria Silva'}),
        )
        .timeout(const Duration(seconds: 75));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('HTTP ${response.statusCode}');
    }
    await prefs.setString(_key, userId);
    return userId;
  }

  static Future<void> reset(String userId) async {
    final response = await http
        .post(Uri.parse('${AppConfig.apiBaseUrl}/demo/session/$userId/reset'))
        .timeout(const Duration(seconds: 75));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('HTTP ${response.statusCode}');
    }
  }
}
