# APF – Assistente Pessoal Financeiro (Itaú Inovacamp)

Protótipo: FastAPI + SQLite + Groq + Flutter.

**Versão 0.6** — agente multimodal, omnichannel e protegido no servidor.

## O que faz

- Chat WebSocket com cards interativos
- **Pix/TED real no fluxo**: multi-turno, edição, contatos recentes, segurança, recibo, saldo
- Boletos que **somem** após pagamento
- **Pix Automático** persistido (a partir do EPC)
- Investimento com débito no extrato
- EPC por agregação SQL + proatividade (`POST /user/demo/proactive/scan`)
- Suitability CVM, LGPD granular, mute de sugestões
- Referências NL: "de novo", "metade", "mesmo de ontem"
- Segurança validada no backend (não pode ser contornada pelo cliente)
- Sugestões proativas acionáveis no menu, respeitando consentimento/cooldown
- Groq assíncrono com modelo configurável e fallback automático
- Captura de boleto por câmera/galeria, com visão Groq e fallback de palco explícito
- Biometria real do dispositivo; fallback identificado quando o ambiente não oferece autenticação nativa
- Continuidade Telegram → app com token de 15 minutos e uso único
- Estado transacional persistido, inclusive entre reinícios e canais
- Vínculo Telegram seguro por código temporário gerado no app

## Como rodar

```bash
cd apf-hackathon
pip install -r requirements.txt
# GROQ_API_KEY no .env
python seed.py
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

```bash
cd flutter_app && flutter pub get && flutter run
```

Em dispositivo físico, informe o endereço do computador sem editar o código:

```bash
flutter run --dart-define=APF_API_BASE_URL=http://192.168.0.10:8000
```

O modelo padrão é `openai/gpt-oss-120b`, recomendado pela Groq para substituir
o Llama 3.3 70B. Para trocar ou configurar fallback:

```bash
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODEL=openai/gpt-oss-20b
```

Testes de regressão (sem Groq):

```bash
python test_transfers.py
python test_new_flows.py
cd flutter_app && flutter analyze && flutter test
```

## Frases úteis

| Texto | Efeito |
|-------|--------|
| pix de 150 para João | Card confirmar → envia |
| quero fazer um pix | Pede dados + chips de contatos |
| manda de novo / metade | Usa última transferência |
| que contas pagar? | Boletos abertos |
| meus padrões | EPC + Pix Automático |
| quero investir em CDB | Sugestão → aplicar debita saldo |
| menu → Sugestões proativas | EPC/boletos/saldo → ação contextual |
| ícone de scanner | Fotografa boleto → revisa → paga |
| Telegram | Inicia fora do app → confirma no app autenticado |

## Telegram pronto para integrar

Copie `.env.example` para `.env`, preencha `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET` e uma `PUBLIC_BASE_URL`
HTTPS. Depois execute:

```bash
python configure_telegram.py
```

Em produção, use `TELEGRAM_ALLOW_DEMO_USER=false`. O cliente gera o vínculo em
`POST /user/{id}/telegram/link-code` e abre o link retornado. Consulte
`docs/telegram-integracao.md` para o checklist completo.
