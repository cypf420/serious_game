import { CHARACTERS } from './characters.ts';
import type { NarrativeItem } from './narrative-model.ts';

export type DialogueSegment = NarrativeItem & { sourceStart: number; sourceEnd: number; displaySceneId?: string };

// Explicit named utterances only. Never infer a speaker from a mention in prose.
export function dialogueSegments(item: NarrativeItem | null | undefined): DialogueSegment[] {
  if (!item) return [];
  const text = item.text;
  const whole = { ...item, sourceStart: 0, sourceEnd: text.length };
  if (item.presentationPhase === 'decision' || item.kind === 'decision') return [whole];
  const names = new Map(CHARACTERS.flatMap(c => [c.name, ...c.aliases].map(name => [name, c.name] as const)));
  const matches = [...text.matchAll(/(?:^|\n)([\t ]*)([^\n：「“:]{1,12})[：:][\t ]*([「“])/gu)];
  const segments: DialogueSegment[] = [];
  let start = 0;
  const append = (end: number, speaker?: string) => {
    if (end <= start) return;
    if (!speaker && !text.slice(start, end).trim() && segments.length) {
      const previous = segments[segments.length - 1];
      previous.text += text.slice(start, end); previous.sourceEnd = end; start = end;
      return;
    }
    segments.push({ ...item, id: `${item.id}:display:${start}`, text: text.slice(start, end),
      speaker, sourceStart: start, sourceEnd: end });
    start = end;
  };
  for (const match of matches) {
    const speaker = names.get(match[2]);
    if (!speaker) continue;
    const quoteStart = match.index! + match[0].length - 1;
    const opening = match[3], closing = opening === '「' ? '」' : '”';
    let depth = 1, end = quoteStart + 1;
    for (; end < text.length && depth; end++) {
      if (text[end] === opening) depth++;
      else if (text[end] === closing) depth--;
    }
    if (depth || match.index! < start) continue;
    const nameStart = match.index! + (match[0].startsWith('\n') ? 1 : 0);
    // Keep paragraph whitespace with the preceding segment, never discard it.
    append(nameStart);
    append(end, speaker);
  }
  if (!segments.length) return [whole];
  if (text.slice(start).trim()) append(text.length);
  else if (start < text.length) {
    const last = segments[segments.length - 1];
    last.text += text.slice(start); last.sourceEnd = text.length;
  }
  // These scene transitions were verified against the restored source blocks.
  const transition = item.blockId === 'd32_ledger' ? text.indexOf('下午三点，巡察组的查账人员坐进会议室。') : -1;
  const output: DialogueSegment[] = [];
  for (const segment of segments) {
    if (transition > segment.sourceStart && transition < segment.sourceEnd) {
      const cut = transition - segment.sourceStart;
      output.push({ ...segment, text: segment.text.slice(0, cut), sourceEnd: transition, displaySceneId: 'C03_S02' });
      output.push({ ...segment, id: `${item.id}:display:${transition}`, text: segment.text.slice(cut), sourceStart: transition, displaySceneId: 'C01_S06' });
    } else output.push({ ...segment, displaySceneId: item.blockId === 'd32_ledger'
      ? (transition >= 0 && segment.sourceStart >= transition ? 'C01_S06' : 'C03_S02')
      : item.blockId === 'd22_shi_arrival' || item.blockId === 'd22_reports' ? 'C01_S02' : undefined });
  }
  return output;
}
