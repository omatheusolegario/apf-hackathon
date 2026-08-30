import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:convert';
import 'chat_screen.dart';
import 'app_config.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  bool consentPadroes = false;
  bool consentHabitos = false;
  bool consentSaldo = false;
  bool loading = false;

  Future<void> _finish() async {
    setState(() => loading = true);

    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/user/demo/consent'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'consent_padroes_pagamento': consentPadroes,
          'consent_habitos_gasto': consentHabitos,
          'consent_saldo_ocioso': consentSaldo,
        }),
      );
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw Exception('HTTP ${response.statusCode}');
      }
    } catch (_) {
      if (mounted) {
        setState(() => loading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text(
                  'Não foi possível salvar. Verifique a conexão com o APF.')),
        );
      }
      return;
    }

    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('has_seen_onboarding', true);
    await prefs.setBool('consent_padroes_pagamento', consentPadroes);
    await prefs.setBool('consent_habitos_gasto', consentHabitos);
    await prefs.setBool('consent_saldo_ocioso', consentSaldo);

    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const ChatScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints:
                  BoxConstraints(minHeight: constraints.maxHeight - 48),
              child: IntrinsicHeight(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 32),
                    const Text(
                      'Assistente Pessoal\nFinanceiro',
                      style: TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.bold,
                        height: 1.2,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFFF3E0),
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(color: const Color(0xFFFF6200)),
                      ),
                      child: const Text(
                        'Assistente Itaú',
                        style: TextStyle(
                          fontSize: 12,
                          color: Color(0xFFE65100),
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    const SizedBox(height: 32),
                    const Text(
                      'Consentimento LGPD (granular)',
                      style:
                          TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Marque apenas o que você autoriza. Pode alterar depois.',
                      style: TextStyle(fontSize: 14, color: Colors.black54),
                    ),
                    const SizedBox(height: 20),
                    _ConsentTile(
                      title: 'Analisar padrões de pagamento recorrente',
                      subtitle: 'Ex: aluguel, Netflix, Pix fixos',
                      value: consentPadroes,
                      onChanged: (v) => setState(() => consentPadroes = v),
                    ),
                    _ConsentTile(
                      title: 'Analisar hábitos de gasto',
                      subtitle: 'Ex: alimentação, transporte, lazer',
                      value: consentHabitos,
                      onChanged: (v) => setState(() => consentHabitos = v),
                    ),
                    _ConsentTile(
                      title: 'Monitorar saldo ocioso para sugerir investimento',
                      subtitle: 'Apenas produtos de baixíssimo risco',
                      value: consentSaldo,
                      onChanged: (v) => setState(() => consentSaldo = v),
                    ),
                    const Spacer(),
                    SizedBox(
                      width: double.infinity,
                      height: 52,
                      child: ElevatedButton(
                        onPressed: loading ? null : _finish,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFFFF6200),
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                        child: loading
                            ? const SizedBox(
                                width: 22,
                                height: 22,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Text(
                                'Começar',
                                style: TextStyle(
                                    fontSize: 16, fontWeight: FontWeight.w600),
                              ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Center(
                      child: Text(
                        'Você pode revogar o consentimento a qualquer momento.',
                        style: TextStyle(fontSize: 12, color: Colors.black45),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ConsentTile extends StatelessWidget {
  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  const _ConsentTile({
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      elevation: 0,
      color: Colors.grey.shade50,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.grey.shade200),
      ),
      child: CheckboxListTile(
        value: value,
        onChanged: (v) => onChanged(v ?? false),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w500)),
        subtitle: Text(subtitle, style: const TextStyle(fontSize: 13)),
        activeColor: const Color(0xFFFF6200),
        controlAffinity: ListTileControlAffinity.leading,
        contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      ),
    );
  }
}
