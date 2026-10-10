export type ReadingPage = { start: number; end: number; text: string };

// Offsets always refer to the original string, including paragraph separators.
export function paginateText(text: string, fits: (text: string) => boolean): ReadingPage[] {
  const paragraphs = text.match(/[^\n]+\n*|\n+/gu) || [];
  const units = paragraphs.flatMap(paragraph => fits(paragraph) ? [paragraph]
    : paragraph.match(/[^。！？!?\n]+[。！？!?]*[”’」』"]*\n*|[。！？!?\n]+/gu) || [paragraph]);
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
