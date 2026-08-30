# Execução e testes da branch `develop`

Este documento descreve como preparar, executar e validar a versão em desenvolvimento do APF.

## 1. Obter a branch

```bash
git fetch origin
git switch develop
git pull origin develop
```

Confirme que a branch e a árvore de trabalho estão corretas:

```bash
git status
```

## 2. Configurar o backend

O projeto requer Python 3.11 ou superior. No Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

No Linux ou macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Crie o arquivo `.env` na raiz. Ele não deve ser enviado ao Git.

```env
GROQ_API_KEY=sua_chave
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODEL=openai/gpt-oss-20b
DATABASE_URL=sqlite+aiosqlite:///./apf.db
```

Sem `GROQ_API_KEY`, os fluxos determinísticos continuam funcionando, mas a resposta conversacional fica limitada.

Para criar ou restaurar os dados demonstrativos:

```bash
python seed.py
```

O comando recria as transações do usuário `demo`. Não o execute quando precisar preservar o banco local.

Inicie a API:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Endereços úteis:

- API: `http://localhost:8000`
- documentação: `http://localhost:8000/docs`
- saúde do serviço: `http://localhost:8000/health`
- WebSocket: `ws://localhost:8000/ws`

## 3. Configurar o Flutter

Em outro terminal:

```bash
cd flutter_app
flutter pub get
flutter analyze
flutter test
```

Para Windows, macOS, Linux ou navegador no mesmo computador:

```bash
flutter run
```

Para Android Emulator:

```bash
flutter run --dart-define=APF_API_BASE_URL=http://10.0.2.2:8000
```

Para aparelho físico, use o IPv4 do computador:

```bash
flutter run --dart-define=APF_API_BASE_URL=http://192.168.0.10:8000
```

O aparelho e o computador devem estar na mesma rede. A porta `8000` precisa estar liberada no firewall.

## 4. Testes automatizados

Na raiz, com o ambiente Python ativado:

```bash
python test_transfers.py
python test_new_flows.py
```

As regressões cobrem:

- classificação e preenchimento de Pix em múltiplas etapas;
- proteção contra alteração de valor ou favorecido pelo cliente;
- verificação de saldo e comprovantes;
- pagamento idempotente de boletos;
- Pix Automático e preferências de notificação;
- continuidade entre Telegram e aplicativo;
- leitura de boleto com fallback sem Groq Vision;
- preservação de Markdown e remoção de emojis;
- valor explícito de investimento;
- aplicação do restante do saldo;
- ausência do antigo fallback fixo de R$ 800;
- cálculo com reserva financeira configurável.

Antes de abrir pull request, execute:

```bash
python test_transfers.py
python test_new_flows.py
cd flutter_app
flutter analyze
flutter test
```

## 5. Novas funcionalidades da `develop`

### Respostas formatadas

O agente agora pode responder com:

- parágrafos curtos;
- listas;
- negrito;
- itálico;
- títulos quando realmente houver seções distintas.

Emojis, emoticons e pictogramas decorativos são proibidos pelo prompt e removidos pelo backend caso o modelo os produza.

### Investimento com valor solicitado

Um número informado pelo usuário é tratado como valor da aplicação.

Exemplo:

```text
guardo 2000 no cdb
```

O card deve preparar exatamente R$ 2.000,00, em vez de deixar R$ 2.000,00 na conta e aplicar o restante.

### Restante do saldo

Frases como `guardar o restante do saldo` são classificadas como investimento e preparam o saldo disponível inteiro. A revisão mostra claramente que o saldo posterior será zero.

### Reserva financeira configurável

A tela `Privacidade / LGPD` possui o campo `Reserva que desejo manter disponível`. Esse valor fica persistido no backend e é usado somente em sugestões sem valor explícito.

Se o usuário não informar uma quantia:

```text
valor sugerido = saldo disponível - reserva configurada
```

Quando não existe excedente, o sistema não oferece uma aplicação automática.

### Confirmação de investimento

O card permite:

- editar o valor;
- revisar saldo atual, valor, saldo posterior e reserva;
- identificar se o valor foi solicitado ou sugerido;
- cancelar sem movimentar dinheiro;
- autenticar no dispositivo antes da confirmação;
- receber um alerta quando a conta ficará com saldo zero.

### Conexão e histórico

- operações e mensagens ficam bloqueadas durante desconexão;
- uma mensagem não é adicionada ao histórico se não tiver sido enviada;
- o aplicativo informa quando a conexão volta;
- cards podem ser recolhidos para reduzir a altura da conversa;
- mensagens mostram horário e status;
- textos possuem rótulos semânticos e contraste melhorado.

## 6. Correções realizadas

### Valor de investimento invertido

Antes, o backend calculava sempre `saldo - 2000`. Assim, `guardo 2000 no cdb` mantinha R$ 2.000,00 na conta e aplicava todo o excedente. Agora pedidos explícitos prevalecem sobre sugestões automáticas.

### Sugestão indevida de R$ 800

Antes, quando o excedente era zero ou muito baixo, o sistema forçava R$ 800,00. Esse fallback foi removido. Sem excedente, não existe botão de aplicação até o usuário informar um valor.

### Linguagem ambígua

O texto agora diferencia `valor solicitado por você` de `valor sugerido pelo assistente`. Termos internos como `gate de suitability` foram substituídos por linguagem compreensível ao usuário.

### Compatibilidade com Python 3.13

`python-Levenshtein` é apenas uma aceleração opcional. A versão fixada não possui pacote pronto para Python 3.13, portanto ela é instalada somente em versões anteriores. Em Python 3.13, o `fuzzywuzzy` usa a implementação Python sem alterar o resultado funcional.

### Console Windows e Telegram

Emojis remanescentes nos logs causavam `UnicodeEncodeError` em consoles Windows CP1252. Eles foram removidos dos logs do backend e das mensagens montadas para o Telegram.

## 7. Roteiro manual de validação

Execute estes cenários em ordem, restaurando o banco com `python seed.py` quando precisar de um saldo conhecido.

### Cenário A: valor explícito

1. Envie `guardo 2000 no cdb`.
2. Confirme que o card mostra `Valor solicitado por você`.
3. Confirme que o campo possui R$ 2.000,00.
4. Toque em `Revisar aplicação`.
5. Verifique o saldo posterior.
6. Edite, cancele ou confirme com autenticação.

### Cenário B: saldo inteiro

1. Envie `guardar o restante do saldo`.
2. Verifique o aviso de que o saldo ficará zerado.
3. Cancele e confirme que nenhuma movimentação foi realizada.

### Cenário C: reserva personalizada

1. Abra `Privacidade / LGPD`.
2. Altere a reserva para R$ 3.500,00 e salve.
3. Envie `quero investir em CDB` sem informar valor.
4. Confirme que a sugestão corresponde ao saldo menos R$ 3.500,00.

### Cenário D: sem excedente

1. Configure uma reserva igual ou superior ao saldo.
2. Envie `quero investir em CDB`.
3. Confirme que nenhum valor de R$ 800,00 é criado e que não existe botão de aplicação.

### Cenário E: perda de conexão

1. Pare o backend.
2. Confirme que o aviso offline aparece.
3. Tente enviar uma mensagem e confirme que ela não entra no histórico.
4. Reinicie o backend e aguarde a confirmação de reconexão.

## 8. Commits principais

```text
68a9c1c feat: support formatted agent responses
24fb086 fix: honor requested investment amounts
84fb989 feat: add configurable investment reserve
64477ea feat: improve financial action usability
dfd761d fix: clarify investment confirmation flow
```

