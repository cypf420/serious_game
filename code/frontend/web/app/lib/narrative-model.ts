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
  | { type: "FEED_MERGE"; sessionId: string; items: NarrativeItem[]; cursor?: number; storyDay?: number; pendingDecisionEntryId?: string | null }
  | { type: "SESSION_REBUILD"; sessionId: string; items: NarrativeItem[]; cursor?: number; storyDay?: number; pendingDecisionEntryId?: string | null; position?: "start" | "latest" | number }
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

export function narrativeReadingComplete(state: Pick<NarrativeState, "items" | "currentIndex">): boolean {
  return state.items.length === 0 || state.currentIndex >= state.items.length - 1;
}

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
    // Collapse only adjacent prose in the same narrative moment. Dialogue,
    // decisions and distinct scene/day contexts must retain their own entries.
    if (previous && ["narration", "narrative", "night"].includes(item.kind)
      && item.kind === previous.kind && !item.speaker && !previous.speaker
      && !item.decisionId && !previous.decisionId
      && !item.mainEndingId && !previous.mainEndingId
      && item.presentationPhase !== "decision" && item.presentationPhase !== "decision_setup"
      && item.readGate !== "decision" && previous.readGate !== "decision"
      && item.readGate === previous.readGate
      && item.presentationPhase === previous.presentationPhase
      && item.storyDay !== undefined && item.storyDay === previous.storyDay
      && item.beatId === previous.beatId && item.sceneId === previous.sceneId
      && item.text.trim().length >= 40 && item.text.trim() === previous.text.trim()) {
      result[result.length - 1] = {
        ...previous,
        mergedKeys: [...(previous.mergedKeys || []), key, ...(item.mergedKeys || [])],
      };
      continue;
    }
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

function splitLatestDay(items: readonly NarrativeItem[], storyDay?: number, pendingDecisionEntryId?: string | null) {
  const latestDay = storyDay ?? Math.max(0, ...items.map(item => item.storyDay || 0));
  // Tonight is read before advancing the clock. Older days belong only in
  // history, including restored saves created by the old one-step settlement.
  const inReadingWindow = (item: NarrativeItem) => (item.storyDay || latestDay) === latestDay;
  // This generic question is an interaction prompt, not story narration.
  // Once resolved it has no content to replay; keep the actual consequences.
  const readable = items.filter(item => !(pendingDecisionEntryId !== undefined
    && item.kind === "decision" && item.text.trim() === "你准备如何处理？"
    && item.contentInstanceId !== pendingDecisionEntryId));
  return {
    items: readable.filter(inReadingWindow),
    historyItems: readable.filter(item => !inReadingWindow(item)),
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
      const split = splitLatestDay(dedupeNarrative(action.items), action.storyDay, action.pendingDecisionEntryId);
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
      const split = splitLatestDay(merged, action.storyDay, action.pendingDecisionEntryId);
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

// Restore prose omitted from the locked package without invalidating existing saves.
// Source: 最终剧本.md, 第八幕, between d11_source_opening and DP1-06.
const restoredDecisionSetup: Record<string, string> = {
  dp1_06_presentation: [
    "周大山：「来来来，谁先签谁是明白人。县长都发话了，补偿一分不少，房子给你安置得妥妥的，还犹豫啥。」",
    "话虽这么喊，那几户跟他沾着亲的人家脚却像钉在了地上，谁也没先挪。孙强在一旁陪着笑。",
    "孙强：「县长您放心，今天这场我盯着，开个好头不成问题。」",
    "嘴上说得热络，眼角却时不时往门外瞟，那点看热闹的意思藏都藏不住。几户被做过工作的人家挤在门外，探头探脑地犹豫着，有的搓着手，有的低声跟身边人嘀咕，就是没人肯头一个跨进那道门槛。屋里的空气一点点绷紧，横幅底下那张空着的协议、红印泥旁边那片刺眼的空白，都在等一个人。破零与否，牵动的不只是一个数字，更是你开局立不立得住的信号。第一个手印按不按得下去，柳林村这一村人都在暗地里掂量着你的斤两。",
  ].join("\n\n"),
};

export function narrativeItemFromFeed(value: Record<string, unknown>, fallbackId: string): NarrativeItem {
  const contentInstanceId = typeof value.content_instance_id === "string" ? value.content_instance_id : undefined;
  const restoredText = value.presentation_phase === "decision_setup"
    ? restoredDecisionSetup[String(value.block_id || "")] : undefined;
  const rawText = (restoredText ?? String(value.text || "")).replaceAll("老皇历", "老黄历");
  const isProse = ["narration", "narrative", "night", "morning_card", "day_intro"].includes(String(value.kind));
  const protectedGate = value.presentation_phase === "decision" || value.read_gate === "decision";
  // Old saves can contain either standalone or merged system transition lines.
  // Remove only whole known boilerplate lines, preserving actual story prose.
  const displayText = isProse && !protectedGate
    ? rawText.split(/\r?\n/u).map(line => ["morning_card", "day_intro"].includes(String(value.kind))
      ? line.replace(/^(?:D\d+|第\s*[\d一二三四五六七八九十百]+\s*[日天])(?:[，、：:]|\s)+/u, "") : line)
      .filter(line => !/^(?:(?:D\d+|第\s*[\d一二三四五六七八九十百]+\s*[日天])[，、：:\s]+)?(?:清晨，专班完成了?昨日材料结转。|县城昨夜无事。|昨夜，与你白天接触有关的消息在熟人圈里传开了。)$/u.test(line.trim()))
      .join("\n").trim()
    : rawText;
  const cursor = typeof value.cursor === "number" ? value.cursor : undefined;
  return {
    id: String(contentInstanceId || cursor || fallbackId),
    cursor,
    storyDay: typeof value.story_day === "number" ? value.story_day : undefined,
    kind: String(value.kind || "narrative"),
    speaker: value.speaker ? String(value.speaker) : undefined,
    // Navigation already communicates the date and available free-day actions.
    text: value.kind === "day_intro" && !protectedGate && !rawText.includes("今天没有必须处理的主线事项")
      ? ""
      : isProse
        ? formatNarrativeDates(displayText) : displayText,
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

// Story prose uses Chinese dates; counters, document contents, IDs and monetary
// amounts keep their source format. This also fixes existing saved story feeds.
function formatNarrativeDates(text: string): string {
  const digits = "零一二三四五六七八九";
  return text.replace(/第\s*([1-9]\d?)\s*([天日])/gu, (match, raw: string, unit: string) => {
    const day = Number(raw);
    if (day > 90) return match;
    const tens = Math.floor(day / 10);
    const ones = day % 10;
    const written = tens === 0 ? digits[ones]
      : `${tens === 1 ? "" : digits[tens]}十${ones ? digits[ones] : ""}`;
    return `第${written}${unit}`;
  });
}
