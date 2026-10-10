"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import type { TutorialDefinition } from "./types";

type Rect = { left: number; top: number; width: number; height: number };
type Measurement = { step: number; hole: Rect | null; card: Rect; viewport: Rect; valid: boolean };
const FOCUSABLE = 'button:not(:disabled), input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex]:not([tabindex="-1"])';
const subscribe = () => () => {};
const clientSnapshot = () => true;
const serverSnapshot = () => false;

function visible(element: HTMLElement) {
  const style = getComputedStyle(element);
  return element.getClientRects().length > 0 && style.visibility !== "hidden" && style.display !== "none";
}

/** Only expose the portion actually visible through every scrolling ancestor. */
function clippedRect(element: HTMLElement, viewport: Rect): Rect | null {
  if (!visible(element)) return null;
  const rect = element.getBoundingClientRect();
  let left = Math.max(viewport.left + 5, rect.left - 6);
  let top = Math.max(viewport.top + 5, rect.top - 6);
  let right = Math.min(viewport.left + viewport.width - 5, rect.right + 6);
  let bottom = Math.min(viewport.top + viewport.height - 5, rect.bottom + 6);
  for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
    const style = getComputedStyle(ancestor);
    const bounds = ancestor.getBoundingClientRect();
    if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) {
      left = Math.max(left, bounds.left + ancestor.clientLeft);
      right = Math.min(right, bounds.left + ancestor.clientLeft + ancestor.clientWidth);
    }
    if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) {
      top = Math.max(top, bounds.top + ancestor.clientTop);
      bottom = Math.min(bottom, bounds.top + ancestor.clientTop + ancestor.clientHeight);
    }
  }
  return right > left && bottom > top ? { left, top, width: right - left, height: bottom - top } : null;
}

function validTarget(target: HTMLElement) {
  if (target.matches('[data-tutorial-valid="false"]') || target.querySelector('[data-tutorial-valid="false"]')) return false;
  const fields = [...target.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input, select, textarea")];
  if (target.matches("input, select, textarea")) fields.push(target as HTMLInputElement);
  return fields.every(field => field.disabled || !visible(field) || field.validity.valid);
}

function placeCard(hole: Rect | null, viewport: Rect, height: number): Rect {
  const margin = 14;
  const width = Math.min(360, viewport.width - margin * 2);
  height = Math.min(height, viewport.height - margin * 2);
  const minX = viewport.left + margin;
  const minY = viewport.top + margin;
  const maxX = viewport.left + viewport.width - width - margin;
  const maxY = viewport.top + viewport.height - height - margin;
  if (!hole || viewport.width <= 780) return { left: minX + (maxX - minX) / 2, top: maxY, width, height };
  let left = hole.left + hole.width + 18;
  let top = hole.top;
  if (left > maxX) left = hole.left - width - 18;
  if (left < minX) {
    left = hole.left + (hole.width - width) / 2;
    top = hole.top + hole.height + 18;
    if (top > maxY) top = hole.top - height - 18;
  }
  return { left: Math.max(minX, Math.min(maxX, left)), top: Math.max(minY, Math.min(maxY, top)), width, height };
}

export default function TutorialOverlay({ definition, initialStep = 0, onStep, onClose, onComplete, onPause }: {
  definition: TutorialDefinition;
  initialStep?: number;
  onStep: (step: number) => void;
  onClose: () => void;
  onComplete: () => void;
  onPause: () => void;
}) {
  const mounted = useSyncExternalStore(subscribe, clientSnapshot, serverSnapshot);
  const [index, setIndex] = useState(() => Math.max(0, Math.min(initialStep, definition.steps.length - 1)));
  const [retry, setRetry] = useState(0);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<HTMLElement | null>(null);
  const finishRef = useRef(false);
  const callbacks = useRef({ onClose, onComplete, onPause, onStep });
  const step = definition.steps[index];
  const labelId = useId();
  const bodyId = useId();
  const maskId = useId().replaceAll(":", "");
  const current = measurement?.step === index ? measurement : null;
  const hole = current?.hole ?? null;
  const hasHole = Boolean(hole);

  useEffect(() => { callbacks.current = { onClose, onComplete, onPause, onStep }; }, [onClose, onComplete, onPause, onStep]);

  useEffect(() => {
    if (!mounted) return;
    const priorFocus = document.activeElement as HTMLElement | null;
    const initialDialogs = new Set(Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"], .modal'))
      .filter(element => visible(element) && !element.closest("[data-tutorial-overlay]")));
    return () => {
      requestAnimationFrame(() => {
        // A higher-priority business dialog can suspend this tutorial. Its own
        // focus setup takes precedence over restoring the old tutorial trigger.
        const activeDialog = document.activeElement?.closest('[role="dialog"], .modal');
        if (activeDialog && !activeDialog.closest("[data-tutorial-overlay]")
            && !initialDialogs.has(activeDialog as HTMLElement)) return;
        const finish = finishRef.current && definition.finishFocusTarget
          ? document.querySelector<HTMLElement>(definition.finishFocusTarget) : null;
        const next = finish || priorFocus;
        if (next?.isConnected) {
          const addedTabIndex = !next.matches(FOCUSABLE) && !next.hasAttribute("tabindex");
          if (addedTabIndex) next.setAttribute("tabindex", "-1");
          next.focus({ preventScroll: true });
          if (addedTabIndex) next.addEventListener("blur", () => next.removeAttribute("tabindex"), { once: true });
        }
      });
    };
  }, [mounted, definition.finishFocusTarget]);

  useEffect(() => {
    if (!mounted || !step) return;
    let frame = 0;
    let didScroll = false;
    let didFocus = false;
    let lastRevealAttempt = "";
    let lastAvoidanceAttempt = "";
    let observedTarget: HTMLElement | null = null;
    let observedAncestors: HTMLElement[] = [];
    let reservedHost: HTMLElement | null = null;
    let restoreReserve: (() => void) | null = null;
    const measure = () => {
      frame = 0;
      const viewport = {
        left: window.visualViewport?.offsetLeft ?? 0,
        top: window.visualViewport?.offsetTop ?? 0,
        width: window.visualViewport?.width ?? window.innerWidth,
        height: window.visualViewport?.height ?? window.innerHeight,
      };
      const target = document.querySelector<HTMLElement>(step.target);
      targetRef.current = target;
      // Optional controls may be revealed by the preceding real form input.
      // Only skip once the actual form is mounted, and never infer completion.
      const formReady = document.querySelector<HTMLElement>('[data-tutorial-id="form-submit"]');
      if (step.optional && (!target || !visible(target)) && formReady && visible(formReady) && index < definition.steps.length - 1) {
        setIndex(index + 1);
        callbacks.current.onStep(index + 1);
        return;
      }
      if (target !== observedTarget) {
        if (observedTarget) resize.unobserve(observedTarget);
        observedAncestors.forEach(ancestor => resize.unobserve(ancestor));
        observedAncestors = [];
        if (target) resize.observe(target);
        for (let ancestor = target?.parentElement; ancestor; ancestor = ancestor.parentElement) {
          observedAncestors.push(ancestor);
          resize.observe(ancestor);
        }
        observedTarget = target;
      }
      const height = cardRef.current?.getBoundingClientRect().height || 310;
      // Every mobile spotlight needs real scroll range, including passive action
      // cards. Otherwise its target can remain entirely beneath the bottom card.
      const mobileHost = viewport.width <= 780
        ? observedAncestors.find(ancestor => /(auto|scroll)/.test(getComputedStyle(ancestor).overflowY)) || null
        : null;
      if (mobileHost !== reservedHost) {
        restoreReserve?.();
        restoreReserve = null;
        reservedHost = mobileHost;
        if (mobileHost) {
          const priorAttribute = mobileHost.getAttribute("data-tutorial-scroll-host");
          const properties = ["--tutorial-scroll-base", "--tutorial-scroll-reserve"];
          const priorProperties = properties.map(name => [name, mobileHost.style.getPropertyValue(name), mobileHost.style.getPropertyPriority(name)]);
          mobileHost.style.setProperty("--tutorial-scroll-base", getComputedStyle(mobileHost).paddingBottom);
          mobileHost.setAttribute("data-tutorial-scroll-host", "true");
          restoreReserve = () => {
            if (priorAttribute === null) mobileHost.removeAttribute("data-tutorial-scroll-host");
            else mobileHost.setAttribute("data-tutorial-scroll-host", priorAttribute);
            priorProperties.forEach(([name, value, priority]) => {
              if (value) mobileHost.style.setProperty(name, value, priority);
              else mobileHost.style.removeProperty(name);
            });
          };
        }
      }
      const reserve = `${Math.ceil(height + 32)}px`;
      if (reservedHost && reservedHost.style.getPropertyValue("--tutorial-scroll-reserve") !== reserve) {
        reservedHost.style.setProperty("--tutorial-scroll-reserve", reserve);
      }
      if (target && visible(target) && !didScroll) {
        didScroll = true;
        target.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
      }
      const geometryKey = () => target ? JSON.stringify([
        target.getBoundingClientRect().toJSON(), viewport,
        observedAncestors.map(ancestor => [ancestor.scrollTop, ancestor.scrollLeft, ancestor.scrollHeight, ancestor.clientHeight]),
      ]) : "";
      let nextHole = target ? clippedRect(target, viewport) : null;
      // A real input can insert earlier form fields and move this target outside
      // its scroller. Retry once for each changed geometry, not on every frame.
      if (target && visible(target) && !nextHole && geometryKey() !== lastRevealAttempt) {
        target.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
        lastRevealAttempt = geometryKey();
        nextHole = clippedRect(target, viewport);
      }
      if (nextHole) lastRevealAttempt = "";
      let card = placeCard(nextHole, viewport, height);
      // On narrow screens reserve space above the card for a field inside its own scroller.
      // Card expansion and form layout changes both require a fresh calculation.
      const avoidanceKey = () => `${geometryKey()}:${card.top}:${height}`;
      if (target && nextHole && viewport.width <= 780 && avoidanceKey() !== lastAvoidanceAttempt && nextHole.top + nextHole.height > card.top - 12) {
        for (let ancestor = target.parentElement; ancestor; ancestor = ancestor.parentElement) {
          const isPageScroller = ancestor === document.scrollingElement;
          if ((isPageScroller || /(auto|scroll)/.test(getComputedStyle(ancestor).overflowY)) && ancestor.scrollHeight > ancestor.clientHeight) {
            const stickyBottom = isPageScroller ? Math.max(viewport.top + 20, ...Array.from(document.querySelectorAll<HTMLElement>(".topbar, .rail"))
              .filter(element => getComputedStyle(element).position === "sticky")
              .map(element => element.getBoundingClientRect().bottom + 10)) : viewport.top + 20;
            const upperEdge = Math.max(stickyBottom, ancestor.getBoundingClientRect().top + ancestor.clientTop + 10);
            const delta = Math.max(0, Math.min(nextHole.top - upperEdge, nextHole.top + nextHole.height - card.top + 12));
            ancestor.scrollTop += delta;
            nextHole = clippedRect(target, viewport);
            card = placeCard(nextHole, viewport, height);
            break;
          }
        }
        lastAvoidanceAttempt = avoidanceKey();
      }
      const next: Measurement = { step: index, hole: nextHole, viewport, card, valid: !step.interactive || Boolean(target && validTarget(target)) };
      setMeasurement(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
      if (!didFocus && cardRef.current) {
        didFocus = true;
        cardRef.current.focus({ preventScroll: true });
      }
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    const resize = new ResizeObserver(schedule);
    if (cardRef.current) resize.observe(cardRef.current);
    const mutation = new MutationObserver(records => {
      if (records.some(record => {
        const element = record.target instanceof Element ? record.target : record.target.parentElement;
        return !element?.closest("[data-tutorial-overlay]");
      })) schedule();
    });
    mutation.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-tutorial-valid", "disabled", "hidden", "class", "style", "required", "min", "max", "aria-invalid"] });
    document.addEventListener("scroll", schedule, true);
    document.addEventListener("input", schedule, true);
    document.addEventListener("change", schedule, true);
    window.addEventListener("resize", schedule);
    window.visualViewport?.addEventListener("resize", schedule);
    window.visualViewport?.addEventListener("scroll", schedule);
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutation.disconnect();
      restoreReserve?.();
      document.removeEventListener("scroll", schedule, true);
      document.removeEventListener("input", schedule, true);
      document.removeEventListener("change", schedule, true);
      window.removeEventListener("resize", schedule);
      window.visualViewport?.removeEventListener("resize", schedule);
      window.visualViewport?.removeEventListener("scroll", schedule);
    };
  }, [mounted, step, index, retry, definition.steps.length]);

  useEffect(() => {
    if (!mounted || !hasHole) return;
    const allowed = (node: EventTarget | null) => node instanceof Node && (
      cardRef.current?.contains(node) || Boolean(step?.interactive && targetRef.current?.contains(node))
    );
    const stop = (event: Event) => { event.preventDefault(); event.stopImmediatePropagation(); };
    const pointer = (event: Event) => { if (!allowed(event.target)) stop(event); };
    const submit = (event: Event) => { if (!cardRef.current?.contains(event.target as Node)) stop(event); };
    const focus = (event: FocusEvent) => { if (!allowed(event.target)) cardRef.current?.focus({ preventScroll: true }); };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { stop(event); callbacks.current.onClose(); return; }
      if (event.key === "Tab") {
        const controls = [
          ...(step?.interactive && targetRef.current ? [targetRef.current, ...targetRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)] : []),
          ...(cardRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) || []),
        ].filter(element => element.matches(FOCUSABLE) && visible(element) && !element.closest("[inert]"));
        stop(event);
        const position = controls.indexOf(document.activeElement as HTMLElement);
        const next = event.shiftKey ? (position <= 0 ? controls.length - 1 : position - 1) : (position + 1) % controls.length;
        const nextControl = controls[next] || cardRef.current;
        nextControl?.focus({ preventScroll: true });
        if (nextControl && targetRef.current?.contains(nextControl)) {
          nextControl.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
        }
        return;
      }
      if (!allowed(event.target)) { stop(event); return; }
      if (event.key === "Enter" && !cardRef.current?.contains(event.target as Node)
          && event.target instanceof HTMLElement && event.target.closest("form")) stop(event);
    };
    const pointerEvents = ["pointerdown", "mousedown", "click", "dblclick", "contextmenu"];
    pointerEvents.forEach(name => document.addEventListener(name, pointer, true));
    document.addEventListener("submit", submit, true);
    document.addEventListener("keydown", key, true);
    document.addEventListener("focusin", focus, true);
    return () => {
      pointerEvents.forEach(name => document.removeEventListener(name, pointer, true));
      document.removeEventListener("submit", submit, true);
      document.removeEventListener("keydown", key, true);
      document.removeEventListener("focusin", focus, true);
    };
  }, [mounted, hasHole, step]);

  const move = (next: number) => {
    const direction = next < index ? -1 : 1;
    const formReady = document.querySelector<HTMLElement>('[data-tutorial-id="form-submit"]');
    if (formReady && visible(formReady)) {
      while (definition.steps[next]?.optional) {
        const target = document.querySelector<HTMLElement>(definition.steps[next].target);
        if (target && visible(target)) break;
        const candidate = next + direction;
        if (candidate < 0 || candidate >= definition.steps.length) return;
        next = candidate;
      }
    }
    setIndex(next); onStep(next);
  };
  const next = () => {
    // Recheck the actual field state at activation, before a MutationObserver update.
    if (!hole || !targetRef.current || (step?.interactive && !validTarget(targetRef.current))) return;
    if (index < definition.steps.length - 1) move(index + 1);
    else { finishRef.current = true; callbacks.current.onComplete(); }
  };
  if (!mounted) return null;
  const cardStyle = current ? { left: current.card.left, top: current.card.top, right: "auto", bottom: "auto", width: current.card.width, maxHeight: current.viewport.width <= 780 ? Math.min(current.viewport.height - 28, current.viewport.height * .55) : current.viewport.height - 28 } : undefined;
  return createPortal(<div className={`tutorial-overlay${hole ? "" : " tutorial-is-paused"}`} data-tutorial-overlay="true">
    {hole && current && <>
      <svg className="tutorial-mask" aria-hidden="true" width="100%" height="100%">
        <defs><mask id={maskId}><rect width="100%" height="100%" fill="white" /><rect width={hole.width} height={hole.height} x={hole.left} y={hole.top} rx="8" fill="black" /></mask></defs>
        <rect width="100%" height="100%" fill="rgba(17, 14, 10, .76)" mask={`url(#${maskId})`} />
        <rect x={hole.left} y={hole.top} width={hole.width} height={hole.height} rx="8" fill="none" stroke="#e3c985" strokeWidth="2" />
      </svg>
      {step?.interactive ? <>
        <div className="tutorial-blocker" style={{ top: 0, left: 0, right: 0, height: hole.top }} />
        <div className="tutorial-blocker" style={{ top: hole.top + hole.height, left: 0, right: 0, bottom: 0 }} />
        <div className="tutorial-blocker" style={{ top: hole.top, left: 0, width: hole.left, height: hole.height }} />
        <div className="tutorial-blocker" style={{ top: hole.top, left: hole.left + hole.width, right: 0, height: hole.height }} />
      </> : <div className="tutorial-blocker" style={{ inset: 0 }} />}
    </>}
    <div ref={cardRef} className="tutorial-popover" style={cardStyle} role="dialog" aria-modal={hole && !step?.interactive ? true : undefined} aria-labelledby={labelId} aria-describedby={bodyId} tabIndex={-1}
      onKeyDown={event => { if (!hole && event.key === "Escape") onClose(); }}>
      <header><span className="tutorial-eyebrow">赴任指南 · {definition.title}</span><button type="button" className="tutorial-close" aria-label="关闭教程" onClick={onClose}>×</button></header>
      {hole && step ? <>
        <div className="tutorial-step-count" aria-live="polite">第 {index + 1} / {definition.steps.length} 步</div>
        <h2 id={labelId}>{step.title}</h2>
        <p id={bodyId}>{step.body}</p>
        {step.detail && <details key={step.id}><summary>展开说明</summary><p>{step.detail}</p></details>}
        {step.interactive && <p className="tutorial-field-hint" role="status">{current?.valid ? "可在高亮区域填写，完成后继续。" : "请先完成高亮区域的有效填写，再继续。"}</p>}
        <div className="tutorial-dots" aria-hidden="true">{definition.steps.map((item, position) => <i key={item.id} className={position === index ? "active" : position < index ? "done" : ""} />)}</div>
        <div className="tutorial-controls"><button type="button" disabled={index === 0} onClick={() => move(index - 1)}>上一步</button><button type="button" className="tutorial-primary" disabled={!current?.valid} onClick={next}>{index === definition.steps.length - 1 ? definition.finishLabel || "完成本节" : "下一步"}</button></div>
        <div className="tutorial-secondary"><button type="button" onClick={onClose}>跳过本节</button><button type="button" onClick={onPause}>暂停，稍后继续</button></div>
      </> : <>
        <h2 id={labelId}>教程已暂停</h2>
        <p id={bodyId} role="status">当前步骤的区域暂不可见。返回对应页面后重试，进度会保留。</p>
        <div className="tutorial-controls"><button type="button" onClick={onClose}>关闭本节</button><button type="button" className="tutorial-primary" onClick={() => setRetry(value => value + 1)}>重试</button></div>
      </>}
    </div>
  </div>, document.body);
}
