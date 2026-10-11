export type ReadingPage = { start: number; end: number; text: string };

// Offsets always refer to the original string, including paragraph separators.
export function paginateText(text: string, fits: (text: string) => boolean): ReadingPage[] {
  const paragraphs = text.match(/[^\n]+\n*|\n+/gu) || [];
  const sentences = paragraphs.flatMap(paragraph => fits(paragraph) ? [paragraph]
    : paragraph.match(/[^。！？!?\n]+[。！？!?]*[”’」』"]*\n*|[。！？!?\n]+/gu) || [paragraph]);
  // Even a sentence without punctuation must fit. Split at code point boundaries
  // so a narrow viewport never cuts a surrogate pair or loses source offsets.
  const units = sentences.flatMap(sentence => {
    if (fits(sentence)) return [sentence];
    const characters = Array.from(sentence);
    const chunks: string[] = [];
    let start = 0;
    while (start < characters.length) {
      let low = 1;
      let high = characters.length - start;
      let length = 1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        if (fits(characters.slice(start, start + middle).join(""))) { length = middle; low = middle + 1; }
        else high = middle - 1;
      }
      chunks.push(characters.slice(start, start + length).join(""));
      start += length;
    }
    return chunks;
  });
  const pages: ReadingPage[] = [];
  let start = 0;
  let chunk = "";
  for (const unit of units) {
    const candidate = chunk + unit;
    const paragraphs = candidate.trim().split(/\n+/u).length;
    if (chunk && (paragraphs > 3 || !fits(candidate))) {
      pages.push({ start, end: start + chunk.length, text: chunk });
      start += chunk.length;
      chunk = "";
    }
    chunk += unit;
  }
  if (chunk || !pages.length) pages.push({ start, end: start + chunk.length, text: chunk });
  return pages;
}

export function pageForOffset(pages: ReadingPage[], offset: number): number {
  const index = pages.findIndex(page => offset < page.end);
  return index < 0 ? Math.max(0, pages.length - 1) : index;
}
