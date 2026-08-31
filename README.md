# Antefato — Assistente Pessoal Financeiro

Protótipo desenvolvido para o Itaú Inovacamp pelo grupo **Antefato**. O APF é
um agente financeiro multimodal e omnichannel que transforma consultas em
jornadas interativas, mantendo consentimento, segurança e confirmação humana
antes de qualquer ação sensível.

> Todos os dados e operações deste repositório são sintéticos e destinados à
> demonstração. Não há integração com contas bancárias reais.

## Demonstração pública

- **Aplicativo:** https://antefato-apf.pages.dev
- **API:** https://antefato-apf.onrender.com
- **Documentação da API:** https://antefato-apf.onrender.com/docs
- **Telegram:** https://t.me/Antefato_bot

O backend gratuito do Render pode levar alguns segundos para responder no
primeiro acesso após um período de inatividade.

Cada navegador recebe uma sessão sintética isolada. Assim, pagamentos e outras
ações de um avaliador não alteram a experiência dos demais. A opção
**Reiniciar demonstração**, disponível no menu, restaura boletos, transações,
conversas e limites de alertas sem remover os consentimentos escolhidos.

## Principais recursos

- Chat em tempo real com cards e ações interativas.
- Pix/TED multi-turno, edição, contatos recentes, validações de segurança e
  recibo.
- Boletos abertos que desaparecem após o pagamento e voltam ao reiniciar a
  demonstração.
- Leitura de boleto por câmera ou galeria, com extração multimodal via Groq,
  validação do arquivo e fallback de palco explicitamente identificado.
- Ditado por voz dentro do chat, com revisão antes do envio.
- Reprodução em áudio das mensagens do assistente, com controles de iniciar e
  parar e voz nativa do dispositivo.
- EPC por agregação SQL para padrões de pagamento recorrente, hábitos de gasto
  e saldo ocioso.
- Notificações proativas acionáveis, respeitando consentimento, horário,
  cooldown, limite diário e categorias silenciadas.
- Pix Automático persistido a partir de padrões detectados.
- Investimentos com suitability e reflexo no saldo e extrato sintéticos.
- LGPD granular, revogação de consentimento e explicação da origem dos dados.
- Biometria nativa quando disponível, com fallback identificado em ambientes
  sem autenticação do dispositivo.
- Continuidade entre Telegram e aplicativo por código temporário e token de uso
  único.
- Estado transacional persistido entre mensagens, reinícios e canais.

## Roteiro rápido de demonstração

1. Abra o aplicativo e escolha os consentimentos desejados.
2. Teste **“Qual meu saldo?”** e **“Que contas tenho que pagar?”**.
3. Faça um Pix, edite os dados e confirme a operação.
4. Envie uma imagem JPG, PNG ou WebP pelo ícone de scanner e revise o boleto
   extraído antes de pagar.
5. Use o microfone para ditar uma pergunta e o alto-falante para ouvir a
   resposta.
6. Abra **Padrões (EPC)** e **Sugestões proativas** no menu.
7. Use **Reiniciar demonstração** para repetir a jornada desde o início.

## Arquitetura

- **Frontend:** Flutter Web, hospedado no Cloudflare Pages.
- **Backend:** FastAPI + WebSocket, hospedado no Render.
- **Persistência pública:** PostgreSQL gerenciado.
- **Persistência local:** SQLite para desenvolvimento e testes.
- **IA generativa:** Groq, com modelo principal e fallback configuráveis.
- **Canais:** aplicativo web e bot do Telegram.

O modelo principal configurado é `openai/gpt-oss-120b`, com
`openai/gpt-oss-20b` como fallback. A leitura multimodal utiliza o modelo
definido em `GROQ_VISION_MODEL`.

## Execução local

Requisitos: Python 3.11+, Flutter compatível com Dart 3.4+ e uma chave da Groq
para os recursos generativos.

```bash
git clone https://github.com/omatheusolegario/apf-hackathon.git
cd apf-hackathon
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python seed.py
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Em outro terminal:

```bash
cd flutter_app
flutter pub get
flutter run -d chrome --dart-define=APF_API_BASE_URL=http://localhost:8000
```

Para executar em um dispositivo físico, substitua `localhost` pelo endereço do
computador na rede local:

```bash
flutter run --dart-define=APF_API_BASE_URL=http://192.168.0.10:8000
```

As variáveis disponíveis estão documentadas em `.env.example`. Nunca envie o
arquivo `.env` ou tokens reais ao repositório.

## Testes

```bash
python test_transfers.py
python test_new_flows.py
cd flutter_app
flutter analyze
flutter test
```

Para gerar o mesmo pacote usado na publicação:

```bash
flutter build web --release \
  --dart-define=APF_API_BASE_URL=https://antefato-apf.onrender.com \
  --no-wasm-dry-run
```

## Exemplos de interação

| Entrada ou ação | Resultado esperado |
|---|---|
| `Pix de 150 para João` | Revisão, segurança, confirmação e recibo |
| `Manda de novo` / `metade` | Reutiliza o contexto da última transferência |
| `Que contas tenho que pagar?` | Lista somente os boletos abertos |
| `Meus padrões` | Mostra padrões detectados pelo EPC |
| `Quero investir em CDB` | Aplica suitability antes da sugestão |
| Ícone do scanner | Fotografa ou seleciona um boleto para revisão |
| Ícone do microfone | Converte uma fala curta em texto editável |
| Ícone do alto-falante | Reproduz ou interrompe a mensagem do assistente |
| Menu → Sugestões proativas | Exibe uma ação contextual ou prévia explicada |

## Telegram

Preencha `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`,
`TELEGRAM_WEBHOOK_SECRET` e `PUBLIC_BASE_URL` no `.env`. Em seguida:

```bash
python configure_telegram.py
```

Em produção, mantenha `TELEGRAM_ALLOW_DEMO_USER=false`. O aplicativo gera o
código de vínculo em `POST /user/{id}/telegram/link-code`. O checklist completo
está em [`docs/telegram-integracao.md`](docs/telegram-integracao.md).

## Segurança e privacidade

- Ações financeiras são confirmadas e validadas no backend.
- Consentimentos são independentes por finalidade e podem ser revogados.
- Tokens de continuidade são temporários e de uso único.
- Uploads de boleto têm limite de 8 MB e validação pela assinatura real do
  arquivo.
- Ditado e síntese de voz utilizam recursos do dispositivo; não devem ser
  usados para senhas, códigos ou outras informações sensíveis.
