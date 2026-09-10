"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PagedReading } from "../reading/PagedReading";
import "./ending.css";

type EndingExperienceProps = {
  ending: Record<string, unknown> | null;
  accountId: string;
  sessionId: string;
  blocked: boolean;
  onReview: () => void;
};
type ReadingState = { dismissed: boolean; offset: number };
const memory = new Map<string, ReadingState>();
const focusSelector = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

function readState(key: string): ReadingState {
  if (memory.has(key)) return memory.get(key)!;
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    if (value && typeof value === "object") {
      return { dismissed: value.dismissed === true, offset: Number.isFinite(value.offset) ? Math.max(0, value.offset) : 0 };
    }
  } catch { /* Browsers can deny storage; the current session still remembers. */ }
  return { dismissed: false, offset: 0 };
}

function saveState(key: string, value: ReadingState) {
  memory.set(key, value);
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Use memory fallback. */ }
}

function readable(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(readable).filter(Boolean).join("\n\n");
  if (value && typeof value === "object") {
    return Object.entries(value).map(([key, item]) => `${key}：${readable(item)}`).join("\n\n");
  }
  return "";
}

function count(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : typeof value === "string" && /^\d+$/.test(value) ? value : "待核实";
}

function appendixText(value: unknown): string {
  if (Array.isArray(value)) return value.map(appendixText).filter(Boolean).join("\n\n");
  if (value && typeof value === "object") {
    const entry = value as Record<string, unknown>;
    return [readable(entry.title), readable(entry.text)].filter(Boolean).join("\n\n");
  }
  return readable(value);
}

export function EndingExperience(props: EndingExperienceProps) {
  if (!props.ending) return null;
  const identity = JSON.stringify([props.accountId, props.sessionId, props.ending.main_ending_id || props.ending.main_ending_name || "pending", props.ending.sub_ending_id || props.ending.sub_ending_title || ""]);
  return <EndingInstance key={identity} {...props} ending={props.ending} persistenceKey={`serious-game:ending:v1:${identity}`} />;
}

function EndingInstance({ ending, blocked, onReview, persistenceKey }: EndingExperienceProps & { ending: Record<string, unknown>; persistenceKey: string }) {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const [initialOffset, setInitialOffset] = useState(0);
  const state = useRef<ReadingState>({ dismissed: false, offset: 0 });
  const dialog = useRef<HTMLElement>(null);
  const titleId = useId();
  const complete = Boolean(ending.main_ending_id && ending.sub_ending_id && readable(ending.main_text));
  const appendix = appendixText(ending.appendices);
  const text = [readable(ending.main_text), readable(ending.sub_text), appendix ? `结局附记\n\n${appendix}` : ""].filter(Boolean).join("\n\n");

  useEffect(() => {
    state.current = readState(persistenceKey);
    setInitialOffset(state.current.offset);
    setReady(true);
  }, [persistenceKey]);

  useEffect(() => {
    if (ready && complete && !blocked && !state.current.dismissed) setOpen(true);
  }, [ready, complete, blocked]);

  const close = useCallback(() => {
    state.current = { ...state.current, dismissed: true };
    saveState(persistenceKey, state.current);
    setOpen(false);
  }, [persistenceKey]);

  const rememberOffset = useCallback((offset: number) => {
    state.current = { ...state.current, offset };
    saveState(persistenceKey, state.current);
  }, [persistenceKey]);

  const visible = ready && open && !blocked;
  useEffect(() => {
    if (!visible) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const root = dialog.current;
    root?.focus();
    const focusables = () => Array.from(root?.querySelectorAll<HTMLElement>(focusSelector) || []).filter(element => element.getClientRects().length > 0);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
      if (event.key !== "Tab") return;
      const elements = focusables();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first) { event.preventDefault(); root?.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === root)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !root?.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    };
    const onFocus = (event: FocusEvent) => { if (event.target instanceof Node && !root?.contains(event.target)) root?.focus(); };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("focusin", onFocus);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("focusin", onFocus);
      if (previous?.isConnected) previous.focus();
    };
  }, [visible, close]);

  return <>
    <button type="button" className="ending-open-button" disabled={blocked || !ready} onClick={() => { setInitialOffset(state.current.offset); setOpen(true); }}>查看结局</button>
    {visible && createPortal(
      <div className="ending-backdrop">
        <section className="ending-card" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={dialog}>
          <button type="button" className="ending-close" aria-label="关闭结局弹窗" onClick={close}>×</button>
          <header className="ending-card-header">
            <p className="ending-eyebrow">尘埃落定 · 此间终章</p>
            <h1 id={titleId}>{readable(ending.main_ending_name) || "结局已定"}</h1>
            {Boolean(ending.sub_ending_title) && <h2>{readable(ending.sub_ending_title)}</h2>}
            <p className="ending-metrics"><span>实际签约 <strong>{count(ending.signed_households)} / {count(ending.total_households)}</strong> 户</span><span>达标要求 <strong>{count(ending.target_signed_households)} / {count(ending.total_households)}</strong> 户</span></p>
          </header>
          <div className="ending-reading"><PagedReading text={text || "结局内容正在准备中。"} initialOffset={initialOffset} onOffsetChange={rememberOffset} /></div>
          <footer className="ending-actions">
            <button type="button" onClick={close}>关闭结局</button>
            <button type="button" className="ending-review" onClick={() => { close(); onReview(); }}>查看复盘</button>
          </footer>
        </section>
      </div>, document.body,
    )}
  </>;
}
