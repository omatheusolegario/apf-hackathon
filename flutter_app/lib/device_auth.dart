import 'package:local_auth/local_auth.dart';

class DeviceAuthResult {
  final bool authenticated;
  final bool available;
  final String message;

  const DeviceAuthResult({
    required this.authenticated,
    required this.available,
    required this.message,
  });
}

class DeviceAuth {
  static final LocalAuthentication _auth = LocalAuthentication();

  static Future<DeviceAuthResult> authenticate() async {
    try {
      final supported = await _auth.isDeviceSupported();
      if (!supported) {
        return const DeviceAuthResult(
          authenticated: false,
          available: false,
          message: 'Autenticação do dispositivo indisponível neste ambiente.',
        );
      }
      final ok = await _auth.authenticate(
        localizedReason: 'Confirme sua identidade para liberar a transação',
        biometricOnly: false,
        persistAcrossBackgrounding: true,
      );
      return DeviceAuthResult(
        authenticated: ok,
        available: true,
        message: ok ? 'Identidade confirmada no dispositivo.' : 'Autenticação cancelada.',
      );
    } catch (_) {
      return const DeviceAuthResult(
        authenticated: false,
        available: false,
        message: 'Autenticação nativa indisponível nesta demonstração.',
      );
    }
  }
}
