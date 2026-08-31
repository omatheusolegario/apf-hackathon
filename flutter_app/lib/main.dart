import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'chat_screen.dart';
import 'onboarding_screen.dart';
import 'demo_session.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ApfApp());
}

class ApfApp extends StatefulWidget {
  final bool? showOnboarding;
  final String? testUserId;

  const ApfApp({super.key, this.showOnboarding, this.testUserId});

  @override
  State<ApfApp> createState() => _ApfAppState();
}

class _ApfAppState extends State<ApfApp> {
  late Future<({String userId, bool showOnboarding})> _startup;

  @override
  void initState() {
    super.initState();
    _startup = _initialize();
  }

  Future<({String userId, bool showOnboarding})> _initialize() async {
    if (widget.showOnboarding != null) {
      return (
        userId: widget.testUserId ?? 'demo_test',
        showOnboarding: widget.showOnboarding!,
      );
    }
    final userId = await DemoSession.initialize();
    final prefs = await SharedPreferences.getInstance();
    return (
      userId: userId,
      showOnboarding: !(prefs.getBool('has_seen_onboarding') ?? false),
    );
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'APF Itaú',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFFF6200),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        fontFamily: 'Roboto',
      ),
      home: FutureBuilder<({String userId, bool showOnboarding})>(
        future: _startup,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Scaffold(
              body: Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.cloud_off_rounded,
                          size: 48, color: Color(0xFFFF6200)),
                      const SizedBox(height: 16),
                      const Text('Não foi possível preparar a demonstração.'),
                      const SizedBox(height: 12),
                      FilledButton(
                        onPressed: () =>
                            setState(() => _startup = _initialize()),
                        child: const Text('Tentar novamente'),
                      ),
                    ],
                  ),
                ),
              ),
            );
          }
          if (!snapshot.hasData) {
            return const Scaffold(
              body: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: Color(0xFFFF6200)),
                    SizedBox(height: 16),
                    Text('Preparando sua demonstração…'),
                  ],
                ),
              ),
            );
          }
          final state = snapshot.data!;
          return state.showOnboarding
              ? OnboardingScreen(userId: state.userId)
              : ChatScreen(userId: state.userId);
        },
      ),
    );
  }
}
