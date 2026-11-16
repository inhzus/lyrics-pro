// Mirrors HEADER, NAMED_CREDIT_HEADER, NOTE and COLUMNS in scripts/prepare_proofread.py.
const HEADER = /^(?:作[詞词曲]\s*[:：]|(?:詞曲|词曲|[詞词曲])\s*[:：]|(?:台羅|台語|客語)拼音\s*[:：])/;
const NAMED_CREDIT_HEADER = /^作詞\s+[^：]+\s*：\s*作曲\s+[^：]+\s*：\s*台語拼音\s*：.+$/;
const NOTE = /^(?:Note\s*:|註\s*[:：]|注\s*[:：]|備註\s*[:：])/i;
const COLUMNS = /[\t　 ]{2,}/;
// Same ranges as lyrics_pro.pronunciation.HAN.
const HAN = /[㐀-䶿一-鿿豈-﫿\u{20000}-\u{323af}]/u;
const SPACES = /\s+/g;

export type Part = { text: string; spelling: string };
export type Item =
  | { kind: "pair"; text: string; spelling: string; parts?: Part[] }
  | { kind: "note"; text: string }
  | { kind: "line"; text: string }
  | { kind: "break"; blanks: number };

const isCredit = (line: string) => HEADER.test(line) || NAMED_CREDIT_HEADER.test(line);
const display = (value: string) => value.replace(SPACES, " ");

function pair(text: string, spelling: string): Item {
  const words = text.split(COLUMNS);
  const readings = spelling.split(COLUMNS);
  const item: Item = { kind: "pair", text: display(text), spelling: display(spelling) };
  if (words.length > 1 && words.length === readings.length && [...words, ...readings].every(Boolean)) {
    item.parts = words.map((word, index) => ({ text: display(word), spelling: display(readings[index]) }));
  }
  return item;
}

/** Split a transcription into credits and body items; every nonempty line is kept once, in order. */
export function classify(source: string): { credits: string[]; items: Item[] } {
  const lines = source.split(/\r?\n/).map((line) => line.trim());
  const credits: string[] = [];
  const items: Item[] = [];
  let blanks = 0;
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (!line) {
      blanks++;
      continue;
    }
    if (items.length && blanks) items.push({ kind: "break", blanks });
    blanks = 0;
    if (isCredit(line)) {
      credits.push(display(line));
      continue;
    }
    if (NOTE.test(line)) {
      items.push({ kind: "note", text: display(line) });
      continue;
    }
    let following = index + 1;
    while (following < lines.length && !lines[following]) following++;
    const spelling = lines[following];
    if (HAN.test(line) && spelling && !HAN.test(spelling) && !isCredit(spelling) && !NOTE.test(spelling)) {
      items.push(pair(line, spelling));
      index = following;
      continue;
    }
    items.push({ kind: "line", text: display(line) });
  }
  return { credits, items };
}
