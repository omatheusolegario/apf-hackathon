import 'dart:convert';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:app_links/app_links.dart';
import 'privacy_screen.dart';
import 'app_config.dart';
import 'device_auth.dart';

/// Renderiza o subconjunto de Markdown usado nas respostas do assistente:
/// parágrafos, listas, **negrito** e *itálico*.
class FormattedText extends StatelessWidget {
  final String text;
  final TextStyle? style;
  final Color? color;

  const FormattedText(this.text, {super.key, this.style, this.color});

  @override
  Widget build(BuildContext context) {
    final base = (style ?? const TextStyle(fontSize: 15, height: 1.4))
        .copyWith(color: color ?? style?.color);
    final blocks = text.split('\n');

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final line in blocks)
          if (line.trim().isEmpty)
            const SizedBox(height: 10)
          else if (RegExp(r'^\s*[-•*]\s+').hasMatch(line))
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('•  ', style: base),
                  Expanded(
                    child: _inlineMarkdown(
                      line.replaceFirst(RegExp(r'^\s*[-•*]\s+'), ''),
                      base,
                    ),
                  ),
                ],
              ),
            )
          else
            _inlineMarkdown(
              line.replaceFirst(RegExp(r'^#{1,3}\s+'), ''),
              RegExp(r'^#{1,3}\s+').hasMatch(line)
                  ? base.copyWith(fontWeight: FontWeight.w700, fontSize: 16)
                  : base,
            ),
      ],
    );
  }

  Widget _inlineMarkdown(String value, TextStyle base) {
    final spans = <TextSpan>[];
    final re = RegExp(r'(\*\*|__)(.+?)\1|(?<!\*)\*([^*\n]+?)\*(?!\*)');
    int last = 0;
    for (final m in re.allMatches(value)) {
      if (m.start > last) {
        spans.add(TextSpan(text: value.substring(last, m.start), style: base));
      }
      spans.add(TextSpan(
        text: m.group(2) ?? m.group(3),
        style: base.copyWith(
          fontWeight: m.group(2) != null ? FontWeight.w700 : null,
          fontStyle: m.group(3) != null ? FontStyle.italic : null,
        ),
      ));
      last = m.end;
    }
    if (last < value.length) {
      spans.add(TextSpan(text: value.substring(last), style: base));
    }
    if (spans.isEmpty) {
      return Text(value, style: base);
    }
    return Text.rich(TextSpan(children: spans));
  }
}

typedef CardActionCallback = void Function(Map<String, dynamic> action);

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<ChatMessage> _messages = [];
  WebSocketChannel? _channel;
  bool _connected = false;
  bool _sending = false;
  Timer? _retryTimer;
  StreamSubscription<Uri>? _linkSubscription;
  final AppLinks _appLinks = AppLinks();
  final ImagePicker _imagePicker = ImagePicker();
  int _connectionEpoch = 0;
  String? _pendingContinuationToken;
  bool _proactiveLoaded = false;

  static String get wsUrl => AppConfig.webSocketUrl;
  static const String baseUrl = AppConfig.apiBaseUrl;

  static const _suggestions = [
    'Qual meu saldo?',
    'Pix de 150 para João',
    'Meus padrões',
    'Que contas tenho que pagar?',
    'Quero investir em CDB',
    'Pix de 2500 para Carlos',
    'Quero investir em ações',
  ];

  @override
  void initState() {
    super.initState();
    _connect();
    _listenForLinks();
    _addSystemMessage(
      'Olá! Sou o Assistente Pessoal Financeiro do Itaú.\n'
      'Posso ajudar com saldo, padrões de gasto, boletos e investimentos.\n\n'
      'Toque em uma sugestão ou digite sua pergunta.',
    );
  }

  void _listenForLinks() {
    _linkSubscription = _appLinks.uriLinkStream.listen((uri) {
      if (uri.scheme == 'apf' && uri.host == 'continue') {
        final token = uri.queryParameters['token'];
        if (token == null || token.isEmpty) return;
        _pendingContinuationToken = token;
        _resumeContinuationIfReady();
      }
    });
  }

  void _resumeContinuationIfReady() {
    final token = _pendingContinuationToken;
    if (token == null || !_connected || _channel == null) return;
    _pendingContinuationToken = null;
    _addSystemMessage('Jornada recebida do Telegram. Validando o link seguro…');
    _sendAction({'type': 'resume_continuation', 'token': token});
  }

  Future<void> _connect() async {
    final epoch = ++_connectionEpoch;
    _retryTimer?.cancel();
    try {
      _channel?.sink.close();
      final channel = WebSocketChannel.connect(Uri.parse(wsUrl));
      _channel = channel;
      await channel.ready.timeout(const Duration(seconds: 5));
      if (!mounted || epoch != _connectionEpoch) return;
      setState(() => _connected = true);
      _resumeContinuationIfReady();
      if (!_proactiveLoaded) {
        _proactiveLoaded = true;
        Timer(const Duration(milliseconds: 900), () {
          if (mounted) _loadProactive(silentWhenEmpty: true);
        });
      }
      channel.stream.listen(
        (data) {
          try {
            final json = jsonDecode(data as String) as Map<String, dynamic>;
            final cards = (json['cards'] as List?)
                    ?.map((c) => Map<String, dynamic>.from(c as Map))
                    .toList() ??
                [];
            if (!mounted) return;
            setState(() {
              _sending = false;
              _messages.add(ChatMessage(
                text: json['text'] ?? '',
                isUser: false,
                intent: json['intent'] as String?,
                cards: cards,
              ));
            });
            _scrollToBottom();
          } catch (_) {
            _addSystemMessage('Recebi uma resposta inválida. Tente novamente.');
          }
        },
        onError: (_) => _handleDisconnect(epoch),
        onDone: () => _handleDisconnect(epoch),
        cancelOnError: true,
      );
    } catch (_) {
      _handleDisconnect(epoch);
    }
  }

  void _handleDisconnect(int epoch) {
    if (!mounted || epoch != _connectionEpoch) return;
    final wasConnected = _connected;
    setState(() {
      _connected = false;
      _sending = false;
    });
    if (wasConnected) {
      _addSystemMessage('Conexão perdida. Tentando reconectar…');
    }
    _retryTimer?.cancel();
    _retryTimer = Timer(const Duration(seconds: 2), _connect);
  }

  void _addSystemMessage(String text) {
    setState(() {
      _messages.add(ChatMessage(text: text, isUser: false, isSystem: true));
    });
  }

  void _send([String? preset]) {
    final text = (preset ?? _controller.text).trim();
    if (text.isEmpty || _sending) return;

    setState(() {
      _messages.add(ChatMessage(text: text, isUser: true));
      _sending = true;
      _controller.clear();
    });
    _scrollToBottom();

    if (_channel != null && _connected) {
      _channel!.sink.add(jsonEncode({'text': text, 'user_id': 'demo'}));
    } else {
      setState(() => _sending = false);
      _addSystemMessage(
          'Backend offline. Suba o uvicorn e toque no ícone de nuvem.');
    }
  }

  void _sendAction(Map<String, dynamic> action) {
    if (_sending) return;
    if (_channel == null || !_connected) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Backend offline')),
      );
      return;
    }
    setState(() => _sending = true);
    final payload = Map<String, dynamic>.from(action)
      ..['request_id'] = DateTime.now().microsecondsSinceEpoch.toString();
    _channel!.sink.add(jsonEncode({
      'user_id': 'demo',
      'action': payload,
    }));
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent + 120,
          duration: const Duration(milliseconds: 280),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _loadDashboard() async {
    try {
      final res = await http.get(Uri.parse('$baseUrl/user/demo/dashboard'));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        setState(() {
          _messages.add(ChatMessage(
            text: 'Resumo da sua conta:',
            isUser: false,
            cards: [
              {
                'type': 'balance',
                'title': 'Seu saldo',
                'data': {
                  'disponivel': data['saldo']['disponivel'],
                  'bloqueado': data['saldo']['bloqueado'] ?? 0,
                  'boletos': data['boletos'] ?? [],
                  '_source': 'sintético',
                },
              }
            ],
          ));
        });
        _scrollToBottom();
      }
    } catch (_) {
      _addSystemMessage('Não foi possível carregar o dashboard.');
    }
  }

  Future<void> _loadPatterns() async {
    try {
      final res = await http.get(Uri.parse('$baseUrl/user/demo/patterns'));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final patterns = data['patterns'] as List? ?? [];
        if (patterns.isEmpty) {
          _addSystemMessage('Nenhum padrão recorrente detectado ainda.');
          return;
        }
        final cards = patterns.map((p) {
          final m = Map<String, dynamic>.from(p as Map);
          return {
            'type': 'pattern',
            'title': m['descricao'] ?? 'Padrão detectado',
            'data': {
              'tipo': m['tipo'],
              'descricao': m['descricao'],
              'valor_medio': m['valor_medio'],
              'frequencia': m['frequencia'],
              'metodo': m['_metodo'] ?? 'agregacao_sql',
              'nota': 'Detectado por agregação SQL (não clustering).',
              'acao_sugerida': m['tipo'] == 'pix_recorrente'
                  ? 'Configurar Pix Automático'
                  : 'Ver detalhes',
              'favorecido': m['favorecido'],
            },
          };
        }).toList();
        setState(() {
          _messages.add(ChatMessage(
            text: 'Padrões encontrados pelo EPC:',
            isUser: false,
            cards: cards,
          ));
        });
        _scrollToBottom();
      }
    } catch (_) {
      _addSystemMessage('Não foi possível carregar os padrões.');
    }
  }

  Future<void> _loadProactive({bool silentWhenEmpty = false}) async {
    try {
      final res =
          await http.post(Uri.parse('$baseUrl/user/demo/proactive/scan'));
      if (res.statusCode != 200) throw Exception('HTTP ${res.statusCode}');
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      final results = (data['results'] as List? ?? [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .where((item) => item['enviado'] == true)
          .toList();
      if (results.isEmpty) {
        if (!silentWhenEmpty) {
          _addSystemMessage(
            'Nenhuma nova sugestão agora. Os controles de consentimento, limite diário e intervalo entre avisos estão ativos.',
          );
        }
        return;
      }
      final cards = results
          .map((item) => {
                'type': 'proactive',
                'title': item['categoria'] == 'boletos'
                    ? 'Conta próxima do vencimento'
                    : item['categoria'] == 'investimento'
                        ? 'Oportunidade no saldo'
                        : 'Padrão detectado pelo EPC',
                'data': item,
              })
          .toList();
      if (!mounted) return;
      setState(() {
        _messages.add(ChatMessage(
          text: 'Encontrei oportunidades relevantes para você:',
          isUser: false,
          cards: cards,
        ));
      });
      _scrollToBottom();
    } catch (_) {
      _addSystemMessage('Não foi possível verificar novas sugestões agora.');
    }
  }

  Future<void> _pickAndScanBill() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Wrap(children: [
          ListTile(
            leading: const Icon(Icons.photo_camera_outlined),
            title: const Text('Fotografar boleto'),
            onTap: () => Navigator.pop(context, ImageSource.camera),
          ),
          ListTile(
            leading: const Icon(Icons.photo_library_outlined),
            title: const Text('Escolher da galeria'),
            onTap: () => Navigator.pop(context, ImageSource.gallery),
          ),
        ]),
      ),
    );
    if (source == null) return;
    try {
      final image = await _imagePicker.pickImage(
        source: source,
        imageQuality: 88,
        maxWidth: 2200,
      );
      if (image == null) return;
      if (mounted) setState(() => _sending = true);
      final request = http.MultipartRequest(
        'POST', Uri.parse('$baseUrl/user/demo/boleto/scan'),
      );
      request.files.add(http.MultipartFile.fromBytes(
        'file', await image.readAsBytes(), filename: image.name,
      ));
      final streamed = await request.send();
      final body = await streamed.stream.bytesToString();
      if (streamed.statusCode != 200) throw Exception(body);
      final data = jsonDecode(body) as Map<String, dynamic>;
      final cards = (data['cards'] as List? ?? [])
          .map((c) => Map<String, dynamic>.from(c as Map)).toList();
      if (!mounted) return;
      setState(() {
        _sending = false;
        _messages.add(ChatMessage(
          text: data['text']?.toString() ?? 'Revise os dados encontrados.',
          isUser: false,
          intent: 'pagar',
          cards: cards,
        ));
      });
      _scrollToBottom();
    } catch (_) {
      if (mounted) setState(() => _sending = false);
      _addSystemMessage('Não consegui ler essa imagem. Tente uma foto mais nítida.');
    }
  }

  @override
  void dispose() {
    _connectionEpoch++;
    _retryTimer?.cancel();
    _linkSubscription?.cancel();
    _channel?.sink.close();
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF7F7F8),
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('APF Itaú',
                style: TextStyle(fontWeight: FontWeight.bold)),
            Text(
              _connected ? 'Online' : 'Offline',
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w400),
            ),
          ],
        ),
        backgroundColor: const Color(0xFFFF6200),
        foregroundColor: Colors.white,
        elevation: 0,
        actions: [
          IconButton(
            icon: Icon(_connected
                ? Icons.cloud_done_rounded
                : Icons.cloud_off_rounded),
            tooltip: 'Reconectar',
            onPressed: _connect,
          ),
          PopupMenuButton<String>(
            onSelected: (v) {
              if (v == 'dashboard') _loadDashboard();
              if (v == 'patterns') _loadPatterns();
              if (v == 'proactive') _loadProactive();
              if (v == 'privacy') {
                Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const PrivacyScreen()),
                );
              }
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'dashboard', child: Text('Dashboard')),
              PopupMenuItem(value: 'patterns', child: Text('Padrões (EPC)')),
              PopupMenuItem(
                  value: 'proactive', child: Text('Sugestões proativas')),
              PopupMenuItem(
                  value: 'privacy', child: Text('Privacidade / LGPD')),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
              itemCount: _messages.length + (_sending ? 1 : 0),
              itemBuilder: (context, index) {
                if (_sending && index == _messages.length) {
                  return const _TypingIndicator();
                }
                return MessageBubble(
                  message: _messages[index],
                  onAction: _sendAction,
                );
              },
            ),
          ),
          _buildSuggestions(),
          _buildInput(),
        ],
      ),
    );
  }

  Widget _buildSuggestions() {
    if (_messages.length > 4) return const SizedBox.shrink();
    return SizedBox(
      height: 44,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        itemCount: _suggestions.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          return ActionChip(
            label: Text(_suggestions[i], style: const TextStyle(fontSize: 12)),
            backgroundColor: Colors.white,
            side: BorderSide(color: Colors.grey.shade300),
            onPressed: _sending ? null : () => _send(_suggestions[i]),
          );
        },
      ),
    );
  }

  Widget _buildInput() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.06),
            blurRadius: 10,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      child: SafeArea(
        top: false,
        child: Row(
          children: [
            IconButton(
              onPressed: _sending ? null : _pickAndScanBill,
              tooltip: 'Fotografar boleto',
              icon: const Icon(Icons.document_scanner_outlined),
              color: const Color(0xFFFF6200),
            ),
            Expanded(
              child: TextField(
                controller: _controller,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _send(),
                enabled: !_sending,
                decoration: InputDecoration(
                  hintText: 'Pergunte sobre saldo, padrões, boletos…',
                  filled: true,
                  fillColor: Colors.grey.shade100,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Material(
              color: const Color(0xFFFF6200),
              shape: const CircleBorder(),
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: _sending ? null : () => _send(),
                child: const Padding(
                  padding: EdgeInsets.all(12),
                  child:
                      Icon(Icons.send_rounded, color: Colors.white, size: 20),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  const _TypingIndicator();

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Colors.grey.shade200),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: Color(0xFFFF6200)),
            ),
            SizedBox(width: 10),
            Text('Pensando…',
                style: TextStyle(fontSize: 13, color: Colors.black54)),
          ],
        ),
      ),
    );
  }
}

class ChatMessage {
  final String text;
  final bool isUser;
  final bool isSystem;
  final String? intent;
  final List<Map<String, dynamic>> cards;

  ChatMessage({
    required this.text,
    required this.isUser,
    this.isSystem = false,
    this.intent,
    this.cards = const [],
  });
}

class MessageBubble extends StatelessWidget {
  final ChatMessage message;
  final CardActionCallback? onAction;

  const MessageBubble({super.key, required this.message, this.onAction});

  @override
  Widget build(BuildContext context) {
    final isUser = message.isUser;
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Column(
        crossAxisAlignment:
            isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          if (message.text.isNotEmpty)
            Container(
              margin: const EdgeInsets.symmetric(vertical: 4),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              constraints: BoxConstraints(
                maxWidth: MediaQuery.of(context).size.width * 0.8,
              ),
              decoration: BoxDecoration(
                color: isUser
                    ? const Color(0xFFFF6200)
                    : message.isSystem
                        ? const Color(0xFFFFF8E1)
                        : Colors.white,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(16),
                  topRight: const Radius.circular(16),
                  bottomLeft: Radius.circular(isUser ? 16 : 4),
                  bottomRight: Radius.circular(isUser ? 4 : 16),
                ),
                border: isUser ? null : Border.all(color: Colors.grey.shade200),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.04),
                    blurRadius: 4,
                    offset: const Offset(0, 1),
                  ),
                ],
              ),
              child: FormattedText(
                message.text,
                color: isUser ? Colors.white : Colors.black87,
                style: const TextStyle(fontSize: 15, height: 1.4),
              ),
            ),
          ...message.cards.map((c) => _buildCard(context, c)),
        ],
      ),
    );
  }

  Widget _buildCard(BuildContext context, Map<String, dynamic> card) {
    final type = card['type'] as String? ?? '';
    final title = card['title'] as String? ?? '';
    final data = Map<String, dynamic>.from(card['data'] as Map? ?? {});
    switch (type) {
      case 'payment_comparison':
        return _PaymentComparisonCard(
            title: title, data: data, onAction: onAction);
      case 'pattern':
        return _PatternCard(title: title, data: data, onAction: onAction);
      case 'proactive':
        return _ProactiveCard(title: title, data: data, onAction: onAction);
      case 'balance':
        return _BalanceCard(title: title, data: data);
      case 'investment_suggestion':
        return _InvestmentCard(title: title, data: data, onAction: onAction);
      case 'suitability_blocked':
        return _BlockedCard(title: title, data: data);
      case 'security_check':
        return _SecurityCard(title: title, data: data, onAction: onAction);
      case 'transfer_confirm':
        return _TransferConfirmCard(
            title: title, data: data, onAction: onAction);
      case 'transfer_receipt':
        return _TransferReceiptCard(title: title, data: data);
      case 'transfer_contacts':
        return _TransferContactsCard(
            title: title, data: data, onAction: onAction);
      case 'pix_auto_configured':
        return _PixAutoCard(title: title, data: data);
      case 'bills':
        return _BillsCard(title: title, data: data, onAction: onAction);
      case 'bill_scan':
        return _BillScanCard(title: title, data: data, onAction: onAction);
      case 'statement':
        return _StatementCard(title: title, data: data);
      case 'payment_confirmed':
        return _PaymentConfirmedCard(title: title, data: data);
      default:
        return const SizedBox.shrink();
    }
  }
}

class _CardShell extends StatelessWidget {
  final String title;
  final IconData icon;
  final Color accent;
  final Widget child;
  final List<Widget>? actions;

  const _CardShell({
    required this.title,
    required this.icon,
    required this.accent,
    required this.child,
    this.actions,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: MediaQuery.of(context).size.width * 0.88,
      margin: const EdgeInsets.only(top: 6, bottom: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: accent.withValues(alpha: 0.3)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.06),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.08),
              borderRadius:
                  const BorderRadius.vertical(top: Radius.circular(13)),
            ),
            child: Row(
              children: [
                Icon(icon, size: 18, color: accent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    title,
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      color: accent,
                      fontSize: 14,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
            child: child,
          ),
          if (actions != null && actions!.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 0, 10, 10),
              child: Wrap(spacing: 8, runSpacing: 6, children: actions!),
            ),
        ],
      ),
    );
  }
}

/// Comparador INTERATIVO: usuário seleciona a forma antes de confirmar.
class _PaymentComparisonCard extends StatefulWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _PaymentComparisonCard({
    required this.title,
    required this.data,
    this.onAction,
  });

  @override
  State<_PaymentComparisonCard> createState() => _PaymentComparisonCardState();
}

class _PaymentComparisonCardState extends State<_PaymentComparisonCard> {
  String? _selectedId;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    final opcoes = (widget.data['opcoes'] as List?) ?? [];
    for (final op in opcoes) {
      final m = Map<String, dynamic>.from(op as Map);
      if (m['recomendado'] == true) {
        _selectedId = m['id']?.toString() ?? m['forma']?.toString();
        break;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final opcoes = (widget.data['opcoes'] as List?) ?? [];
    final valor = widget.data['valor'];

    return _CardShell(
      title: widget.title,
      icon: Icons.compare_arrows_rounded,
      accent: const Color(0xFF1565C0),
      actions: [
        FilledButton(
          onPressed: _selectedId == null || _submitting
              ? null
              : () {
                  final forma = _selectedLabel(opcoes);
                  setState(() => _submitting = true);
                  widget.onAction?.call({
                    'type': 'confirm_payment',
                    'forma': forma,
                    'valor': valor,
                    'opcao_id': _selectedId,
                  });
                },
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xFFFF6200),
            disabledBackgroundColor: Colors.grey.shade300,
          ),
          child:
              Text(_submitting ? 'Processando…' : 'Continuar com esta opção'),
        ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Selecione a forma de pagamento:',
            style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
          ),
          const SizedBox(height: 8),
          ...opcoes.map((op) {
            final m = Map<String, dynamic>.from(op as Map);
            final id = m['id']?.toString() ?? m['forma']?.toString() ?? '';
            final recommended = m['recomendado'] == true;
            final selected = _selectedId == id;
            return GestureDetector(
              onTap: () => setState(() => _selectedId = id),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: selected
                      ? const Color(0xFFE3F2FD)
                      : recommended
                          ? const Color(0xFFE8F5E9)
                          : Colors.grey.shade50,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: selected
                        ? const Color(0xFF1565C0)
                        : recommended
                            ? const Color(0xFF66BB6A)
                            : Colors.grey.shade200,
                    width: selected ? 2 : 1,
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      selected
                          ? Icons.radio_button_checked
                          : Icons.radio_button_off,
                      size: 22,
                      color: selected ? const Color(0xFF1565C0) : Colors.grey,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            m['forma']?.toString() ?? '',
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: selected
                                  ? const Color(0xFF1565C0)
                                  : Colors.black87,
                            ),
                          ),
                          Text(
                            m['motivo']?.toString() ?? '',
                            style: const TextStyle(
                                fontSize: 12, color: Colors.black54),
                          ),
                          Text(
                            'Prazo: ${m['prazo'] ?? '-'}',
                            style: const TextStyle(
                                fontSize: 11, color: Colors.black38),
                          ),
                          if (m['impacto'] != null)
                            Text(
                              m['impacto'].toString(),
                              style: const TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                                color: Color(0xFF37474F),
                              ),
                            ),
                        ],
                      ),
                    ),
                    if (recommended)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xFF2E7D32),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          'Recomendado',
                          style: TextStyle(color: Colors.white, fontSize: 10),
                        ),
                      ),
                  ],
                ),
              ),
            );
          }),
          if (widget.data['_disclaimer'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                widget.data['_disclaimer'].toString(),
                style: const TextStyle(fontSize: 11, color: Colors.black38),
              ),
            ),
          if ((widget.data['premissas'] as List?)?.isNotEmpty == true)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                dense: true,
                title: const Text('Premissas da comparação',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                children: (widget.data['premissas'] as List)
                    .map((item) => Align(
                          alignment: Alignment.centerLeft,
                          child: Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Text('• $item',
                                style: const TextStyle(fontSize: 11, color: Colors.black54)),
                          ),
                        ))
                    .toList(),
              ),
            ),
        ],
      ),
    );
  }

  String _selectedLabel(List opcoes) {
    for (final op in opcoes) {
      final m = Map<String, dynamic>.from(op as Map);
      final id = m['id']?.toString() ?? m['forma']?.toString();
      if (id == _selectedId) return m['forma']?.toString() ?? id ?? 'Pix';
    }
    return 'Pix';
  }
}

class _BillsCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _BillsCard({required this.title, required this.data, this.onAction});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    final boletos = (data['boletos'] as List?) ?? [];
    return _CardShell(
      title: title,
      icon: Icons.receipt_long_rounded,
      accent: const Color(0xFF6A1B9A),
      child: Column(
        children: boletos.map((b) {
          final m = Map<String, dynamic>.from(b as Map);
          return Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.grey.shade50,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.grey.shade200),
            ),
            child: Row(
              children: [
                const Icon(Icons.receipt, size: 20, color: Color(0xFF6A1B9A)),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        m['beneficiario']?.toString() ?? '',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      Text(
                        'Vence ${m['vencimento'] ?? '-'}',
                        style: const TextStyle(
                            fontSize: 12, color: Colors.black54),
                      ),
                    ],
                  ),
                ),
                Text(
                  'R\$ ${_fmt(m['valor'])}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w600, fontSize: 15),
                ),
                const SizedBox(width: 8),
                TextButton(
                  onPressed: () {
                    onAction?.call({
                      'type': 'confirm_payment',
                      'forma': 'Pix',
                      'boleto_id': m['id'],
                      'beneficiario': m['beneficiario'],
                    });
                  },
                  style: TextButton.styleFrom(
                    foregroundColor: const Color(0xFFFF6200),
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                  ),
                  child: const Text('Pagar',
                      style: TextStyle(fontWeight: FontWeight.w600)),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _BillScanCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _BillScanCard({required this.title, required this.data, this.onAction});

  String _fmt(dynamic value) {
    final number = value is num ? value.toDouble() : double.tryParse('$value') ?? 0;
    return number.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    final confidence = ((data['confidence'] as num?)?.toDouble() ?? 0) * 100;
    final realVision = data['extraction_mode'] == 'groq_vision';
    return _CardShell(
      title: title,
      icon: Icons.document_scanner_rounded,
      accent: const Color(0xFF6A1B9A),
      actions: [
        FilledButton.icon(
          onPressed: () => onAction?.call({
            'type': 'confirm_payment',
            'forma': 'Pix',
            'boleto_id': data['id'],
          }),
          style: FilledButton.styleFrom(backgroundColor: const Color(0xFFFF6200)),
          icon: const Icon(Icons.lock_outline_rounded),
          label: const Text('Confirmar no app'),
        ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(data['beneficiario']?.toString() ?? 'Beneficiário não identificado',
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 17)),
          const SizedBox(height: 4),
          Text('R\$ ${_fmt(data['valor'])}',
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
          Text('Vencimento: ${data['vencimento'] ?? 'não identificado'}'),
          if (data['linha_digitavel'] != null) ...[
            const SizedBox(height: 8),
            Text('Linha: ${data['linha_digitavel']}',
                maxLines: 2, style: const TextStyle(fontSize: 11, color: Colors.black54)),
          ],
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: realVision ? Colors.green.shade50 : Colors.orange.shade50,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              realVision
                  ? 'Leitura multimodal · confiança ${confidence.toStringAsFixed(0)}%. Revise antes de pagar.'
                  : 'Modo demonstração · dados de exemplo. Revise antes de pagar.',
              style: const TextStyle(fontSize: 12, height: 1.3),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatementCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;

  const _StatementCard({required this.title, required this.data});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    final txs = (data['transacoes'] as List?) ?? [];
    return _CardShell(
      title: title,
      icon: Icons.list_alt_rounded,
      accent: const Color(0xFF455A64),
      child: Column(
        children: txs.map((t) {
          final m = Map<String, dynamic>.from(t as Map);
          return Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(m['descricao']?.toString() ?? '',
                          style: const TextStyle(fontSize: 13)),
                      Text(
                        '${m['data']} · ${m['tipo']}',
                        style: const TextStyle(
                            fontSize: 11, color: Colors.black45),
                      ),
                    ],
                  ),
                ),
                Text(
                  'R\$ ${_fmt(m['valor'])}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w600, fontSize: 13),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _PaymentConfirmedCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;

  const _PaymentConfirmedCard({required this.title, required this.data});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    return _CardShell(
      title: title,
      icon: Icons.check_circle_rounded,
      accent: const Color(0xFF2E7D32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'R\$ ${_fmt(data['valor'])} via ${data['forma'] ?? 'Pix'}',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          Text(
            'Status: ${data['status'] ?? 'confirmado'}',
            style: const TextStyle(fontSize: 12, color: Colors.black54),
          ),
        ],
      ),
    );
  }
}

class _PatternCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _PatternCard({required this.title, required this.data, this.onAction});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    final isPix = data['tipo'] == 'pix_recorrente';
    return _CardShell(
      title: title,
      icon: Icons.repeat_rounded,
      accent: const Color(0xFF6A1B9A),
      actions: isPix
          ? [
              FilledButton(
                onPressed: () {
                  onAction?.call({
                    'type': 'configure_pix_auto',
                    'favorecido': data['favorecido'] ?? data['descricao'],
                    'valor': data['valor_medio'],
                  });
                },
                style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFFFF6200)),
                child: Text(data['acao_sugerida']?.toString() ??
                    'Configurar Pix Automático'),
              ),
            ]
          : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'R\$ ${_fmt(data['valor_medio'])}  ·  ${data['frequencia'] ?? '-'} ocorrências',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 6),
          Text(
            data['nota']?.toString() ??
                'Detectado por agregação SQL (não clustering).',
            style: const TextStyle(fontSize: 12, color: Colors.black54),
          ),
          Text(
            'Método: ${data['metodo'] ?? 'agregacao_sql'}',
            style: const TextStyle(fontSize: 11, color: Colors.black38),
          ),
        ],
      ),
    );
  }
}

class _ProactiveCard extends StatefulWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _ProactiveCard(
      {required this.title, required this.data, this.onAction});

  @override
  State<_ProactiveCard> createState() => _ProactiveCardState();
}

class _ProactiveCardState extends State<_ProactiveCard>
    with SingleTickerProviderStateMixin {
  bool _dismissed = false;
  bool _muted = false;
  late final AnimationController _anim;

  @override
  void initState() {
    super.initState();
    _anim = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 280),
      value: 1.0,
    );
  }

  @override
  void dispose() {
    _anim.dispose();
    super.dispose();
  }

  Future<void> _mute() async {
    setState(() => _muted = true);
    widget.onAction?.call({
      'type': 'mute_suggestion',
      'categoria': widget.data['categoria'] ?? 'geral',
    });
    await Future.delayed(const Duration(milliseconds: 900));
    if (!mounted) return;
    await _anim.reverse();
    if (!mounted) return;
    setState(() => _dismissed = true);
  }

  @override
  Widget build(BuildContext context) {
    if (_dismissed) return const SizedBox.shrink();

    return SizeTransition(
      sizeFactor: _anim,
      alignment: Alignment.topCenter,
      child: FadeTransition(
        opacity: _anim,
        child: _muted
            ? const _CardShell(
                title: 'Preferência salva',
                icon: Icons.notifications_off_outlined,
                accent: Color(0xFF78909C),
                child: Text(
                  'Não falaremos mais sobre isso.',
                  style: TextStyle(fontSize: 14, height: 1.4),
                ),
              )
            : _CardShell(
                title: widget.title,
                icon: Icons.lightbulb_outline_rounded,
                accent: const Color(0xFFFF6200),
                actions: [
                  if (widget.data['action'] is Map)
                    FilledButton(
                      onPressed: () => widget.onAction?.call(
                        Map<String, dynamic>.from(widget.data['action'] as Map),
                      ),
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFFFF6200),
                      ),
                      child: Text(
                        widget.data['acao_sugerida']?.toString() ?? 'Continuar',
                      ),
                    ),
                  TextButton(
                    onPressed: _mute,
                    child: const Text(
                      'Não me avise mais',
                      style: TextStyle(color: Colors.black54),
                    ),
                  ),
                ],
                child: Text(
                  widget.data['mensagem']?.toString() ?? '',
                  style: const TextStyle(fontSize: 14, height: 1.4),
                ),
              ),
      ),
    );
  }
}

class _BalanceCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;

  const _BalanceCard({required this.title, required this.data});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    final boletos = (data['boletos'] as List?) ?? [];
    return _CardShell(
      title: title,
      icon: Icons.account_balance_wallet_rounded,
      accent: const Color(0xFF2E7D32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'R\$ ${_fmt(data['disponivel'])}',
            style: const TextStyle(
              fontSize: 26,
              fontWeight: FontWeight.bold,
              color: Color(0xFF2E7D32),
            ),
          ),
          const Text('disponível',
              style: TextStyle(fontSize: 13, color: Colors.black54)),
          if (boletos.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('Próximos boletos',
                style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
            const SizedBox(height: 6),
            ...boletos.map((b) {
              final m = Map<String, dynamic>.from(b as Map);
              return Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: [
                    const Icon(Icons.receipt_long,
                        size: 16, color: Colors.grey),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        '${m['beneficiario']} — R\$ ${_fmt(m['valor'])}',
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                    Text(
                      m['vencimento']?.toString() ?? '',
                      style:
                          const TextStyle(fontSize: 12, color: Colors.black45),
                    ),
                  ],
                ),
              );
            }),
          ],
          const SizedBox(height: 6),
          const SizedBox.shrink(),
        ],
      ),
    );
  }
}

class _InvestmentCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _InvestmentCard(
      {required this.title, required this.data, this.onAction});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    final suggestedValue = data['valor_sugerido'];
    return _CardShell(
      title: title,
      icon: Icons.trending_up_rounded,
      accent: const Color(0xFF00695C),
      actions: suggestedValue == null
          ? null
          : [
              FilledButton(
                onPressed: () {
                  onAction?.call({
                    'type': 'apply_investment',
                    'produto': data['produto'] ?? title,
                    'produto_id': data['produto_id'],
                    'valor': suggestedValue,
                  });
                },
                style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFFFF6200)),
                child: Text('Aplicar R\$ ${_fmt(suggestedValue)}'),
              ),
            ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(data['descricao']?.toString() ?? '',
              style: const TextStyle(fontSize: 14)),
          if (data['rendimento_estimado'] != null) ...[
            const SizedBox(height: 6),
            Text(
              'Rendimento estimado: ${data['rendimento_estimado']}',
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
            ),
          ],
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              _chip('Risco: ${data['risco'] ?? '-'}', const Color(0xFF00695C)),
              _chip(
                  'Perfil: ${data['perfil'] ?? '-'}', const Color(0xFF455A64)),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            data['disclaimer']?.toString() ??
                'Projeção estimada. Rentabilidade passada não garante rentabilidade futura.',
            style: const TextStyle(fontSize: 11, color: Colors.black45),
          ),
        ],
      ),
    );
  }

  Widget _chip(String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(label,
          style: TextStyle(
              fontSize: 11, color: color, fontWeight: FontWeight.w500)),
    );
  }
}

class _BlockedCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;

  const _BlockedCard({required this.title, required this.data});

  @override
  Widget build(BuildContext context) {
    return _CardShell(
      title: title,
      icon: Icons.block_rounded,
      accent: const Color(0xFFC62828),
      child: Text(
        data['mensagem']?.toString() ??
            'Produto não disponível para o seu perfil.',
        style: const TextStyle(fontSize: 14),
      ),
    );
  }
}

class _TransferContactsCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _TransferContactsCard(
      {required this.title, required this.data, this.onAction});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    final contatos = (data['contatos'] as List?) ?? [];
    return _CardShell(
      title: title,
      icon: Icons.contacts_rounded,
      accent: const Color(0xFF5E35B1),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: contatos.map((c) {
          final m = Map<String, dynamic>.from(c as Map);
          return ActionChip(
            avatar: const Icon(Icons.person, size: 16),
            label: Text(
              '${m['favorecido']} · R\$ ${_fmt(m['ultimo_valor'])}',
              style: const TextStyle(fontSize: 12),
            ),
            onPressed: () {
              onAction?.call({
                'type': 'select_contact',
                'favorecido': m['favorecido'],
                'ultimo_valor': m['ultimo_valor'],
                'valor': data['valor_sugerido'],
              });
            },
          );
        }).toList(),
      ),
    );
  }
}

class _TransferConfirmCard extends StatefulWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _TransferConfirmCard({
    required this.title,
    required this.data,
    this.onAction,
  });

  @override
  State<_TransferConfirmCard> createState() => _TransferConfirmCardState();
}

class _TransferConfirmCardState extends State<_TransferConfirmCard> {
  bool _sent = false;
  bool _locked = false;
  bool _editing = false;
  late TextEditingController _valorCtrl;
  late TextEditingController _favCtrl;

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  void initState() {
    super.initState();
    _locked = widget.data['needs_security'] == true;
    _valorCtrl = TextEditingController(text: _fmt(widget.data['valor']));
    _favCtrl = TextEditingController(
        text: widget.data['favorecido']?.toString() ?? '');
  }

  @override
  void didUpdateWidget(covariant _TransferConfirmCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.data['needs_security'] != true) _locked = false;
    if (!_editing) {
      _valorCtrl.text = _fmt(widget.data['valor']);
      _favCtrl.text = widget.data['favorecido']?.toString() ?? '';
    }
  }

  @override
  void dispose() {
    _valorCtrl.dispose();
    _favCtrl.dispose();
    super.dispose();
  }

  double? _parseValor(String s) {
    final cleaned = s.replaceAll('.', '').replaceAll(',', '.');
    return double.tryParse(cleaned);
  }

  void _saveEdit() {
    final v = _parseValor(_valorCtrl.text);
    final fav = _favCtrl.text.trim();
    if (v == null || fav.isEmpty) return;
    setState(() => _editing = false);
    widget.onAction?.call({
      'type': 'update_transfer',
      'valor': v,
      'favorecido': fav,
      'tipo': widget.data['tipo'] ?? 'pix',
    });
  }

  @override
  Widget build(BuildContext context) {
    final data = widget.data;
    final tipo = (data['tipo']?.toString() ?? 'pix').toUpperCase();
    final contatos = (data['contatos_recentes'] as List?) ?? [];

    if (_sent) {
      return const _CardShell(
        title: 'Enviando…',
        icon: Icons.hourglass_top_rounded,
        accent: Color(0xFF1565C0),
        child:
            Text('Processando transferência.', style: TextStyle(fontSize: 14)),
      );
    }

    return _CardShell(
      title: widget.title,
      icon: Icons.send_rounded,
      accent: const Color(0xFF1565C0),
      actions: [
        if (!_editing && data['editavel'] == true)
          TextButton(
            onPressed: () => setState(() => _editing = true),
            child: const Text('Editar'),
          ),
        if (_editing)
          FilledButton(
            onPressed: _saveEdit,
            style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFF1565C0)),
            child: const Text('Salvar alterações'),
          ),
        FilledButton(
          onPressed: (_locked || _editing)
              ? null
              : () {
                  setState(() => _sent = true);
                  widget.onAction?.call({
                    'type': 'execute_transfer',
                    'tipo': data['tipo'] ?? 'pix',
                    'valor': data['valor'],
                    'favorecido': data['favorecido'],
                    'descricao': data['descricao'],
                  });
                },
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xFFFF6200),
            disabledBackgroundColor: Colors.grey.shade300,
          ),
          child: Text(_locked
              ? 'Confirme a identidade acima'
              : (_editing ? 'Salve antes de enviar' : 'Confirmar e enviar')),
        ),
        TextButton(
          onPressed: () => widget.onAction?.call({'type': 'cancel_transfer'}),
          child: const Text('Cancelar',
              style: TextStyle(color: Color(0xFFC62828))),
        ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_editing) ...[
            TextField(
              controller: _valorCtrl,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                labelText: 'Valor (R\$)',
                border: OutlineInputBorder(),
                isDense: true,
              ),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _favCtrl,
              decoration: const InputDecoration(
                labelText: 'Destinatário',
                border: OutlineInputBorder(),
                isDense: true,
              ),
            ),
          ] else ...[
            Text(
              'R\$ ${_fmt(data['valor'])}',
              style: const TextStyle(
                fontSize: 26,
                fontWeight: FontWeight.bold,
                color: Color(0xFF1565C0),
              ),
            ),
            const SizedBox(height: 8),
            _row('Tipo', tipo == 'PIX' ? 'Pix' : tipo),
            _row('Para', data['favorecido']?.toString() ?? '—'),
            if (data['descricao'] != null)
              _row('Descrição', data['descricao'].toString()),
            _row('Saldo disponível', 'R\$ ${_fmt(data['saldo_disponivel'])}'),
          ],
          if (contatos.isNotEmpty && !_editing) ...[
            const SizedBox(height: 10),
            const Text('Trocar destinatário:',
                style: TextStyle(fontSize: 12, color: Colors.black54)),
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: contatos.take(4).map((c) {
                final m = Map<String, dynamic>.from(c as Map);
                return ActionChip(
                  label: Text(m['favorecido']?.toString() ?? '',
                      style: const TextStyle(fontSize: 11)),
                  onPressed: () {
                    widget.onAction?.call({
                      'type': 'update_transfer',
                      'favorecido': m['favorecido'],
                      'valor': data['valor'],
                      'tipo': data['tipo'] ?? 'pix',
                    });
                  },
                );
              }).toList(),
            ),
          ],
          if (_locked) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF3E0),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Text(
                'Envio bloqueado até você confirmar a identidade no alerta de segurança.',
                style: TextStyle(fontSize: 12, color: Color(0xFFE65100)),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _row(String k, String v) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          SizedBox(
              width: 120,
              child: Text(k,
                  style: const TextStyle(fontSize: 13, color: Colors.black54))),
          Expanded(
              child: Text(v,
                  style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w600))),
        ],
      ),
    );
  }
}

class _TransferReceiptCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;

  const _TransferReceiptCard({required this.title, required this.data});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    final tipo = (data['tipo']?.toString() ?? 'pix').toLowerCase();
    final label = tipo == 'pix'
        ? 'Pix'
        : (tipo == 'investimento' ? 'Investimento' : tipo.toUpperCase());
    final comprovante = data['comprovante_texto']?.toString() ??
        'Comprovante #${data['transaction_id']}\n$label · R\$ ${_fmt(data['valor'])}\nPara: ${data['favorecido']}\nSaldo após: R\$ ${_fmt(data['saldo_apos'])}';

    return _CardShell(
      title: title,
      icon: Icons.check_circle_rounded,
      accent: const Color(0xFF2E7D32),
      actions: [
        OutlinedButton.icon(
          onPressed: () {
            Clipboard.setData(ClipboardData(text: comprovante));
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Comprovante copiado.')),
            );
          },
          icon: const Icon(Icons.copy, size: 16),
          label: const Text('Copiar comprovante'),
        ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'R\$ ${_fmt(data['valor'])}',
            style: const TextStyle(
                fontSize: 26,
                fontWeight: FontWeight.bold,
                color: Color(0xFF2E7D32)),
          ),
          const SizedBox(height: 8),
          _row('Status', data['status']?.toString() ?? 'enviado'),
          _row('Tipo', label),
          _row('Para', data['favorecido']?.toString() ?? '—'),
          if (data['transaction_id'] != null)
            _row('Comprovante', '#${data['transaction_id']}'),
          if (data['saldo_apos'] != null)
            _row('Saldo após', 'R\$ ${_fmt(data['saldo_apos'])}'),
          if (data['data'] != null) _row('Data', data['data'].toString()),
        ],
      ),
    );
  }

  Widget _row(String k, String v) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          SizedBox(
              width: 120,
              child: Text(k,
                  style: const TextStyle(fontSize: 13, color: Colors.black54))),
          Expanded(
              child: Text(v,
                  style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w600))),
        ],
      ),
    );
  }
}

class _PixAutoCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;

  const _PixAutoCard({required this.title, required this.data});

  String _fmt(dynamic v) {
    if (v == null) return '-';
    final n = (v is num) ? v.toDouble() : double.tryParse(v.toString()) ?? 0;
    return n.toStringAsFixed(2).replaceAll('.', ',');
  }

  @override
  Widget build(BuildContext context) {
    return _CardShell(
      title: title,
      icon: Icons.event_repeat_rounded,
      accent: const Color(0xFF00695C),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'R\$ ${_fmt(data['valor'])} · dia ${data['dia_mes'] ?? '-'}',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          Text('Para: ${data['favorecido'] ?? '—'}',
              style: const TextStyle(fontSize: 14)),
          const SizedBox(height: 4),
          const Text('Ativo — lembrete antes de cada débito',
              style: TextStyle(fontSize: 12, color: Colors.black54)),
        ],
      ),
    );
  }
}

class _SecurityCard extends StatelessWidget {
  final String title;
  final Map<String, dynamic> data;
  final CardActionCallback? onAction;

  const _SecurityCard({required this.title, required this.data, this.onAction});

  Future<void> _confirmOnDevice(BuildContext context) async {
    final result = await DeviceAuth.authenticate();
    if (result.authenticated) {
      onAction?.call({'type': 'security_pass', 'auth_mode': 'device'});
      return;
    }
    if (result.available) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result.message)));
      }
      return;
    }
    if (!context.mounted) return;
    final confirmed = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.fingerprint_rounded,
                  size: 64, color: Color(0xFFFF6200)),
              const SizedBox(height: 12),
              const Text(
                'Confirme no dispositivo',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              const Text(
                'A autenticação nativa não está disponível neste ambiente. Para a apresentação, você pode usar um desbloqueio de demonstração claramente identificado.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.black54, height: 1.4),
              ),
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: () => Navigator.pop(sheetContext, true),
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFFFF6200),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  icon: const Icon(Icons.verified_user_rounded),
                  label: const Text('Desbloquear em modo demonstração'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (confirmed == true) {
      onAction?.call({'type': 'security_pass', 'auth_mode': 'demo_fallback'});
    }
  }

  @override
  Widget build(BuildContext context) {
    return _CardShell(
      title: title,
      icon: Icons.shield_outlined,
      accent: const Color(0xFFC62828),
      actions: [
        FilledButton(
          onPressed: () => _confirmOnDevice(context),
          style:
              FilledButton.styleFrom(backgroundColor: const Color(0xFF2E7D32)),
          child:
              Text(data['acao_sugerida']?.toString() ?? 'Confirmar identidade'),
        ),
        TextButton(
          onPressed: () {
            onAction?.call({'type': 'cancel_transfer'});
          },
          child: Text(
            data['acao_secundaria']?.toString() ?? 'Cancelar',
            style: const TextStyle(color: Color(0xFFC62828)),
          ),
        ),
      ],
      child: Text(
        data['mensagem']?.toString() ?? '',
        style: const TextStyle(fontSize: 14, height: 1.4),
      ),
    );
  }
}
