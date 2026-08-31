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
    expect(
      find.byTooltip('Ditar mensagem (não diga senhas ou códigos)'),
      findsOneWidget,
    );
    expect(find.byIcon(Icons.send_rounded), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });
}
