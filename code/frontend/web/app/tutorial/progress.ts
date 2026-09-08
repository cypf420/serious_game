import type { TutorialDefinition, TutorialProgress } from "./types.ts";

const PREFIX = "qingjiang:tutorial:v1:";
const memory = new Map<string, TutorialProgress>();

export function emptyProgress(): TutorialProgress {
  return { version: 1, auto: true, chapters: {} };
}

function validStep(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function parseProgress(value: unknown): TutorialProgress | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as Record<string, unknown>;
  if (data.version !== 1 || typeof data.auto !== "boolean" || !data.chapters || typeof data.chapters !== "object" || Array.isArray(data.chapters)) return null;
  const chapters: TutorialProgress["chapters"] = Object.fromEntries(Object.entries(data.chapters).flatMap(([id, raw]) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const chapter = raw as Record<string, unknown>;
    if (!validStep(chapter.revision) || chapter.revision < 1 || !validStep(chapter.step) || (chapter.status !== "seen" && chapter.status !== "completed")) return [];
    return [[id, { revision: chapter.revision, status: chapter.status, step: chapter.step }]];
  }));
  const rawPaused = data.paused && typeof data.paused === "object" ? data.paused as Record<string, unknown> : null;
  const paused = rawPaused && typeof rawPaused.id === "string" && rawPaused.id && validStep(rawPaused.step)
    ? { id: rawPaused.id, step: rawPaused.step } : undefined;
  return { version: 1, auto: data.auto, chapters, ...(paused ? { paused } : {}) };
}

function browserStorage(): Storage | undefined {
  try { return typeof window === "undefined" ? undefined : window.localStorage; } catch { return undefined; }
}

export function loadProgress(accountId: string, storage?: Pick<Storage, "getItem">): TutorialProgress {
  if (!accountId) return emptyProgress();
  const key = PREFIX + encodeURIComponent(accountId);
  try {
    const raw = (storage ?? browserStorage())?.getItem(key);
    const parsed = raw ? parseProgress(JSON.parse(raw)) : null;
    if (parsed) {
      memory.set(key, parsed);
      return parseProgress(parsed)!;
    }
  } catch { /* Unavailable or corrupt local storage uses the account's in-memory progress. */ }
  return parseProgress(memory.get(key)) ?? emptyProgress();
}

export function saveProgress(accountId: string, progress: TutorialProgress, storage?: Pick<Storage, "setItem">): void {
  if (!accountId) return;
  const key = PREFIX + encodeURIComponent(accountId);
  const safe = parseProgress(progress) ?? emptyProgress();
  memory.set(key, safe);
  try { (storage ?? browserStorage())?.setItem(key, JSON.stringify(safe)); } catch { /* Keep progress usable for this account in this tab. */ }
}

export function markChapter(progress: TutorialProgress, definition: TutorialDefinition, status: "seen" | "completed", step: number): TutorialProgress {
  const previous = progress.chapters[definition.id];
  const completed = previous?.revision === definition.revision && previous.status === "completed";
  const nextStep = Math.max(0, Math.min(definition.steps.length - 1, Number.isFinite(step) ? Math.floor(step) : 0));
  return { ...progress, chapters: { ...progress.chapters, [definition.id]: { revision: definition.revision, status: completed ? "completed" : status, step: nextStep } } };
}

export function shouldAutoShow(progress: TutorialProgress, definition: TutorialDefinition): boolean {
  return progress.auto && definition.steps.length > 0 && progress.chapters[definition.id]?.revision !== definition.revision;
}
