export type NarrativeItem = {
  id: string;
  cursor?: number;
  storyDay?: number;
  kind: string;
  speaker?: string;
  text: string;
  contentInstanceId?: string;
  blockId?: string;
  decisionId?: string;
  mainEndingId?: string;
  beatId?: string;
  sceneId?: string;
  presentationPhase?: string;
  daySequence?: number;
  readGate?: string;
  mergedKeys?: string[];
};

export type NarrativeState = {
  sessionId: string;
  items: NarrativeItem[];
  historyItems: NarrativeItem[];
  currentIndex: number;
  unreadCount: number;
  feedCursor: number;
  rebuildCount: number;
};

export type NarrativeAction =
  | { type: "SESSION_OPEN"; sessionId: string }
  | { type: "FEED_MERGE"; sessionId: string; items: NarrativeItem[]; cursor?: number }
  | { type: "SESSION_REBUILD"; sessionId: string; items: NarrativeItem[]; cursor?: number; position?: "start" | "latest" | number }
  | { type: "PREVIOUS" }
  | { type: "NEXT" }
  | { type: "GO_TO"; index: number }
  | { type: "GO_LATEST" }
  | { type: "CLEAR" };

export const initialNarrativeState: NarrativeState = {
  sessionId: "",
  items: [],
  historyItems: [],
  currentIndex: -1,
  unreadCount: 0,
  feedCursor: 0,
  rebuildCount: 0,
};

export function pendingDecisionIsReady(
  currentItem: NarrativeItem | null | undefined,
  presentationEntryId: unknown,
): boolean {
  const gateId = typeof presentationEntryId === "string" ? presentationEntryId : "";
  return Boolean(currentItem && gateId && currentItem.contentInstanceId === gateId
    && currentItem.presentationPhase === "decision");
}

const keyFor = (item: NarrativeItem) => item.contentInstanceId
  ? `content:${item.contentInstanceId}`
  : Number.isFinite(item.cursor)
    ? `cursor:${item.cursor}`
    : `id:${item.id}`;

export function dedupeNarrative(items: readonly NarrativeItem[]): NarrativeItem[] {
  const known = new Set<string>();
  const result: NarrativeItem[] = [];
  for (const item of items) {
    // Retired filler may still exist in saved feeds. Never remove a decision gate.
    if (!item.text.trim() || (item.presentationPhase !== "decision"
      && item.text.startsWith("决定已经写入当天案卷。现场的人带着各自的判断离开"))) continue;
    const key = keyFor(item);
    if (known.has(key)) continue;
    known.add(key);
    for (const mergedKey of item.mergedKeys || []) known.add(mergedKey);
    const previous = result[result.length - 1];
    if (item.kind === "day_intro" && item.text.includes("今天没有必须处理的主线事项")
      && previous?.kind === "morning_card" && previous.storyDay === item.storyDay) {
      result[result.length - 1] = {
        ...previous,
        text: `${previous.text}\n${item.text}`,
        mergedKeys: [...(previous.mergedKeys || []), key],
      };
    } else {
      result.push(item);
    }
  }
  return result;
}

function splitLatestDay(items: readonly NarrativeItem[]) {
  const latestDay = Math.max(0, ...items.map(item => item.storyDay || 0));
  // End-day returns last night's new entries together with the next morning.
  // Keep that bridge on incremental merges AND full reloads, instead of
  // archiving it before the player has had a chance to read it.
  const inReadingWindow = (item: NarrativeItem) => (item.storyDay || latestDay) === latestDay
    || (item.storyDay === latestDay - 1
      && (item.presentationPhase === "night" || item.kind === "night"));
  return {
    items: items.filter(inReadingWindow),
    historyItems: items.filter(item => !inReadingWindow(item)),
    latestDay,
  };
}

export function narrativeReducer(state: NarrativeState, action: NarrativeAction): NarrativeState {
  switch (action.type) {
    case "CLEAR":
      return initialNarrativeState;
    case "SESSION_OPEN":
      return action.sessionId === state.sessionId
        ? state
        : { ...initialNarrativeState, sessionId: action.sessionId };
    case "SESSION_REBUILD": {
      const split = splitLatestDay(dedupeNarrative(action.items));
      const items = split.items;
      const currentIndex = items.length
        ? typeof action.position === "number"
          ? Math.max(0, Math.min(items.length - 1, Math.trunc(action.position)))
          : action.position === "latest" ? items.length - 1 : 0
        : -1;
      return {
        sessionId: action.sessionId,
        items,
        historyItems: split.historyItems,
        currentIndex,
        unreadCount: Math.max(0, items.length - currentIndex - 1),
        feedCursor: action.cursor ?? Math.max(0, ...action.items.map(item => item.cursor || 0)),
        rebuildCount: state.rebuildCount + 1,
      };
    }
    case "FEED_MERGE": {
      const base = action.sessionId === state.sessionId ? state : { ...initialNarrativeState, sessionId: action.sessionId };
      const previousDay = Math.max(0, ...base.items.map(item => item.storyDay || 0));
      const merged = dedupeNarrative([...base.historyItems, ...base.items, ...action.items]);
      const split = splitLatestDay(merged);
      const enteredNewDay = split.latestDay > previousDay;
      const knownCurrentKeys = new Set(base.items.map(keyFor));
      const firstAddedIndex = split.items.findIndex(item => !knownCurrentKeys.has(keyFor(item)));
      const currentIndex = enteredNewDay
        ? (split.items.length ? 0 : -1)
        : firstAddedIndex >= 0 && base.currentIndex >= base.items.length - 1
          ? firstAddedIndex
          : Math.min(base.currentIndex, split.items.length - 1);
      return {
        ...base,
        items: split.items,
        historyItems: split.historyItems,
        currentIndex,
        unreadCount: Math.max(0, split.items.length - currentIndex - 1),
        feedCursor: action.cursor ?? base.feedCursor,
      };
    }
    case "PREVIOUS":
      return state.currentIndex > 0 ? { ...state, currentIndex: state.currentIndex - 1 } : state;
    case "NEXT": {
      if (state.currentIndex >= state.items.length - 1) return state;
      const currentIndex = state.currentIndex + 1;
      return { ...state, currentIndex, unreadCount: Math.max(0, state.items.length - currentIndex - 1) };
    }
    case "GO_TO": {
      if (!state.items.length) return state;
      const currentIndex = Math.max(0, Math.min(state.items.length - 1, Math.trunc(action.index)));
      return { ...state, currentIndex, unreadCount: Math.max(0, state.items.length - currentIndex - 1) };
    }
    case "GO_LATEST":
      return { ...state, currentIndex: state.items.length - 1, unreadCount: 0 };
  }
}

export function narrativeItemFromFeed(value: Record<string, unknown>, fallbackId: string): NarrativeItem {
  const contentInstanceId = typeof value.content_instance_id === "string" ? value.content_instance_id : undefined;
  const rawText = String(value.text || "");
  const displayText = ["morning_card", "day_intro"].includes(String(value.kind))
    ? rawText.replace(/^(?:D\d+|第\s*[\d一二三四五六七八九十百]+\s*[日天])(?:[，、：:]|\s)+/u, "")
    : rawText;
  const cursor = typeof value.cursor === "number" ? value.cursor : undefined;
  return {
    id: String(contentInstanceId || cursor || fallbackId),
    cursor,
    storyDay: typeof value.story_day === "number" ? value.story_day : undefined,
    kind: String(value.kind || "narrative"),
    speaker: value.speaker ? String(value.speaker) : undefined,
    // Dates are already shown in the status/header. Suppress their standalone
    // feed page (including older clipped headings); retain free-day guidance.
    text: value.kind === "day_intro" && typeof value.story_day === "number"
      && !String(value.text || "").includes("今天没有必须处理的主线事项")
      ? ""
      : displayText,
    contentInstanceId,
    blockId: typeof value.block_id === "string" ? value.block_id : undefined,
    decisionId: typeof value.decision_id === "string" ? value.decision_id : undefined,
    mainEndingId: typeof value.main_ending_id === "string" ? value.main_ending_id : undefined,
    beatId: typeof value.beat_id === "string" ? value.beat_id : undefined,
    sceneId: typeof value.scene_id === "string" ? value.scene_id : undefined,
    presentationPhase: typeof value.presentation_phase === "string" ? value.presentation_phase : undefined,
    daySequence: typeof value.day_sequence === "number" ? value.day_sequence : undefined,
    readGate: typeof value.read_gate === "string" ? value.read_gate : undefined,
  };
}
