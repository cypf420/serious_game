"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { BASIC_TUTORIAL, actionTutorial, actionTour, formTutorial, sceneTutorial } from "./definitions";
import { loadProgress, markChapter, saveProgress, shouldAutoShow } from "./progress";
import TutorialOverlay from "./TutorialOverlay";
import type { TutorialContext, TutorialDefinition, TutorialRecord } from "./types";
import "./tutorial.css";

type TutorialControls = {
  openDirectory: () => void;
  start: (definition: TutorialDefinition) => void;
  context: TutorialContext;
  canAuto: (definition: TutorialDefinition) => boolean;
  dismiss: (definition: TutorialDefinition) => void;
};
const Controls = createContext<TutorialControls | null>(null);

function visibleTarget(selector: string) {
  const element = document.querySelector<HTMLElement>(selector);
  return Boolean(element?.getClientRects().length);
}

// This component is keyed by account and session by GameShell. Transient targets
// and pending invitations can never cross an account or save boundary.
export function TutorialProvider({ context, onNavigate, children }: {
  context: TutorialContext;
  onNavigate: (panel: string) => Promise<void>;
  children: ReactNode;
}) {
  const [progress, setProgress] = useState(() => loadProgress(context.accountId));
  const [active, setActive] = useState<{ definition: TutorialDefinition; step: number; panel: string; formId: string; scene: string | null } | null>(null);
  const [directory, setDirectory] = useState(false);
  const [pendingChapter, setPendingChapter] = useState<string | null>(null);
  const [publicActions, setPublicActions] = useState<TutorialRecord[]>([]);
  const [sceneHistory, setSceneHistory] = useState<string[]>([]);
  const formId = String(context.form?.variant_id || "");
  const sceneModal = ["archive-result", "contract", "document"].includes(context.scene || "");
  const formKey = context.form ? `${context.sessionId}:${formId}` : "";
  const attemptedForm = useRef("");
  const directoryRef = useRef<HTMLDivElement>(null);
  const update = (next: typeof progress) => { setProgress(next); saveProgress(context.accountId, next); };
  const dismiss = (definition: TutorialDefinition) => {
    let next = markChapter(progress, definition, "seen", 0);
    if (definition.id === "actions") {
      for (const family of context.actions) {
        const variants = Array.isArray(family.variants) ? (family.variants as TutorialRecord[]).map(variant => ({ ...family, ...variant })) : [family];
        for (const item of variants.filter(variant => variant.available === true)) next = markChapter(next, actionTutorial(item), "seen", 0);
      }
    }
    update(next);
  };
  const canAuto = (definition: TutorialDefinition) => Boolean(context.sessionId && !context.readOnly && !context.blocked && shouldAutoShow(progress, definition));

  useEffect(() => {
    if (!context.actions.length) return;
    // Remember only descriptors actually returned for this save, never the static catalog.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPublicActions(context.actions);
  }, [context.actions]);
  useEffect(() => {
    if (!context.scene || context.readOnly) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSceneHistory(previous => previous.includes(context.scene!) ? previous : [...previous, context.scene!]);
  }, [context.scene, context.readOnly]);

  const start = (definition: TutorialDefinition, step = 0) => {
    if (context.blocked || context.readOnly) return;
    if (sceneModal && definition.id !== `scene:${context.scene}`) return;
    const steps = definition.steps;
    if (!steps.length) return;
    const readyDefinition = { ...definition, steps };
    update(markChapter(progress, definition, "seen", step));
    setDirectory(false);
    setActive({ definition: readyDefinition, step: Math.min(step, steps.length - 1), panel: context.panel, formId, scene: context.scene });
  };

  useEffect(() => {
    if (!pendingChapter || context.blocked || context.panel !== "actions") return;
    const flat = context.actions.flatMap(family => Array.isArray(family.variants)
      ? (family.variants as TutorialRecord[]).map(variant => ({ ...family, ...variant })) : [family]);
    const item = flat.find(value => `action:${String(value.variant_id)}` === pendingChapter);
    // Re-resolve from the new response; the cached descriptor may no longer be available.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPendingChapter(null);
    if (item) start(actionTutorial(item));
    else setDirectory(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingChapter, context.blocked, context.panel, context.actions]);

  useEffect(() => {
    if (!formKey) { attemptedForm.current = ""; return; }
    if (context.blocked || context.readOnly || active || directory || attemptedForm.current === formKey) return;
    const definition = formTutorial(context.form!);
    if (!shouldAutoShow(progress, definition)) { attemptedForm.current = formKey; return; }
    // Form data arrives asynchronously. Observe the mounted form, not a fixed delay.
    const attempt = () => {
      if (!visibleTarget('[data-tutorial-id="form-submit"]')) return;
      attemptedForm.current = formKey;
      start(definition);
      observer.disconnect();
    };
    const observer = new MutationObserver(attempt);
    observer.observe(document.body, { childList: true, subtree: true });
    attempt();
    return () => observer.disconnect();
    // start reads the current progress and context; rerun when these inputs change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formKey, context.blocked, context.readOnly, context.form, active, directory, progress]);

  const applicable = active && !context.blocked && !context.readOnly
    && (!sceneModal || active.definition.id === `scene:${context.scene}`)
    && active.panel === context.panel
    && active.formId === formId
    && (active.definition.id === BASIC_TUTORIAL.id || !active.definition.id.startsWith("scene:") || active.scene === context.scene);

  const close = (completed = false) => {
    if (!active) return;
    const next = markChapter(progress, active.definition, completed ? "completed" : "seen", active.step);
    if (active.definition.id === "actions") {
      const flat = publicActions.flatMap(family => Array.isArray(family.variants)
        ? (family.variants as TutorialRecord[]).map(variant => ({ ...family, ...variant })) : [family]);
      for (const item of flat.filter(value => value.available === true)) {
        const definition = actionTutorial(item);
        if (completed || active.definition.steps.slice(0, active.step + 1).some(step => definition.steps[0]?.target === step.target)) {
          Object.assign(next.chapters, markChapter(next, definition, completed ? "completed" : "seen", 0).chapters);
        }
      }
    }
    next.paused = completed ? undefined : { id: active.definition.id, step: active.step };
    update(next); setActive(null);
  };
  const stepChanged = (step: number) => {
    if (!active || active.step === step) return;
    setActive({ ...active, step });
    const next = markChapter(progress, active.definition, "seen", step);
    next.paused = { id: active.definition.id, step };
    update(next);
  };

  const availableChapters = useMemo(() => {
    const items = publicActions.flatMap(family => Array.isArray(family.variants)
      ? (family.variants as TutorialRecord[]).map(variant => ({ ...family, ...variant })) : [family]);
    return items.map(item => actionTutorial(item));
  }, [publicActions]);
  const intro = context.entryKind === "new" && canAuto(BASIC_TUTORIAL) && !active && !directory && !context.form && !sceneModal;
  const sceneDefinition = context.scene ? sceneTutorial(context.scene) : null;
  const sceneInvite = sceneDefinition && canAuto(sceneDefinition) && !intro && !active && !directory && !context.form;
  const resumable = progress.paused && [BASIC_TUTORIAL, actionTour(publicActions), ...availableChapters,
    ...(context.form ? [formTutorial(context.form)] : []), ...(sceneDefinition ? [sceneDefinition] : [])]
    .find(definition => definition.id === progress.paused!.id
      && progress.chapters[definition.id]?.revision === definition.revision
      && (definition.id === "basic" ? !context.form && visibleTargetSafe("narrative-controls")
        : definition.id === "actions" || definition.id.startsWith("action:") ? context.panel === "actions" && !context.form : true)
      && (!sceneModal || definition.id === `scene:${context.scene}`));

  useEffect(() => {
    if (!directory || context.blocked) return;
    const previous = document.activeElement as HTMLElement | null;
    directoryRef.current?.querySelector<HTMLElement>("button")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setDirectory(false); }
      if (event.key !== "Tab") return;
      const buttons = Array.from(directoryRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') || []);
      const current = buttons.indexOf(document.activeElement as HTMLElement);
      event.preventDefault(); buttons[(current + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length]?.focus();
    };
    document.addEventListener("keydown", keydown, true);
    const focus = (event: FocusEvent) => { if (!directoryRef.current?.contains(event.target as Node)) directoryRef.current?.querySelector<HTMLElement>("button")?.focus(); };
    document.addEventListener("focusin", focus, true);
    return () => { document.removeEventListener("keydown", keydown, true); document.removeEventListener("focusin", focus, true); if (previous?.isConnected) previous.focus(); };
  }, [directory, context.blocked]);

  const openChapter = async (definition: TutorialDefinition) => {
    if (definition.id.startsWith("action:") && context.panel !== "actions") {
      setPendingChapter(definition.id);
      setDirectory(false); await onNavigate("actions"); return;
    }
    start(definition);
  };
  return <Controls.Provider value={{ openDirectory: () => setDirectory(true), start, context, canAuto, dismiss }}>
    {children}
    {intro && <aside className="tutorial-invitation" aria-label="赴任指南邀请"><b>赴任指南</b><p>用六个小步骤认识案头。操作与决定始终由你掌握。</p><button type="button" onClick={() => start(BASIC_TUTORIAL)}>开始赴任指南</button><button type="button" onClick={() => dismiss(BASIC_TUTORIAL)}>稍后再看</button></aside>}
    {sceneInvite && <aside className="tutorial-invitation" aria-label="场景操作帮助"><b>{sceneDefinition.title}</b><button type="button" onClick={() => start(sceneDefinition)}>查看操作提示</button><button type="button" onClick={() => dismiss(sceneDefinition)}>知道了</button></aside>}
    {active && applicable && !directory && <TutorialOverlay key={active.definition.id} definition={active.definition} initialStep={active.step} onStep={stepChanged} onClose={() => close()} onComplete={() => close(true)} onPause={() => close()} />}
    {active && !applicable && !context.blocked && !directory && <aside className="tutorial-invitation"><b>教程已暂停</b><p>回到对应场景后可继续，或先自由操作。</p><button type="button" onClick={() => close()}>关闭本节</button></aside>}
    {directory && !context.blocked && <div className="tutorial-directory-backdrop"><div className="tutorial-directory" ref={directoryRef} role="dialog" aria-modal="true" aria-label="赴任指南目录">
      <header><div><small>云溪县政府 · 操作帮助</small><h2>赴任指南</h2></div><button type="button" aria-label="关闭赴任指南" onClick={() => setDirectory(false)}>×</button></header>
      <label><input type="checkbox" checked={progress.auto} onChange={event => update({ ...progress, auto: event.target.checked })} /> 自动提示新内容</label>
      {context.readOnly ? <p>当前为只读复盘。可执行教程在可游玩的存档中提供。</p> : <>
        {active && applicable && <button type="button" onClick={() => setDirectory(false)}>继续暂停的教程</button>}
        {!active && resumable && <button type="button" onClick={() => start(resumable, progress.paused!.step)}>继续上次学习</button>}
        <button type="button" disabled={!context.sessionId || Boolean(context.form) || sceneModal} onClick={() => start(BASIC_TUTORIAL)}>重新查看基础导览</button>
        {!publicActions.length && <button type="button" disabled={!context.sessionId || Boolean(context.form)} onClick={async () => { setDirectory(false); await onNavigate("actions"); }}>前往行动页查看教程</button>}
        {availableChapters.map(definition => <button type="button" key={definition.id} disabled={Boolean(context.form)} onClick={() => void openChapter(definition)}>{definition.title}<small>{progress.chapters[definition.id]?.status === "completed" ? "已学 · 重播" : "查看介绍"}</small></button>)}
        {context.form && <button type="button" onClick={() => start(formTutorial(context.form!))}>重新查看本次填写指南</button>}
        {sceneHistory.map(scene => { const definition = sceneTutorial(scene); return definition ? <button type="button" key={scene} disabled={scene !== context.scene} onClick={() => start(definition)}>{definition.title}{scene !== context.scene && <small>回到对应场景后可重播</small>}</button> : null; })}
      </>}
    </div></div>}
  </Controls.Provider>;
}

export function TutorialButton({ label = "赴任指南" }: { label?: string }) {
  const controls = useContext(Controls);
  return <button type="button" className="tutorial-open" onClick={() => controls?.openDirectory()}>{label}</button>;
}

export function ActionTutorialButton({ item }: { item: TutorialRecord }) {
  const controls = useContext(Controls);
  return <button type="button" className="tutorial-action-help" onClick={() => controls?.start(actionTutorial(item))}>了解此行动</button>;
}

export function ActionsTutorialIntro({ items }: { items: TutorialRecord[] }) {
  const controls = useContext(Controls);
  const definition = actionTour(items);
  if (!definition.steps.length || !controls) return null;
  const variants = items.flatMap(item => Array.isArray(item.variants) ? (item.variants as TutorialRecord[]).map(variant => ({ ...item, ...variant })) : [item]);
  const unseen = variants.filter(item => item.available === true && controls.canAuto(actionTutorial(item)));
  const fresh = controls.canAuto(definition) || unseen.length > 0;
  return <section className="tutorial-action-intro"><b>行动指南</b><p>{fresh ? `有 ${unseen.length || definition.steps.length} 项可用行动尚未介绍，可逐项了解，也可选择单项。` : "随时重看当前可用行动的用途、消耗与结果。"}</p><button type="button" onClick={() => controls.start(definition)}>逐项了解</button>{fresh && <button type="button" onClick={() => controls.dismiss(definition)}>稍后再看</button>}</section>;
}

function visibleTargetSafe(id: string) {
  return typeof document !== "undefined" && visibleTarget(`[data-tutorial-id="${id}"]`);
}
