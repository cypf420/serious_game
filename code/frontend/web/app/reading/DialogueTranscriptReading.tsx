"use client";
import { useState } from "react";
import { PagedReading } from "./PagedReading";

type Entry = { speaker: string; speaker_type?: string; text: string; live?: boolean; complete?: boolean };

// Only presentation state lives here. The original transcript remains available
// in the scene's full-record disclosure, including document references.
export function DialogueTranscriptReading({ entries, opening }: { entries: Entry[]; opening: string }) {
  const playerTurns = entries.filter(entry => entry.speaker_type === "player").length;
  const [selection, setSelection] = useState({ index: 0, followLatest: true, offset: 0, playerTurns });
  // A new player turn resumes the live conversation after browsing history.
  // Streaming more text in the same turn must not reset the current page.
  const followLatest = selection.followLatest || selection.playerTurns !== playerTurns;
  const latestIndex = Math.max(0, entries.length - 1);
  const index = followLatest ? latestIndex : Math.min(selection.index, latestIndex);
  const select = (index: number, offset = 0) => setSelection({ index, offset, playerTurns, followLatest: index === latestIndex });
  const entry = entries[index];
  return <div className="dialogue-transcript-reading">
    <header><b>{entry?.speaker || "现场记录"}</b><small>{entries.length ? `第 ${index + 1} / ${entries.length} 条` : "会谈开始"}{entry?.live && !entry.complete ? " · 正在回应…" : ""}</small></header>
    <PagedReading key={`${playerTurns}:${index}`} text={entry?.text || opening} className="dialogue-reading" initialOffset={selection.playerTurns === playerTurns && selection.index === index ? selection.offset : 0}
      onOffsetChange={offset => select(index, offset)}
      onPreviousBoundary={index > 0 ? () => select(index - 1, Number.MAX_SAFE_INTEGER) : undefined}
      onNextBoundary={index < latestIndex ? () => select(index + 1) : undefined}
      controlsExtra={index < latestIndex ? <button type="button" onClick={() => select(latestIndex)}>最新回复</button> : undefined}
    />
  </div>;
}
