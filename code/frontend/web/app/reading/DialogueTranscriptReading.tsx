"use client";
import { useState } from "react";
import { PagedReading } from "./PagedReading";

type Entry = { speaker: string; text: string; live?: boolean; complete?: boolean };

// Only presentation state lives here. The original transcript remains available
// in the scene's full-record disclosure, including document references.
export function DialogueTranscriptReading({ entries, opening }: { entries: Entry[]; opening: string }) {
  const [selection, setSelection] = useState({ index: 0, followLatest: true, offset: 0 });
  const index = selection.followLatest ? Math.max(0, entries.length - 1) : Math.min(selection.index, Math.max(0, entries.length - 1));
  const entry = entries[index];
  return <div className="dialogue-transcript-reading">
    <header><b>{entry?.speaker || "现场记录"}</b><small>{entries.length ? `第 ${index + 1} / ${entries.length} 条` : "会谈开始"}{entry?.live && !entry.complete ? " · 正在回应…" : ""}</small></header>
    <PagedReading key={index} text={entry?.text || opening} className="dialogue-reading" initialOffset={selection.offset}
      onOffsetChange={() => setSelection(current => ({ ...current, index, followLatest: false }))}
      onPreviousBoundary={index > 0 ? () => setSelection({ index: index - 1, followLatest: false, offset: Number.MAX_SAFE_INTEGER }) : undefined}
      onNextBoundary={index < entries.length - 1 ? () => setSelection({ index: index + 1, followLatest: false, offset: 0 }) : undefined}
      controlsExtra={index < entries.length - 1 ? <button type="button" onClick={() => setSelection({ index: entries.length - 1, followLatest: true, offset: 0 })}>最新回复</button> : undefined}
    />
  </div>;
}
