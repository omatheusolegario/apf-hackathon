import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';

const input = '/Users/mgolegario/Downloads/deck-pitch-inovacamp-v9.pptx';
const output = '/Users/mgolegario/bcc/itau_inovacamp/apf-hackathon/tmp/pitch-v10/all-inspect.ndjson';
const presentation = await PresentationFile.importPptx(await FileBlob.load(input));
const snapshot = await presentation.inspect({
  kind: 'slide,textbox,shape,image,table,chart,notes,layout',
  include: 'id,slide,name,title,text,textPreview,textChars,textLines,bbox,isPlaceholder,placeholders',
  maxChars: 120000,
});
await fs.writeFile(output, snapshot.ndjson);
