class AppConfig {
  AppConfig._();

  /// Pode ser sobrescrito sem alterar código:
  /// flutter run --dart-define=APF_API_BASE_URL=http://192.168.0.10:8000
  static const String apiBaseUrl = String.fromEnvironment(
    'APF_API_BASE_URL',
    defaultValue: 'http://localhost:8000',
  );

  static String get webSocketUrl {
    final uri = Uri.parse(apiBaseUrl);
    return uri
        .replace(scheme: uri.scheme == 'https' ? 'wss' : 'ws', path: '/ws')
        .toString();
  }
}
