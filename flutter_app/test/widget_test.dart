import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:apf_flutter/main.dart';
import 'package:apf_flutter/chat_screen.dart';

void main() {
  testWidgets('onboarding mostra consentimentos granulares', (tester) async {
    await tester.pumpWidget(const ApfApp(showOnboarding: true));
    await tester.pump();

    expect(find.text('Assistente Pessoal\nFinanceiro'), findsOneWidget);
    expect(find.text('Consentimento LGPD (granular)'), findsOneWidget);
    expect(find.text('Começar'), findsOneWidget);
    expect(find.byType(Checkbox), findsNWidgets(3));

    await tester.tap(find.byType(Checkbox).first);
    await tester.pump();
    final checkbox = tester.widget<Checkbox>(find.byType(Checkbox).first);
    expect(checkbox.value, isTrue);
  });

  testWidgets('chat oferece ditado por voz sem envio automático',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: ChatScreen(
          userId: 'demo_widgettest',
          connectOnStart: false,
        ),
      ),
    );
    await tester.pump();

    expect(find.byIcon(Icons.mic_none_rounded), findsOneWidget);
    expect(find.byIcon(Icons.volume_up_outlined), findsOneWidget);
    expect(find.byTooltip('Ouvir mensagem'), findsOneWidget);
    expect(
      find.byTooltip('Ditar mensagem (não diga senhas ou códigos)'),
      findsOneWidget,
    );
    expect(find.byIcon(Icons.send_rounded), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('mensagem do assistente oferece reproduzir e parar áudio',
      (tester) async {
    var requested = false;
    final message =
        ChatMessage(text: '**Seu saldo** é R\$ 100.', isUser: false);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MessageBubble(
            message: message,
            onToggleSpeech: (_) => requested = true,
          ),
        ),
      ),
    );
    await tester.tap(find.byTooltip('Ouvir mensagem'));
    expect(requested, isTrue);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MessageBubble(message: message, isSpeaking: true),
        ),
      ),
    );
    expect(find.byTooltip('Parar áudio'), findsOneWidget);
    expect(find.byIcon(Icons.stop_circle_outlined), findsOneWidget);
  });
}
