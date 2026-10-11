"use client";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { paginateText, pageForOffset, type ReadingPage } from "./pagination";
import "./reading.css";

type Props = { text: string; storageKey?: string; readingKey?: string; streaming?: boolean; initialOffset?: number; onOffsetChange?: (offset: number) => void; className?: string; onNextBoundary?: () => void; onPreviousBoundary?: () => void; nextBoundaryDisabled?: boolean; previousBoundaryDisabled?: boolean; controlsExtra?: ReactNode; narrative?: boolean };
export function PagedReading({ text, storageKey, readingKey, streaming, initialOffset = 0, onOffsetChange, className = "", onNextBoundary, onPreviousBoundary, nextBoundaryDisabled, previousBoundaryDisabled, controlsExtra, narrative }: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const measure = useRef<HTMLDivElement>(null);
  const offset = useRef(initialOffset);
  const previousReading = useRef({ key: readingKey, text, streaming });
  const [pages, setPages] = useState<ReadingPage[]>([{ start: 0, end: text.length, text }]);
  const [index, setIndex] = useState(0);
  useLayoutEffect(() => {
    offset.current = initialOffset;
    if (storageKey) { try { const value = localStorage.getItem(storageKey); const saved = Number(value); if (value !== null && Number.isFinite(saved)) offset.current = Math.max(0, saved); } catch { /* Reading works without storage. */ } }
  }, [storageKey, initialOffset]);
  useLayoutEffect(() => {
    const previous = previousReading.current;
    if (readingKey !== previous.key) {
      const continuation = previous.streaming && previous.text ? text.indexOf(previous.text) : -1;
      offset.current = continuation >= 0 ? offset.current + continuation : initialOffset;
    }
    previousReading.current = { key: readingKey, text, streaming };
  }, [readingKey, text, streaming, initialOffset]);
  useLayoutEffect(() => {
    const update = () => {
      if (!viewport.current || !measure.current) return;
      const element = measure.current;
      element.style.width = `${viewport.current.clientWidth}px`;
      const height = Math.max(1, viewport.current.clientHeight);
      const next = paginateText(text, candidate => { element.textContent = candidate; return element.scrollHeight <= height; });
      element.textContent = "";
      setPages(next);
      setIndex(pageForOffset(next, offset.current));
    };
    update();
    const observer = new ResizeObserver(update);
    if (viewport.current) observer.observe(viewport.current);
    let disposed = false;
    void document.fonts.ready.then(() => { if (!disposed) update(); });
    return () => { disposed = true; observer.disconnect(); };
  }, [text, storageKey, readingKey, initialOffset]);
  const turn = (next: number) => {
    if (next < 0) { onPreviousBoundary?.(); return; }
    if (next >= pages.length) { onNextBoundary?.(); return; }
    offset.current = pages[next].start;
    setIndex(next);
    if (viewport.current) viewport.current.scrollTop = 0;
    if (storageKey) { try { localStorage.setItem(storageKey, String(offset.current)); } catch { /* Optional persistence. */ } }
    onOffsetChange?.(offset.current);
  };
  return <div className={`paged-reading ${className}`} data-reading-offset={pages[index]?.start || 0}>
    <div className="reading-viewport" ref={viewport} tabIndex={0} aria-label="分页正文"><div className="reading-text">{pages[index]?.text}</div></div>
    <div className="reading-measure reading-text" ref={measure} aria-hidden="true" />
    <nav className="reading-controls" data-tutorial-id={narrative ? "narrative-controls" : undefined} aria-label={narrative ? "剧情阅读控制" : "正文翻页"}>
      <button type="button" disabled={index === 0 && (!onPreviousBoundary || previousBoundaryDisabled)} onClick={() => turn(index - 1)}>{narrative ? "上一段" : "上一页"}</button>
      <span role="status" aria-live="polite">{index + 1} / {pages.length}</span>
      <button type="button" disabled={index === pages.length - 1 && (!onNextBoundary || nextBoundaryDisabled)} onClick={() => turn(index + 1)}>{narrative ? "下一段" : "下一页"}</button>
      {controlsExtra}
    </nav>
  </div>;
}
