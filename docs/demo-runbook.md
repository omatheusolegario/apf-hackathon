# Roteiro de palco — 4 minutos

## Preparação

- Backend ligado e `/health` respondendo.
- App aberto após onboarding, com as três permissões demonstrativas ativadas.
- Bot vinculado ao usuário demo.
- Imagem `sabesp-demo.png` disponível na galeria; o nome garante fallback previsível se a visão estiver offline.
- Não executar `seed.py` durante a apresentação: ele recria a base sintética.

## História principal

1. **Antecipação:** abra o app e deixe a sugestão automática de boleto aparecer.
2. **Multimodal:** fotografe o boleto, revise beneficiário, valor, vencimento e confiança.
3. **Decisão explicável:** compare Pix, débito e crédito; abra “Premissas da comparação”.
4. **Omnichannel:** inicie um Pix no Telegram e continue no app.
5. **Segurança:** autentique no dispositivo; em web, mostre o rótulo “modo demonstração”.
6. **Conclusão:** confirme, mostre comprovante e saldo atualizado.

## Plano B honesto

- Groq indisponível: o chat usa resposta determinística e o scanner mostra “modo demonstração”.
- Telegram indisponível: abra diretamente `apf://continue` somente para explicar a arquitetura; não simule envio real.
- Biometria indisponível: use o fallback rotulado, explicando que a transação segue bloqueada no backend até essa etapa.
- Rede instável: use a build web local e mantenha o backend na mesma máquina.
