import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';

const input = '/Users/mgolegario/bcc/itau_inovacamp/apf-hackathon/tmp/pitch-v10/template-starter.pptx';
const output = '/Users/mgolegario/bcc/itau_inovacamp/apf-hackathon/deliverables/deck-pitch-inovacamp-v10.pptx';
const qaDir = '/Users/mgolegario/bcc/itau_inovacamp/apf-hackathon/tmp/pitch-v10/final';
await fs.mkdir(qaDir, { recursive: true });
await fs.mkdir('/Users/mgolegario/bcc/itau_inovacamp/apf-hackathon/deliverables', { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(input));
const edits = new Map([
  ['Segurança validada. Débito (R$ 187,40) é R$ 23 mais barato que crédito. Confirmar?', 'Pix debita agora; crédito leva R$ 187,40 à fatura. Revise premissas. Confirmar?'],
  ['Liberado. Débito tem saldo suficiente e é mais barato. Quer usar?', 'Liberado. Pix debita agora; crédito preserva caixa e aumenta a fatura. Qual usar?'],
  ['ARROJADA — BOT EM MENSAGEIRO (TELEGRAM → WHATSAPP)', 'ARROJADA — TELEGRAM → APP SEGURO'],
  ['• Encontra o cliente onde ele já passa o dia', '• Webhook e vínculo por código de uso único'],
  ['• Protótipo em Telegram representa o padrão de WhatsApp em produção', '• Estado persiste entre canais e reinícios'],
  ['• Ação de dinheiro sempre reabre o app via deep link, com biometria', '• Deep link com token de 15 min e uso único'],
  ['• WhatsApp em produção depende de aprovação comercial da Meta', '• Confirmação financeira só no app autenticado'],
  ['Conservadora — chat no app (Flutter): pagamento respondido dentro do próprio app', 'App Flutter: câmera lê boleto; usuário revisa e confirma'],
  ['Arrojada — bot no Telegram, representando WhatsApp: o mesmo fluxo, onde o cliente já está', 'Telegram: inicia o Pix; deep link retoma o mesmo estado no app'],
  ['Comparador de pagamento em rich card, nos dois protótipos', 'Comparador: impacto em saldo, fatura e limite, com premissas visíveis'],
  ['EPC ao vivo: detecção de padrão de aluguel e sugestão de Pix Automático, com dados sintéticos representativos', 'EPC: sugestão automática, ação contextual, consentimento, mute e cooldown'],
  ['“O Itaú já tem Alerta Pix etc. para pessoa física?”', '“O que está realmente integrado no protótipo?”'],
  ['O lançamento oficial de agosto de 2025 foi para PJ. Nossa proposta leva esse padrão ao PF.', 'Imagem de boleto, proatividade, biometria e handoff Telegram→app com estado e token persistidos.'],
]);

const before = await presentation.inspect({kind:'textbox', maxChars:120000});
const records = before.ndjson.split('\n').filter(Boolean).map(line => JSON.parse(line));
for (const [original, value] of edits) {
  const record = records.find(item => item.kind === 'textbox' && item.text === original);
  if (!record) throw new Error(`Texto alvo não encontrado: ${original}`);
  const shape = presentation.resolve(record.id);
  shape.text = value;
}

async function saveBlob(path, blob) {
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

for (const [index, slide] of presentation.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, '0')}`;
  await saveBlob(`${qaDir}/${stem}.png`, await presentation.export({slide, format:'png', scale:1}));
  const layout = await slide.export({format:'layout'});
  await fs.writeFile(`${qaDir}/${stem}.layout.json`, await layout.text());
}
await saveBlob(`${qaDir}/montage.webp`, await presentation.export({format:'webp', montage:true, scale:1}));
const snapshot = await presentation.inspect({kind:'slide,textbox,shape,notes,layout', maxChars:120000});
await fs.writeFile(`${qaDir}/final-inspect.ndjson`, snapshot.ndjson);
const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(output);
