import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:apf_flutter/main.dart';

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
}
