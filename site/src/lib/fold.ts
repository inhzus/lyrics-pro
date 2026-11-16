/** Search folding shared by the build and the browser: lowercase, then map each character through the table. */
export type FoldTable = Record<string, string>;

export const foldWith = (table: FoldTable, text: string) =>
  [...text.toLowerCase()].map((character) => table[character] ?? character).join("");
