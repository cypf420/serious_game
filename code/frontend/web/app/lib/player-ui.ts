export type PlayerRecord = Record<string, unknown>;

export function speakerSelectionForTimelineEntry(
  entry: PlayerRecord,
  timelineLength: number,
): { npcId: string; timelineLength: number } | null {
  if (entry.speaker_type === "player") return null;
  return { npcId: String(entry.npc_id || ""), timelineLength };
}

export function aiConfigurationView(value: PlayerRecord | null | undefined): {
  configured: boolean;
  mode: string;
  summary: string;
  serverDefaultAvailable: boolean;
  serverDefaultSummary: string;
  compatibilityStatus: string;
  capabilities: string[];
  testedAt: string;
} {
  const active = value?.active === true;
  const mode = active ? String(value?.mode || "unconfigured") : "unconfigured";
  const endpoint = String(value?.endpoint || "");
  const model = String(value?.model || "");
  const serverDefault = value?.server_default && typeof value.server_default === "object" && !Array.isArray(value.server_default)
    ? value.server_default as PlayerRecord
    : {};
  const defaultEndpoint = String(serverDefault.endpoint || "");
  const defaultModel = String(serverDefault.model || "");
  const capabilityLabels: Record<string, string> = {
    single_choice: "单选",
    multiple_choice: "多选",
    expression: "人物表达",
    night_followup: "夜间与后续会谈",
    contract_rendering: "合同转写",
    document_rendering: "行政文书转写",
  };
  const capabilities = value?.capabilities && typeof value.capabilities === "object" && !Array.isArray(value.capabilities)
    ? Object.entries(value.capabilities as PlayerRecord)
      .filter(([, status]) => status === "passed")
      .map(([id]) => capabilityLabels[id] || id)
    : [];
  return {
    configured: active,
    mode,
    summary: active
      ? `${mode === "personal" ? "个人 API" : "服务器默认"} · ${endpoint || "已启用"}${model ? ` · ${model}` : ""}`
      : "尚未配置 AI 接口",
    serverDefaultAvailable: value?.server_default_available === true,
    serverDefaultSummary: [defaultEndpoint, defaultModel].filter(Boolean).join(" · "),
    compatibilityStatus: String(value?.compatibility_status || "untested"),
    capabilities,
    testedAt: String(value?.tested_at || ""),
  };
}

export function aiConfigurationMode(
  value: PlayerRecord | null | undefined,
): "personal" | "server_default" {
  return aiConfigurationView(value).mode === "server_default"
    ? "server_default"
    : "personal";
}

export function conversationContractWorkflow(
  activeAction: PlayerRecord | null | undefined,
  rawBatches: unknown,
  rawContracts: unknown,
): { proposal: PlayerRecord | null; contract: PlayerRecord | null } | null {
  if (
    activeAction?.status !== "active"
    || activeAction.action_kind !== "household_visit"
  ) return null;
  const targets = Array.isArray(activeAction.target_ids)
    ? activeAction.target_ids.map(String)
    : [];
  if (targets.length !== 1) return null;
  const targetId = targets[0];
  const batches = Array.isArray(rawBatches)
    ? rawBatches.filter(item => item && typeof item === "object" && !Array.isArray(item)) as PlayerRecord[]
    : [];
  const contracts = Array.isArray(rawContracts)
    ? rawContracts.filter(item => item && typeof item === "object" && !Array.isArray(item)) as PlayerRecord[]
    : [];
  const matchingBatches = batches.filter(
    item => String(item.representative_npc_id || "") === targetId,
  );
  const proposal = matchingBatches.find(
    item => item.status === "pending_confirmation",
  );
  if (proposal) return { proposal, contract: null };
  const confirmedBatchIds = new Set(
    matchingBatches
      .filter(item => item.status === "confirmed")
      .map(item => String(item.batch_id || "")),
  );
  const allConfirmedBatchIds = new Set(
    batches
      .filter(item => item.status === "confirmed")
      .map(item => String(item.batch_id || "")),
  );
  const contract = contracts.find(
    item => (
      confirmedBatchIds.has(String(item.batch_id || ""))
      || (
        String(item.signatory_npc_id || "") === targetId
        && allConfirmedBatchIds.has(String(item.batch_id || ""))
      )
    )
      && !["signed", "rejected"].includes(String(item.status || "")),
  );
  return contract ? { proposal: null, contract } : null;
}

export function conversationTimelineUpdate(
  wasAtBottom: boolean,
  previousLength: number,
  nextLength: number,
): { followLatest: boolean; showNewDialogue: boolean } {
  if (nextLength <= previousLength) {
    return { followLatest: false, showNewDialogue: false };
  }
  return wasAtBottom
    ? { followLatest: true, showNewDialogue: false }
    : { followLatest: false, showNewDialogue: true };
}

export function investigationLeadView(raw: unknown): Array<{
  factId: string;
  title: string;
  category: string;
  methods: Array<{
    routeType: string;
    label: string;
    instructions: string;
    unlockDay: number;
  }>;
}> {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap(item => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const lead = item as PlayerRecord;
    const methods = Array.isArray(lead.methods)
      ? lead.methods.flatMap(value => {
        if (!value || typeof value !== "object" || Array.isArray(value)) return [];
        const method = value as PlayerRecord;
        const routeType = String(method.route_type || "");
        const label = String(method.label || "").trim();
        const instructions = String(method.instructions || "").trim();
        const unlockDay = Number(method.unlock_day);
        if (
          !["archive", "conversation"].includes(routeType)
          || !label
          || !instructions
          || !Number.isInteger(unlockDay)
          || unlockDay < 1
        ) return [];
        return [{ routeType, label, instructions, unlockDay }];
      })
      : [];
    const factId = String(lead.fact_id || "");
    const title = String(lead.title || "").trim();
    if (!factId || !title || !methods.length) return [];
    return [{
      factId,
      title,
      category: String(lead.category || "clue"),
      methods,
    }];
  });
}

export function requiresAIConfiguration(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  return String((value as PlayerRecord).code || "") === "ROLE_LLM_CONFIGURATION_REQUIRED";
}

const SAFE_AI_CONFIGURATION_MESSAGES = new Set([
  "API Key 无效，或该账号没有模型权限",
  "AI 接口连接超时或暂时不可用",
  "该接口不兼容游戏所需的结构化输出",
  "服务器未配置可用的默认 AI 接口",
  "Base URL 必须是公共 HTTPS 地址，且不能包含账号、查询参数或片段",
  "Base URL 域名无法安全解析",
  "Base URL 不能指向内网、回环、链路本地或保留地址",
  "API Key 和模型名不能为空",
  "该接口未通过游戏所需的选择与表达能力测试",
]);

export function aiConfigurationErrorMessage(value: unknown): string {
  if (!value || typeof value !== "object") {
    return "AI 接口测试失败，请检查地址、Key 和模型名后重试。";
  }
  const error = value as PlayerRecord;
  const message = String(error.message || "");
  if (
    ["ROLE_LLM_CONFIGURATION_INVALID", "ROLE_LLM_CAPABILITY_UNSUPPORTED"].includes(String(error.code || ""))
    && SAFE_AI_CONFIGURATION_MESSAGES.has(message)
  ) {
    return message;
  }
  return "AI 接口测试失败，请检查地址、Key 和模型名后重试。";
}

const RELATIONSHIP_LABELS: Record<string, string> = {
  closed: "封闭", guarded: "谨慎", working: "可协作", trusted: "信任",
  hostile: "对立", resistant: "抵触", neutral: "中立", cooperative: "合作", supportive: "支持",
  calm: "平稳", uneasy: "不安", worried: "担忧", strained: "紧张", critical: "高度焦虑",
  not_assessed: "尚待观察",
};

export function qualitativeRelationshipLabel(value: unknown): string {
  return RELATIONSHIP_LABELS[String(value)] || "尚待观察";
}

export function archivePlayerSections(value: PlayerRecord | null | undefined): Array<{
  heading: string;
  body: string;
  kind?: "household";
}> {
  const sections = Array.isArray(value?.player_sections) ? value.player_sections : [];
  const projected = sections.flatMap(raw => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const item = raw as PlayerRecord;
    const heading = toPlayerText(item.heading, "档案记录");
    const body = toPlayerText(item.body);
    if (!body) return [];
    return [{
      heading,
      body,
      ...(item.kind === "household" ? { kind: "household" as const } : {}),
    }];
  });
  return projected.length ? projected : [{ heading: "档案正文", body: "这份档案暂无可读正文。" }];
}

function isReadArchive(value: PlayerRecord): boolean {
  return value.read_status === "read"
    || (Array.isArray(value.read_at_days) && value.read_at_days.length > 0);
}

export function archiveInvestigationGroups(value: unknown): {
  unread: PlayerRecord[];
  read: PlayerRecord[];
  unreadCount: number;
} {
  const archives = Array.isArray(value)
    ? value.filter(item => item && typeof item === "object" && !Array.isArray(item)) as PlayerRecord[]
    : [];
  const read = archives.filter(isReadArchive);
  const unread = archives.filter(item => !isReadArchive(item));
  return { unread, read, unreadCount: unread.length };
}

export function meetingEvidenceArchives(value: unknown): PlayerRecord[] {
  return archiveInvestigationGroups(value).read;
}

export function decisionUnlockRequirements(value: PlayerRecord | null | undefined): Array<{
  archiveName: string;
  reason: string;
}> {
  return (Array.isArray(value?.unlock_requirements) ? value.unlock_requirements : []).flatMap(raw => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const requirement = raw as PlayerRecord;
    const archiveName = String(requirement.archive_name || "").trim();
    if (!archiveName) return [];
    return [{ archiveName, reason: String(requirement.reason || "").trim() }];
  });
}

export function archiveReadGains(value: PlayerRecord | null | undefined): {
  facts: PlayerRecord[];
  strategicUses: string[];
} {
  const facts = Array.isArray(value?.newly_learned_facts)
    ? value.newly_learned_facts.filter(item => item && typeof item === "object" && !Array.isArray(item)) as PlayerRecord[]
    : [];
  const strategicUses = Array.isArray(value?.strategic_uses)
    ? value.strategic_uses.map(String).filter(Boolean)
    : [];
  return { facts, strategicUses };
}

export function conversationSpeakerLabel(turn: PlayerRecord, npcName: string): string {
  const speaker = String(turn.speaker_type || turn.speaker || "npc");
  return speaker === "player" ? "你" : npcName || "对方";
}

export function budgetEnvelopeChoices(value: unknown): Array<PlayerRecord & { envelope_id: string; resource_id: string; name: string }> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value as PlayerRecord).flatMap(([envelopeId, raw]) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const item = raw as PlayerRecord;
    return [{
      ...item,
      envelope_id: envelopeId,
      resource_id: String(item.resource_id || `budget:${envelopeId}`),
      name: toPlayerText(item.label, "专项预算"),
      unit: toPlayerText(item.unit, "万元"),
    }];
  });
}

export function publicWindowRewardAvailable(storyDay: unknown): boolean {
  const day = Number(storyDay);
  return Number.isFinite(day) && day <= 75;
}

export function reviewEndingView(value: PlayerRecord | null | undefined): {
  mainId: string;
  mainName: string;
  subId: string;
  subTitle: string;
  mainText: string;
  subText: string;
  axes: Array<{ key: string; value: string }>;
  appendices: PlayerRecord[];
} | null {
  const raw = value?.ending;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const ending = raw as PlayerRecord;
  const mainId = String(ending.main_ending_id || "");
  if (!mainId) return null;
  const rawAxes = ending.axes && typeof ending.axes === "object" && !Array.isArray(ending.axes)
    ? ending.axes as PlayerRecord
    : {};
  return {
    mainId,
    mainName: String(ending.main_ending_name || "治理周期结局"),
    subId: String(ending.sub_ending_id || ""),
    subTitle: String(ending.sub_ending_title || ""),
    mainText: String(ending.main_text || ""),
    subText: String(ending.sub_text || ""),
    axes: Object.entries(rawAxes).map(([key, axisValue]) => ({ key, value: String(axisValue ?? "") })),
    appendices: Array.isArray(ending.appendices)
      ? ending.appendices.filter(item => item && typeof item === "object" && !Array.isArray(item)) as PlayerRecord[]
      : [],
  };
}

const INTERNAL_PREFIX = /^\s*(?:(?:DP|BEAT|EV|CH|NPC)[A-Z0-9_-]+\s*[·:：\u2014-]\s*)/i;
const INTERNAL_BRACKET = /[【\[](?:突发[·:：-])?(?:(?:DP|BEAT|EV|CH|NPC)[A-Z0-9_-]+)[】\]]\s*/gi;

export function toPlayerText(value: unknown, fallback = ""): string {
  return String(value ?? fallback)
    .replace(INTERNAL_PREFIX, "")
    .replace(INTERNAL_BRACKET, "")
    .replace(/\bD(\d{1,2})\b/g, "第$1日")
    .replace(/\bNPC\b/gi, "人物")
    .replace(/玩家/g, "你")
    .replace(/剧本注册材料/g, "已归档材料")
    .replace(/已注册且/g, "已经归档且")
    .replace(/注册过的/g, "已有的")
    .replace(/对应剧情节点/g, "后续事态")
    .replace(/规则节点/g, "事态发展")
    .replace(/硬结算/g, "实际影响")
    .trim();
}

export function actionPointCost(item: PlayerRecord | null | undefined): number | null {
  if (!item) return null;
  const nested = item.cost && typeof item.cost === "object" && !Array.isArray(item.cost)
    ? (item.cost as PlayerRecord).action_points
    : undefined;
  const raw = item.cost_action_points
    ?? item.action_point_cost
    ?? nested
    ?? (typeof item.cost === "number" ? item.cost : undefined)
    ?? item.ap_cost;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim() !== "" && Number.isFinite(Number(raw))) return Number(raw);
  return null;
}

export function actionPointLabel(item: PlayerRecord | null | undefined): string {
  const cost = actionPointCost(item);
  return cost === null ? "消耗待确认" : cost === 0 ? "不消耗精力" : `消耗 ${cost} 点精力`;
}

const RESOURCE_UNIT_LABELS: Record<string, string> = {
  housing: "套",
  medical: "名额",
  school: "学位",
  employment: "名额",
  business: "份",
  grave: "户次",
  household_case: "户次",
  case: "个",
  batch: "批次",
  session: "场",
  slot: "名额",
  unit: "份",
};

function resourceUnitLabel(name: string, rawUnit: string, category: string): string {
  const namedUnits: Array<[RegExp, string]> = [
    [/名额/, "名额"], [/学位/, "学位"], [/岗位/, "岗位"], [/户次/, "户次"],
    [/批次/, "批次"], [/工时/, "工时"], [/场次/, "场次"], [/房/, "套"], [/包/, "份"],
  ];
  return namedUnits.find(([pattern]) => pattern.test(name))?.[1]
    || RESOURCE_UNIT_LABELS[rawUnit]
    || RESOURCE_UNIT_LABELS[category]
    || "份";
}

export function resourceInventoryView(value: unknown): Array<{
  resourceId: string;
  name: string;
  category: string;
  capacity: number;
  available: number;
  used: number;
  unit: string;
  availableDay: number;
  allocatableScope: string;
}> {
  if (!Array.isArray(value)) return [];
  return value.flatMap(raw => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const item = raw as PlayerRecord;
    const resourceId = String(item.resource_id || "");
    if (!resourceId) return [];
    const category = String(item.category || "other");
    const capacityValue = Number(item.capacity || 0);
    const capacity = Number.isFinite(capacityValue) ? Math.max(0, capacityValue) : 0;
    const availableValue = Number(item.available_to_reserve ?? item.available ?? capacity);
    const available = Number.isFinite(availableValue) ? Math.max(0, Math.min(capacity, availableValue)) : capacity;
    const usedValue = Number(item.blocked_total ?? item.used ?? capacity - available);
    const used = Number.isFinite(usedValue) ? Math.max(0, Math.min(capacity, usedValue)) : capacity - available;
    const attributes = item.attributes && typeof item.attributes === "object" && !Array.isArray(item.attributes)
      ? item.attributes as PlayerRecord
      : {};
    const name = toPlayerText(item.name || item.label, "专项资源");
    const rawUnit = String(item.unit || attributes.unit || category);
    return [{
      resourceId,
      name,
      category,
      capacity,
      available,
      used,
      unit: resourceUnitLabel(name, rawUnit, category),
      availableDay: Math.max(1, Number(item.available_day || 1)),
      allocatableScope: String(item.allocatable_scope || "contract"),
    }];
  });
}

export type AIActivity = { label: string };

export async function withAIActivity<Result>(
  setActivity: (value: AIActivity | null) => void,
  label: string,
  action: () => Promise<Result>,
): Promise<Result> {
  setActivity({ label });
  try {
    return await action();
  } finally {
    setActivity(null);
  }
}

export function governanceCancelMessage(action: PlayerRecord | null | undefined): string {
  return action?.cost_status === "pending"
    ? "确认终止当前行动？尚未形成有效交流，不会消耗精力。"
    : "确认终止当前行动？已经消耗的精力不会返还。";
}

export function governanceFinishMessage(action: PlayerRecord | null | undefined): string {
  return action?.cost_status === "pending"
    ? "本次行动未形成有效交流，未消耗精力，也未产生完成效果。"
    : "本次行动已经收束，取得的材料已收入案头。";
}

export function governanceLocationLocked(descriptor: PlayerRecord | null | undefined): boolean {
  return Boolean(descriptor?.opportunity_id) || descriptor?.location_locked === true;
}

export function governanceLocationLockMessage(
  descriptor: PlayerRecord | null | undefined,
): string {
  if (descriptor?.opportunity_id) return "人物会谈机会已锁定本次办理地点。";
  if (descriptor?.location_locked === true) return "地图入口已锁定本次办理地点。";
  return "";
}

export function governanceActionTitle(
  action: PlayerRecord | null | undefined,
  fallback: string,
): string {
  const title = action?.display_title;
  return typeof title === "string" && title.trim() ? title.trim() : fallback;
}

/**
 * Resolve the player-facing name for an action family or one of its variants.
 * The backend may provide display_title; the fallbacks keep legacy packages
 * from collapsing three different conversations into “干部访谈”.
 */
export function governanceDisplayTitle(
  action: PlayerRecord | null | undefined,
  fallback = "治理行动",
): string {
  const explicit = action?.display_title;
  if (typeof explicit === "string" && explicit.trim()) return explicit.trim();
  const mapTitle = action?.map_entry_id && action?.title;
  if (typeof mapTitle === "string" && mapTitle.trim()) return mapTitle.trim();
  const variantId = String(action?.variant_id || "");
  const actionId = String(action?.action_id || action?.action_kind || "");
  const targetKind = String(action?.target_kind || "");
  const targetIds = [
    ...(Array.isArray(action?.target_ids) ? action.target_ids : []),
    ...(Array.isArray(action?.legal_target_ids) ? action.legal_target_ids : []),
    ...(Array.isArray(action?.preselected_npc_ids) ? action.preselected_npc_ids : []),
  ].map(String);
  if (variantId === "interview_enterprise" || targetKind === "enterprise_representative" || targetIds.includes("npc_qian_wei")) return "约谈钱伟";
  if (variantId === "contact_media" || targetKind === "media_contact") return "媒体沟通";
  if (variantId === "interview_cadre") return "干部约谈";
  if (!variantId && actionId === "cadre_interview") return "政务沟通";
  return governanceActionTitle(action, fallback);
}

export function governanceActionButtonLabel(
  action: PlayerRecord | null | undefined,
  fallback = "填写方案",
): string {
  const variantId = String(action?.variant_id || "");
  const actionId = String(action?.action_id || action?.action_kind || "");
  if (actionId === "inspect_archives") return "开始查阅";
  if (actionId === "leadership_meeting") return "发起会议";
  if (actionId === "household_visit") return "开始走访";
  if (variantId === "contact_media" || String(action?.target_kind || "") === "media_contact") return "开始沟通";
  if (actionId === "cadre_interview") return "开始约谈";
  return fallback;
}

export function governanceActionProgressLabels(
  action: PlayerRecord | null | undefined,
  fallback: string,
): { footer: string; task: string } {
  const title = governanceActionTitle(action, fallback);
  return {
    footer: `${title}进行中`,
    task: `完成正在进行的${title}`,
  };
}

function governanceTimelineIdentity(entry: PlayerRecord): string {
  const npcId = String(entry.npc_id || entry.speaker_id || "");
  const conversationId = String(entry.conversation_id || entry.action_instance_id || entry.meeting_id || "");
  const turnId = String(entry.reply_id || entry.turn_id || entry.turn_index || entry.turn_number || "");
  const streamId = String(entry.stream_id || "");
  if (conversationId && turnId && npcId) return `turn:${conversationId}:${turnId}:${npcId}`;
  if (turnId && npcId) return `turn:${turnId}:${npcId}`;
  if (streamId && npcId) return `stream:${streamId}:${npcId}`;
  return "";
}

/**
 * Join the authoritative transcript with the short-lived streaming replies.
 * Some older API responses do not carry turn IDs, so a completed identical
 * reply is matched to the most recent reply from that NPC as a safe fallback.
 */
export function mergeGovernanceTimeline(rawTranscript: unknown, rawReplies: unknown): PlayerRecord[] {
  const records = (value: unknown) => Array.isArray(value)
    ? value.filter(item => item && typeof item === "object" && !Array.isArray(item)) as PlayerRecord[]
    : [];
  const timeline: PlayerRecord[] = records(rawTranscript).map(item => ({ ...item, live: false } as PlayerRecord));
  const committedByKey = new Map<string, number>();
  timeline.forEach((item, index) => {
    const key = governanceTimelineIdentity(item);
    if (key) committedByKey.set(key, index);
  });
  records(rawReplies).forEach(reply => {
    const live: PlayerRecord = { ...reply, speaker_type: "npc", live: true };
    const key = governanceTimelineIdentity(live);
    let duplicateIndex = key ? committedByKey.get(key) : undefined;
    if (duplicateIndex === undefined && live.complete === true && String(live.text || "")) {
      const npcId = String(live.npc_id || "");
      const text = String(live.text || "");
      for (let index = timeline.length - 1; index >= 0; index -= 1) {
        const item = timeline[index];
        if (item.live !== true && item.speaker_type !== "player" && String(item.npc_id || "") === npcId && String(item.text || "") === text) {
          duplicateIndex = index;
          break;
        }
      }
    }
    if (duplicateIndex !== undefined) {
      timeline[duplicateIndex] = { ...timeline[duplicateIndex], ...live, live: false };
      return;
    }
    timeline.push(live);
  });
  return timeline;
}

const CANONICAL_ACTION_IDS = [
  "household_visit",
  "cadre_interview",
  "leadership_meeting",
  "inspect_archives",
] as const;

export function canonicalActionFamilies(value: unknown): PlayerRecord[] {
  const items = Array.isArray(value) ? value.filter(item => item && typeof item === "object") as PlayerRecord[] : [];
  const byId = new Map(items.map(item => [String(item.action_id || ""), item]));
  return CANONICAL_ACTION_IDS.flatMap(actionId => {
    const item = byId.get(actionId);
    return item ? [{ ...item, variants: Array.isArray(item.variants) ? item.variants : [] }] : [];
  });
}

type PublicPerson = {
  npc_id: string;
  name: string;
  contact_state: "known" | "contactable";
  discovery_state: "mentioned" | "encountered" | "contactable";
  trust_band: string;
  attitude_band: string;
  anxiety_band: string;
  relationship_reasons: { trust: string; attitude: string; anxiety: string };
  recent_change_reasons: string[];
};

type PublicEdge = {
  edge_id: string;
  source_npc_id: string;
  target_npc_id: string;
  visibility: "suspected" | "confirmed";
  channel: string;
  discovery_reason: string;
  discovery_day?: number;
};

export function peopleRelationshipView(value: PlayerRecord | null | undefined): { people: PublicPerson[]; edges: PublicEdge[] } {
  const people = (Array.isArray(value?.people) ? value.people : []).flatMap(raw => {
    if (!raw || typeof raw !== "object") return [];
    const item = raw as PlayerRecord;
    const contactState = String(item.contact_state || "");
    if (!new Set(["known", "contactable"]).has(contactState)) return [];
    const rawDiscoveryState = String(item.discovery_state || "");
    const discoveryState = new Set(["mentioned", "encountered", "contactable"]).has(rawDiscoveryState)
      ? rawDiscoveryState
      : contactState === "contactable" ? "contactable" : "encountered";
    const rawReasons = item.relationship_reasons && typeof item.relationship_reasons === "object" && !Array.isArray(item.relationship_reasons)
      ? item.relationship_reasons as PlayerRecord : {};
    return [{
      npc_id: String(item.npc_id || ""),
      name: String(item.name || ""),
      contact_state: contactState as PublicPerson["contact_state"],
      discovery_state: discoveryState as PublicPerson["discovery_state"],
      trust_band: String(item.trust_band || "not_assessed"),
      attitude_band: String(item.attitude_band || "not_assessed"),
      anxiety_band: String(item.anxiety_band || "not_assessed"),
      relationship_reasons: {
        trust: String(rawReasons.trust || ""),
        attitude: String(rawReasons.attitude || ""),
        anxiety: String(rawReasons.anxiety || ""),
      },
      recent_change_reasons: (Array.isArray(item.recent_change_reasons) ? item.recent_change_reasons : []).slice(0, 3).map(String),
    }];
  });
  const visibleNpcIds = new Set(people.map(item => item.npc_id));
  const edges = (Array.isArray(value?.relationship_edges) ? value.relationship_edges : []).flatMap(raw => {
    if (!raw || typeof raw !== "object") return [];
    const item = raw as PlayerRecord;
    const visibility = String(item.visibility || "");
    const source = String(item.source_npc_id || "");
    const target = String(item.target_npc_id || "");
    if (visibility !== "confirmed" || !visibleNpcIds.has(source) || !visibleNpcIds.has(target)) return [];
    return [{
      edge_id: String(item.edge_id || ""),
      source_npc_id: source,
      target_npc_id: target,
      visibility: visibility as PublicEdge["visibility"],
      channel: String(item.channel || "association"),
      discovery_reason: String(item.discovery_reason || ""),
      ...(typeof item.discovery_day === "number" ? { discovery_day: item.discovery_day } : {}),
    }];
  });
  return { people, edges };
}

export function personDiscoveryPresentation(value: {
  discovery_state?: unknown;
  contact_state?: unknown;
}): {
  statusLabel: string;
  showRelationship: boolean;
  allowProfile: boolean;
} {
  if (value.discovery_state === "mentioned") {
    return {
      statusLabel: "卷宗提及 · 尚未接触",
      showRelationship: false,
      allowProfile: false,
    };
  }
  if (value.discovery_state === "contactable" || value.contact_state === "contactable") {
    return {
      statusLabel: "当前可联系",
      showRelationship: true,
      allowProfile: true,
    };
  }
  return {
    statusLabel: "已见面 · 目前不可联系",
    showRelationship: true,
    allowProfile: true,
  };
}

export type NpcStreamViewState = {
  requestPending: boolean;
  thinking: Record<string, { npc_id: string; npc_name: string }>;
  replies: Array<{ stream_id: string; npc_id: string; npc_name: string; text: string; complete: boolean }>;
  error: string;
  /** Maps a backend stream id to the latest in-flight UI reply. */
  activeStreamIds?: Record<string, string>;
  streamCounts?: Record<string, number>;
};

export function initialNpcStreamState(): NpcStreamViewState {
  return { requestPending: false, thinking: {}, replies: [], error: "", activeStreamIds: {}, streamCounts: {} };
}

export function reduceNpcStream(state: NpcStreamViewState, event: PlayerRecord): NpcStreamViewState {
  const type = String(event.type || "");
  const streamId = String(event.stream_id || "");
  if (type === "request_started") {
    return { ...state, requestPending: true, error: "" };
  }
  if (type === "request_finished") {
    return { ...state, requestPending: false };
  }
  if (type === "npc_thinking_start" && streamId) {
    return { ...state, error: "", thinking: { ...state.thinking, [streamId]: { npc_id: String(event.npc_id || ""), npc_name: String(event.npc_name || "") } } };
  }
  if (type === "npc_thinking_end" && streamId) {
    const thinking = { ...state.thinking };
    delete thinking[streamId];
    return { ...state, thinking };
  }
  if (type === "npc_start" && streamId) {
    const counts = { ...(state.streamCounts || {}) };
    const nextCount = (counts[streamId] || 0) + 1;
    counts[streamId] = nextCount;
    const uiStreamId = nextCount === 1 ? streamId : `${streamId}#${nextCount}`;
    return {
      ...state,
      requestPending: false,
      activeStreamIds: { ...(state.activeStreamIds || {}), [streamId]: uiStreamId },
      streamCounts: counts,
      replies: [...state.replies, { stream_id: uiStreamId, npc_id: String(event.npc_id || ""), npc_name: String(event.npc_name || ""), text: "", complete: false }],
    };
  }
  if (type === "npc_delta" && streamId) {
    const activeId = state.activeStreamIds?.[streamId] || streamId;
    return { ...state, replies: state.replies.map(item => item.stream_id === activeId ? { ...item, text: item.text + String(event.delta || "") } : item) };
  }
  if (type === "npc_end" && streamId) {
    const activeId = state.activeStreamIds?.[streamId] || streamId;
    return { ...state, replies: state.replies.map(item => item.stream_id === activeId ? { ...item, complete: true } : item) };
  }
  if (type === "error") {
    return { ...state, requestPending: false, thinking: {}, error: String(event.message || "对方暂时无法回应，请稍后重试。") };
  }
  if (type === "complete") {
    return { ...state, requestPending: false };
  }
  return state;
}

export function createSingleFlight<Args extends unknown[], Result>(fn: (...args: Args) => Promise<Result>) {
  let pending: Promise<Result> | null = null;
  return (...args: Args): Promise<Result> => {
    if (pending) return pending;
    pending = Promise.resolve().then(() => fn(...args));
    pending.then(
      () => { pending = null; },
      () => { pending = null; },
    );
    return pending;
  };
}

export function contractBatchTabs(
  rawContracts: unknown,
  currentContract: PlayerRecord,
): PlayerRecord[] {
  const batchId = String(currentContract.batch_id || "");
  const currentId = String(currentContract.contract_id || "");
  if (!batchId) return [];
  return (Array.isArray(rawContracts) ? rawContracts : [])
    .filter(item => item && typeof item === "object" && !Array.isArray(item))
    .map(item => item as PlayerRecord)
    .filter(item => String(item.batch_id || "") === batchId)
    .map(item => String(item.contract_id || "") === currentId
      ? { ...item, ...currentContract }
      : item);
}

export function createActivityLatch(setActive: (active: boolean) => void) {
  let activeScopes = 0;
  return {
    acquire() {
      activeScopes += 1;
      if (activeScopes === 1) setActive(true);
      let released = false;
      return () => {
        if (released) return;
        released = true;
        activeScopes -= 1;
        if (activeScopes === 0) setActive(false);
      };
    },
  };
}

export function canonicalActionEntry(value: PlayerRecord): PlayerRecord | null {
  const raw = value.canonical_action_descriptor;
  const descriptor = raw && typeof raw === "object" && !Array.isArray(raw)
    ? raw as PlayerRecord
    : value;
  const actionId = String(descriptor.action_id || "");
  const variantId = String(descriptor.variant_id || "");
  if (!CANONICAL_ACTION_IDS.includes(actionId as typeof CANONICAL_ACTION_IDS[number]) || !variantId) return null;
  const targetChoices = Array.isArray(descriptor.target_choices) ? descriptor.target_choices as PlayerRecord[] : [];
  const locationChoices = Array.isArray(descriptor.location_choices) ? descriptor.location_choices as PlayerRecord[] : [];
  const targetIds = (Array.isArray(descriptor.preselected_npc_ids) ? descriptor.preselected_npc_ids : []).map(String);
  const legalTargetIds = new Set(targetChoices.map(item => String(item.target_id || item.id || "")));
  const preselectedNpcIds = targetIds.filter(id => legalTargetIds.has(id));
  const requestedLocationId = String(descriptor.preselected_location_id || descriptor.location_id || "");
  const legalLocationIds = new Set(locationChoices.map(item => String(item.location_id || "")));
  const preselectedLocationId = legalLocationIds.has(requestedLocationId)
    ? requestedLocationId
    : String(locationChoices[0]?.location_id || "");
  return {
    ...descriptor,
    action_id: actionId,
    variant_id: variantId,
    preselected_npc_ids: preselectedNpcIds,
    preselected_location_id: preselectedLocationId,
  };
}

type GovernanceWriter = {
  write: (sessionId: string, path: string, method: "POST" | "PUT", body: PlayerRecord) => Promise<unknown>;
};

export function submitGovernanceAction(
  api: GovernanceWriter,
  sessionId: string,
  input: {
    state_version: number;
    descriptor: PlayerRecord;
    location_id: string;
    target_ids: string[];
    topic: string;
    archive_ids: string[];
    proposed_document_type: string | null;
    lead_npc_id: string | null;
  },
) {
  const isCanonicalOpportunity = Boolean(input.descriptor.opportunity_id);
  const isLockedLocation = governanceLocationLocked(input.descriptor);
  const canonicalTargets = (Array.isArray(input.descriptor.preselected_npc_ids)
    ? input.descriptor.preselected_npc_ids
    : []).map(String);
  return api.write(sessionId, "/governance/actions", "POST", {
    state_version: input.state_version,
    action_kind: String(input.descriptor.action_id || ""),
    variant_id: String(input.descriptor.variant_id || ""),
    location_id: isLockedLocation
      ? String(input.descriptor.preselected_location_id || "")
      : input.location_id,
    ...(input.descriptor.map_entry_id
      ? { map_entry_id: String(input.descriptor.map_entry_id) }
      : {}),
    opportunity_id: input.descriptor.opportunity_id || null,
    target_ids: isCanonicalOpportunity ? canonicalTargets : input.target_ids,
    topic: isCanonicalOpportunity
      ? String(input.descriptor.canonical_topic || "")
      : input.topic,
    archive_ids: isCanonicalOpportunity ? [] : input.archive_ids,
    proposed_document_type: isCanonicalOpportunity
      ? null
      : input.proposed_document_type,
    lead_npc_id: isCanonicalOpportunity ? null : input.lead_npc_id,
  });
}

export function primaryScenePlan(value: PlayerRecord): string[] {
  if (!value.has_session) return [];
  const mode = activeInteractionMode(value, value.active_governance_action as PlayerRecord | null);
  if (mode === "group") return ["forced_group_conversation"];
  if (mode === "conversation") return ["conversation"];
  const action = value.active_governance_action as PlayerRecord | null;
  if (mode === "governance" && action) {
    return value.active_meeting && action.action_kind === "leadership_meeting"
      ? ["leadership_meeting"]
      : ["governance_action"];
  }
  return ["narrative"];
}

export function activeInteractionMode(
  state: PlayerRecord,
  governanceAction: PlayerRecord | null,
): "group" | "conversation" | "governance" | null {
  if (state.active_group_conversation) return "group";
  if (state.active_conversation) return "conversation";
  return governanceAction ? "governance" : null;
}

export function sessionEntry(value: PlayerRecord): {
  session_id: string;
  mode: "review" | "continue" | "unavailable";
  label: string;
  canContinue: boolean;
  openKind: "review" | "load" | null;
  unavailableReason: string;
} {
  const retired = value.package_status === "retired" || value.review_only === true || value.mode === "review_only";
  const unavailable = value.mode === "content_unavailable"
    || value.content_available === false
    || (value.loadable === false && !retired);
  if (unavailable) return {
    session_id: String(value.session_id || ""),
    mode: "unavailable",
    label: "内容不可用",
    canContinue: false,
    openKind: null,
    unavailableReason: String(value.unavailable_reason || "该进度锁定的剧本内容已不在当前版本中，暂时无法打开。"),
  };
  return retired
    ? { session_id: String(value.session_id || ""), mode: "review", label: "仅可复盘", canContinue: false, openKind: "review", unavailableReason: "" }
    : { session_id: String(value.session_id || ""), mode: "continue", label: "继续游戏", canContinue: true, openKind: "load", unavailableReason: "" };
}
