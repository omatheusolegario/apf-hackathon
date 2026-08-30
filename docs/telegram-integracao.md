# Telegram — integração pronta

## O que já está implementado

- Webhook com validação do segredo enviado pelo Telegram.
- Conversa e cards convertidos para uma resposta adequada ao canal.
- Botão “Continuar com segurança no app” quando existe ação financeira.
- Token de continuação de uso único, com validade de 15 minutos.
- Estado da jornada salvo no banco e recuperado no app.
- Deep link `apf://continue?token=...` configurado no Android e no iOS.
- Vínculo entre chat e cliente por código de uso único, válido por 10 minutos.
- Nenhum Pix, boleto ou investimento é confirmado pelo Telegram.

## Cinco passos para conectar o bot

1. Crie o bot no BotFather e copie token e nome de usuário.
2. Exponha o backend por HTTPS durante a demo (domínio ou túnel).
3. Copie `.env.example` para `.env` e preencha as variáveis Telegram.
4. Execute `python configure_telegram.py`.
5. Defina `TELEGRAM_ALLOW_DEMO_USER=false` antes de qualquer teste fora do palco.

## Vínculo do cliente

O app chama `POST /user/demo/telegram/link-code`. A API devolve um link no
formato `https://t.me/<bot>?start=<código>`. Ao abrir esse link, o webhook valida
e consome o código, salvando o vínculo do chat. O código não pode ser reutilizado.

## Roteiro de demonstração

1. No Telegram, envie “Pix de 150 para João”.
2. Mostre que o bot entende e prepara a jornada, mas não oferece confirmação no chat.
3. Toque em “Continuar com segurança no app”.
4. O app abre no card correto, solicita autenticação do dispositivo e só então libera o envio.
5. Mostre o comprovante e o novo saldo.

## Checklist de produção

- Trocar o usuário sintético por autenticação Itaú e identidade vinculada.
- Usar HTTPS estável e configurar Universal Links/App Links verificados.
- Guardar segredos em cofre, rotacionar token do bot e auditar acessos.
- Assinar a confirmação do dispositivo e validar atestação no backend.
- Configurar observabilidade, idempotência distribuída e fila de eventos.

