# Premissas e evidências do protótipo

Este arquivo separa claramente o que foi demonstrado, o que usa dado sintético e
o que ainda depende de validação com clientes ou infraestrutura Itaú.

| Afirmação | Estado | Evidência disponível | Próxima validação |
|---|---|---|---|
| O agente conclui Pix, boleto e investimento ponta a ponta | Implementado no protótipo | Testes `test_transfers.py`; comprovante e saldo pós-operação | Sandbox transacional Itaú |
| A jornada continua entre Telegram e app | Implementado no protótipo | Token de uso único, persistência SQL e `test_new_flows.py` | Universal Link em domínio Itaú |
| O boleto pode ser lido por imagem | Implementado com duas modalidades | Visão Groq quando disponível; fallback de demo rotulado | Conjunto de boletos anonimizados e OCR homologado |
| A biometria protege ações sensíveis | Implementado no dispositivo compatível | `local_auth`; fallback de demo explícito | Atestação assinada e política antifraude Itaú |
| A proatividade aumenta engajamento | Hipótese | Motor com consentimento, mute, limite e cooldown | Experimento A/B com clientes |
| O EPC reduz esquecimentos de pagamentos | Hipótese | Detecção SQL de recorrência e ação Pix Automático | Piloto controlado e métrica de atraso |
| A recomendação de pagamento é útil | Implementado, eficácia não validada | Impacto em saldo/fatura/limite e premissas visíveis | Teste de compreensão e decisão |
| O produto reduz custo de atendimento | Hipótese de negócio | Não há dado real no protótipo | Baseline do contact center e piloto |

## Dados e limites

- Saldo, extrato, fatura, limite, boletos e perfis são sintéticos.
- O EPC atual usa agregação SQL determinística; não deve ser apresentado como clustering.
- O modelo textual padrão é configurável. A resposta financeira é ancorada nos dados do backend.
- O modelo de visão é preview; indisponibilidade aciona um fallback identificado na tela.
- Rentabilidade e suitability são ilustrativas e não constituem recomendação financeira real.

