import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'app_config.dart';

class PrivacyScreen extends StatefulWidget {
  const PrivacyScreen({super.key});

  @override
  State<PrivacyScreen> createState() => _PrivacyScreenState();
}

class _PrivacyScreenState extends State<PrivacyScreen> {
  bool consentPadroes = false;
  bool consentHabitos = false;
  bool consentSaldo = false;
  bool loading = false;
  final reservaController = TextEditingController(text: '2000,00');
  static const baseUrl = AppConfig.apiBaseUrl;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    try {
      final response =
          await http.get(Uri.parse('$baseUrl/user/demo/preferences'));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final reserva = (data['reserva_seguranca'] as num?)?.toDouble();
        if (reserva != null) {
          reservaController.text = reserva.toStringAsFixed(2).replaceAll('.', ',');
        }
      }
    } catch (_) {
      // Mantém o valor padrão quando o backend estiver indisponível.
    }
    if (!mounted) return;
    setState(() {
      consentPadroes = prefs.getBool('consent_padroes_pagamento') ?? false;
      consentHabitos = prefs.getBool('consent_habitos_gasto') ?? false;
      consentSaldo = prefs.getBool('consent_saldo_ocioso') ?? false;
    });
  }

  Future<void> _save() async {
    setState(() => loading = true);
    try {
      final reserva = double.tryParse(
        reservaController.text.trim().replaceAll('.', '').replaceAll(',', '.'),
      );
      if (reserva == null || reserva < 0) {
        throw const FormatException('Reserva inválida');
      }
      final response = await http.post(
        Uri.parse('$baseUrl/user/demo/consent'),
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
      final preferenceResponse = await http.post(
        Uri.parse('$baseUrl/user/demo/preferences'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'reserva_seguranca': reserva}),
      );
      if (preferenceResponse.statusCode < 200 ||
          preferenceResponse.statusCode >= 300) {
        throw Exception('HTTP ${preferenceResponse.statusCode}');
      }
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool('consent_padroes_pagamento', consentPadroes);
      await prefs.setBool('consent_habitos_gasto', consentHabitos);
      await prefs.setBool('consent_saldo_ocioso', consentSaldo);
    } catch (_) {
      if (!mounted) return;
      setState(() => loading = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text('Não foi possível salvar as preferências.')),
      );
      return;
    }
    if (!mounted) return;
    setState(() => loading = false);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Preferências de privacidade salvas')),
      );
    }
  }

  @override
  void dispose() {
    reservaController.dispose();
    super.dispose();
  }

  Future<void> _forget() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Excluir meus dados'),
        content: const Text(
          'Isso apaga transações, padrões e conversas (direito ao esquecimento – LGPD). Continuar?',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancelar')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Excluir'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final response = await http.delete(Uri.parse('$baseUrl/user/demo/data'));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw Exception('HTTP ${response.statusCode}');
      }
      final prefs = await SharedPreferences.getInstance();
      await prefs.clear();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Dados excluídos. Seus consentimentos também foram revogados.',
            ),
          ),
        );
        Navigator.of(context).pop();
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text('Falha ao excluir. Backend está no ar?')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Privacidade'),
        backgroundColor: const Color(0xFFFF6200),
        foregroundColor: Colors.white,
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Consentimento granular (LGPD)',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          const Text(
            'Você controla cada categoria. Desmarque para optar out.',
            style: TextStyle(color: Colors.black54),
          ),
          const SizedBox(height: 16),
          SwitchListTile(
            title: const Text('Padrões de pagamento recorrente'),
            subtitle: const Text('Ex.: aluguel, assinaturas'),
            value: consentPadroes,
            activeThumbColor: const Color(0xFFFF6200),
            onChanged: (v) => setState(() => consentPadroes = v),
          ),
          SwitchListTile(
            title: const Text('Hábitos de gasto'),
            subtitle: const Text('Ex.: alimentação, transporte'),
            value: consentHabitos,
            activeThumbColor: const Color(0xFFFF6200),
            onChanged: (v) => setState(() => consentHabitos = v),
          ),
          SwitchListTile(
            title: const Text('Dinheiro disponível para investir'),
            subtitle: const Text('Apenas renda fixa simples'),
            value: consentSaldo,
            activeThumbColor: const Color(0xFFFF6200),
            onChanged: (v) => setState(() => consentSaldo = v),
          ),
          const SizedBox(height: 16),
          const Text(
            'Planejamento financeiro',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          TextFormField(
            controller: reservaController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(
              labelText: 'Reserva que desejo manter disponível',
              prefixText: 'R\$ ',
              helperText: 'Usada apenas para calcular sugestões de investimento.',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: loading ? null : _save,
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFFF6200),
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
              child: loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('Salvar preferências'),
            ),
          ),
          const SizedBox(height: 32),
          const Divider(),
          const SizedBox(height: 12),
          const Text(
            'Direito ao esquecimento',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          const Text(
            'Apaga seus dados deste ambiente (transações, padrões e conversas).',
            style: TextStyle(color: Colors.black54),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _forget,
            icon: const Icon(Icons.delete_forever, color: Colors.red),
            label: const Text('Excluir meus dados',
                style: TextStyle(color: Colors.red)),
            style: OutlinedButton.styleFrom(
              side: const BorderSide(color: Colors.red),
              padding: const EdgeInsets.symmetric(vertical: 14),
            ),
          ),
        ],
      ),
    );
  }
}
