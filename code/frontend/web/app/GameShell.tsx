"use client";
import { dialogueSegments } from "./lib/dialogue-segments";
import { actionForNextStep, nextSteps, type NextStep } from "./lib/action-guidance";
import { firstMeetingHint } from "./lib/player-ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { ReferenceInput, ReferenceLibrary, ReferenceAttachments, type ReferenceDocument } from "./ReferenceDocuments";
import Image from "next/image";
import { EndingExperience } from "./ending/EndingExperience";
import { PagedReading } from "./reading/PagedReading";
import { actionPresentation, meetingAction, participantCountLabel } from "./lib/action-presentation";
import { TutorialProvider, TutorialButton, ActionTutorialButton } from "./tutorial/TutorialProvider";
import type { TutorialContext } from "./tutorial/types";
import { FormEvent, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { ApiError, GameApi, type NpcStreamEvent } from "./lib/api";
import { resolveCharacter, type Character } from "./lib/characters";
import { initialNarrativeState, narrativeItemFromFeed, narrativeReducer, pendingDecisionIsReady, narrativeReadingComplete, type NarrativeItem } from "./lib/narrative-model";
import { resolveSceneForView } from "./lib/scene-resolver";
import { actionPointCost, actionPointLabel, activeInteractionMode, aiConfigurationErrorMessage, aiConfigurationMode, aiConfigurationView, archiveInvestigationGroups, archivePlayerSections, archiveReadGains, budgetEnvelopeChoices, canonicalActionEntry, canonicalActionFamilies, contractBatchTabs, conversationContractWorkflow, conversationTimelineUpdate, createActivityLatch, createSingleFlight, decisionUnlockRequirements, governanceActionButtonLabel, governanceActionProgressLabels, governanceDisplayTitle, governanceCancelMessage, governanceFinishMessage, initialNpcStreamState, investigationLeadView, meetingEvidenceArchives, mergeGovernanceTimeline, peopleRelationshipView, personDiscoveryPresentation, primaryScenePlan, qualitativeRelationshipLabel, reduceNpcStream, requiresAIConfiguration, resourceInventoryView, reviewEndingView, sessionEntry, speakerSelectionForTimelineEntry, submitGovernanceAction, toPlayerText, withAIActivity } from "./lib/player-ui";

type Dict = Record<string, any>;
type Line = NarrativeItem;
type PanelName = "scene" | "actions" | "opportunities" | "governance" | "desk" | "knowledge" | "review";
type ConfirmRequest = { title: string; message: string; confirmLabel: string; danger?: boolean; action: () => void | Promise<void> };

const NAV: { id: PanelName; label: string; hint: string }[] = [
  { id: "scene", label: "今日", hint: "目标与现场" },
  { id: "actions", label: "行动", hint: "安排工作" },
  { id: "opportunities", label: "人物", hint: "人物与会谈" },
  { id: "governance", label: "治理", hint: "会议与资源" },
  { id: "desk", label: "卷宗", hint: "任务与政策" },
  { id: "knowledge", label: "线索", hint: "事实与证据" },
  { id: "review", label: "复盘", hint: "选择与后果" },
];

const PANEL_TITLES: Record<PanelName, string> = {
  scene: "今日案头", actions: "可安排的行动", opportunities: "可以会谈的人", governance: "治理进展",
  desk: "县长卷宗", knowledge: "已掌握的线索", review: "本局纪要",
};

const MEETING_TOPICS = [
  "明确搬迁补偿口径与签约推进安排",
  "协调安置住房、医疗与就学资源",
  "封存并审计村级搬迁账目",
  "启动环境污染调查与第三方检测",
  "处理重点户矛盾与群体风险",
  "明确部门分工、责任人与完成期限",
];
const CUSTOM_MEETING_TOPIC = "custom";
const EVIDENCE_RANK: Record<string, number> = { E0: 0, E1: 1, E2: 2, E3: 3 };

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  implementation_notice: "实施工作通知", medical_guarantee: "医疗保障文件", grave_or_shrine_approval: "迁葬专项批复",
  compensation_adjustment: "补偿调整方案", hearing_notice: "公开听证通知", investigation_notice: "专项调查通知",
};

const PARAMETER_LABELS: Record<string, string> = {
  topic: "议题", public_scope: "公开范围", staffing_principle: "用人原则", scope: "核查范围",
  archive_type: "档案类型", request_type: "请示事项", message_scope: "传达内容", consent_status: "知情同意情况",
  relief_status: "救济程序状态", legal_basis: "法律依据", plan_status: "现场处置预案", inspection_theme: "走访重点",
  agenda: "协商议程", case_type: "案件类型", procedure: "办理方式", public_matter: "公开事项",
};

const GOVERNANCE_ACTION_LABELS: Record<string, string> = {
  household_visit: "入户走访",
  cadre_interview: "政务沟通",
  leadership_meeting: "班子会议",
  inspect_archives: "查阅档案",
};

const get = (obj: Dict | null | undefined, path: string, fallback: any = undefined) => path.split(".").reduce((value, key) => value?.[key], obj) ?? fallback;
const arr = (value: unknown): Dict[] => Array.isArray(value) ? value.filter(item => item && typeof item === "object") as Dict[] : [];
const values = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const displayValue = (value: unknown, fallback: string | number = "待定"): string | number => {
  if (typeof value === "string" || typeof value === "number") return value;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Dict;
    for (const key of ["label", "name", "text", "remaining", "current", "available", "value", "signed", "total"]) {
      if (typeof record[key] === "string" || typeof record[key] === "number") return record[key];
    }
  }
  return fallback;
};
const playerText = toPlayerText;
function actionLocationLabel(item: Dict, locationId: string, choices: Dict[]): string {
  const direct = item.location_name || item.location_label || item.resolved_location_name || get(item, "location.name");
  if (direct) return playerText(direct);
  const choice = choices.find(value => String(value.location_id || "") === locationId);
  return playerText(choice?.label || choice?.name, locationId || "现场待定");
}
const chineseIndex = (index: number) => {
  const digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
  const value = index + 1;
  if (value < 10) return digits[value];
  if (value === 10) return "十";
  if (value < 20) return `十${digits[value - 10]}`;
  if (value < 100) return `${digits[Math.floor(value / 10)]}十${value % 10 ? digits[value % 10] : ""}`;
  return String(value);
};
const friendlyStatus = (value: unknown) => {
  const labels: Record<string, string> = {
    active: "进行中", ended: "已结束", completed: "已完成", published: "已公示", draft: "草拟中",
    pending_countersign: "待会签", approved: "会签通过", issued: "已印发",
    pass: "审校通过", needs_revision: "需要修订", reject: "审校未通过",
    not_reviewed: "尚未审校",
    awaiting_terms: "待核定条款", under_review: "复核中", accepted: "本户已接受", signed: "已签署",
    explanation_requested: "要求解释", counteroffered: "提出调整", rejected: "本户拒绝",
    critical: "紧急", high: "较高", medium: "一般", low: "较低",
    pending: "待处理", checkpoint: "自动保存", manual: "手动存档", public: "公开", internal: "内部掌握",
    confidential: "保密", restricted: "限内部查阅", secret: "机密", 内部: "内部掌握", 敏感: "敏感材料", 机密: "机密材料", E1: "初步材料", E2: "可核材料", E3: "正式证据",
    unknown: "尚未发现", discovered: "已经发现", acknowledged: "已经确认", committed: "历史资源记录", allocated: "已分配",
    satisfied: "已经办结", lawfully_refused: "已依法拒绝", breached: "承诺违约", expired: "处置逾期",
  };
  return labels[String(value)] || "已记录";
};
const playerErrorMessage = (error: unknown) => {
  const value = error as ApiError;
  const message = String(value?.message || "");
  const safeMessage = message && !/HTTP|API|backend|frontend|session|state|version|token|JSON|ID|端口|后端|客户端/i.test(message) ? message : "";
  if (value?.status === 401) return "登录状态已失效，请重新登录后继续。";
  if (value?.status === 403) return "当前账号没有执行这项操作的权限。";
  if (value?.status === 404) return "没有找到这份进度，它可能已经被移除。";
  if (value?.code === "STATE_VERSION_CONFLICT") return "进度刚刚发生了变化，已为你重新读取最新状态。";
  if (value?.status === 409 && safeMessage) return safeMessage;
  if (value?.status === 422) return "所填内容还不完整，请检查后再提交。";
  if (["CLIENT_STREAM_TIMEOUT", "CLIENT_STREAM_INCOMPLETE", "NPC_RESPONSE_UNAVAILABLE"].includes(value?.code) && safeMessage) return safeMessage;
  if (!value?.status || value.status >= 500) return "游戏服务暂时没有响应，请稍后重试。";
  if (safeMessage) return safeMessage;
  return "这项操作暂时无法完成，请换一种安排或稍后重试。";
};

const ENDING_AXIS_LABELS: Record<string, string> = {
  A: "签约完成度", C: "旧账处置", D: "廉政底线", T: "污染治理", M: "推进方式", X: "项目真实性", R: "上报口径",
  P: "群众关系", F: "责任承担", Z: "政策立场", J: "巡察进展", K: "班子关系", E: "媒体关系", V: "上级态度",
};
async function playProgressCue(tone = "wry") {
  if (typeof window === "undefined" || !window.AudioContext) return;
  try {
    const context = new window.AudioContext();
    await context.resume();
    const now = context.currentTime;
    const notes = tone === "stern"
      ? [392, 293.66, 196]
      : tone === "encouraging"
        ? [392, 523.25, 659.25]
        : [349.23, 440, 349.23];
    notes.forEach((frequency, index) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = index === 0 ? "triangle" : "sine";
      oscillator.frequency.value = frequency;
      const startsAt = now + index * 0.18;
      gain.gain.setValueAtTime(0.0001, startsAt);
      gain.gain.exponentialRampToValueAtTime(index === 0 ? 0.16 : 0.1, startsAt + 0.025);
      gain.gain.exponentialRampToValueAtTime(0.0001, startsAt + 0.34);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(startsAt);
      oscillator.stop(startsAt + 0.36);
    });
    window.setTimeout(() => void context.close(), 1100);
  } catch { /* browsers may block audio until the next explicit replay */ }
}

function ProgressBroadcast({ broadcast, onReplay }: { broadcast: Dict; onReplay: () => void }) {
  const progress = broadcast.progress || {};
  return <div className={`progress-broadcast tone-${broadcast.tone || "wry"}`} data-testid="progress-broadcast">
    <div className="broadcast-seal" aria-hidden="true">督</div>
    <div className="broadcast-kicker">第 {broadcast.story_day} 日 · 阶段督办</div>
    <h3>{playerText(broadcast.headline)}</h3>
    <p className="broadcast-message">{playerText(broadcast.message)}</p>
    <div className="broadcast-progress" aria-label="阶段签约进度">
      <span>已签约 <b>{progress.signed}</b> 户</span>
      <span>阶段参考 <b>{progress.expected}</b> 户</span>
      <span>剩余 <b>{progress.days_left}</b> 日</span>
    </div>
    <ul>{values(broadcast.signals).map((item, index) => <li key={index}>{playerText(item)}</li>)}</ul>
    <button type="button" className="broadcast-replay" onClick={onReplay}>重播督办提示音</button>
  </div>;
}
const isPlayerFacingLine = (line: Line) => {
  if (line.blockId === "d04_source_opening" || line.text.startsWith("再补一条口径，免得和各章那句“连续满负荷降点”对不上")) return false;
  if (["system", "success", "error", "input", "help"].includes(line.kind)) return false;
  const text = line.text.trim();
  if (!text) return false;
  return !/^(SESSION\s|清江治理终端|正在等待连接|已连接\s+\/api|操作已提交$)/i.test(text)
    && !/游戏开局，玩家|玩家在到任第一天/.test(text);
};
function Modal({ title, children, onClose, className = "" }: { title: string; children: React.ReactNode; onClose?: () => void; className?: string }) {
  return <div className="modal-backdrop" role="dialog" aria-modal="true"><div className={`modal ${className}`.trim()}><div className="modal-head"><div><small>云溪县政府</small><h2>{title}</h2></div>{onClose && <button className="icon-button" onClick={onClose} aria-label="关闭">×</button>}</div>{children}</div></div>;
}

function CharacterPortrait({ character, fallbackName, priority = false }: { character: Character | null; fallbackName: string; priority?: boolean }) {
  const [failedPath, setFailedPath] = useState("");
  if (!character || failedPath === character.portraitPath) {
    return <div className="portrait-fallback" aria-label={`${fallbackName}暂无立绘`}>{fallbackName.slice(0, 1) || "人"}</div>;
  }
  return <Image className="character-portrait" src={character.portraitPath} alt={`${character.name}立绘`} fill sizes="(max-width: 640px) 38vw, 220px" priority={priority} unoptimized style={{ objectFit: "contain", objectPosition: "center bottom" }} onError={() => setFailedPath(character.portraitPath)} />;
}

export default function GameShell() {
  const [baseUrl] = useState("/api/backend");
  const api = useMemo(() => new GameApi(baseUrl), [baseUrl]);
  const [connected, setConnected] = useState(false);
  const [account, setAccount] = useState("");
  const [authRequired, setAuthRequired] = useState(false);
  const [selfRegistration, setSelfRegistration] = useState(false);
  const [modelConsentRequired, setModelConsentRequired] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const [consentInfo, setConsentInfo] = useState<Dict | null>(null);
  const [consentGranted, setConsentGranted] = useState(true);
  const [consentError, setConsentError] = useState("");
  const [csrfCookieName, setCsrfCookieName] = useState("serious_game_session_csrf");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authError, setAuthError] = useState("");
  const [authStep, setAuthStep] = useState<"account" | "ai">("account");
  const [aiConfiguration, setAiConfiguration] = useState<Dict | null>(null);
  const [aiMode, setAiMode] = useState<"personal" | "server_default">("personal");
  const [aiError, setAiError] = useState("");
  const [aiSuccess, setAiSuccess] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [tutorialGeneration, setTutorialGeneration] = useState(0);
  const [tutorialEntry, setTutorialEntry] = useState<TutorialContext["entryKind"]>(null);
  const [tutorialResult, setTutorialResult] = useState<"morning" | "action-result" | null>(null);
  const [tutorialResultNotice, setTutorialResultNotice] = useState("");
  const [state, setState] = useState<Dict>({});
  const [commands, setCommands] = useState<Dict>({});
  const [narrative, dispatchNarrative] = useReducer(narrativeReducer, initialNarrativeState);
  const sourceLine = narrative.items[narrative.currentIndex] || null;
  const displaySegments = useMemo(() => dialogueSegments(sourceLine), [sourceLine]);
  const segmentKey = `${sessionId}:${narrative.rebuildCount}:${sourceLine?.id}:${sourceLine?.text}`;
  const [segmentSelection, setSegmentSelection] = useState({ key: "", index: 0 });
  const segmentIndex = segmentSelection.key === segmentKey ? Math.min(segmentSelection.index, Math.max(0, displaySegments.length - 1)) : 0;
  const hasMoreSegments = segmentIndex < displaySegments.length - 1;

  const [showHistory, setShowHistory] = useState(false);
  const [panel, setPanel] = useState<PanelName>("scene");
  const [panelData, setPanelData] = useState<Dict | null>(null);
  const [governance, setGovernance] = useState<Dict | null>(null);
  const [busy, setBusy] = useState(false);
  const [aiActivity, setAiActivity] = useState<{ label: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [pendingSync, setPendingSync] = useState<{ sessionId: string; after: number; rebuild: boolean; panel: PanelName } | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [sessionOpen, setSessionOpen] = useState(false);
  const [savedSessionsOpen, setSavedSessionsOpen] = useState(false);
  const [savedSessions, setSavedSessions] = useState<Dict[]>([]);
  const [savedSessionsError, setSavedSessionsError] = useState("");
  const [formOpen, setFormOpen] = useState<null | { title: string; kind: string; item?: Dict }>(null);
  const [governanceRecordOpen, setGovernanceRecordOpen] = useState<null | { meeting?: Dict; document?: Dict }>(null);
  const [characterProfileOpen, setCharacterProfileOpen] = useState<Character | null>(null);
  const [archiveReadingOpen, setArchiveReadingOpen] = useState<Dict | null>(null);
  const [meetingResolutionOpen, setMeetingResolutionOpen] = useState(false);
  const [contractProposalOpen, setContractProposalOpen] = useState<Dict | null>(null);
  const [contractOpen, setContractOpen] = useState<Dict | null>(null);
  const [contractTutorialState, setContractTutorialState] = useState<{ id: string; stage: import("./tutorial/types").ContractTutorialStage } | null>(null);
  const contractDirty = useRef(false);
  const [progressBroadcastOpen, setProgressBroadcastOpen] = useState(false);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [conversationInput, setConversationInput] = useState("");
  const [referenceDocuments, setReferenceDocuments] = useState<ReferenceDocument[]>([]);
  const [referenceIds, setReferenceIds] = useState<string[]>([]);
  const [referenceError, setReferenceError] = useState("");
  const [referenceLoading, setReferenceLoading] = useState(false);
  const [loadedReferenceContext, setLoadedReferenceContext] = useState("");
  const [referenceReload, setReferenceReload] = useState(0);
  const referenceConversationKey = `${sessionId}:${state.active_conversation?.conversation_id || ""}:${state.active_group_conversation?.conversation_id || ""}:${governance?.governance_actions?.find((item: Dict) => item.status === "active")?.action_instance_id || ""}`;
  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(async () => {
      if (disposed) return null;
      setReferenceDocuments([]); setReferenceError("");
      if (!sessionId) return null;
      setReferenceLoading(true);
      return api.referenceDocuments(sessionId);
    }).then(result => {
      if (!disposed) { setReferenceDocuments(result?.documents || []); setLoadedReferenceContext(referenceConversationKey); }
    }).catch(() => { if (!disposed) setReferenceError("档案列表暂时无法读取，普通对话仍可使用。"); })
      .finally(() => { if (!disposed) setReferenceLoading(false); });
    return () => { disposed = true; };
  }, [api, sessionId, state.state_version, referenceReload, referenceConversationKey]);
  useEffect(() => { let disposed = false; queueMicrotask(() => { if (!disposed) setReferenceIds([]); }); return () => { disposed = true; }; }, [referenceConversationKey]);
  const availableReferenceDocuments = loadedReferenceContext === referenceConversationKey ? referenceDocuments : referenceDocuments.map(doc => ({ ...doc, can_reference: false, reference_unavailable_reason: "正在核验当前会谈的引用范围…" }));
  const [npcStream, setNpcStream] = useState(initialNpcStreamState);
  const streamingReplies = npcStream.replies;
  const performSingleFlightRef = useRef(createSingleFlight(
    async (operation: () => Promise<boolean>) => operation(),
  ));
  const activityLatchRef = useRef(createActivityLatch(setBusy));
  const contextRef = useRef<HTMLElement>(null);
  const storyScrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = storyScrollRef.current;
    root?.scrollTo({ top: 0 });
    root?.querySelectorAll(".gal-dialogue > p").forEach(element => element.scrollTo({ top: 0 }));
  }, [narrative.currentIndex, segmentIndex, sessionId]);
  const progressBroadcast = state.progress_broadcast as Dict | null;
  const progressBroadcastId = String(progressBroadcast?.broadcast_id || "");
  const progressBroadcastTone = String(progressBroadcast?.tone || "wry");
  const aiView = aiConfigurationView(aiConfiguration || {});

  useEffect(() => {
    const current = narrative.items[narrative.currentIndex];
    if (!sessionId || !current || narrative.currentIndex < 0) return;
    const readingDay = Math.max(0, ...narrative.items.map(item => item.storyDay || 0));
    try {
      window.localStorage.setItem(
        `qingjiang-read-position:v2:${sessionId}:${readingDay}`,
        String(narrative.currentIndex),
      );
    } catch { /* reading still works when local persistence is unavailable */ }
  }, [sessionId, narrative.currentIndex, narrative.items]);

  useEffect(() => {
    if (!sessionId || !progressBroadcastId) return;
    const storageKey = `qingjiang-progress-broadcast:${sessionId}:${progressBroadcastId}`;
    try {
      if (window.sessionStorage.getItem(storageKey)) return;
      window.sessionStorage.setItem(storageKey, "shown");
    } catch { /* private browsing still receives the in-session broadcast */ }
    const timer = window.setTimeout(() => {
      setProgressBroadcastOpen(true);
      void playProgressCue(progressBroadcastTone);
    }, 120);
    return () => window.clearTimeout(timer);
  }, [sessionId, progressBroadcastId, progressBroadcastTone]);

  useEffect(() => {
    const savedToken = sessionStorage.getItem("qingjiang-csrf");
    if (savedToken) api.setCsrfToken(savedToken);
  }, [api]);

  const fail = (error: unknown) => {
    if (requiresAIConfiguration(error)) {
      setAiConfiguration(null);
      setAiError("请先测试并启用一个可用的 AI 接口。");
      setAuthStep("ai");
      setAuthOpen(true);
      setSessionOpen(false);
    }
    setNotice(playerErrorMessage(error));
  };

  function clearAuthenticatedClientState() {
    api.clearCsrf(csrfCookieName);
    api.setAccountId("");
    setAccount(""); setSessionId(""); setState({}); setCommands({});
    dispatchNarrative({ type: "CLEAR" }); setShowHistory(false);
    setPanel("scene"); setPanelData(null); setGovernance(null);
    setSessionOpen(false); setSavedSessionsOpen(false); setSavedSessions([]); setPendingSync(null);
    setSavedSessionsError(""); setFormOpen(null); setMeetingResolutionOpen(false);
    setGovernanceRecordOpen(null); setCharacterProfileOpen(null); setArchiveReadingOpen(null);
    setContractProposalOpen(null); setContractOpen(null);
    setProgressBroadcastOpen(false);
    setConfirmRequest(null);
    setConsentOpen(false); setConsentInfo(null); setConsentGranted(!modelConsentRequired); setConsentError("");
    setConversationInput(""); setNpcStream(initialNpcStreamState()); setNotice(""); setAuthMode("login");
    setAuthStep("account"); setAiConfiguration(null); setAiMode("personal");
    setAiError(""); setAiSuccess(""); setShowApiKey(false);
  }

  async function loadAIConfiguration(openWhenMissing = true) {
    try {
      const value = await api.aiConfiguration() as Dict;
      setAiConfiguration(value);
      setAiError("");
      const view = aiConfigurationView(value);
      setAiMode(aiConfigurationMode(value));
      if (!view.configured && openWhenMissing) {
        setAuthStep("ai");
        setAuthOpen(true);
        setSessionOpen(false);
      }
      return view.configured;
    } catch (error) {
      setAiConfiguration(null);
      setAiError(playerErrorMessage(error));
      if (openWhenMissing) {
        setAuthStep("ai");
        setAuthOpen(true);
        setSessionOpen(false);
      }
      return false;
    }
  }

  async function connect() {
    setBusy(true); setNotice("");
    try {
      await api.health();
      const ready = await api.ready();
      const requiresAuth = Boolean(ready.authentication_required);
      const cookieName = ready.csrf_cookie_name || "serious_game_session_csrf";
      setAuthRequired(requiresAuth);
      setSelfRegistration(Boolean(ready.self_registration));
      const requiresModelConsent = Boolean(ready.model_consent_required);
      setModelConsentRequired(requiresModelConsent);
      setCsrfCookieName(cookieName);
      setConnected(true);
      if (requiresAuth) {
        const restoredCsrf = api.restoreCsrf(cookieName);
        if (!restoredCsrf) {
          clearAuthenticatedClientState();
          setAuthError("");
          setAuthOpen(true);
        } else {
          try {
            const me = await api.me();
            api.setAccountId(me.account_id);
            setAccount(me.username || "已登录");
            const configured = await loadAIConfiguration(true);
            if (configured) {
              await loadConsent(requiresModelConsent);
              setAuthOpen(false);
            }
          } catch (error) {
            clearAuthenticatedClientState();
            setAuthError(playerErrorMessage(error));
            setAuthOpen(true);
          }
        }
      } else {
        api.enableSandboxAccount();
        setAccount("本地试玩");
        const configured = await loadAIConfiguration(true);
        if (configured) await loadConsent(requiresModelConsent);
      }
    } catch (error) { setConnected(false); fail(error); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void connect(), 0);
    return () => window.clearTimeout(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadConsent(required = modelConsentRequired, openWhenMissing = true) {
    if (!required) { setConsentGranted(true); setConsentOpen(false); return true; }
    try {
      const info = await api.consent() as Dict;
      const record = info.record as Dict | null;
      const granted = Boolean(record && !record.withdrawn_at && record.consent_version === info.required_version && values(record.scopes).includes("third_party_model"));
      setConsentInfo(info); setConsentGranted(granted); setConsentError(""); setConsentOpen(openWhenMissing && !granted);
      return granted;
    } catch (error) {
      setConsentGranted(false); setConsentError(playerErrorMessage(error)); setConsentOpen(openWhenMissing);
      return false;
    }
  }

  async function signModelConsent() {
    const version = String(consentInfo?.required_version || "");
    if (!version) return;
    setBusy(true); setConsentError("");
    try { await api.signConsent(version); await loadConsent(true); setNotice("模型处理授权已经记录，NPC 会谈现已开放"); }
    catch (error) { setConsentError(playerErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function withdrawModelConsent() {
    setBusy(true); setConsentError("");
    try { await api.withdrawConsent(); await loadConsent(true); setNotice("授权已撤回；重新同意前无法进行 NPC 会谈"); }
    catch (error) { setConsentError(playerErrorMessage(error)); }
    finally { setBusy(false); }
  }

  function confirmWithdrawModelConsent() {
    setConfirmRequest({
      title: "撤回模型授权",
      message: "撤回后，所有需要角色模型的会谈将暂停。你可以稍后重新授权。",
      confirmLabel: "确认撤回",
      danger: true,
      action: withdrawModelConsent,
    });
  }

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setAuthError("");
    const data = new FormData(event.currentTarget);
    try {
      const result = await api.auth(authMode, String(data.get("username")), String(data.get("password")));
      api.setCsrfToken(result.csrf_token, csrfCookieName);
      api.setAccountId(result.account_id);
      setAccount(result.username || "已登录");
      setAuthStep("ai"); setAuthOpen(true); setSessionOpen(false);
      await loadAIConfiguration(false);
      await loadConsent(modelConsentRequired, false);
    } catch (error) { setAuthError(playerErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function logoutAccount() {
    setBusy(true); setAuthError("");
    let logoutWarning = "";
    try {
      await api.logout();
    } catch (error) {
      // An expired server session is already logged out. Other failures must
      // not leave sensitive local state visible, but are still explained.
      if ((error as ApiError)?.status !== 401) {
        logoutWarning = playerErrorMessage(error);
      }
    } finally {
      clearAuthenticatedClientState();
      setAuthError(logoutWarning);
      setAuthOpen(true);
      setBusy(false);
    }
  }

  async function configureAI(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setAiError(""); setAiSuccess("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const value = await withAIActivity(setAiActivity, "正在测试接口所需的六项游戏能力", () => api.configureAI(aiMode === "server_default"
        ? { mode: "server_default" }
        : {
            mode: "personal",
            base_url: String(data.get("base_url") || ""),
            api_key: String(data.get("api_key") || ""),
            model: String(data.get("model") || ""),
          })) as Dict;
      setAiConfiguration(value);
      setAiSuccess(aiMode === "personal" ? "个人 AI 接口测试通过并已启用。" : "服务器默认 AI 接口已启用。");
      form.reset();
      setShowApiKey(false);
      await loadConsent(modelConsentRequired);
    } catch (error) {
      setAiError(aiConfigurationErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function continueAfterAIConfiguration() {
    if (!aiView.configured) return;
    if (modelConsentRequired && !consentGranted) {
      setConsentOpen(true);
      return;
    }
    setAuthOpen(false);
    if (!sessionId) setSessionOpen(true);
  }

  async function clearAIConfiguration() {
    setBusy(true); setAiError(""); setAiSuccess("");
    try {
      const value = await api.clearAIConfiguration() as Dict;
      setAiConfiguration(value);
      setAiSuccess("当前登录的个人接口已清除。");
      setAiMode("personal");
    } catch (error) {
      setAiError(playerErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function openGameEntry() {
    if (authRequired && !account) {
      setAuthStep("account"); setAuthOpen(true); return;
    }
    if (!aiView.configured) {
      setAuthStep("ai"); setAuthOpen(true); setSessionOpen(false); return;
    }
    setSessionOpen(true);
  }

  async function refresh(after = narrative.feedCursor, targetSession = sessionId, clearNotice = true, rebuild = false, rebuildPosition: "start" | "latest" = "start", requireGovernance = false) {
    if (!targetSession) return false;
    const releaseActivity = activityLatchRef.current.acquire();
    if (clearNotice) setNotice("");
    try {
      const [view, governanceOverview] = await Promise.all([
        api.view(targetSession, after) as Promise<Dict>,
        api.panel(targetSession, "governance").catch(error => { if (requireGovernance) throw error; return null; }),
      ]);
      const nextState = view.state || view.visible_state || view;
      setState(nextState); setCommands(view.commands || {});
      setGovernance(governanceOverview);
      const feed = view.feed || {};
      const incoming = arr(feed.items)
        .map((item, index) => {
          const line = narrativeItemFromFeed(item, `${targetSession}:${index}:${String(item.text || "")}`);
          return { ...line, text: playerText(line.text) };
        })
        .filter(isPlayerFacingLine);
      const nextCursor = typeof feed.cursor === "number" ? feed.cursor : undefined;
      if (rebuild) {
        const latestDay = nextState.story?.day ?? Math.max(0, ...incoming.map(item => item.storyDay || 0));
        const savedPosition = rebuildPosition === "latest" && typeof window !== "undefined"
          ? Number(window.localStorage.getItem(`qingjiang-read-position:v2:${targetSession}:${latestDay}`))
          : Number.NaN;
        dispatchNarrative({ type: "SESSION_REBUILD", sessionId: targetSession, items: incoming, cursor: nextCursor, storyDay: nextState.story?.day, pendingDecisionEntryId: nextState.pending_decision?.presentation_entry_id ?? null, position: Number.isInteger(savedPosition) && savedPosition >= 0 ? savedPosition : "start" });
      } else {
        dispatchNarrative({ type: "FEED_MERGE", sessionId: targetSession, items: incoming, cursor: nextCursor, storyDay: nextState.story?.day, pendingDecisionEntryId: nextState.pending_decision?.presentation_entry_id ?? null });
      }
      setPanelData(nextState); setPanel("scene");
      return true;
    } catch (error) { fail(error); return false; }
    finally { releaseActivity(); }
  }

  async function openSession(kind: "new" | "load" | "review", value?: string) {
    if (kind !== "review" && !aiView.configured) {
      setAuthStep("ai"); setAuthOpen(true); setSessionOpen(false);
      setAiError("开始或继续游戏前，请先测试并启用 AI 接口。");
      return;
    }
    if (kind !== "review" && modelConsentRequired && !consentGranted) { setConsentOpen(true); setSessionOpen(false); return; }
    setBusy(true); setNotice("");
    try {
      const result = kind === "new" ? await api.newSession(value) : await api.session(value || "");
      const id = String(result.session_id || get(result, "state.session_id") || value || "");
      if (!id) throw new ApiError("没有找到可继续的游戏进度。", "SESSION_NOT_FOUND", 404);
      setTutorialEntry(kind); setTutorialResult(null); setTutorialGeneration(value => value + 1);
      setPendingSync(null); setSessionId(id); dispatchNarrative({ type: "SESSION_OPEN", sessionId: id }); setShowHistory(false); setSessionOpen(false); setSavedSessionsOpen(false);
      if (!await refresh(0, id, true, true, kind === "load" ? "latest" : "start")) return;
      if (kind === "review") {
        setPanel("review");
        setPanelData(await api.panel(id, "review"));
        setNotice("该剧本包已退役，本进度仅可安全复盘。");
      }
    } catch (error) {
      if ((error as ApiError)?.code === "PACKAGE_RETIRED" && value) {
        const result = await api.session(value);
        const id = String(result.session_id || value);
        setTutorialEntry("review"); setTutorialResult(null); setTutorialGeneration(value => value + 1);
        setPendingSync(null); setSessionId(id); dispatchNarrative({ type: "SESSION_OPEN", sessionId: id });
        setSessionOpen(false); setSavedSessionsOpen(false);
        if (!await refresh(0, id, false, true, "start")) return;
        setPanel("review"); setPanelData(await api.panel(id, "review"));
        setNotice("该剧本包已退役，本进度仅可安全复盘。");
      } else fail(error);
    }
    finally { setBusy(false); }
  }

  async function showSavedSessions() {
    setSavedSessionsOpen(true); setSavedSessionsError(""); setBusy(true);
    try { const result = await api.sessions(); setSavedSessions(arr(result.sessions)); }
    catch (error) { setSavedSessionsError(playerErrorMessage(error)); }
    finally { setBusy(false); }
  }

  const [signingOnly, setSigningOnly] = useState(false);

  async function loadPanel(name: PanelName, signing = false) {
    setSigningOnly(signing);
    setPanel(name); setNotice("");
    const revealOnMobile = () => {
      if (window.matchMedia("(max-width: 780px)").matches) window.requestAnimationFrame(() => contextRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    };
    if (name === "scene") { setPanelData(state); revealOnMobile(); return; }
    setBusy(true);
    try { setPanelData(await api.panel(sessionId, name)); }
    catch (error) { fail(error); setPanelData(null); }
    finally { setBusy(false); revealOnMobile(); }
  }

  async function openNextStep(step: NextStep) {
    if (busy || step.unavailable_reason) return;
    if (contractDirty.current && !window.confirm("方案有修改尚未保存，确定放弃修改并查看办理入口？")) return;
    setBusy(true); setNotice("");
    try {
      const actions = await api.panel(sessionId, "actions");
      const descriptor = actionForNextStep(actions, step);
      if (!descriptor || descriptor.available === false) {
        setNotice(playerText(descriptor?.unavailable_reason, "当前无法直接进入这项办理，请核对行动页的开放条件和材料状态。"));
        return;
      }
      contractDirty.current = false; setContractOpen(null);
      setFormOpen({ title: governanceDisplayTitle(descriptor, step.label), kind: "resource", item: descriptor });
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  }

  async function perform(action: () => Promise<Dict>, success: string | ((result: Dict) => string) = "安排已落实", rebuildNarrative = false, onResult?: (result: Dict) => void, aiLabel = "") {
    return performSingleFlightRef.current(async () => {
      if (pendingSync?.sessionId === sessionId) {
        setNotice("上次操作已保存，请先重新同步现场后再继续办理。");
        return false;
      }
      const releaseActivity = activityLatchRef.current.acquire();
      setNotice("");
      try {
        const result = await (aiLabel ? withAIActivity(setAiActivity, aiLabel, action) : action());
        // The write response already contains authoritative option availability.
        // Preserve it even when the subsequent feed refresh cannot be fetched.
        if (result.visible_state) setState(result.visible_state);
        onResult?.(result);
        setFormOpen(null);
        setConversationInput(""); setReferenceIds([]);
        const recovery = { sessionId, after: rebuildNarrative ? 0 : narrative.feedCursor, rebuild: rebuildNarrative, panel };
        try {
          const synced = await refresh(recovery.after, sessionId, false, rebuildNarrative, rebuildNarrative ? "latest" : "start", true);
          if (!synced) throw new Error("现场同步尚未完成");
          if (panel !== "scene") {
            const nextPanel = await api.panel(sessionId, panel);
            setPanel(panel); setPanelData(nextPanel);
          }
        } catch {
          setPendingSync(recovery);
          setNotice("本次操作已保存，但现场同步失败。请重新同步，无需再次提交。");
          return false;
        }
        setPendingSync(null);
        setNotice(typeof success === "function" ? success(result) : success);
        return true;
      }
      catch (error) {
        const apiError = error as ApiError;
        if (apiError?.code === "STATE_VERSION_CONFLICT") {
          if (await refresh(0, sessionId, false, true, "latest")) setNotice("现场情况刚刚更新，请根据最新信息重新选择。");
        } else if (apiError?.code === "ACTION_UNAVAILABLE" && apiError.details?.action_instance_id) {
          setFormOpen(null);
          if (await refresh(0, sessionId, false, true, "latest")) setNotice("已有一项治理行动正在进行，已为你切换到当前现场。");
        } else if (["CLIENT_STREAM_TIMEOUT", "CLIENT_STREAM_INCOMPLETE"].includes(apiError?.code)) {
          await refresh(0, sessionId, false, true, "latest");
          fail(error);
        } else fail(error);
      }
      finally { releaseActivity(); }
      return false;
    });
  }

  async function retrySavedSync() {
    if (!pendingSync || pendingSync.sessionId !== sessionId || busy) return;
    const recovery = pendingSync;
    const releaseActivity = activityLatchRef.current.acquire();
    try {
      if (!await refresh(recovery.after, recovery.sessionId, false, recovery.rebuild, recovery.rebuild ? "latest" : "start", true)) return;
      if (recovery.panel !== "scene") {
        const nextPanel = await api.panel(recovery.sessionId, recovery.panel);
        setPanel(recovery.panel); setPanelData(nextPanel);
      }
      setPendingSync(null);
      setNotice("现场已同步，已保存的操作无需重复提交。");
    } catch { setNotice("操作已保存，现场仍未同步成功，请稍后再次同步。"); }
    finally { releaseActivity(); }
  }

  function openCanonicalAction(raw: Dict, fallbackTitle: string) {
    const item = canonicalActionEntry(raw) as Dict | null;
    if (!item) {
      setNotice("当前入口没有可安全执行的统一行动描述，请刷新后重试。");
      return;
    }
    setNotice("");
    setFormOpen({ title: governanceDisplayTitle(item, fallbackTitle), kind: "resource", item });
  }

  function applyNpcStreamEvent(event: NpcStreamEvent) {
    setNpcStream(current => reduceNpcStream(current, event as Dict));
  }

  async function performNpcStream(
    action: (onEvent: (event: NpcStreamEvent) => void) => Promise<Dict>,
    success: string | ((result: Dict) => string),
    onResult?: (result: Dict) => void,
  ) {
    setNpcStream(reduceNpcStream(initialNpcStreamState(), { type: "request_started" }));
    const completed = await perform(() => action(applyNpcStreamEvent), success, false, onResult, "正在生成人物回应");
    setNpcStream(initialNpcStreamState());
    return completed;
  }

  async function submitDecision(option: Dict) {
    const pending = state.pending_decision || {};
    await perform(() => api.action(sessionId, {
      input_mode: "decision", client_action_id: api.key("decision"), state_version: state.state_version,
      decision_id: pending.decision_id, option_id: option.option_id,
    }), "");
  }

  async function nextNarrative() {
    if (busy) return;
    if (hasMoreSegments) { setSegmentSelection({ key: segmentKey, index: segmentIndex + 1 }); return; }
    if (narrative.currentIndex < narrative.items.length - 1) {
      dispatchNarrative({ type: "NEXT" });
    } else if (commands.can_continue_story) {
      await perform(() => api.write(sessionId, "/story/continue", "POST", {
        client_action_id: api.key("story-continue"), state_version: state.state_version,
      }), "");
    }
  }

  async function endDay() {
    if (!commands.can_end_day || hasMoreSegments || !narrativeReadingComplete(narrative)) { setNotice("请先读完当前剧情，再结束今日。"); return; }
    const completed = await perform(() => api.write(sessionId, "/end-day", "POST", {
      client_action_id: api.key("end-day"), state_version: state.state_version, active_rest: false,
    }), "夜间结算完成，新一天已经开始", false, undefined, "正在推演夜间人物行动与新一天局势");
    if (completed) {
      setPanel("scene");
      setTutorialResult("morning");
      setTutorialResultNotice("夜间结算完成，新一天已经开始");
    }
  }

  async function submitConversation(event: FormEvent) {
    event.preventDefault();
    const text = String(
      new FormData(event.currentTarget as HTMLFormElement).get("player_text") || conversationInput,
    ).trim();
    if (!text) return;
    const group = state.active_group_conversation;
    const conversation = state.active_conversation;
    if (group) {
      await performNpcStream(onEvent => api.streamWrite(sessionId, "/group-conversation/turn/stream", {
        client_action_id: api.key("group-turn"), state_version: state.state_version, player_text: text, ...(referenceIds.length ? { reference_ids: referenceIds } : {}),
      }, onEvent), result => result.input_rejected
        ? playerText(result.message, "这句话没有送达，请围绕当前议题继续交流。")
        : "你的回应已经传达给在场各方");
    } else if (conversation) {
      await performNpcStream(onEvent => api.streamWrite(sessionId, "/action/stream", {
        input_mode: "free_text", client_action_id: api.key("talk"), state_version: state.state_version,
        conversation_id: conversation.conversation_id, opportunity_id: conversation.opportunity_id,
        target_npc_id: conversation.npc_id || conversation.target_npc_id, player_text: text, ...(referenceIds.length ? { reference_ids: referenceIds } : {}),
      }, onEvent), "你的话已经传达");
    }
  }

  async function leaveConversation() {
    const conversation = state.active_conversation;
    if (!conversation) return;
    const completed = await perform(() => api.action(sessionId, {
      input_mode: "conversation_end", client_action_id: api.key("conversation-end"), state_version: state.state_version,
      conversation_id: conversation.conversation_id,
    }), "会谈已经结束");
    if (completed) { setTutorialResult("action-result"); setTutorialResultNotice("会谈已经结束"); }
  }

  const activeGovernanceAction = arr(governance?.governance_actions).find(item => item.status === "active") || null;
  const activeMeeting = activeGovernanceAction?.action_kind === "leadership_meeting"
    ? arr(governance?.meetings).find(item => item.action_instance_id === activeGovernanceAction.action_instance_id) || null
    : null;
  const activeGovernanceLabels = governanceActionProgressLabels(
    activeGovernanceAction,
    governanceDisplayTitle(activeGovernanceAction, GOVERNANCE_ACTION_LABELS[activeGovernanceAction?.action_kind] || "治理行动"),
  );
  const activeContractWorkflow = conversationContractWorkflow(
    activeGovernanceAction,
    governance?.contract_batches,
    governance?.contracts,
  );
  const activeConversationCharacter = state.active_conversation
    ? resolveCharacter(state.active_conversation.npc_id, state.active_conversation.target_npc_id, state.active_conversation.npc_name)
    : null;
  const activeConversationName = state.active_conversation
    ? activeConversationCharacter?.name
      || playerText(state.active_conversation.npc_name)
      || playerText(arr(get(governance, "target_catalogs.meeting_participants")).find(item => item.target_id === state.active_conversation.npc_id)?.label, "对方")
    : "";

  async function submitGovernanceTurn(event: FormEvent) {
    event.preventDefault();
    const text = String(
      new FormData(event.currentTarget as HTMLFormElement).get("player_text") || conversationInput,
    ).trim();
    if (!text || !activeGovernanceAction) return;
    if (activeMeeting) {
      await performNpcStream(onEvent => api.streamWrite(sessionId, `/governance/meetings/${encodeURIComponent(String(activeMeeting.meeting_id))}/turn/stream`, {
        client_action_id: api.key("meeting-turn"), state_version: state.state_version, player_text: text, addressed_npc_id: null, ...(referenceIds.length ? { reference_ids: referenceIds } : {}),
      }, onEvent), "你的意见已经传达给全体参会人员");
      return;
    }
    await performNpcStream(onEvent => api.streamWrite(sessionId, `/governance/actions/${encodeURIComponent(String(activeGovernanceAction.action_instance_id))}/turn/stream`, {
      client_action_id: api.key("governance-turn"), state_version: state.state_version, player_text: text, ...(referenceIds.length ? { reference_ids: referenceIds } : {}),
    }, onEvent), result => result.input_rejected
      ? playerText(result.message, "这句话没有送达，请说明你想了解的具体问题。")
      : result.contract_batch_proposal
        ? "对方已经愿意进入合同流程，可点击下方“签订合同”继续。"
        : "你的询问已经得到回应");
  }

  async function openContractDetail(contract: Dict) {
    const contractId = String(contract.contract_id || "");
    if (!contractId) return;
    setBusy(true); setNotice("");
    try {
      const result = await api.contractDetail(sessionId, contractId) as Dict;
      setContractOpen(result.contract || contract);
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  }

  async function prepareContracts() {
    if (!activeGovernanceAction) return;
    await perform(() => api.write(sessionId, `/governance/actions/${encodeURIComponent(String(activeGovernanceAction.action_instance_id))}/prepare-contracts`, "POST", { state_version: state.state_version }), "", false, result => setContractProposalOpen(result.batch));
  }

  async function confirmContractBatch(confirmed: boolean) {
    const batchId = String(contractProposalOpen?.batch_id || "");
    if (!batchId) return;
    await perform(() => api.write(sessionId, `/governance/contract-batches/${encodeURIComponent(batchId)}/confirm`, "POST", {
      state_version: state.state_version, confirmed,
    }), confirmed ? "逐户合同已经建立，请分别核定条款并完成签署" : "本次合同提议已撤回", false, result => {
      setContractProposalOpen(null);
      const first = arr(result.contracts)[0];
      if (first) setContractOpen(first);
    });
  }

  async function performContractAction(action: () => Promise<Dict>, success: string, aiLabel = "") {
    await perform(action, success, false, result => {
      if (result.contract) setContractOpen(result.contract);
    }, aiLabel);
  }

  async function finishGovernanceAction() {
    if (!activeGovernanceAction) return;
    if (activeMeeting) {
      if (!arr(activeMeeting.transcript).length) {
        setNotice(`${actionPresentation(activeGovernanceAction).title}需要先完成公开讨论，再形成结论。`);
        return;
      }
      setNotice("");
      setMeetingResolutionOpen(true);
      return;
    }
    setConfirmRequest({ title: "结束本次行动", message: "确认结束本次交流？已获得的信息和已发生的对话会保留，已消耗的精力不退还。系统会根据实际交流进展判断是否完成任务。", confirmLabel: "确认结束", action: async () => {
      const completed = await perform(() => api.write(sessionId, `/governance/actions/${encodeURIComponent(String(activeGovernanceAction.action_instance_id))}/finish`, "POST", {
        state_version: state.state_version,
      }), governanceFinishMessage(activeGovernanceAction));
      if (completed) { setTutorialResult("action-result"); setTutorialResultNotice(governanceFinishMessage(activeGovernanceAction)); }
    } });
  }

  async function submitMeetingResolution(resolution: Dict) {
    if (!activeMeeting) return;
    const presentation = actionPresentation(activeGovernanceAction);
    const resultNotice = `${presentation.title}结果已收入卷宗，请核对结论与各方意见`;
    const succeeded = await perform(() => api.write(sessionId, `/governance/meetings/${encodeURIComponent(String(activeMeeting.meeting_id))}/resolve`, "POST", {
      state_version: state.state_version,
      adopt: true,
      resolution,
    }), resultNotice, false, () => setMeetingResolutionOpen(false), presentation.leadership ? "正在汇总班子意见并生成、审校会议文件" : `正在汇总${presentation.title}意见与结论`);
    if (succeeded) { setMeetingResolutionOpen(false); setTutorialResult("action-result"); setTutorialResultNotice(resultNotice); }
  }

  async function performDocumentAction(documentId: string, suffix: string, method: "POST" | "PUT", body: Dict, success: string) {
    let result: Dict | null = null;
    const succeeded = await perform(async () => {
      result = await api.write(sessionId, `/governance/documents/${encodeURIComponent(documentId)}${suffix}`, method, {
        state_version: state.state_version,
        ...body,
      });
      return result;
    }, success, false, response => {
      if (response.document) setGovernanceRecordOpen(current => ({ ...current, document: response.document }));
    }, suffix === "/countersign"
      ? "正在生成会签意见"
      : suffix === "" ? "正在审校并修订行政文书" : "");
    if (!succeeded) return;
    const response = result as Dict | null;
    if (response?.accepted === false) setNotice(`会签未通过：${playerText(response.reason, "会签人对当前文本仍有异议")}`);
    try {
      const overview = await api.panel(sessionId, "governance");
      setGovernance(overview);
      const nextDocument = arr(overview.documents).find(item => String(item.document_id) === documentId) || response?.document;
      const meetingId = String(nextDocument?.source_meeting_id || governanceRecordOpen?.meeting?.meeting_id || "");
      const nextMeeting = arr(overview.meetings).find(item => String(item.meeting_id) === meetingId) || governanceRecordOpen?.meeting;
      setGovernanceRecordOpen({ document: nextDocument, meeting: nextMeeting });
    } catch {
      if (response?.document) setGovernanceRecordOpen(current => ({ ...current, document: response.document }));
    }
  }

  async function finishGroupConversation() {
    const group = state.active_group_conversation;
    if (!group || group.phase !== "resolved") return;
    const completed = await perform(() => api.write(sessionId, "/group-conversation/finish", "POST", {
      client_action_id: api.key("group-finish"), state_version: state.state_version,
    }), "夜间会谈已经归档，次晨简报已恢复");
    if (completed) { setTutorialResult("morning"); setTutorialResultNotice("夜间会谈已经归档，次晨简报已恢复"); }
  }

  function confirmEndDay() {
    if (!commands.can_end_day || hasMoreSegments || !narrativeReadingComplete(narrative)) { setNotice("请先读完当前剧情，再结束今日。"); return; }
    setConfirmRequest({
      title: "结束今日工作",
      message: "确认结束今天的工作并进入夜间结算？尚未使用的精力不会保留到明天。",
      confirmLabel: "进入夜间结算",
      action: endDay,
    });
  }

  async function openArchiveDetail(archive: Dict) {
    const archiveId = String(archive.archive_id || "");
    if (!archiveId) return;
    setBusy(true); setNotice("");
    try {
      const result = await api.archiveDetail(sessionId, archiveId) as Dict;
      setArchiveReadingOpen({ records: arr(result.archive ? [result.archive] : []) });
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  }

  async function cancelGovernanceAction() {
    if (!activeGovernanceAction) return;
    await perform(() => api.write(sessionId, `/governance/actions/${encodeURIComponent(String(activeGovernanceAction.action_instance_id))}/cancel`, "POST", {
      state_version: state.state_version,
    }), "当前行动已经终止");
  }

  function confirmCancelGovernanceAction() {
    if (!activeGovernanceAction) return;
    setConfirmRequest({
      title: "终止当前行动",
      message: governanceCancelMessage(activeGovernanceAction),
      confirmLabel: "确认终止",
      danger: true,
      action: cancelGovernanceAction,
    });
  }

  const savedSyncNotice = pendingSync?.sessionId === sessionId ? <div className="saved-sync-recovery" role="alert"><strong>操作已保存，现场尚未同步</strong><p>请先重新同步后继续办理。同步只读取最新进度，不会重复提交、扣款或消耗精力。</p><button type="button" disabled={busy} onClick={() => void retrySavedSync()}>{busy ? "正在同步…" : "重新同步现场"}</button></div> : null;
  const story = state.story || {}; const ledger = state.ledger || {}; const indicators = state.indicators || {};
  const pending = state.pending_decision || null; const options = arr(pending?.options);
  const currentEnding = state.session_id === sessionId ? state.ending_result || state.ending || null : null;
  const signed = displayValue(currentEnding?.signed_households ?? get(ledger, "relocation.signed", get(ledger, "signed_households.signed", typeof ledger.signed_households === "number" ? ledger.signed_households : "待核实")), "待核实");
  const total = displayValue(currentEnding?.total_households ?? get(ledger, "relocation.total", get(ledger, "signed_households.total", 36)), 36);
  const actionPoints = displayValue(get(state, "action_points.remaining", get(ledger, "action_points.remaining", "待定")));
  const dailyCap = displayValue(get(state, "action_points.daily_cap", get(ledger, "action_points.daily_cap", 8)), 8);
  const budget = displayValue(get(ledger, "budget.available", get(ledger, "budget.remaining", "待定")));
  const publicTrust = displayValue(get(indicators, "public_trust.label", get(indicators, "public_trust", "未判定")), "未判定");
  const socialStability = displayValue(get(indicators, "social_stability.label", get(indicators, "social_stability", "未判定")), "未判定");
  const mediaPressure = displayValue(get(indicators, "media_pressure.label", get(indicators, "media_pressure", "未判定")), "未判定");
  const cadreDiscontent = displayValue(get(indicators, "cadre_discontent.label", get(indicators, "cadre_discontent", "未判定")), "未判定");
  const readingCommands = { ...commands, can_end_day: Boolean(commands.can_end_day) && !commands.can_continue_story && !hasMoreSegments && narrativeReadingComplete(narrative) };
  const playerLines = narrative.items;
  const currentLine = displaySegments[segmentIndex] || null;
  const decisionReady = Boolean(pending) && pendingDecisionIsReady(currentLine, pending?.presentation_entry_id);
  const visibleHistoryLines = [...narrative.historyItems, ...playerLines].flatMap(line => dialogueSegments(line));
  const currentScene = resolveSceneForView({
    line: currentLine || undefined,
    lines: playerLines,
    currentIndex: narrative.currentIndex,
    itemCount: playerLines.length,
    currentStoryDay: story.day,
    decisionId: decisionReady ? pending?.decision_id : undefined,
    pendingSceneId: activeGovernanceAction && arr(activeGovernanceAction.hard_outcomes).some(item => item.kind === "contract_fact" && item.id === "real_unit_viewed")
      ? "C06_S10" : decisionReady ? pending?.scene_id : currentLine?.displaySceneId,
    mainEndingId: get(state, "ending.main_ending_id") || get(state, "ending_result.main_ending_id") || state.main_ending_id,
    beatId: get(state, "story.beat_id") || get(state, "story.story_beat_id") || state.story_beat_id,
  });
  const latestStreamingReply = streamingReplies.length ? streamingReplies[streamingReplies.length - 1] : null;
  const thinkingNpcs = Object.entries(npcStream.thinking).map(([streamId, identity]) => ({ stream_id: streamId, ...identity }));
  const conversationStreamingReply = state.active_conversation ? latestStreamingReply : null;
  const lineCharacter = currentLine?.speaker ? resolveCharacter(currentLine.speaker) : null;
  const conversationOpening = currentLine?.kind === "conversation_opening" && Boolean(state.active_conversation);
  const stageCharacter = conversationStreamingReply
    ? resolveCharacter(conversationStreamingReply.npc_id, conversationStreamingReply.npc_name)
    : currentLine?.speaker ? lineCharacter : conversationOpening || !currentLine && state.active_conversation ? activeConversationCharacter : null;
  const stageSpeaker = conversationStreamingReply
    ? playerText(conversationStreamingReply.npc_name, activeConversationName || "对方")
    : currentLine?.speaker ? playerText(currentLine.speaker) : conversationOpening || !currentLine && state.active_conversation ? activeConversationName : "";
  const stageText = playerText(conversationStreamingReply?.text) || (currentLine ? playerText(currentLine.text) : pending ? "请阅读当前事项并作出决定。" : "案头暂时平静。可以从行动、会谈或卷宗继续推进。");
  const activeConversation = state.active_conversation || state.active_group_conversation;
  const interactionMode = activeInteractionMode(state, activeGovernanceAction);
  const primaryScene = primaryScenePlan({
    has_session: Boolean(sessionId),
    active_governance_action: activeGovernanceAction,
    active_meeting: activeMeeting,
    active_group_conversation: state.active_group_conversation,
    active_conversation: state.active_conversation,
  })[0];

  const thinkingLabel = thinkingNpcs.length > 0
    ? `${thinkingNpcs.map(person => resolveCharacter(person.npc_id, person.npc_name)?.name || playerText(person.npc_name, "在场人物")).join("、")}正在回应`
    : aiActivity?.label || "正在理解现场并组织回应";

  const tutorialContext: TutorialContext = {
    accountId: api.accountId,
    sessionId,
    entryKind: tutorialEntry,
    panel,
    readOnly: tutorialEntry === "review" || state.status === "ended" || state.status === "completed",
    blocked: busy || Boolean(aiActivity) || npcStream.requestPending || thinkingNpcs.length > 0
      || authOpen || consentOpen || sessionOpen || Boolean(confirmRequest) || progressBroadcastOpen
      || Boolean(characterProfileOpen) || Boolean(contractProposalOpen) || meetingResolutionOpen,
    contractStage: contractOpen && contractTutorialState && contractTutorialState.id === contractOpen.contract_id ? contractTutorialState.stage : null,
    contractId: contractOpen?.contract_id,
    form: formOpen?.item || null,
    actions: panel === "actions" && !busy ? canonicalActionFamilies(panelData?.actions || panelData?.items || panelData) : [],
    scene: archiveReadingOpen ? "archive-result" : contractOpen ? "contract" : governanceRecordOpen ? governanceRecordOpen.document ? "document" : "action-result"
      : activeMeeting ? activeGovernanceAction?.variant_id === "public_hearing" ? "hearing" : activeGovernanceAction?.variant_id === "clan_leader_campaign" ? "clan" : "meeting" : activeGovernanceAction ? "governance"
      : state.active_group_conversation ? state.active_group_conversation.phase === "resolved" ? null : "group" : state.active_conversation ? "conversation"
      : decisionReady ? "decision" : tutorialResult && notice === tutorialResultNotice ? tutorialResult
      : readingCommands.can_end_day ? "end-day" : null,
  };

  return <TutorialProvider key={`${api.accountId}:${sessionId}:${tutorialGeneration}`} context={tutorialContext} onNavigate={name => loadPanel(name as PanelName)}><main className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="seal">清</span><div><h1>浊流之上</h1><p>县域治理情境模拟</p></div></div>
      <div className="top-status">
        <TutorialButton />
        {sessionId && <EndingExperience ending={currentEnding} accountId={api.accountId} sessionId={sessionId} blocked={tutorialContext.blocked || Boolean(contractOpen || archiveReadingOpen || governanceRecordOpen || formOpen)} onReview={() => { void loadPanel("review"); }} />}
        <span className={connected ? "online" : "offline"}><i />{connected ? "游戏已就绪" : "正在连接"}</span>
        {progressBroadcast && <button className="broadcast-reopen" onClick={() => { setProgressBroadcastOpen(true); void playProgressCue(progressBroadcastTone); }}>第 {progressBroadcast.story_day} 日督办</button>}
        <button onClick={openGameEntry} disabled={busy}>{sessionId ? `第 ${story.day || 1} 日 · 游戏进度` : authRequired && !account ? "登录" : "进入游戏"}</button>
        <button className="avatar" onClick={() => { setAuthStep("account"); setAuthOpen(true); }} aria-label="账号与身份">{account ? account.slice(0, 1).toUpperCase() : "?"}</button>
      </div>
    </header>

    {(aiActivity || npcStream.requestPending || thinkingNpcs.length > 0) && <AIThinkingBanner label={thinkingLabel} />}

    <aside className="rail" aria-label="游戏导航">
      {NAV.map(item => <button data-tutorial-id={"nav-" + item.id} key={item.id} className={panel === item.id ? "active" : ""} onClick={() => loadPanel(item.id)} disabled={!sessionId}><b>{item.label}</b><em>{item.hint}</em></button>)}
    </aside>

    <section className="workspace" data-state-version={state.state_version}>
      <div data-tutorial-id="metrics" className="metric-strip" aria-label="当前治理状态">
        <div><small>当前日期</small><strong>第 {displayValue(story.day)} 日</strong><em>余 {Math.max(0, 90 - Number(story.day || 0))} 日</em></div>
        <div><small>今日精力</small><strong>{actionPoints}</strong><em>/ {dailyCap} 点</em></div>
        <div><small>财政余额</small><strong>{budget}</strong><em>万元</em></div>
        <div><small>签约进度</small><strong>{signed}</strong><em>/ {total} 户</em></div>
        <div><small>社会稳定</small><strong>{socialStability}</strong><em>当前态势</em></div>
        <div><small>舆论压力</small><strong>{mediaPressure}</strong><em>当前态势</em></div>
        <div><small>班子情绪</small><strong>{cadreDiscontent}</strong><em>当前态势</em></div>
        <div><small>群众信任</small><strong>{publicTrust}</strong><em>当前态势</em></div>
        <button data-tutorial-id="advance-signing" className="metric-signing" disabled={busy} onClick={() => void loadPanel("opportunities", true)}>推进签约</button>
      </div>

      <div className="main-grid">
        <section className="story-card">
          <Image key={currentScene.asset} className="scene-backdrop" src={currentScene.asset} alt={currentScene.title} fill priority sizes="(max-width: 980px) 100vw, 70vw" unoptimized />
          <div className="story-head"><div><small>县长手记 · 第 {displayValue(primaryScene === "narrative" ? currentLine?.storyDay || story.day : story.day, "待定")} 日</small><h2>{sessionId ? currentScene.title : "一纸调令，九十天限期"}</h2></div></div>
          <div data-tutorial-id={tutorialContext.scene === "morning" ? "morning" : undefined} className="story-scroll" ref={storyScrollRef} aria-live="polite" data-scene-match={currentScene.matchedBy}>
            {notice && !(activeConversation || (activeGovernanceAction && !activeMeeting)) && <div className="notice" role="status"><b>案头提醒</b><span>{notice}</span></div>}
            {!sessionId && <div className="welcome-block"><span className="eyebrow">云溪县 · 柳林村搬迁专班</span><h2>你有九十天，处理一场正在失控的搬迁。</h2><p>三十六户人家、八千万元预算，还有一条没人愿意说透的旧账。你的每次会谈、批示、承诺和沉默，都会留下痕迹。</p><p className="currency-notice" role="note">剩余的财政余额能兑换百晓智能“通晓币”，详情xxx</p><div className="welcome-credits"><small>开发：杨钞越　剧情：吉瑞新　美术：章钊林　指导：蒋俊彦、高翔</small></div><div className="welcome-action"><button onClick={openGameEntry} disabled={busy}>{authRequired && !account ? "登录后赴任" : "接下调令，前往云溪"}</button></div></div>}
            {(primaryScene === "narrative" || primaryScene === "conversation") && <section className={activeConversation ? "gal-stage conversation-mode" : decisionReady ? "gal-stage decision-mode" : "gal-stage"} data-primary-scene={primaryScene} data-testid={state.active_conversation ? "active-conversation-character" : undefined}>
              {stageSpeaker && <div className="gal-portrait" aria-label={`${stageSpeaker}立绘`}><CharacterPortrait character={stageCharacter} fallbackName={stageSpeaker} priority /></div>}
              <div className={stageSpeaker ? "gal-dialogue has-speaker" : "gal-dialogue narration"}>
                <header><span>{decisionReady ? "当前必须作出决定" : stageSpeaker || (currentLine ? "县长手记" : "现场暂歇")}</span><small>{playerLines.length ? `第 ${currentLine?.storyDay || story.day} 日 · ${Math.max(1, narrative.currentIndex + 1)} / ${playerLines.length + (commands.can_continue_story ? Number(commands.remaining_story_items || 0) : 0)}` : "等待新消息"}{displaySegments.length > 1 ? ` · 本段 ${segmentIndex + 1}/${displaySegments.length}` : ""}</small></header>
                {decisionReady && pending ? <div data-tutorial-id="decision" className="decision-stage-inline"><h3>{playerText(pending.title || pending.prompt || pending.situation, "当前事项需要你的决定")}</h3>{pending.description && <p>{playerText(pending.description)}</p>}{["sorting", "allocation"].includes(pending.input_kind) ? <StructuredDecision key={pending.decision_id} pending={pending} busy={busy} onSubmit={async payload => { await perform(() => api.action(sessionId, { input_mode: "decision", client_action_id: api.key("decision"), state_version: state.state_version, decision_id: pending.decision_id, ...payload }), ""); }} /> : <div className="decision-options">{options.map((option, index) => {
                  const requirements = nextSteps(option.next_steps).length ? [] : decisionUnlockRequirements(option);
                  const locked = option.available === false;
                  return <section className={locked ? "decision-option locked" : "decision-option"} key={option.option_id || index}><button onClick={() => submitDecision(option)} disabled={busy || locked}><span>{chineseIndex(index)}</span><div><b>{playerText(option.text || option.label, `方案${chineseIndex(index)}`)}</b>{option.description && <small>{playerText(option.description)}</small>}</div><i>{locked ? "条件不足" : "采纳"}</i></button>{locked && option.unavailable_reason && <p className="decision-blocked-reason">{playerText(option.unavailable_reason)}</p>}{locked && requirements.length > 0 && <div className="decision-unlock-guidance"><b>证据条件尚未满足</b><ul>{requirements.map(requirement => <li key={`${requirement.archiveName}:${requirement.reason}`}>《{requirement.archiveName}》{requirement.reason ? `：${requirement.reason}` : "：请核对当前要求的材料状态。"}</li>)}</ul><button type="button" onClick={() => void loadPanel("actions")}>前往查档</button></div>}{locked && <NextStepGuidance steps={option.next_steps} busy={busy} onOpen={openNextStep} />}</section>;
                })}</div>}</div> : <p>{stageText}{conversationStreamingReply && !conversationStreamingReply.complete && <i className="stream-cursor" aria-hidden="true" />}</p>}
                <nav data-tutorial-id="narrative-controls" className="narrative-controls" aria-label="剧情阅读控制">
                  <button onClick={() => {
                    if (segmentIndex > 0) { setSegmentSelection({ key: segmentKey, index: segmentIndex - 1 }); return; }
                    const previous = playerLines[narrative.currentIndex - 1];
                    if (previous) setSegmentSelection({ key: `${sessionId}:${narrative.rebuildCount}:${previous.id}:${previous.text}`, index: dialogueSegments(previous).length - 1 });
                    dispatchNarrative({ type: "PREVIOUS" });
                  }} disabled={narrative.currentIndex <= 0 && segmentIndex === 0}>上一段</button>
                  <button onClick={() => void nextNarrative()} disabled={busy || (!hasMoreSegments && narrative.currentIndex >= playerLines.length - 1 && !commands.can_continue_story)}>下一段</button>
                  <button className="history-toggle" onClick={() => setShowHistory(value => !value)}>{showHistory ? "关闭回看" : "剧情回看"}</button>
                </nav>
              </div>
            </section>}
            {sessionId && showHistory && <section className="history-drawer" aria-label="剧情回看"><header><h3>剧情回看</h3><button onClick={() => setShowHistory(false)}>关闭</button></header><div>{visibleHistoryLines.map(line => <article key={line.id}><small>第 {line.storyDay || "?"} 日 · {line.speaker ? playerText(line.speaker) : "旁白"}</small><span>{playerText(line.text)}</span></article>)}</div></section>}
            {primaryScene === "forced_group_conversation" && <ForcedGroupConversationScene conversation={state.active_group_conversation} streamingReplies={streamingReplies} />}
            {primaryScene === "governance_action" && activeGovernanceAction && <GovernanceActionScene action={activeGovernanceAction} overview={governance} streamingReplies={streamingReplies} />}
            {primaryScene === "leadership_meeting" && activeGovernanceAction && activeMeeting && <LeadershipMeetingScene action={activeGovernanceAction} meeting={activeMeeting} overview={governance} streamingReplies={streamingReplies} />}
          </div>
          <PlayerActionBar referenceDocuments={availableReferenceDocuments} referenceIds={referenceIds} onReferenceIds={setReferenceIds} referenceError={referenceError} state={state} commands={readingCommands} busy={busy} waitingForAI={npcStream.requestPending || thinkingNpcs.length > 0} notice={notice} pending={pending} decisionReady={decisionReady} interactionMode={interactionMode} governanceAction={activeGovernanceAction} meeting={activeMeeting} contractAvailable={Boolean(activeContractWorkflow)} contractPreparation={governance?.active_contract_preparation} onPrepareContracts={() => void prepareContracts()} conversationName={activeConversationName} value={conversationInput} onChange={setConversationInput} onSubmit={interactionMode === "governance" ? submitGovernanceTurn : submitConversation} onOpenContract={() => { if (activeContractWorkflow?.proposal) setContractProposalOpen(activeContractWorkflow.proposal); else if (activeContractWorkflow?.contract) void openContractDetail(activeContractWorkflow.contract); }} onLeave={leaveConversation} onFinishGroup={finishGroupConversation} onFinishGovernance={finishGovernanceAction} onCancelGovernance={confirmCancelGovernanceAction} onNavigate={loadPanel} onEndDay={confirmEndDay} />
        </section>

        <aside data-tutorial-id="today" className="context-panel" ref={contextRef}>
          <div className="panel-head"><div><small>云溪县政府 · 案头</small><h2>{PANEL_TITLES[panel]}</h2></div>{busy && <span className="sync-state" aria-live="polite">正在整理</span>}</div>
          <div className="panel-body">
            {sessionId && <PlayerIdentityCard />}
            {panel === "scene" && <SceneSummary state={state} commands={readingCommands} requiredOpportunity={(commands.required_opportunity || state.required_opportunity || get(commands, "current_required_opportunity")) as Dict | null} governanceAction={activeGovernanceAction} decisionReady={decisionReady} onNavigate={loadPanel} onEndDay={confirmEndDay} />}
            {panel === "actions" && <ActionPanel data={panelData} onRun={item => { setNotice(""); setFormOpen({ title: governanceDisplayTitle(item, "安排治理行动"), kind: "resource", item }); }} />}
            {panel === "opportunities" && <OpportunityPanel signingOnly={signingOnly} data={panelData} activeConversation={state.active_conversation || null} onOpenProfile={setCharacterProfileOpen} onContinue={() => void loadPanel("scene")} onStart={item => openCanonicalAction(item, `与 ${playerText(item.npc_name, "对方")} 会谈`)} />}
            {panel === "governance" && <ReferenceLibrary documents={availableReferenceDocuments} loading={referenceLoading} error={referenceError} onRetry={() => setReferenceReload(value => value + 1)} onReference={interactionMode ? id => { setReferenceIds(ids => ids.includes(id) || ids.length >= 8 ? ids : [...ids, id]); setPanel("scene"); setNotice("文件已加入当前对话引用，请补充你要说的话。"); } : undefined} />}
            {panel === "governance" && <GovernancePanel data={panelData} onOpenRecord={setGovernanceRecordOpen} onOpenArchive={openArchiveDetail} onOpenContract={openContractDetail} />}
            {panel === "desk" && <DeskPanel data={panelData} />}
            {panel === "knowledge" && <KnowledgePanel data={panelData} />}
            {panel === "review" && <ReviewPanel data={panelData} api={api} sessionId={sessionId} governance={governance} />}

          </div>
        </aside>
      </div>
    </section>

    <footer><span>{sessionId ? "每次行动与决定都会自动保存" : "准备好后，从右上角进入游戏"}</span><span>开发：杨钞越　剧情：吉瑞新　美术：章钊林　指导：蒋俊彦、高翔</span><span>{activeGovernanceAction ? activeGovernanceLabels.footer : activeConversation ? "会谈进行中" : pending ? decisionReady ? "等待你的决定" : "请继续阅读当前剧情" : sessionId ? "请合理分配今日精力" : "清江水急，民心难测"}</span></footer>

    {authOpen && <Modal title={authStep === "ai" ? "配置 AI 接口" : authRequired ? account ? "账号中心" : "登录治理档案" : "本地试玩"} onClose={aiView.configured || authStep === "account" ? () => setAuthOpen(false) : undefined}>
      {authStep === "ai" ? <AIConfigurationPanel
        view={aiView}
        mode={aiMode}
        busy={busy}
        error={aiError}
        success={aiSuccess}
        showApiKey={showApiKey}
        onMode={value => { setAiMode(value); setAiError(""); setAiSuccess(""); }}
        onToggleKey={() => setShowApiKey(value => !value)}
        onSubmit={configureAI}
        onClear={clearAIConfiguration}
        onContinue={continueAfterAIConfiguration}
        onBack={authRequired ? () => setAuthStep("account") : undefined}
        onReview={() => { setAuthOpen(false); setSessionOpen(true); void showSavedSessions(); }}
      /> : authRequired ? account ? <div className="account-card"><small>当前账号</small><strong>{account}</strong><p>你的游戏进度已绑定当前账号，重新登录后仍可继续。</p><div className={`ai-config-summary ${aiView.configured ? "active" : ""}`}><small>当前 AI 接口</small><b>{aiView.summary}</b></div>{authError && <div className="notice">{authError}</div>}<button className="secondary" onClick={() => { setAuthStep("ai"); setAiError(""); setAiSuccess(""); void loadAIConfiguration(false); }} disabled={busy}>AI 接口设置</button>{modelConsentRequired && <button className="secondary" onClick={() => setConsentOpen(true)} disabled={busy}>模型与数据授权</button>}<button onClick={logoutAccount} disabled={busy}>退出登录</button></div> : <form className="stack-form" onSubmit={authenticate}><div className="auth-tabs"><button type="button" className={authMode === "login" ? "active" : ""} onClick={() => { setAuthMode("login"); setAuthError(""); }}>登录</button>{selfRegistration && <button type="button" className={authMode === "register" ? "active" : ""} onClick={() => { setAuthMode("register"); setAuthError(""); }}>注册</button>}</div><p>{authMode === "login" ? "登录后可继续这个账号的历史进度。" : "创建账号后即可保留多条游戏进度。"}</p>{authError && <div className="notice">{authError}</div>}<label>用户名<input name="username" minLength={authMode === "register" ? 3 : 1} maxLength={32} autoComplete="username" required autoFocus /></label><label>密码<input name="password" type="password" minLength={authMode === "register" ? 8 : 1} maxLength={256} autoComplete={authMode === "register" ? "new-password" : "current-password"} required /></label><button disabled={busy}>{busy ? "正在处理…" : authMode === "login" ? "登录并继续" : "注册并开始"}</button></form> : <div className="account-card"><small>当前身份</small><strong>本地试玩</strong><p>无需注册。游戏进度会保存在这台电脑上。</p><button onClick={() => setAuthStep("ai")}>配置 AI 接口</button></div>}
    </Modal>}
    {sessionOpen && <Modal title="进入云溪县" onClose={() => { setSessionOpen(false); setSavedSessionsOpen(false); }}><div className="session-actions"><button onClick={() => openSession("new")} disabled={!aiView.configured}>开始新游戏<span>{aiView.configured ? "从上任第一天开始一条新的九十天时间线" : "请先测试并启用 AI 接口"}</span></button><button onClick={showSavedSessions} className={savedSessionsOpen ? "selected" : ""}>查看已有进度<span>可继续当前版本，或复盘已退役剧本</span></button></div>{savedSessionsOpen && <div className="saved-session-list" aria-live="polite">{busy && !savedSessions.length && <div className="form-loading">正在整理存档…</div>}{savedSessionsError && <div className="notice">{savedSessionsError}</div>}{!busy && !savedSessionsError && !savedSessions.length && <div className="empty-state"><p>还没有保存过的游戏，可以从新游戏开始。</p></div>}{savedSessions.map((saved, index) => { const entry = sessionEntry(saved); const needsAI = entry.openKind === "load" && !aiView.configured; return <button key={saved.session_id} className={entry.mode === "review" ? "review-only" : entry.mode === "unavailable" ? "unavailable" : ""} disabled={entry.openKind === null || needsAI} onClick={() => { if (entry.openKind && !needsAI) openSession(entry.openKind, String(saved.session_id)); }}><span><b>进度{chineseIndex(index)} · {entry.label}</b><small>第 {saved.story_day || 1} 日 · {needsAI ? "配置 AI 接口后可继续" : entry.mode === "review" ? "仅可复盘" : entry.mode === "unavailable" ? entry.unavailableReason : friendlyStatus(saved.status)}</small></span><time>{saved.updated_at ? new Date(saved.updated_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</time></button>; })}</div>}</Modal>}
    {!contractOpen && savedSyncNotice}
    {formOpen && <Modal title={formOpen.title} onClose={() => setFormOpen(null)}><TutorialButton label="填写指南" /><ContextForm config={formOpen} state={state} api={api} sessionId={sessionId} notice={notice} onPerform={perform} onArchivesRead={setArchiveReadingOpen} onOpenProfile={setCharacterProfileOpen} /></Modal>}
    {meetingResolutionOpen && activeMeeting && <Modal title={`确认${actionPresentation(activeGovernanceAction).conclusion}`} onClose={() => { if (!busy) setMeetingResolutionOpen(false); }}><MeetingResolutionForm meeting={activeMeeting} governance={governance || {}} state={state} busy={busy} notice={notice} onOpenProfile={setCharacterProfileOpen} onCancel={() => setMeetingResolutionOpen(false)} onSubmit={submitMeetingResolution} /></Modal>}
    {characterProfileOpen && <Modal title="人物介绍" className="character-profile-modal" onClose={() => setCharacterProfileOpen(null)}><CharacterProfileView character={characterProfileOpen} /></Modal>}
    {governanceRecordOpen && <Modal title={governanceRecordOpen.document ? "决议文件详情" : actionPresentation(meetingAction(governanceRecordOpen.meeting, governance || panelData)).result} onClose={() => { if (!busy) setGovernanceRecordOpen(null); }}><div data-tutorial-id={governanceRecordOpen.document ? "document" : "action-result"}><TutorialButton label={governanceRecordOpen.document ? "文件操作指南" : "记录阅读指南"} /><GovernanceRecordDetail key={`${governanceRecordOpen.document?.document_id || governanceRecordOpen.meeting?.meeting_id}:${governanceRecordOpen.document?.version || governanceRecordOpen.document?.status || "meeting"}`} record={governanceRecordOpen} governance={governance || panelData || {}} busy={busy} onAction={performDocumentAction} /></div></Modal>}
    {archiveReadingOpen && <Modal title="档案查阅结果" className="archive-reading-modal" onClose={() => setArchiveReadingOpen(null)}><ArchiveReading result={archiveReadingOpen} /></Modal>}
    {contractProposalOpen && <Modal title="确认逐户合同提议" onClose={() => { if (!busy) setContractProposalOpen(null); }}><ContractBatchProposal proposal={contractProposalOpen} busy={busy} onConfirm={confirmContractBatch} /></Modal>}
    {contractOpen && <Modal title={`逐户合同 · ${playerText(contractOpen.signatory_name, contractOpen.household_id || "待确认")}`} className="contract-modal" onClose={() => { if (!busy && (!contractDirty.current || window.confirm("方案有修改尚未保存，确定放弃修改并关闭？"))) { contractDirty.current = false; setContractOpen(null); } }}><div data-tutorial-id="contract"><TutorialButton label="合同操作指南" />{savedSyncNotice}<ContractWorkspace key={`${contractOpen.contract_id}:${contractOpen.current_version}:${contractOpen.status}`} onTutorialStageChange={setContractTutorialState} onNextStep={openNextStep} contract={contractOpen} governance={governance || panelData || {}} state={state} busy={busy} api={api} sessionId={sessionId} onPerform={performContractAction} onDirtyChange={dirty => { contractDirty.current = dirty; }} onContinue={() => { contractDirty.current = false; setContractOpen(null); setPanel("scene"); }} onOpenContract={openContractDetail} /></div></Modal>}
    {progressBroadcastOpen && progressBroadcast && <Modal title={playerText(progressBroadcast.title, "云溪县十日督办播报")} className="progress-broadcast-modal" onClose={() => setProgressBroadcastOpen(false)}><ProgressBroadcast broadcast={progressBroadcast} onReplay={() => void playProgressCue(progressBroadcastTone)} /></Modal>}
    {consentOpen && <Modal title="角色模型与数据授权" onClose={consentGranted ? () => setConsentOpen(false) : undefined}><ConsentPanel info={consentInfo} aiSummary={aiView.summary} granted={consentGranted} busy={busy} error={consentError} onSign={signModelConsent} onWithdraw={confirmWithdrawModelConsent} /></Modal>}
    {confirmRequest && <Modal title={confirmRequest.title} onClose={() => { if (!busy) setConfirmRequest(null); }}><div className="confirm-panel"><p>{confirmRequest.message}</p><div><button disabled={busy} onClick={() => setConfirmRequest(null)}>返回</button><button className={confirmRequest.danger ? "danger" : "primary"} disabled={busy} onClick={() => { const action = confirmRequest.action; setConfirmRequest(null); void action(); }}>{confirmRequest.confirmLabel}</button></div></div></Modal>}
  </main></TutorialProvider>;
}

function characterPublicIntroduction(character: Character) {
  const role = character.role;
  if (character.id === "player_li_zhiyuan") return "云溪县新任县长、县委副书记，也是本次柳林村整体搬迁治理工作的主要决策者。";
  if (/县长|书记|局长|干部|组长|站长|科/.test(role)) return `${character.name}以${role}身份进入当前治理进程。其职责、掌握的材料和能够作出的承诺，需要通过正式会谈逐步核实。`;
  if (/记者/.test(role)) return `${character.name}是${role}，关注柳林村搬迁中的公共事实、程序透明与社会影响。其尚未公开的线索不会在人物档案中提前显示。`;
  if (/法人|公司/.test(role)) return `${character.name}以${role}身份与搬迁及相关项目发生联系。其利益关系和具体主张，需要以会谈、合同与卷宗为准。`;
  return `${character.name}以${role}身份参与柳林村搬迁。当前档案只展示已经公开的身份信息，个人诉求、关系与底线将在实际接触中逐步显现。`;
}

function CharacterProfileView({ character }: { character: Character }) {
  return <article className="character-profile-view" data-character-id={character.id}>
    <div className="character-profile-stage"><CharacterPortrait character={character} fallbackName={character.name} priority /></div>
    <div className="character-profile-copy">
      <small>柳林村搬迁人物档案</small>
      <h3>{character.name}</h3>
      <strong>{character.role}</strong>
      <p>{characterPublicIntroduction(character)}</p>
      <dl><div><dt>当前状态</dt><dd>已进入可选人物名单</dd></div><div><dt>信息边界</dt><dd>仅显示游戏中已经公开的身份资料</dd></div>{character.aliases.length > 0 && <div><dt>常用称呼</dt><dd>{character.aliases.join("、")}</dd></div>}</dl>
      <div className="profile-guidance">选择人物后可通过走访、访谈或会谈核实其立场；人物介绍不会提前泄露隐藏剧情。</div>
    </div>
  </article>;
}

function CharacterChoiceCard({ character, fallbackName, inputId, type, name, value, checked, disabled = false, onChange, onOpenProfile }: { character: Character | null; fallbackName: string; inputId: string; type: "radio" | "checkbox"; name?: string; value: string; checked: boolean; disabled?: boolean; onChange: () => void; onOpenProfile: (character: Character) => void }) {
  const displayName = character?.name || fallbackName;
  return <div className={checked ? "choice-card character-choice-card selected" : "choice-card character-choice-card"} data-target-id={value}>
    <button type="button" className="choice-character-avatar" aria-label={`查看${displayName}人物介绍`} onClick={() => character && onOpenProfile(character)} disabled={!character}><CharacterPortrait character={character} fallbackName={displayName} /></button>
    <label htmlFor={inputId}><input id={inputId} type={type} name={name} value={value} checked={checked} disabled={disabled} onChange={onChange} /><span><b>{displayName}</b><small>{character?.role || "身份资料尚未公开"}</small></span></label>
  </div>;
}

function PlayerIdentityCard() {
  const player = resolveCharacter("player_li_zhiyuan");
  return <section className="player-identity-card" data-testid="player-identity-card"><div className="player-portrait"><CharacterPortrait character={player} fallbackName="李致远" /></div><div><small>你的身份</small><h3>{player?.name || "李致远"}</h3><p>{player?.role || "云溪县县长"}</p></div></section>;
}

function GovernanceActionScene({ action, overview, streamingReplies }: { action: Dict; overview: Dict | null; streamingReplies: Dict[] }) {
  const catalogs = [
    ...arr(get(overview, "target_catalogs.household_representative")),
    ...arr(get(overview, "target_catalogs.cadre")),
    ...arr(get(overview, "target_catalogs.meeting_participants")),
  ];
  const names = new Map(catalogs.map(item => [String(item.target_id), String(item.label || item.name || "相关人员")]));
  const targets = (Array.isArray(action.target_ids) ? action.target_ids : []).map((id: unknown) => names.get(String(id)) || resolveCharacter(String(id))?.name || "相关人员");
  const transcript = arr(action.transcript);
  const title = governanceDisplayTitle(
    action,
    GOVERNANCE_ACTION_LABELS[String(action.action_kind)] || "治理行动",
  );
  const targetId = String((Array.isArray(action.target_ids) ? action.target_ids : [])[0] || "");
  const targetName = targets[0] || "对方";
  const targetCharacter = resolveCharacter(targetId, targetName);
  const timeline = mergeGovernanceTimeline(transcript, streamingReplies) as Dict[];
  const latestEntry = timeline[timeline.length - 1] || null;
  const latestNpcEntry = [...timeline].reverse().find(entry => entry.speaker_type === "npc") || null;
  const narration = latestEntry?.speaker_type === "system";
  const speakerName = narration ? "县长手记" : playerText(latestNpcEntry?.npc_name, targetCharacter?.name || targetName);
  const timelineSignature = timeline.map(entry => [entry.speaker_type, entry.npc_id, entry.stream_id, entry.text, entry.live ? "live" : "committed"].join("\u0001")).join("\u0002");
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const previousTimelineSignature = useRef(timelineSignature);
  const previousTimelineLength = useRef(timeline.length);
  const [timelineAtBottom, setTimelineAtBottom] = useState(true);
  const [acknowledgedTimelineLength, setAcknowledgedTimelineLength] = useState(timeline.length);
  const hasNewDialogue = !timelineAtBottom && timeline.length > acknowledgedTimelineLength;

  useEffect(() => {
    if (timelineSignature === previousTimelineSignature.current) return;
    const element = timelineRef.current;
    const grew = timeline.length > previousTimelineLength.current;
    previousTimelineSignature.current = timelineSignature;
    previousTimelineLength.current = timeline.length;
    if (element && timelineAtBottom) {
      element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    }
    if (timelineAtBottom && grew) setAcknowledgedTimelineLength(timeline.length);
  }, [timelineAtBottom, timeline.length, timelineSignature]);

  const jumpToLatest = () => {
    const element = timelineRef.current;
    if (element) element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    setTimelineAtBottom(true);
    setAcknowledgedTimelineLength(timeline.length);
  };
  return <section className="gal-stage governance-gal-stage conversation-mode" data-primary-scene="governance_action" data-testid="governance-gal-scene" data-action-kind={String(action.action_kind)}>
    <div className="gal-scene-meta"><small>正在进行 · {title}</small><strong>{playerText(action.topic, `与${targetName}当面沟通`)}</strong><span>第 {action.story_day || "待定"} 日</span></div>
    <div className="gal-portrait" aria-label={`${targetName}立绘`}><CharacterPortrait character={targetCharacter} fallbackName={targetName} priority /></div>
    <div className="gal-dialogue has-speaker">
      <header><span>{speakerName || targetName}</span><small>{narration ? "现场记录" : targetCharacter?.role || title}{latestEntry?.live ? latestEntry.complete ? " · 回应完成" : " · 正在回应" : ""}</small></header>
      <div className="governance-action-timeline" ref={timelineRef} onScroll={event => {
        const element = event.currentTarget;
        const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 36;
        setTimelineAtBottom(atBottom);
        if (atBottom) setAcknowledgedTimelineLength(timeline.length);
      }} aria-label="本次治理行动完整记录" aria-live="polite">
        {timeline.length === 0 && <div className="governance-action-opening"><p>你已经到达现场。先说明来意，再围绕事实、诉求与可行安排展开交流。</p></div>}
        {timeline.map((entry, index) => {
          const player = entry.speaker_type === "player";
          const system = entry.speaker_type === "system";
          const character = !player && !system ? resolveCharacter(entry.npc_id, entry.npc_name) : null;
          const name = player ? "你" : system ? "县长手记" : playerText(entry.npc_name, character?.name || targetName);
          return <article className={`${player ? "player" : system ? "system" : "npc"}${entry.live ? " live" : ""}`} key={`${entry.speaker_type}-${entry.npc_id || "player"}-${entry.conversation_id || entry.action_instance_id || ""}-${entry.turn_id || entry.reply_id || ""}-${entry.stream_id || ""}-${index}`}><strong>{name}</strong><p>{playerText(entry.text, "对方暂未表态。")}{entry.live && !entry.complete && <i className="stream-cursor" aria-hidden="true" />}</p><ReferenceAttachments references={entry.references} /></article>;
        })}
      </div>
      {hasNewDialogue && <button type="button" className="new-dialogue-button governance-new-dialogue" onClick={jumpToLatest}>有新回复</button>}
    </div>
  </section>;
}

function LeadershipMeetingScene({ action, meeting, overview, streamingReplies }: { action: Dict; meeting: Dict; overview: Dict | null; streamingReplies: Dict[] }) {
  const presentation = actionPresentation(action);
  const title = governanceDisplayTitle(action, presentation.title);
  const catalogs = arr(get(overview, "target_catalogs.meeting_participants"));
  const names = new Map(catalogs.map(item => [String(item.target_id), String(item.label || item.name || "相关人员")]));
  const targets = values(action.target_ids).map(id => names.get(String(id)) || resolveCharacter(String(id))?.name || "相关人员");
  const transcript = arr(meeting.transcript);
  const isFollowup = Boolean(action.followup_plan_id || meeting.followup_plan_id || action.source === "night_followup");
  return <section className="governance-scene leadership-meeting-scene leadership-meeting-room" style={action.variant_id === "clan_leader_campaign" ? { backgroundImage: 'linear-gradient(rgba(17,14,11,.62), rgba(17,14,11,.62)), url("/scenes/c05-s02.webp")' } : undefined} data-primary-scene="leadership_meeting" data-testid="leadership-meeting-scene">
    <header><div><small>{isFollowup ? "夜间后续会议" : `正在进行 · ${title}`}</small><h3>{playerText(action.topic, title)}</h3></div><span>第 {action.story_day || "待定"} 日</span></header>
    {targets.length > 0 && <p className="scene-participants">在场：{targets.join("、")}</p>}
    {transcript.length ? <div className="scene-transcript">{transcript.map((entry, index) => <article className={entry.speaker_type === "player" ? "player" : "npc"} key={index}><strong>{entry.speaker_type === "player" ? "你" : entry.npc_name || "参会人员"}</strong><p>{playerText(entry.text, "对方暂未表态。")}</p><ReferenceAttachments references={entry.references} /></article>)}</div> : <div className="scene-opening"><span>议</span><p>人员已经到齐。先说明本次{presentation.noun}议题，听取各方意见后再{presentation.finish}。</p></div>}
    {streamingReplies.length > 0 && <NpcStreamingReplies replies={streamingReplies} />}
  </section>;
}

function ForcedGroupConversationScene({ conversation, streamingReplies }: { conversation: Dict; streamingReplies: Dict[] }) {
  const participants = values(conversation.participant_ids).map(id => resolveCharacter(String(id))).filter(Boolean) as Character[];
  const initiator = resolveCharacter(String(conversation.initiator_npc_id || ""));
  const transcript = arr(conversation.transcript);
  const liveEntries = streamingReplies.map(item => ({ ...item, speaker_type: "npc", live: true }));
  const timeline: Dict[] = [...transcript, ...liveEntries];
  const latestNpcEntry = [...timeline].reverse().find(entry => entry.speaker_type !== "player");
  const [speakerSelection, setSpeakerSelection] = useState({
    npcId: String(latestNpcEntry?.npc_id || conversation.initiator_npc_id || ""),
    timelineLength: timeline.length,
  });
  const [timelineAtBottom, setTimelineAtBottom] = useState(true);
  const [acknowledgedTimelineLength, setAcknowledgedTimelineLength] = useState(timeline.length);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const previousTimelineLength = useRef(timeline.length);
  const followsLatestSpeaker = timelineAtBottom && timeline.length > speakerSelection.timelineLength;
  const selectedNpcId = followsLatestSpeaker && latestNpcEntry?.npc_id
    ? String(latestNpcEntry.npc_id)
    : speakerSelection.npcId;
  const hasNewDialogue = !timelineAtBottom && timeline.length > acknowledgedTimelineLength;
  const selectedEntry = [...timeline].reverse().find(entry => String(entry.npc_id || "") === selectedNpcId);
  const speaker = resolveCharacter(selectedNpcId, selectedEntry?.npc_name) || initiator || participants[0] || null;
  const speakerName = playerText(selectedEntry?.npc_name, speaker?.name || "来访者");
  const participantStates = arr(conversation.participant_states);

  useEffect(() => {
    const element = timelineRef.current;
    if (!element || timeline.length <= previousTimelineLength.current) {
      previousTimelineLength.current = timeline.length;
      return;
    }
    const update = conversationTimelineUpdate(
      timelineAtBottom,
      previousTimelineLength.current,
      timeline.length,
    );
    previousTimelineLength.current = timeline.length;
    if (update.followLatest) {
      element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    }
  }, [timeline.length, timelineAtBottom]);

  const jumpToLatest = () => {
    const element = timelineRef.current;
    if (element) element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    setTimelineAtBottom(true);
    setAcknowledgedTimelineLength(timeline.length);
    if (latestNpcEntry?.npc_id) {
      setSpeakerSelection({ npcId: String(latestNpcEntry.npc_id), timelineLength: timeline.length });
    }
  };

  return <section className="forced-group-gal-stage leadership-meeting-room" data-primary-scene="forced_group_conversation" data-testid="forced-group-conversation">
    <header className="forced-group-header"><div><small>夜间强制会谈</small><h3>{playerText(conversation.agenda, "在场各方要求当面说明")}</h3><p>发起人：{initiator?.name || "相关人员"} · {values(conversation.demands).map(item => playerText(item)).filter(Boolean).join("；") || "请回应人物的担忧，直到发起人确认不再追问。"}</p></div><span>{conversation.phase === "resolved" ? "等待玩家收起会谈" : "会谈进行中"}</span></header>
    <div className="forced-group-participants" aria-label="在场人物状态">{participants.map(character => {
      const state = participantStates.find(item => String(item.npc_id) === character.id) || {};
      return <button type="button" key={character.id} className={selectedNpcId === character.id ? "selected" : ""} onClick={() => setSpeakerSelection({ npcId: character.id, timelineLength: timeline.length })}><b>{character.name}</b><small>{playerText(state.public_summary, state.status === "settled" ? "暂时接受，仍在旁听" : "仍在追问")}</small></button>;
    })}</div>
    <div className="forced-group-workspace">
      <aside className="forced-group-speaker" aria-label={`${speakerName}立绘`}><div><CharacterPortrait character={speaker} fallbackName={speakerName} /></div><strong>{speakerName}</strong><span>{speaker?.role || "在场人物"}</span></aside>
      <div className="forced-group-timeline-wrap">
        <div className="forced-group-timeline" ref={timelineRef} onScroll={event => {
          const element = event.currentTarget;
          const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 36;
          setTimelineAtBottom(atBottom);
          if (atBottom) setAcknowledgedTimelineLength(timeline.length);
        }} aria-label="夜间会谈完整记录">
          {timeline.length === 0 && <div className="forced-group-opening"><p>{playerText(conversation.opening_narrative, "来访者已经到场。请直接回应他们最在意的问题；人物会根据你的说法决定是否继续追问。")}</p></div>}
          {timeline.map((entry, index) => {
            const player = entry.speaker_type === "player";
            const character = player ? null : resolveCharacter(entry.npc_id, entry.npc_name);
            const name = player ? "你" : playerText(entry.npc_name, character?.name || "在场人物");
            return <button type="button" className={`${player ? "player" : "npc"}${entry.live ? " live" : ""}`} key={`${entry.speaker_type}-${entry.npc_id || "player"}-${index}`} onClick={() => !player && setSpeakerSelection(speakerSelectionForTimelineEntry(entry, timeline.length)!)} disabled={player}><strong>{name}</strong><p>{playerText(entry.text, "……")}{entry.live && !entry.complete && <i className="stream-cursor" aria-hidden="true" />}</p><ReferenceAttachments references={entry.references} />{!player && entry.dialogue_act && <small>{({ press: "继续追问", challenge: "指出矛盾", soften: "态度动摇", settle: "暂时接受", reopen: "重新追问", close: "确认收束" } as Record<string, string>)[String(entry.dialogue_act)] || "回应"}</small>}</button>;
          })}
        </div>
        {hasNewDialogue && <button type="button" className="new-dialogue-button" onClick={jumpToLatest}>有新发言</button>}
      </div>
    </div>
    {conversation.phase === "resolved" && <footer className="forced-group-resolution"><b>本次话题已经收束</b><p>{playerText(conversation.closure_summary, "在场人物暂时停止追问。这不代表你作出的承诺已经兑现，相关说法会留在人物记忆中。")}</p></footer>}
  </section>;
}

function NpcStreamingReplies({ replies }: { replies: Dict[] }) {
  return <section className="npc-stream" aria-live="polite" aria-busy={replies.some(item => !item.complete)}>
    <header><small>实时回应</small><span>{replies.some(item => !item.complete) ? "正在输入…" : "回应完成"}</span></header>
    {replies.map(item => {
      const character = resolveCharacter(item.npc_id, item.npc_name);
      const name = character?.name || playerText(item.npc_name, "对方");
      return <article key={item.stream_id}>
        <div className="npc-stream-portrait"><CharacterPortrait character={character} fallbackName={name} /></div>
        <div><strong>{name}</strong><p>{playerText(item.text, "…")}{!item.complete && <i className="stream-cursor" aria-hidden="true" />}</p></div>
      </article>;
    })}
  </section>;
}

function AIThinkingBanner({ label }: { label: string }) {
  return <section className="ai-thinking-banner" role="status" aria-live="assertive" aria-busy="true">
    <span className="thinking-dots" aria-hidden="true"><i /><i /><i /></span>
    <div><strong>AI 正在思考</strong><small>{label}</small></div>
  </section>;
}

function PlayerActionBar({ referenceDocuments, referenceIds, onReferenceIds, referenceError, state, commands, busy, waitingForAI, notice, pending, decisionReady, interactionMode, governanceAction, meeting, contractAvailable, contractPreparation, onPrepareContracts, conversationName, value, onChange, onSubmit, onOpenContract, onLeave, onFinishGroup, onFinishGovernance, onCancelGovernance, onNavigate, onEndDay }: { referenceDocuments: ReferenceDocument[]; referenceIds: string[]; onReferenceIds: (ids: string[]) => void; referenceError: string; state: Dict; commands: Dict; busy: boolean; waitingForAI: boolean; notice: string; pending: Dict | null; decisionReady: boolean; interactionMode: "group" | "conversation" | "governance" | null; governanceAction: Dict | null; meeting: Dict | null; contractAvailable: boolean; contractPreparation?: Dict; onPrepareContracts: () => void; conversationName: string; value: string; onChange: (value: string) => void; onSubmit: (event: FormEvent) => void; onOpenContract: () => void; onLeave: () => void; onFinishGroup: () => void; onFinishGovernance: () => void; onCancelGovernance: () => void; onNavigate: (panel: PanelName) => void; onEndDay: () => void }) {
  if (!state.session_id) return <div className="next-action pending"><span>等待赴任</span><p>接下调令后，今天可以执行的事务会显示在这里。</p></div>;
  const endingId = get(state, "ending.main_ending_id") || get(state, "ending_result.main_ending_id") || state.main_ending_id;
  if (endingId) return <div className="next-action pending"><span>九十日治理周期已结束</span><p>结局已经生成；可以进入复盘查看关键节点、治理结果与后续影响。</p><div className="next-buttons"><button className="primary" onClick={() => onNavigate("review")} disabled={busy}>查看结局复盘</button></div></div>;
  const conversation = state.active_conversation;
  const group = state.active_group_conversation;
  const groupParticipantStates = arr(group?.participant_states);
  const groupPursuingCount = groupParticipantStates.filter(item => item.status !== "settled").length;
  const groupStatusSummary = groupParticipantStates.length > 0 && groupPursuingCount === 0
    ? "在场人物已暂时接受，等待发起人确认收束"
    : `${groupPursuingCount || values(group?.participant_ids).length} 人仍在追问`;
  const compactCharacter = conversation ? resolveCharacter(conversation.npc_id, conversation.target_npc_id, conversation.npc_name) : null;
  const groupResolved = interactionMode === "group" && group?.phase === "resolved";
  if (interactionMode === "group" || interactionMode === "conversation") return <form data-tutorial-id={interactionMode} className="conversation-bar gal-conversation-bar" onSubmit={onSubmit} aria-busy={waitingForAI}>
    {notice && <div className="conversation-notice" role="status">{notice}</div>}
    {interactionMode === "conversation" && conversation && <header className="conversation-compact" data-testid="active-conversation-compact"><div className="compact-portrait"><CharacterPortrait character={compactCharacter} fallbackName={conversationName || "对方"} /></div><div><small>正在会谈</small><strong>{compactCharacter?.name || conversationName || "对方"}</strong><span>{compactCharacter?.role || playerText(conversation.npc_title, "身份待确认")}</span></div><b>第 {Number(conversation.turn_count || conversation.turns_completed || 0)} 轮</b></header>}
    {interactionMode === "group" && group && <header className="conversation-compact group-compact" data-testid="active-group-conversation-compact"><div><small>{groupResolved ? "多人会谈已收束，可继续补充" : "强制多人会谈"}</small><strong>{playerText(group.agenda, "在场各方要求立即说明")}</strong><span>{groupResolved ? "发起人已确认暂不追问；你仍可补充事实或说明。" : groupStatusSummary}</span><span>在场人物：{values(group.participant_ids).map(id => resolveCharacter(String(id))?.name || "在场人物").join("、")}</span></div><b>{groupResolved ? "可继续回应" : "不可跳过"}</b></header>}
    <label data-tutorial-id="conversation-input"><span>{interactionMode === "group" ? "回应在场各方" : `回应 ${conversationName || "对方"}`}</span><ReferenceInput value={value} onChange={onChange} documents={referenceDocuments} selected={referenceIds} onSelected={onReferenceIds} error={referenceError} disabled={busy} placeholder="说清事实、诉求、承诺或你要追问的问题…" /></label><div><small>{waitingForAI ? "正在思考回应…" : `${value.length} / 1000`}</small>{interactionMode === "conversation" && conversation && <button type="button" className="secondary" onClick={onLeave} disabled={busy}>结束会谈</button>}{interactionMode === "group" && groupResolved && <button type="button" className="secondary" onClick={onFinishGroup} disabled={busy}>结束夜间会谈</button>}<button data-tutorial-id="conversation-send" disabled={busy || !value.trim()}>{waitingForAI ? "正在思考…" : "送出回应"}</button></div>
  </form>;
  if (pending) return <div className="next-action pending"><span>{decisionReady ? "先处理上方事项" : "继续阅读上方剧情"}</span><p>{decisionReady ? "作出决定后，行动与会谈会重新开放。" : "请使用“下一段”按顺序读完当前现场；相关情节出现后才会开放决定。"}</p></div>;
  if (commands.can_continue_story) return <div className="next-action pending"><span>继续阅读上方剧情</span><p>请点击“下一段”继续今天的故事，读完后再结束今日。</p></div>;
  if (governanceAction) {
    const presentation = actionPresentation(governanceAction);
    const isMeeting = presentation.collective;
    const respondingNpcIds = new Set(arr(meeting?.transcript).filter(item => item.speaker_type === "npc").map(item => String(item.npc_id)));
    const hasDiscussion = values(meeting?.participant_ids).every(id => respondingNpcIds.has(String(id)));
    return <form data-tutorial-id={isMeeting ? governanceAction.variant_id === "public_hearing" ? "hearing" : governanceAction.variant_id === "clan_leader_campaign" ? "clan" : "meeting" : "governance"} className="conversation-bar governance-bar" onSubmit={onSubmit} aria-busy={waitingForAI}>{notice && <div className="governance-inline-notice" role="status">{notice}</div>}<label data-tutorial-id="conversation-input"><span>{presentation.discussionLabel}</span><ReferenceInput value={value} onChange={onChange} documents={referenceDocuments} selected={referenceIds} onSelected={onReferenceIds} error={referenceError} disabled={busy} placeholder={`${presentation.prompt}，或回应在场意见…`} /></label><div><small>{waitingForAI ? "正在思考回应…" : `${value.length} / 1000`}</small>{isMeeting && <button type="button" className="danger-quiet" onClick={onCancelGovernance} disabled={busy}>终止{presentation.noun}</button>}<button data-tutorial-id="conversation-finish" type="button" className="secondary" onClick={onFinishGovernance} disabled={busy || (isMeeting && !hasDiscussion)}>{presentation.finish}</button>{!contractAvailable && !isMeeting && contractPreparation && contractPreparation.household_count > 0 && <button type="button" className="secondary" title={contractPreparation.reason || "保存方案并预览合同后，仍需由本户接受签署"} disabled={busy || !contractPreparation.available} onClick={onPrepareContracts}>{contractPreparation.available ? "准备逐户合同" : "签约条件待满足"}</button>}{contractAvailable && !isMeeting && <button type="button" className="primary" onClick={onOpenContract} disabled={busy}>继续办理合同</button>}<button data-tutorial-id="conversation-send" disabled={busy || !value.trim()}>{waitingForAI ? "正在思考…" : "送出回应"}</button></div></form>;
  }
  return <div className="next-action"><div><span>下一步</span><p>{firstMeetingHint(state, commands) || (commands.can_end_day ? "今日工作可以收束，也可以继续使用剩余精力。" : "从行动或会谈中选择一个推进方向。")}</p></div><div className="next-buttons"><button onClick={() => onNavigate("actions")} disabled={busy}>安排行动</button><button onClick={() => onNavigate("opportunities")} disabled={busy}>寻找会谈</button>{commands.can_end_day && <button data-tutorial-id="end-day" className="primary" onClick={onEndDay} disabled={busy}>结束今日</button>}</div></div>;
}

function MeetingResolutionForm({ meeting, governance, state, busy, notice, onCancel, onSubmit, onOpenProfile }: { meeting: Dict; governance: Dict; state: Dict; busy: boolean; notice: string; onCancel: () => void; onSubmit: (resolution: Dict) => Promise<void>; onOpenProfile: (character: Character) => void }) {
  const presentation = actionPresentation(meetingAction(meeting, governance));
  const topic = playerText(meeting.topic, `本次${presentation.noun}议题`);
  const participantIds = values(meeting.participant_ids).map(String);
  const participantCatalog = arr(get(governance, "target_catalogs.meeting_participants"));
  const participantNames = new Map(participantCatalog.map(item => [String(item.target_id), playerText(item.label || item.name, "相关人员")]));
  const [decision, setDecision] = useState(`围绕“${topic}”记录${presentation.conclusion}，并按本次确认的责任分工推进。`);
  const [targetScope, setTargetScope] = useState("本次议题涉及的相关部门和柳林村群众");
  const [responsibleIds, setResponsibleIds] = useState<string[]>(participantIds);
  const [deadlineDay, setDeadlineDay] = useState(String(Math.min(90, Number(get(state, "story.day", 1)) + 7)));
  const [publicScope, setPublicScope] = useState("参会部门、柳林村相关群众");
  const [documentTitle, setDocumentTitle] = useState(`${topic}${presentation.conclusion}`);
  const [resourceLimits, setResourceLimits] = useState<Record<string, string>>({});
  const pools = arr(get(governance, "resources.resource_pools"));
  const envelopes = budgetEnvelopeChoices(get(governance, "resources.budget_envelopes", {}));
  const resourceOptions = [...pools, ...envelopes];
  const documentType = String(meeting.proposed_document_type || "");
  const toggleResponsible = (id: string) => setResponsibleIds(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  const valid = decision.trim() && targetScope.trim() && responsibleIds.length > 0 && Number(deadlineDay) >= Number(get(state, "story.day", 1)) && Number(deadlineDay) <= 90 && publicScope.trim() && documentTitle.trim();
  const parsePublicScope = () => publicScope.split(/[、，,\n]/).map(item => item.trim()).filter(Boolean);

  return <form className="stack-form meeting-resolution-form" data-testid="meeting-resolution-form" onSubmit={async event => {
    event.preventDefault();
    if (!valid) return;
    const resources = Object.fromEntries(Object.entries(resourceLimits).map(([id, amount]) => [id, Number(amount)]).filter(([, amount]) => Number.isFinite(amount) && Number(amount) > 0));
    await onSubmit({
      decision: decision.trim(),
      target_scope: targetScope.trim(),
      resources,
      resource_mode: "authorization_ceiling",
      responsible_ids: responsibleIds,
      deadline_day: Number(deadlineDay),
      public_scope: parsePublicScope(),
      document_title: documentTitle.trim(),
    });
  }}>
    <div className="resolution-brief"><strong>{topic}</strong><p>{presentation.leadership ? "分管领导与其他参会领导已完成发言。现在由你作出末位决定。" : "参与人已完成发言。请核对各方意见，记录结论与后续安排。"}提交后生成{presentation.result}{documentType ? `和${DOCUMENT_TYPE_LABELS[documentType] || "行政文件"}` : ""}。</p></div>
    <label>{presentation.leadership ? "主要领导末位决定" : presentation.conclusion}<textarea value={decision} onChange={event => setDecision(event.target.value)} maxLength={1000} required autoFocus /><small>只写入你最终确认的内容，不会自动采纳角色发言中的金额或承诺。</small></label>
    <label>适用范围<input value={targetScope} onChange={event => setTargetScope(event.target.value)} maxLength={300} required /></label>
    <fieldset className="choice-fieldset resolution-responsibles"><legend>责任主体</legend><p className="field-help">至少选择一名本次参与人员。</p><div className="choice-grid character-choice-grid">{participantIds.map(id => { const fallbackName = participantNames.get(id) || id; return <CharacterChoiceCard key={id} character={resolveCharacter(id, fallbackName)} fallbackName={fallbackName} inputId={`resolution-person-${id}`} type="checkbox" value={id} checked={responsibleIds.includes(id)} onChange={() => toggleResponsible(id)} onOpenProfile={onOpenProfile} />; })}</div></fieldset>
    <div className="resolution-fields"><label>完成期限<input type="number" min={Number(get(state, "story.day", 1))} max={90} value={deadlineDay} onChange={event => setDeadlineDay(event.target.value)} required /><small>填写剧情日，最晚为 D90。</small></label><label>公开范围<input value={publicScope} onChange={event => setPublicScope(event.target.value)} maxLength={300} required /><small>多个范围用顿号或逗号分隔。</small></label></div>
    {resourceOptions.length > 0 && <fieldset className="choice-fieldset resolution-resources"><legend>资源授权上限（可选）</legend><p className="field-help">留空表示本次{presentation.conclusion}不新增资源授权。填写的是上限，不会立即占用资源。</p><div className="resource-limit-list">{resourceOptions.map(item => { const id = String(item.resource_id); return <label key={id}><span><b>{playerText(item.name || item.label, id)}</b><small>全局容量 {item.capacity} {item.unit || "份"}</small></span><span className="resource-limit-input"><input type="number" min="0" max={Number(item.capacity || 0)} value={resourceLimits[id] || ""} onChange={event => setResourceLimits(current => ({ ...current, [id]: event.target.value }))} placeholder="不授权" /><em>{item.unit || "份"}</em></span></label>; })}</div></fieldset>}
    <label>{documentType ? "文件标题" : "记录标题"}<input value={documentTitle} onChange={event => setDocumentTitle(event.target.value)} maxLength={300} required /></label>
    {notice && <div className="notice form-notice" role="alert">{notice}</div>}
    <div className="resolution-actions"><button type="button" className="secondary" onClick={onCancel} disabled={busy}>返回讨论</button><button disabled={busy || !valid}>{busy ? "正在形成决定…" : presentation.leadership ? "末位表态并形成决定" : presentation.finish}</button></div>
  </form>;
}

function SceneSummary({ state, commands, requiredOpportunity, governanceAction, decisionReady, onNavigate, onEndDay }: { state: Dict; commands: Dict; requiredOpportunity: Dict | null; governanceAction: Dict | null; decisionReady: boolean; onNavigate: (panel: PanelName) => void; onEndDay: () => void }) {
  if (!state.session_id) return <div className="scene-summary"><div className="empty-state"><span>令</span><h3>尚未赴任</h3><p>进入游戏后，这里会显示今日目标和可行安排。</p></div></div>;
  const endingId = get(state, "ending.main_ending_id") || get(state, "ending_result.main_ending_id") || state.main_ending_id;
  if (endingId) return <div className="scene-summary"><section className="objective-card"><small>治理周期完成</small><h3>查看九十日结局复盘</h3><p>行动阶段已经结束。复盘会汇总关键选择、治理指标和最终影响。</p></section><div className="quick-links"><button className="primary" onClick={() => onNavigate("review")}>进入结局复盘</button></div></div>;
  const active = state.active_conversation || state.active_group_conversation;
  const pending = state.pending_decision;
  const firstActionPending = !state.onboarding?.free_action_completed;
  const requiredOpportunityPending = Boolean(requiredOpportunity)
    && requiredOpportunity?.completed !== true
    && requiredOpportunity?.satisfied !== true
    && !["completed", "resolved", "done"].includes(String(requiredOpportunity?.status || ""))
    && !pending && !governanceAction && !active;
  const requiredOpportunityDescription = requiredOpportunityPending
    ? firstMeetingHint(state, { ...commands, required_opportunity: requiredOpportunity }) || playerText(requiredOpportunity?.reason || requiredOpportunity?.description || requiredOpportunity?.entry_description, "请先寻找当前指定会谈，了解村庄关系与顾虑。")
    : "";
  const governanceLabels = governanceActionProgressLabels(
    governanceAction,
    GOVERNANCE_ACTION_LABELS[governanceAction?.action_kind] || "治理行动",
  );
  const current = pending ? decisionReady ? "处理当前必须决定的事项" : "继续阅读当前剧情" : governanceAction ? governanceLabels.task : active ? "完成正在进行的会谈" : requiredOpportunityPending ? "寻找会谈" : commands.can_continue_story ? "继续阅读当前剧情" : commands.can_end_day ? "决定继续工作还是结束今日" : "选择一项行动或会谈";
  return <div className="scene-summary"><section className="objective-card"><small>当前首要事项</small><h3>{current}</h3><p>{pending ? decisionReady ? "相关情节已经展开，请根据现场信息作出选择。" : "请按顺序读完当前现场；相关情节出现后才会开放决定。" : governanceAction ? "在左侧现场继续交流；取得所需信息后，记得正式结束行动。" : active ? "认真回应对方；你的措辞和承诺都会被记录。" : requiredOpportunityPending ? requiredOpportunityDescription : commands.can_continue_story ? "请点击上方“下一段”继续今天的故事。" : "查看行动成本和开放条件，再决定如何使用今日精力。"}</p></section>{firstActionPending && <section className="tutorial-card"><small>上手指引</small><TutorialButton label="查看赴任指南" /><ol><li className={pending ? "active" : "done"}><b>{pending && !decisionReady ? "读完现场并处理决定" : "处理必须决定的事项"}</b><span>剧情决定不消耗精力，读完铺垫后才会开放</span></li><li className={!pending && !commands.can_end_day ? "active" : ""}><b>剧情之外，也能主动安排行动</b><span>推进签约是独立于剧情和决策的自由行动，剧情不会自动替你签约。逐户接受合同后才计入进度；最终实际签约数直接影响结局，但不是唯一因素。</span>{!pending && !active && !governanceAction && commands.can_act && <button onClick={() => onNavigate("actions")}>试着安排一次行动</button>}</li><li className={governanceAction ? "active" : commands.can_end_day ? "active" : ""}><b>{governanceAction ? "收束当前行动" : "结束今日"}</b><span>{governanceAction ? "交流后从左下方结束行动" : "夜间会结算后续影响，私下联络仅汇入次晨简报"}</span></li></ol></section>}<div className="quick-links"><button onClick={() => onNavigate(requiredOpportunityPending ? "opportunities" : governanceAction ? "governance" : "actions")}>{requiredOpportunityPending ? "寻找会谈" : governanceAction ? "查看治理进展" : "查看行动"}</button><button onClick={() => onNavigate("desk")}>阅读任务卷宗</button>{commands.can_end_day && !governanceAction && <button className="primary" onClick={onEndDay}>结束今日</button>}</div></div>;
}


function AIConfigurationPanel({
  view, mode, busy, error, success, showApiKey,
  onMode, onToggleKey, onSubmit, onClear, onContinue, onBack, onReview,
}: {
  view: ReturnType<typeof aiConfigurationView>;
  mode: "personal" | "server_default";
  busy: boolean;
  error: string;
  success: string;
  showApiKey: boolean;
  onMode: (value: "personal" | "server_default") => void;
  onToggleKey: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClear: () => void;
  onContinue: () => void;
  onBack?: () => void;
  onReview: () => void;
}) {
  return <form className="stack-form ai-config-form" onSubmit={onSubmit} autoComplete="off">
    <div className="auth-progress" aria-label="登录步骤"><span>一　账号身份</span><strong>二　AI 接口</strong></div>
    <p>接口只在本次登录期间保存在游戏后端内存中；退出登录或重启服务后需要重新填写。</p>
    <fieldset className="ai-source-options">
      <legend>选择接口来源</legend>
      <label className={mode === "personal" ? "selected" : ""}><input type="radio" name="ai_mode" value="personal" checked={mode === "personal"} onChange={() => onMode("personal")} />使用个人 API<span>适用于 OpenAI Chat Completions 兼容服务</span></label>
      <label className={mode === "server_default" ? "selected" : ""}><input type="radio" name="ai_mode" value="server_default" checked={mode === "server_default"} disabled={!view.serverDefaultAvailable} onChange={() => onMode("server_default")} />使用服务器默认接口<span>{view.serverDefaultAvailable ? view.serverDefaultSummary || "管理员已配置" : "当前服务器没有可用的默认接口"}</span></label>
    </fieldset>
    {mode === "personal" && <div className="ai-personal-fields">
      <label>API Base URL<input name="base_url" type="url" defaultValue="https://api.qianzhang-ai.cn/v1" maxLength={2048} inputMode="url" spellCheck={false} required /></label>
      <label>模型名<input name="model" defaultValue="qwen3.6-plus" maxLength={256} spellCheck={false} required /></label>
      <label>API Key<span className="secret-field"><input name="api_key" type={showApiKey ? "text" : "password"} maxLength={1024} autoComplete="off" data-1p-ignore="true" required /><button type="button" className="secondary" onClick={onToggleKey} aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"}>{showApiKey ? "隐藏" : "显示"}</button></span></label>
      <small className="cost-hint">“测试并启用”会依次验证单选、多选、人物表达、夜间会谈、合同和行政文书六项能力，供应商可能收取少量 Token 费用。</small>
    </div>}
    {view.configured && <div className="ai-config-summary active"><small>当前已启用</small><b>{view.summary}</b>{view.compatibilityStatus === "compatible" && <><span>六项游戏能力已验证</span><span>{view.capabilities.join("、")}</span>{view.testedAt && <time>最近测试：{new Date(view.testedAt).toLocaleString("zh-CN")}</time>}</>}</div>}
    {error && <div className="notice ai-test-result" role="alert"><b>接口测试失败</b><span>{error}</span></div>}
    {success && <div className="success-note ai-test-result" role="status"><b>接口测试成功</b><span>{success}</span></div>}
    <button disabled={busy || (mode === "server_default" && !view.serverDefaultAvailable)}>{busy ? "正在测试接口…" : mode === "personal" ? "测试并启用" : "启用服务器默认接口"}</button>
    {success && view.configured && <button type="button" className="primary" onClick={onContinue} disabled={busy}>配置成功，继续</button>}
    <div className="ai-config-actions">{onBack && <button type="button" className="secondary" onClick={onBack} disabled={busy}>返回账号</button>}<button type="button" className="secondary" onClick={onReview} disabled={busy}>查看只读复盘</button>{view.mode === "personal" && <button type="button" className="danger-quiet" onClick={onClear} disabled={busy}>清除个人接口</button>}</div>
  </form>;
}

function ConsentPanel({ info, aiSummary, granted, busy, error, onSign, onWithdraw }: { info: Dict | null; aiSummary: string; granted: boolean; busy: boolean; error: string; onSign: () => void | Promise<void>; onWithdraw: () => void | Promise<void> }) {
  if (!info) return <div className="consent-panel"><p>正在读取当前授权说明…</p>{error && <div className="notice">{error}</div>}</div>;
  return <div className="consent-panel">
    <p>NPC 会谈会把你输入的文字发送给已配置的角色模型，以生成符合人物设定的回应。不同意时仍可查看已有卷宗，但无法继续需要模型的会谈。</p>
    <dl><div><dt>当前 AI 接口</dt><dd>{playerText(aiSummary, "尚未配置")}</dd></div><div><dt>处理区域</dt><dd>{playerText(info.processing_region, "由所选接口决定")}</dd></div><div><dt>原始文本最长保留</dt><dd>{displayValue(info.retention_days_raw_text, "未说明")} 天</dd></div><div><dt>授权版本</dt><dd>{playerText(info.required_version, "未说明")}</dd></div></dl>
    <ul><li>保存游戏进度与会谈记录，用于继续当前游戏。</li><li>把会谈输入交给上述模型服务生成 NPC 回应。</li><li>不会自动授予研究用途或原文研究用途。</li></ul>
    {error && <div className="notice">{error}</div>}
    {granted ? <div className="consent-actions"><span>当前授权有效</span><button className="danger-quiet" disabled={busy} onClick={() => void onWithdraw()}>撤回授权</button></div> : <button disabled={busy} onClick={() => void onSign()}>{busy ? "正在记录授权…" : "同意必要授权并继续"}</button>}
  </div>;
}

function StructuredDecision({ pending, busy, onSubmit }: { pending: Dict; busy: boolean; onSubmit: (payload: Dict) => Promise<void> }) {
  const schema = pending.input_schema || {};
  const items: string[] = Array.isArray(schema.items) ? (schema.items as unknown[]).map(String) : [];
  const fields: string[] = Array.isArray(schema.fields) ? (schema.fields as unknown[]).map(String) : [];
  const total = Number(schema.total || 0);
  const [order, setOrder] = useState(items);
  const [allocations, setAllocations] = useState<Record<string, number>>(() => Object.fromEntries(fields.map((field, index) => [field, index === 0 ? total : 0])));
  const itemLabel = (item: string, index: number) => playerText(schema.labels?.[item] || arr(pending.options).find(option => option.option_id === item)?.text, `事项${chineseIndex(index)}`);
  if (pending.input_kind === "sorting") {
    const move = (index: number, delta: number) => setOrder(current => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current]; [next[index], next[target]] = [next[target], next[index]]; return next;
    });
    return <div className="structured-decision"><p>请按优先顺序排列，越靠上越先推进。</p>{order.map((item, index) => <div className="sort-row" key={item}><strong>{index + 1}</strong><span>{itemLabel(item, index)}</span><button onClick={() => move(index, -1)} disabled={busy || index === 0} aria-label={`上移第${index + 1}项`}>↑</button><button onClick={() => move(index, 1)} disabled={busy || index === order.length - 1} aria-label={`下移第${index + 1}项`}>↓</button></div>)}<button className="structured-submit" onClick={() => onSubmit({ ordered_option_ids: order })} disabled={busy || !order.length}>确认优先顺序</button></div>;
  }
  const allocated = Object.values(allocations).reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0);
  return <div className="structured-decision"><p>请分配全部 {total} {schema.unit || "份"}，不能剩余或超额。</p>{fields.map((field, index) => <label className="allocation-row" key={field}><span>{schema.labels?.[field] || `项目${chineseIndex(index)}`}</span><input type="number" min="0" step="1" value={allocations[field] ?? 0} onChange={event => setAllocations(current => ({ ...current, [field]: Math.max(0, Number(event.target.value) || 0) }))}/><em>{schema.unit || ""}</em></label>)}<div className={allocated === total ? "allocation-total valid" : "allocation-total invalid"}>已分配 {allocated} / {total}</div><button className="structured-submit" onClick={() => onSubmit({ parameters: { allocations } })} disabled={busy || allocated !== total}>确认分配</button></div>;
}

function ActionPanel({ data, onRun }: { data: Dict | null; onRun: (item: Dict) => void }) {
  const items = canonicalActionFamilies(data?.actions || data?.items || data) as Dict[];
  return <><div className="card-list action-list canonical-actions">{items.length ? items.map((item, index) => <article key={item.action_id || index} data-action-id={String(item.action_id || "")}><div className="card-number">{chineseIndex(index)}</div><div><h3>{governanceDisplayTitle(item, GOVERNANCE_ACTION_LABELS[String(item.action_id)] || "治理行动")}</h3><p>{playerText(item.description, "根据当前情况安排工作")}</p><div className="action-variants">{arr(item.variants).map(variant => { const descriptor = { ...item, ...variant, action_id: item.action_id }; const unreadArchiveCount = item.action_id === "inspect_archives" ? arr(variant.target_choices).length : 0; const buttonLabel = governanceActionButtonLabel(descriptor, variant.available === false ? "条件不足" : "填写方案"); return <section key={String(variant.variant_id)} data-variant-id={String(variant.variant_id || "")} className={variant.available === false ? "unavailable" : ""}><div><b>{governanceDisplayTitle(descriptor, playerText(variant.name, "当前办理方式"))}</b><p>{playerText(variant.description || variant.visible_result)}</p><small>{actionPointLabel(variant)}{item.action_id === "inspect_archives" ? ` · 待查档案 ${unreadArchiveCount} 份` : ""}</small>{variant.available === false && <em>{playerText(variant.unavailable_reason, "当前条件尚未满足")}</em>}</div><ActionTutorialButton item={descriptor} />{variant.variant_id === "consult_county_archives" && <button type="button" className="secondary" onClick={() => onRun(descriptor)}>已查阅的档案</button>}<button onClick={() => onRun(descriptor)} disabled={variant.available === false}>{variant.available === false ? "条件不足" : buttonLabel}</button></section>; })}</div></div></article>) : <Empty text="目前没有可安排的行动。先处理现场事项，或结束今天。"/>}</div></>;
}

function OpportunityPanel({ data, signingOnly = false, activeConversation, onStart, onContinue, onOpenProfile }: { data: Dict | null; signingOnly?: boolean; activeConversation: Dict | null; onStart: (item: Dict) => void; onContinue: () => void; onOpenProfile: (character: Character) => void }) {
  const opportunities = arr(data?.opportunities || []);
  const routines = arr(data?.person_actions);
  const { people, edges } = peopleRelationshipView(data) as { people: Dict[]; edges: Dict[] };
  const names = new Map(people.map(item => [String(item.npc_id), playerText(item.name, "相关人员")]));
  const shown = signingOnly ? people.filter(person => routines.some(item => item.npc_id === person.npc_id && item.contract_preparation?.household_count > 0)) : people;
  return <div className="people-relationship-view">
    {signingOnly && <section className="panel-note"><b>主动推进签约</b><p>选择住户或代表开展入户协商，了解顾虑后点击“准备逐户合同”。核定条款、通过审校，再由本人复核签署；只有实际签署才计入进度。</p></section>}
    {data?.blocked_reason && <div className="panel-note">{playerText(data.blocked_reason)}，完成后可继续安排。</div>}
    <div className="card-list people">{shown.length ? shown.map(person => {
      const character = resolveCharacter(person.npc_id, person.name);
      const name = character?.name || playerText(person.name, "已知人物");
      const presentation = personDiscoveryPresentation(person);
      const personActions = routines.filter(item => item.npc_id === person.npc_id);
      const hasNegotiation = personActions.some(item => item.variant_id === "contract_negotiation");
      const actions = personActions.filter(item => !signingOnly || (hasNegotiation ? item.variant_id === "contract_negotiation" : item.action_id === "household_visit"));
      const topics = signingOnly ? [] : opportunities.filter(item => item.npc_id === person.npc_id);
      const contactLabel = actions.length ? (actions.some(item => item.available !== false) ? "可主动联系" : "已见面 · 暂不能安排行动") : presentation.statusLabel;
      return <article key={String(person.npc_id)} data-character-id={character?.id || person.npc_id} className={actions.length ? "contactable" : "known-only"}>
        {presentation.allowProfile ? <button type="button" className="person-portrait profile-avatar-button" aria-label={`查看${name}人物介绍`} onClick={() => character && onOpenProfile(character)} disabled={!character}><CharacterPortrait character={character} fallbackName={name} /></button> : <div className="person-portrait dossier-mention-placeholder">档</div>}
        <div className="person-copy"><small>{character?.role || "已知人物"} · {contactLabel}</small><h3>{name}</h3>
          {presentation.showRelationship ? <div className="relationship-bands" aria-label={`${name}关系态势`}><span>信任：{qualitativeRelationshipLabel(person.trust_band)}</span><span>态度：{qualitativeRelationshipLabel(person.attitude_band)}</span><span>焦虑：{qualitativeRelationshipLabel(person.anxiety_band)}</span></div> : <p>材料中已提及此人，等待本人正式进入现场。</p>}
           {presentation.showRelationship && values(person.recent_change_reasons).length > 0 && <details className="relationship-reasons"><summary>近期关系变化依据</summary>{values(person.recent_change_reasons).map((reason, index) => <p key={index}>{playerText(reason)}</p>)}</details>}
          {actions.map(item => <div className="person-action" key={String(item.variant_id)}><div><b>{governanceDisplayTitle(item, playerText(item.name, "当前会谈"))}</b><small>{actionPointLabel(item)}</small>{item.available === false && <p>{playerText(item.unavailable_reason)}</p>}{signingOnly && item.contract_preparation?.reason && <p>{playerText(item.contract_preparation.reason)}；可先走访了解情况。</p>}</div><button disabled={Boolean(activeConversation) || item.available === false} onClick={() => onStart({...item, canonical_topic: signingOnly ? "了解本户搬迁顾虑，协商逐户合同与安置安排" : ""})}>{signingOnly ? "入户协商" : governanceActionButtonLabel(item, "开始会谈")}</button></div>)}
          {topics.map(item => { const descriptor = item.canonical_action_descriptor; const matching = actions.find(action => action.variant_id === descriptor?.variant_id); const isActive = activeConversation?.opportunity_id === item.opportunity_id; return <div className="person-action" key={String(item.opportunity_id)}><div><small>当前剧情话题</small><p>{playerText(item.opening_narrative || item.conversation_goal)}</p>{matching && <small>{actionPointLabel(matching)}</small>}</div>{isActive ? <button onClick={onContinue}>继续会谈</button> : descriptor && <button disabled={!matching?.available || Boolean(activeConversation)} onClick={() => onStart(item)}>谈这件事</button>}</div>; })}
          {!actions.length && !topics.length && presentation.showRelationship && <p>当前没有已开放的会谈安排。</p>}
        </div></article>;
    }) : <Empty text={signingOnly ? "尚未接触可办理签约的住户。请先完成当前剧情，认识村民后再来安排入户协商。" : "尚未认识可以查看档案的人物。"} />}</div>
    {!signingOnly && edges.length > 0 && <section className="relationship-graph" aria-label="已揭示的人物关系"><h3>已揭示关系</h3><div>{edges.map(edge => <article key={String(edge.edge_id)}><b>{names.get(String(edge.source_npc_id)) || "相关人员"}</b><span>{friendlyStatus(edge.channel)} · 已确认</span><b>{names.get(String(edge.target_npc_id)) || "相关人员"}</b>{edge.discovery_reason && <p>{playerText(edge.discovery_reason)}</p>}</article>)}</div></section>}
  </div>;
}

function GovernancePanel({ data, onOpenRecord, onOpenArchive, onOpenContract }: { data: Dict | null; onOpenRecord: (record: { meeting?: Dict; document?: Dict }) => void; onOpenArchive: (archive: Dict) => void; onOpenContract: (contract: Dict) => void }) {
  const [archiveNoticeId, setArchiveNoticeId] = useState("");
  if (!data) return <Empty text="正在整理治理进展…"/>;
  const actions = arr(data.governance_actions);
  const meetings = arr(data.meetings);
  const documents = arr(data.documents);
  const archives = arr(data.archives);
  const archiveGroups = archiveInvestigationGroups(archives);
  const contracts = arr(data.contracts);
  const resourceInventory = resourceInventoryView(get(data, "resources.resource_pools"));
  const activeActions = actions.filter(item => item.status === "active");
  const stats = [
    ["进行中的行动", activeActions.length], ["已召开会议", arr(data.meetings).length],
    ["已形成文件", arr(data.documents).length], ["待查档案", archiveGroups.unreadCount],
  ];
  const cash = get(data, "resources.cash_ledger");
  return <div className="governance-panel"><div className="governance-grid">{stats.map(([label, value]) => <div key={String(label)}><strong>{value}</strong><span>{label}</span></div>)}</div>{cash && <section className="resource-card"><small>财政资源</small><h3>可安排 {displayValue(cash.available_unencumbered, "待定")} 万元</h3><p>已支付 {displayValue(cash.paid, 0)} 万元</p></section>}{resourceInventory.length > 0 && <ResourceInventoryLedger items={resourceInventory} />}<PanelSection title="行动记录" items={actions.slice().reverse().slice(0, 6)} empty="尚未开展治理行动" render={(item) => <><div className="evidence-head"><h4>{governanceDisplayTitle(item, GOVERNANCE_ACTION_LABELS[item.action_kind] || "治理行动")}</h4><span>{friendlyStatus(item.status)}</span></div><p>{playerText(item.topic, `第 ${item.story_day || "待定"} 日开展`)}</p></>} /><PanelSection title="逐户合同记录" items={contracts} empty="尚未建立逐户合同；请在与相关人员或代表的入户会谈中提出签约" render={(item) => <div className="governance-record-row"><div><h4>{playerText(item.signatory_name, item.household_id || "待确认家庭")}</h4><p>{item.household_id} · {friendlyStatus(item.status)} · {playerText(item.resource_hold_status, "尚未扣除资源")}</p></div>{item.status === "signed" ? <button onClick={() => onOpenContract(item)}>查看合同</button> : <small>请在相关人员或代表的入户会谈中继续办理</small>}</div>} /><PanelSection title="已取得档案" items={archives} empty="尚未取得可查阅档案" render={(item) => { const archiveId = String(item.archive_id || ""); const hasBeenRead = values(item.read_at_days).length > 0; const archiveUnavailable = data.can_inspect_archives === false || get(data, "permissions.can_inspect_archives") === false; const archiveHint = archiveUnavailable ? playerText(data.inspect_blocked_reason || data.action_blocked_reason, "当前决策期间无法发起查阅行动。请先处理当前决策。") : "这份档案尚未查阅，请前往“行动 → 查阅档案”完成首次查阅。"; return <div className="governance-record-row"><div><h4>{playerText(item.title, "治理档案")}</h4><p>{friendlyStatus(item.evidence_level)} · {hasBeenRead ? `已于第 ${values(item.read_at_days).at(-1)} 日查阅` : "尚未查阅"}</p></div>{hasBeenRead ? <button type="button" onClick={() => onOpenArchive(item)}>重读正文</button> : <><button type="button" className="archive-unread-status" aria-describedby={`archive-hint-${archiveId}`} onClick={() => setArchiveNoticeId(archiveId)}>等待查阅</button>{archiveNoticeId === archiveId && <small id={`archive-hint-${archiveId}`} className="archive-unread-hint" role="status">{archiveHint}</small>}</>}</div>; }} /><PanelSection title="会议、听证与议事记录" items={meetings} empty="尚无会议、听证或议事记录" render={(item) => { const document = documents.find(value => String(value.source_meeting_id) === String(item.meeting_id)); const presentation = actionPresentation(meetingAction(item, data)); return <div className="governance-record-row"><div><h4>{playerText(item.topic || item.title, presentation.title)}</h4><small>{presentation.result}</small><p>第 {item.story_day || "待定"} 日 · {friendlyStatus(item.status)}</p></div><button onClick={() => onOpenRecord({ meeting: item, document })}>{document ? "查看决议" : `查看${presentation.result}`}</button></div>; }} /><PanelSection title="已形成文件" items={documents} empty="尚未形成新的正式文件" render={(item) => <div className="governance-record-row"><div><h4>{playerText(item.title || DOCUMENT_TYPE_LABELS[item.document_type], "治理文件")}</h4><p>{friendlyStatus(item.status)} · 第 {item.issued_day || item.story_day || "待定"} 日</p></div><button onClick={() => onOpenRecord({ document: item, meeting: meetings.find(value => String(value.source_meeting_id) === String(item.source_meeting_id)) })}>查看文件</button></div>} /></div>;
}

function ResourceInventoryLedger({ items }: { items: ReturnType<typeof resourceInventoryView> }) {
  const groups = [
    { title: "安置房源", items: items.filter(item => item.category === "housing") },
    { title: "合同配套服务", items: items.filter(item => item.category !== "housing" && item.allocatableScope !== "npc_demand") },
    { title: "治理专项能力", items: items.filter(item => item.allocatableScope === "npc_demand") },
  ].filter(group => group.items.length > 0);
  return <section className="resource-card resource-pool-card" data-testid="resource-pool-summary"><small>完整资源台账</small><h3>签约资源台账</h3><p className="resource-scope-note">全局共享库存（所有住户共用）。签约成功后立即扣除对应资金、房源和服务名额；标有开放日的资源到期后才能使用。</p>{groups.map(group => <section className="resource-inventory-group" key={group.title}><h4>{group.title}</h4><div className="resource-pool-grid">{group.items.map(item => <article key={item.resourceId}><b>{item.name}</b><span>剩余 {item.available} / 总量 {item.capacity} {item.unit}</span>{item.used > 0 && <em>已分配 {item.used} {item.unit}</em>}{item.availableDay > 1 && <small>第 {item.availableDay} 日开放</small>}</article>)}</div></section>)}</section>;
}

function ContractBatchProposal({ proposal, busy, onConfirm }: { proposal: Dict; busy: boolean; onConfirm: (confirmed: boolean) => void }) {
  const households = values(proposal.household_ids).map(String);
  return <div className="contract-proposal">
    <p>{playerText(proposal.intent_reason, "你正在为以下家庭准备逐户合同。")}</p>
    <section><small>本次涉及家庭</small><div className="contract-households">{households.map(id => <span key={id}>{id}</span>)}</div></section>
    <div className="contract-warning"><b>逐户独立签署</b><p>确认后只会建立 {households.length} 份独立草案。每户仍需单独核定资源、接受审阅并亲自签署，代表不能代签。</p></div>
    <div className="form-actions"><button type="button" className="secondary" disabled={busy} onClick={() => onConfirm(false)}>撤回提议</button><button type="button" disabled={busy} onClick={() => onConfirm(true)}>建立 {households.length} 份逐户合同</button></div>
  </div>;
}

function ContractWorkspace({ onTutorialStageChange, onNextStep, contract, governance, state, busy, api, sessionId, onPerform, onOpenContract, onDirtyChange, onContinue }: { onTutorialStageChange: (value: { id: string; stage: import("./tutorial/types").ContractTutorialStage }) => void; onNextStep: (step: NextStep) => void; contract: Dict; governance: Dict; state: Dict; busy: boolean; api: GameApi; sessionId: string; onPerform: (action: () => Promise<Dict>, success: string, aiLabel?: string) => Promise<void>; onOpenContract: (contract: Dict) => void; onDirtyChange: (dirty: boolean) => void; onContinue: () => void }) {
  const detailKey = `${sessionId}:${contract.contract_id}:${contract.current_version}:${state.story?.day}`;
  const [loadedBreakdown, setLoadedBreakdown] = useState<{key: string; value: Dict | null}>({key: "", value: null});
  const breakdown = contract.compensation_breakdown || (loadedBreakdown.key === detailKey ? loadedBreakdown.value : null);
  useEffect(() => {
    if (contract.compensation_breakdown) return;
    let cancelled = false;
    void api.contractDetail(sessionId, String(contract.contract_id)).then(result => {
      if (!cancelled) setLoadedBreakdown({key: detailKey, value: (result as Dict).contract?.compensation_breakdown || null});
    }).catch(() => { if (!cancelled) setLoadedBreakdown({key: detailKey, value: null}); });
    return () => { cancelled = true; };
  }, [api, sessionId, contract.contract_id, contract.compensation_breakdown, detailKey]);
  const status = String(contract.status || "awaiting_terms");
  const contractStatusLabel = (item: Dict) => item.status !== "signed" && item.current_version && ["rejected", "explanation_requested", "counteroffered"].includes(String(item.status)) && Number(item.review_version) !== Number(item.current_version) ? "待提交" : friendlyStatus(String(item.status || "awaiting_terms"));
  const editable = ["awaiting_terms", "draft", "explanation_requested", "counteroffered", "rejected"].includes(status);
  const terms = contract.term_sheet || {};
  const resources = arr(get(governance, "resources.resource_pools"));
  const housing = resources.filter(item => item.category === "housing");
  const services = resources.filter(item => item.category !== "housing" && item.allocatable_scope !== "npc_demand");
  const serviceInventory = new Map(resourceInventoryView(services).map(item => [item.resourceId, item]));
  const documents = arr(governance.documents);
  const policyDocuments = documents.filter(item => item.document_type === "compensation_policy" && ["issued", "published"].includes(String(item.status)));
  const approvalDocuments = documents.filter(item => item.document_type !== "compensation_policy" && ["issued", "published"].includes(String(item.status)));
  const siblingContracts = contractBatchTabs(governance.contracts, contract) as Dict[];
  const [editing, setEditing] = useState(!contract.current_version || Boolean(contract.legacy_draft));
  const [housingId, setHousingId] = useState(String(terms.housing_resource_id || ""));
  const selectedHousing = housing.find(item => String(item.resource_id) === housingId);
  const [dirty, setDirty] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [operationError, setOperationError] = useState("");
  const currentFeedback = contract.review_reason && Number(contract.review_version) === Number(contract.current_version);
  const tutorialStage = status === "signed" ? "signed" : contract.legacy_draft ? "legacy" : editing ? "terms" : currentFeedback ? "feedback" : "preview";
  useEffect(() => { onTutorialStageChange({ id: String(contract.contract_id), stage: tutorialStage }); }, [contract.contract_id, tutorialStage, onTutorialStageChange]);
  const showExistingReply = !busy && !dirty && !editing && !contract.legacy_draft && !contract.can_review && Boolean(currentFeedback);
  const submitBlockedReason = busy ? "正在处理，请勿重复提交。"
    : dirty ? "方案有修改尚未保存，请先保存方案并预览合同。"
    : contract.legacy_draft ? "请先核对旧约定并保存当前方案。"
    : editing ? "请先保存方案并预览合同，再提交签约。"
    : !contract.can_review ? playerText(contract.review_blocked_reason, "方案或实际事项变化后，可再次提交。") : "";
  const history = arr(contract.review_history).filter((item, index, all) => !(currentFeedback && index === all.length - 1 && Number(item.version) === Number(contract.current_version)));
  if (!history.length && contract.review_reason && !currentFeedback) history.push({ version: contract.review_version, reason: contract.review_reason });
  const fieldError = (name: string) => fieldErrors[name] ? <small role="alert">{playerText(fieldErrors[name])}</small> : null;
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  const mayLeave = () => !dirty || window.confirm("方案有修改尚未保存，确定放弃修改？");
  const [serviceAllocations, setServiceAllocations] = useState<Record<string, string>>(() => Object.fromEntries(services.map(item => [String(item.resource_id), String(get(terms, `service_allocations.${item.resource_id}`, 0))])));

  function submitTerms(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const allocations: Record<string, number> = {};
    services.forEach(item => {
      const amount = Number(serviceAllocations[String(item.resource_id)] || data.get(`service:${item.resource_id}`) || 0);
      if (amount > 0) allocations[String(item.resource_id)] = amount;
    });
    const payload = {
      state_version: state.state_version,
      acknowledge_legacy_text: acknowledged,
      policy_document_id: String(data.get("policy_document_id") || "doc_compensation_policy_v1"),
      cash_amount: Number(data.get("cash_amount") || 0),
      auto_arrange: true,
      housing_resource_id: String(data.get("housing_resource_id") || "") || null,
      service_allocations: allocations,
      ...(contract.household_id === "HE-02" ? { followup_plan: {
        ...(String(data.get("medical_provider") || "").trim() ? { medical_provider: String(data.get("medical_provider")).trim() } : {}),
        ...(data.get("recheck_interval_days") ? { recheck_interval_days: Number(data.get("recheck_interval_days")) } : {}),
        ...(String(data.get("employment_receiver") || "").trim() ? { employment_receiver: String(data.get("employment_receiver")).trim() } : {}),
        ...(data.get("medical_fee_arrangement") ? { medical_fee_arrangement: "allocated_medical_service" } : {}),
      } } : {}),
      approval_document_ids: data.getAll("approval_document_ids").map(String),
    };
    setFieldErrors({});
    setOperationError("");
    void onPerform(async () => {
      try {
        const result = await api.write(sessionId, `/governance/contracts/${encodeURIComponent(String(contract.contract_id))}/terms`, "PUT", payload) as Dict;
        setDirty(false); onDirtyChange(false); setEditing(false);
        return result;
      } catch (error) {
        setOperationError(error instanceof Error ? error.message : "保存失败，请重试。");
        if (error instanceof ApiError) setFieldErrors((error.details.field_errors || {}) as Record<string, string>);
        throw error;
      }
    }, "方案已保存，请核对合同后提交签约");
  }

  function submitReview() {
    setOperationError("");
    void onPerform(async () => {
      try {
        return await api.write(sessionId, `/governance/contracts/${encodeURIComponent(String(contract.contract_id))}/review`, "POST", { state_version: state.state_version, expected_contract_version: Number(contract.current_version) }) as Dict;
      } catch (error) {
        setOperationError(error instanceof Error ? error.message : "提交失败，请重试。");
        if (error instanceof ApiError && error.details.field_errors) {
          setFieldErrors(error.details.field_errors as Record<string, string>);
          setEditing(true);
        }
        throw error;
      }
    }, "本户签约处理结果已更新", "AI 正在阅读方案并生成签约答复");
  }

  return <div className="contract-workspace">
    <header data-tutorial-id="contract-household" className="contract-status"><div><small>{contract.household_id} · 逐户独立合同</small><h3>{playerText(contract.signatory_name, "待确认签约人")}</h3><p>当前方案：{contract.current_version ? `第 ${contract.current_version} 版` : "尚未保存"}</p>{contract.conversation_npc_name && <p>当前谈话人：{playerText(contract.conversation_npc_name)}{contract.conversation_npc_id !== contract.signatory_npc_id ? "（相关代表；本合同仍由上述本户签署）" : "（本户签约人）"}</p>}</div><span>{contractStatusLabel(contract)}</span></header>
    {siblingContracts.length > 1 && <nav className="contract-tabs" aria-label="同批次逐户合同">{siblingContracts.map(item => <button key={item.contract_id} className={item.contract_id === contract.contract_id ? "active" : ""} disabled={busy} onClick={() => { if (item.contract_id !== contract.contract_id && mayLeave()) { onDirtyChange(false); onOpenContract(item); } }}>{item.household_id}<small>{contractStatusLabel(item)}</small></button>)}</nav>}
    <div className="contract-progress"><span className={editing ? "active" : "done"}>一 填写方案</span><span className={!editing && status !== "signed" ? "active" : contract.current_version ? "done" : ""}>二 预览合同</span><span className={status === "signed" ? "done" : ""}>三 提交签约</span></div>
    {breakdown && <details className="compensation-breakdown"><summary>查看基础补偿计算明细（万元）</summary><p>{breakdown.source}</p><ul>{arr(breakdown.rows).map((row, index) => <li key={index}>{row.label}：{row.quantity} {row.unit} × {row.rate} 万元/{row.unit} = {Number(row.amount).toFixed(4)} 万元</li>)}</ul><p>向上取整补差：{Number(breakdown.rounding_adjustment).toFixed(4)} 万元；政策建议基础额：{breakdown.suggested_base_total} 万元。</p><p>过渡补偿按 {breakdown.transition_population} 人 × 等待月数 × {breakdown.transition_rate} 万元/人/月计算；未选安置房不产生等待交房补偿。</p>{breakdown.saved_total != null && <p>已保存方案：基础 {breakdown.saved_base_amount ?? "未单列"} 万元；过渡 {breakdown.saved_transition_amount ?? "未单列"} 万元；总额 {breakdown.saved_total} 万元。未保存的编辑不计入此明细。</p>}</details>}
    <p className="contract-hold">资源状态：{playerText(contract.resource_hold_status, "尚未扣除资源")}</p>
    {currentFeedback && <div data-tutorial-id="contract-feedback" tabIndex={-1} className="contract-review"><b>对方的签约答复 · 方案第{contract.review_version}版</b><p>{playerText(contract.review_reason)}</p></div>}
    {values(contract.remaining_conditions).length > 0 && <section className="contract-review"><b>当前尚需办理</b><ul>{values(contract.remaining_conditions).map((condition, index) => <li key={index}>{playerText(condition)}</li>)}</ul></section>}
    <NextStepGuidance steps={contract.next_steps} busy={busy} onOpen={onNextStep} />
    {history.length > 0 && <details className="contract-review"><summary>协商记录 · 历次答复</summary>{history.map((item, index) => <article key={index}><b>针对方案第{item.version || "先前"}版</b>{Number(item.version) !== Number(contract.current_version) && <small> · 当前方案已更新</small>}<p>{playerText(item.reason)}</p></article>)}</details>}
    {editable && <div><button type="button" className="secondary" disabled={busy || !contract.conversation_available} onClick={() => { if (mayLeave()) onContinue(); }}>继续协商</button>{!contract.conversation_available && <p>请先与本户签约人或相关代表开展入户会谈，再继续协商。</p>}</div>}
    {arr(contract.legacy_versions).length > 0 && <details className="contract-review"><summary>旧版正文存档</summary><p>旧正文中的额外约定不会自动成为新方案的资源安排，请逐项核对后保存方案。</p>{arr(contract.legacy_versions).map(item => <article key={item.version}><b>第{item.version}版</b><pre className="contract-body">{String(item.text || "")}</pre></article>)}</details>}
    {editable && editing && <form className="contract-terms-form" onSubmit={submitTerms} onChange={() => setDirty(true)} onInvalidCapture={event => { const input = event.target as HTMLInputElement; setOperationError("请检查方案中的输入，修正标出的项目后再保存。"); setFieldErrors(current => ({ ...current, [input.name]: input.validationMessage })); }}>
      <h3>补偿与安置方案</h3><p>填写基础补偿，选择住房和配套服务。系统安排日期、计算过渡补偿并加入总额；保存后核对合同及总花费，签约成功才扣款。</p>
      <div data-tutorial-id="contract-fields" className="contract-field-grid">
        {policyDocuments.length > 1 ? <label>依据补偿方案<select name="policy_document_id" defaultValue={terms.policy_document_id || policyDocuments[0]?.document_id}>{policyDocuments.map(item => <option key={item.document_id} value={item.document_id}>{item.title}</option>)}</select>{fieldError("policy_document_id")}</label> : <div><input type="hidden" name="policy_document_id" value={terms.policy_document_id || policyDocuments[0]?.document_id || "doc_compensation_policy_v1"} /><b>依据补偿方案</b><p>{policyDocuments[0]?.title || "云溪县柳林村整体搬迁补偿安置方案"}</p>{policyDocuments[0]?.content && <details><summary>查看政策原文</summary><p>{policyDocuments[0].content}</p></details>}{fieldError("policy_document_id")}</div>}
        <label>基础补偿（万元）<input name="cash_amount" type="number" min="0" max="8000" defaultValue={terms.automatic_arrangement?.base_cash_amount ?? terms.cash_amount ?? contract.suggested_base_cash_amount ?? contract.suggested_cash_amount ?? ""} placeholder="按本户补偿方案填写" required />{fieldError("cash_amount")}</label>
        <label data-tutorial-id="contract-housing">安置房源<select name="housing_resource_id" value={housingId} onChange={event => setHousingId(event.target.value)}><option value="">不采用实物安置</option>{housing.map(item => <option key={item.resource_id} value={item.resource_id} disabled={Number(item.available ?? item.capacity) <= 0}>{item.name}（可用 {displayValue(item.available, item.capacity)}）</option>)}</select>{fieldError("housing_resource_id")}</label>
      </div>
      {selectedHousing && <p className="contract-housing-details" role="note">所选房源：{playerText(selectedHousing.name)}{selectedHousing.attributes?.area_m2 != null ? ` · 面积 ${selectedHousing.attributes.area_m2}㎡` : ""}{typeof selectedHousing.attributes?.accessible === "boolean" ? ` · ${selectedHousing.attributes.accessible ? "具备低楼层无障碍条件" : "不具备无障碍条件"}` : ""}{selectedHousing.available_day != null ? ` · 最早可用日：第 ${selectedHousing.available_day} 日` : ""}。实际交房日以保存后的合同为准。</p>}
      <p>预算自动记账。搬离日为当前日后20天（最晚第90日），交房日按房源安排。等待交房每30天计一个过渡月，不足一月按一月计；未选安置房不产生等待交房补偿。</p>
       <fieldset data-tutorial-id="contract-services"><legend>配套服务资源</legend><p className="contract-resource-hint">这些服务由所有住户共用。保存方案暂不占用资源，对方接受签约后分配；提交时会再次检查剩余数量。</p><div className="service-allocation-grid">{services.map(item => { const inventory = serviceInventory.get(String(item.resource_id)); const contractAmount = Number(serviceAllocations[String(item.resource_id)] || 0); const unit = inventory?.unit || "份"; return <label className="service-resource-label" key={item.resource_id}><span>{item.name}</span><small>本合同 {contractAmount} {unit} · 预计签后剩余 {Math.max(0, (inventory?.available ?? 0) - contractAmount)} {unit}</small><small>当前库存 {inventory?.available ?? 0} / {inventory?.capacity ?? 0} {unit}{inventory?.used ? ` · 已分配 ${inventory.used}` : ""}</small><input name={`service:${item.resource_id}`} type="number" min="0" max={inventory?.available ?? 0} value={serviceAllocations[String(item.resource_id)] ?? "0"} onChange={event => setServiceAllocations(current => ({ ...current, [String(item.resource_id)]: event.target.value }))} />{fieldError(`service_allocations.${item.resource_id}`)}</label>; })}</div></fieldset>
      {contract.household_id === "HE-02" && <fieldset className="contract-followup-plan"><legend>复查与就业转介附件</legend><p>请填写与本户商定的机构和接收单位，并在上方分配复查及就业或培训名额。这些是约定安排，不表示服务已完成；可先保存未完善的草案。</p><div className="contract-field-grid">
        <label>复查机构<input name="medical_provider" maxLength={120} defaultValue={terms.followup_plan?.medical_provider || ""} />{fieldError("followup_plan.medical_provider")}</label>
        <label>复查间隔（天）<input name="recheck_interval_days" type="number" min="1" max="365" step="1" defaultValue={terms.followup_plan?.recheck_interval_days || ""} />{fieldError("followup_plan.recheck_interval_days")}</label>
        <label>就业转介接收单位<input name="employment_receiver" maxLength={120} defaultValue={terms.followup_plan?.employment_receiver || ""} />{fieldError("followup_plan.employment_receiver")}</label>
        <label>复查费用安排<select name="medical_fee_arrangement" defaultValue={terms.followup_plan?.medical_fee_arrangement || ""}><option value="">尚未约定</option><option value="allocated_medical_service">按已分配医疗服务资源承担</option></select>{fieldError("followup_plan.medical_fee_arrangement")}</label>
      </div>{fieldError("followup_plan")}</fieldset>}
      {approvalDocuments.length > 0 && <fieldset><legend>已签发的红头文件</legend><div className="contract-check-grid">{approvalDocuments.map(item => <label key={item.document_id}><input name="approval_document_ids" type="checkbox" value={item.document_id} defaultChecked={values(terms.approval_document_ids).includes(item.document_id)} />{item.title}</label>)}</div>{fieldError("approval_document_ids")}</fieldset>}
      {contract.legacy_draft && <label data-tutorial-id="contract-legacy"><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} />我已核对旧正文中的额外约定，并在方案中安排需要保留的内容。</label>}
      {dirty && <p role="status">有修改尚未保存，请先保存方案再提交签约。</p>}
      {operationError && <p role="alert">{playerText(operationError)}</p>}
      <button data-tutorial-id="contract-save" disabled={busy || (contract.legacy_draft && !acknowledged)}>{busy ? "正在处理…" : "保存方案并预览合同"}</button>
    </form>}
    {!editing && operationError && <p role="alert">{playerText(operationError)}</p>}
    {contract.contract_text && !contract.legacy_draft && <section data-tutorial-id="contract-preview" className="contract-text-section"><header><div><small>当前方案第{contract.current_version}版{dirty ? "（尚未包含未保存的修改）" : ""}</small><h3>合同预览</h3></div></header><pre className="contract-body">{String(contract.contract_text)}</pre>{editable && !editing && <button className="secondary" disabled={busy} onClick={() => setEditing(true)}>修改方案</button>}</section>}
    {contract.term_sheet && status !== "signed" && <section data-tutorial-id="contract-deduction" className="contract-deduction-preview" aria-label="当前方案扣除预览"><h3>签订成功时扣除</h3><p>现金 {displayValue(terms.cash_amount, 0)} 万元{terms.housing_resource_id ? ` · ${playerText(resources.find(item => item.resource_id === terms.housing_resource_id)?.name, "所选房源")} 1 套` : ""}{Object.entries(terms.service_allocations || {}).filter(([, amount]) => Number(amount) > 0).map(([id, amount]) => ` · ${playerText(resources.find(item => item.resource_id === id)?.name, "所选服务")} ×${amount}`).join("")}</p><small>以上为已生成合同的条款。对方接受后立即扣除；拒绝或继续协商不扣除。</small></section>}
    <div className="contract-final-actions">{editable && contract.current_version > 0 && <div><p>对方接受后合同立即生效，并扣除约定款项和资源。</p><p className="contract-effort" role="note">{playerText(contract.review_cost_hint, "有效提交签约每次消耗 1 点精力，接受或拒签均计费；关联对话不另扣。重复请求、输入校验失败或技术失败不计费。")}{typeof contract.review_cost_action_points === "number" ? ` 本次提交需 ${contract.review_cost_action_points} 点精力。` : ""}</p>{submitBlockedReason && <p id="contract-submit-status" role="status">{submitBlockedReason}</p>}{operationError && editing && <p className="contract-submit-error">保存未成功：{playerText(operationError)}</p>}{editing && <button type="button" className="secondary" onClick={event => { event.currentTarget.closest(".contract-workspace")?.querySelector(".contract-terms-form")?.scrollIntoView({ block: "start", behavior: "smooth" }); }}>返回方案检查</button>}<button data-tutorial-id="contract-submit" aria-describedby={submitBlockedReason ? "contract-submit-status" : undefined} disabled={!showExistingReply && Boolean(submitBlockedReason)} onClick={showExistingReply ? event => { const feedback = event.currentTarget.closest(".contract-workspace")?.querySelector<HTMLElement>('[data-tutorial-id="contract-feedback"]'); feedback?.scrollIntoView({ block: "center", behavior: "instant" }); feedback?.focus({ preventScroll: true }); } : submitReview}>{showExistingReply ? "查看本次答复" : busy ? "正在处理…" : dirty || editing ? "请先保存方案" : "提交签约"}</button></div>}{status === "signed" && <div data-tutorial-id="contract-signed" className="signed-contract-seal"><b>已签署</b><span>第 {contract.signed_day} 日</span></div>}</div>
  </div>;
}

function ArchiveReading({ result }: { result: Dict }) {
  const records = arr(result.records);
  const gains = archiveReadGains(result);
  return <div data-tutorial-id="archive-result" className="archive-reading">{records.map((record, index) => <ArchiveRecordView key={record.archive_id || index} record={record} index={index} />)}{gains.facts.length > 0 && <section className="archive-read-gains learned"><h3>新掌握线索</h3>{gains.facts.map((fact, index) => <article key={String(fact.fact_id || index)}><b>{playerText(fact.title || fact.name, `线索${chineseIndex(index)}`)}</b>{Boolean(fact.summary) && <p>{playerText(fact.summary)}</p>}</article>)}</section>}{gains.strategicUses.length > 0 && <section className="archive-read-gains uses"><h3>可用于什么</h3><ul>{gains.strategicUses.map(item => <li key={item}>{playerText(item)}</li>)}</ul></section>}</div>;
}

function ArchiveRecordView({ record, index }: { record: Dict; index: number }) {
  const sections = archivePlayerSections(record);
  const householdLedger = sections.some(section => section.kind === "household");
  return <article><header><small>{playerText(record.category, "治理档案")} · {friendlyStatus(record.evidence_level)}</small><h3>{playerText(record.title, `档案${chineseIndex(index)}`)}</h3><p>取得于第 {record.acquired_day || "待定"} 日 · {friendlyStatus(record.confidentiality)}</p></header><div className={householdLedger ? "archive-body household-ledger" : "archive-body"}>{sections.map((section, sectionIndex) => <section className={section.kind === "household" ? "archive-section-household" : undefined} key={`${section.heading}:${sectionIndex}`}><h4>{section.heading}</h4><p>{section.body}</p></section>)}</div></article>;
}

function GovernanceRecordDetail({ record, governance, busy, onAction }: { record: { meeting?: Dict; document?: Dict }; governance: Dict; busy: boolean; onAction: (documentId: string, suffix: string, method: "POST" | "PUT", body: Dict, success: string) => Promise<void> }) {
  const document = record.document;
  const meeting = record.meeting;
  const presentation = actionPresentation(meetingAction(meeting, governance));
  const [content, setContent] = useState(playerText(document?.content));
  const people = arr(get(governance, "target_catalogs.meeting_participants"));
  const nameFor = (id: unknown) => playerText(people.find(item => String(item.target_id || item.id) === String(id))?.label, resolveCharacter(String(id))?.name || "相关人员");
  const required = values(document?.required_countersign_ids).map(String);
  const signed = values(document?.countersigned_by).map(String);
  const missing = required.filter(id => !signed.includes(id));
  const scope = values(get(document, "resolution_snapshot.public_scope", document?.public_scope)).map(String).filter(Boolean);
  const status = String(document?.status || "");
  const reviewStatus = String(document?.review_status || "not_reviewed");
  const reviewPassed = reviewStatus === "pass";
  const statusStep = status === "published" ? 5 : status === "issued" ? 4 : status === "approved" ? 3 : reviewPassed ? 2 : 1;
  const reviewHistory = arr(document?.review_history);
  const latestReview = reviewHistory.at(-1) || {};
  const revisionHistory = arr(document?.revision_history);
  const resolution = document?.resolution_snapshot || meeting?.resolution || {};
  const summary = playerText(resolution.decision || resolution.decision_summary || resolution.summary || resolution.implementation_plan || meeting?.topic, `${presentation.conclusion}已收入${presentation.result}。`);
  if (!document) return <div className="governance-record-detail"><section className="record-brief"><small>{presentation.result}</small><h3>{playerText(meeting?.topic, presentation.title)}</h3><p>第 {meeting?.story_day || "待定"} 日 · {friendlyStatus(meeting?.status)}</p></section><section className="record-content"><h4>{presentation.conclusion}</h4><p>{summary}</p></section>{arr(meeting?.transcript).length > 0 && <section className="record-content"><h4>讨论记录</h4>{arr(meeting?.transcript).map((line, index) => <p key={line.turn_id || index}><b>{nameFor(line.npc_id || line.speaker_id || line.speaker)}</b>{playerText(line.text || line.content || line.response)}<ReferenceAttachments references={line.references} /></p>)}</section>}</div>;
  const id = String(document.document_id);
  return <div className="governance-record-detail">
    <section className="record-brief"><small>{DOCUMENT_TYPE_LABELS[document.document_type] || "会议形成文件"}</small><h3>{playerText(document.title, "治理文件")}</h3><p>源自第 {meeting?.story_day || document.story_day || "待定"} 日{presentation.title} · 当前{friendlyStatus(status)}</p></section>
    <ol className="document-progress" aria-label="文件办理进度">{["形成文本", "文书审校", "完成会签", "正式印发", "对外公示"].map((label, index) => <li key={label} className={statusStep > index ? "done" : statusStep === index ? "current" : ""}><span>{index + 1}</span><b>{label}</b></li>)}</ol>
    <section className="record-content"><h4>会议决议</h4><p>{summary}</p></section>
    <section className="record-content"><h4>文件正文</h4>{["draft", "pending_countersign"].includes(status) ? <textarea value={content} onChange={event => setContent(event.target.value)} maxLength={30000} disabled={busy} /> : <p className="document-text">{playerText(document.content, "暂无正文")}</p>}{["draft", "pending_countersign"].includes(status) && <button className="secondary record-action" disabled={busy || !content.trim() || content.trim() === playerText(document.content)} onClick={() => void onAction(id, "", "PUT", { content: content.trim() }, "文件修订已经保存，会签进度将重新开始")}>保存修订</button>}</section>
    <section className={`record-content document-review ${reviewPassed ? "passed" : "pending"}`}><div className="document-review-head"><div><h4>文书 Agent 审校</h4><p>{playerText(document.review_summary, "等待独立审校模型检查正文。")}</p></div><b>{friendlyStatus(reviewStatus)}</b></div>{document.review_model_id && <small>审校模型：{playerText(document.review_model_id)}</small>}{values(latestReview.issues).length > 0 && <ul>{arr(latestReview.issues).map((issue, index) => <li key={issue.issue_id || index}><strong>{playerText(issue.message, "发现正文问题")}</strong><span>{playerText(issue.suggestion, "请按会议决议修订。")}</span></li>)}</ul>}{revisionHistory.length > 0 && <details><summary>查看自动修订记录（{revisionHistory.length}）</summary>{revisionHistory.map((item, index) => <p key={index}>第 {item.from_version} 版 → 第 {item.to_version} 版：{playerText(item.change_summary, "已根据审校意见修订")}</p>)}</details>}</section>
    <section className="record-content"><h4>必要会签</h4>{required.length ? <div className="signer-list">{required.map(signerId => <div key={signerId} className={signed.includes(signerId) ? "signed" : "pending"}><span>{nameFor(signerId)}</span><b>{signed.includes(signerId) ? "已会签" : "待会签"}</b>{!signed.includes(signerId) && ["draft", "pending_countersign"].includes(status) && <button disabled={busy || !reviewPassed} title={!reviewPassed ? "文书审校通过后才能会签" : undefined} onClick={() => void onAction(id, "/countersign", "POST", { npc_id: signerId }, `${nameFor(signerId)}已完成会签`)}>请其会签</button>}</div>)}</div> : <p>本文件无需额外会签。</p>}</section>
    <div className="record-next-step">{!reviewPassed ? <>下一步：等待文书审校与自动修订通过。</> : missing.length > 0 ? <>下一步：请 {missing.map(nameFor).join("、")} 完成会签。</> : status === "approved" ? <>会签已经齐备，可以正式印发。</> : status === "issued" ? <>文件已印发，可以按会议确定的范围进行公示。</> : status === "published" ? <>文件已完成公示，后续执行情况会进入治理记录。</> : <>文件正在按会议决议办理。</>}</div>
    <div className="record-actions">{status === "approved" && <button disabled={busy} onClick={() => void onAction(id, "/issue", "POST", {}, "决议文件已经正式印发并归档")}>正式印发</button>}{status === "issued" && <button disabled={busy || !scope.length} onClick={() => void onAction(id, "/publish", "POST", { scope }, "决议文件已经按会议范围公示")}>按决议范围公示</button>}</div>
  </div>;
}

function DeskPanel({ data }: { data: Dict | null }) {
  if (!data) return <Empty text="正在整理案头卷宗…"/>;
  const mission = data.mission || {};
  const policy = data.compensation_policy || {};
  return <div className="desk-panel"><section className="mission-card"><small>专班任务书</small><h3>{playerText(mission.title, "清江搬迁任务")}</h3><p>{playerText(mission.summary, "在期限、财政、稳定和程序约束下推进柳林村整村搬迁。")}</p></section><div className="constraint-grid">{arr(mission.hard_constraints).map((item, index) => <article key={item.key || index}><small>{playerText(item.label, `约束${chineseIndex(index)}`)}</small><strong>{playerText(displayValue(item.value))}</strong><p>{playerText(item.detail)}</p></article>)}</div>{policy.title && <details className="policy-details"><summary>查看补偿与安置执行口径</summary><section><h3>{playerText(policy.title)}</h3><p>{playerText(policy.status)}</p>{arr(policy.funding).length > 0 && <div className="policy-funding">{arr(policy.funding).map((item, index) => <div key={index}><small>{playerText(item.label)}</small><strong>{playerText(item.value)}</strong></div>)}</div>}<h4>适用原则</h4><ul>{values(policy.principles).map((item, index) => <li key={index}>{playerText(item)}</li>)}</ul><h4>县长权限边界</h4><ul>{values(policy.authority_boundaries).map((item, index) => <li key={index}>{playerText(item)}</li>)}</ul></section></details>}<PanelSection title="背景卷宗" items={arr(data.dossiers)} empty="暂无可读卷宗" render={(item) => <><h4>{playerText(item.title, "背景材料")}</h4><p>{playerText(item.summary)}</p>{values(item.known_points).length > 0 && <ul>{values(item.known_points).map((point, index) => <li key={index}>{playerText(point)}</li>)}</ul>}</>} /></div>;
}

function KnowledgePanel({ data }: { data: Dict | null }) {
  if (!data) return <Empty text="正在核对已掌握材料…"/>;
  const groups = [["已确认事实", arr(data.facts)], ["待核线索", arr(data.clues)], ["证据材料", arr(data.evidence)]] as const;
  const leads = investigationLeadView(data.investigation_leads);
  return <div className="knowledge-panel">{leads.length > 0 && <section className="panel-section investigation-leads"><h3>当前可调查方向</h3><p className="panel-note">这里只提示当前已经开放的调查入口；材料尚未取得前，不会把待核内容当成事实。</p><div>{leads.map(lead => <article key={lead.factId}><div className="evidence-head"><h4>{lead.title}</h4><span>{lead.category === "evidence" ? "证据方向" : lead.category === "fact" ? "事实核对" : "线索方向"}</span></div>{lead.methods.map(method => <div className="investigation-method" key={`${lead.factId}:${method.routeType}:${method.label}`}><b>{method.routeType === "archive" ? "查档" : "会谈"} · {method.label}</b><p>{method.instructions}</p></div>)}</article>)}</div></section>}{groups.map(([title, items]) => <PanelSection key={title} title={title} items={items} empty={`暂无${title}`} render={(item) => <><div className="evidence-head"><h4>{playerText(item.title || item.name || item.label, "新材料")}</h4>{(item.evidence_level || item.confidentiality) && <span>{friendlyStatus(item.evidence_level || item.confidentiality)}</span>}</div><p>{playerText(item.text || item.summary || item.description || item.content, "已收入案头，等待进一步核实。")}</p>{(item.source_label || item.use_hint) && <dl className="knowledge-provenance">{item.source_label && <><dt>来源</dt><dd>{playerText(item.source_label)}</dd></>}{item.use_hint && <><dt>用途</dt><dd>{playerText(item.use_hint)}</dd></>}</dl>}</>} />)}</div>;
}

function ReviewPanel({ data, api, sessionId, governance }: { data: Dict | null; api: GameApi; sessionId: string; governance: Dict | null }) {
  const [historyResult, setHistoryResult] = useState<{
    requestKey: string;
    items: Dict[];
    error: string;
  }>({ requestKey: "", items: [], error: "" });
  const [npcFilter, setNpcFilter] = useState("");
  const [dayFilter, setDayFilter] = useState("");
  const [conversationFilter, setConversationFilter] = useState("");
  const historyRequestKey = `${sessionId}|${npcFilter}|${dayFilter}`;
  const historyLoading = Boolean(sessionId) && historyResult.requestKey !== historyRequestKey;
  const conversationHistory = historyResult.requestKey === historyRequestKey ? historyResult.items : [];
  const historyError = historyResult.requestKey === historyRequestKey ? historyResult.error : "";
  useEffect(() => {
    if (!sessionId) return;
    let active = true;
    api.completeConversationHistory(sessionId, {
      ...(npcFilter ? { npc_id: npcFilter } : {}),
      ...(dayFilter ? { story_day: Number(dayFilter) } : {}),
      limit: 100,
    }).then(items => {
      if (active) setHistoryResult({ requestKey: historyRequestKey, items: items as Dict[], error: "" });
    }).catch(error => {
      if (active) setHistoryResult({ requestKey: historyRequestKey, items: [], error: playerErrorMessage(error) });
    });
    return () => { active = false; };
  }, [api, sessionId, npcFilter, dayFilter, historyRequestKey]);
  if (!data) return <Empty text="正在整理本局纪要…"/>;
  const ending = reviewEndingView(data);
  const timelines = ([
    ...arr(data.decision_timeline).map(item => ({ ...item, typeLabel: "你的决定" })),
    ...arr(data.action_timeline).map(item => ({ ...item, typeLabel: "治理行动" })),
    ...arr(data.conversation_timeline).map(item => ({ ...item, typeLabel: "人物会谈" })),
    ...arr(data.group_conversation_timeline).map(item => ({ ...item, typeLabel: "多人会谈" })),
    ...arr(data.visible_events).map(item => ({ ...item, typeLabel: "重要事件" })),
  ] as Array<Dict & { typeLabel: string }>).sort((a, b) => Number(a.story_day || a.day || 0) - Number(b.story_day || b.day || 0));
  const timelineTitle = (item: Dict) => {
    if (item.typeLabel === "人物会谈") {
      if (item.event === "conversation_started") return `开始与${item.npc_name || "相关人员"}会谈`;
      if (item.event === "conversation_ended") return `结束与${item.npc_name || "相关人员"}的会谈${item.completion_status === "incomplete" ? "（仍有事项未谈妥）" : ""}`;
    }
    if (item.typeLabel === "多人会谈") return playerText(item.agenda, "完成一次必须回应的多人会谈");
    return playerText(item.title || item.name || item.summary || item.text, "已记录事项");
  };
  const npcOptions = new Map(arr(data.conversation_timeline).filter(item => item.npc_id).map(item => [String(item.npc_id), playerText(item.npc_name, "相关人员")]));
  const filteredConversations = conversationFilter.trim()
    ? conversationHistory.filter(item => String(item.conversation_id || "").includes(conversationFilter.trim()))
    : conversationHistory;
  const otherRecords = ([
    ...arr(data.group_conversation_timeline).map(item => ({ ...item, recordTitle: playerText(item.agenda, "多人会谈") })),
    ...arr(governance?.governance_actions).filter(item => item.action_kind !== "leadership_meeting").map(item => ({ ...item, recordTitle: playerText(item.topic, "治理行动") })),
    ...arr(governance?.meetings).map(item => ({ ...item, recordTitle: playerText(item.topic, "会议记录") })),
  ] as Dict[]).filter(item => arr(item.transcript).length);
  return <div className="review-panel">{ending && <section className="ending-review-card" aria-label="最终结局"><header><small>九十日治理结局</small><h3>{ending.mainName}</h3>{ending.subTitle && <p>余波：{ending.subTitle}</p>}</header><div className="ending-axis-grid">{ending.axes.map(axis => <div key={axis.key}><small>{ENDING_AXIS_LABELS[axis.key] || "治理影响"}</small><b>{playerText(axis.value)}</b></div>)}</div><p className="ending-review-metrics">本局签约 {data.ending?.signed_households ?? "待核实"}/{data.ending?.total_households ?? 36} 户 · 达标要求 {data.ending?.target_signed_households ?? 30}/{data.ending?.total_households ?? 36} 户</p><PagedReading text={[ending.mainText, ending.subText, ...ending.appendices.map(appendix => `${playerText(appendix.title)}\n${playerText(appendix.text)}`)].filter(Boolean).join("\n\n")} storageKey={`serious-game:review-reading:v1:${api.accountId}:${sessionId}:${ending.mainId}:${ending.subId}`} /></section>}<section className="review-summary"><small>当前进程</small><h3>{friendlyStatus(data.status)}</h3><p>这里只记录你已经经历的事件，不会提前透露尚未发生的剧情。</p></section><div className="timeline">{timelines.length ? timelines.map((item, index) => <article key={index}><time>第 {item.story_day || item.day || "待定"} 日</time><div><small>{item.typeLabel}</small><h4>{timelineTitle(item)}</h4>{item.choice && <p>你的选择：{playerText(item.choice)}</p>}{item.summary && item.title && <p>{playerText(item.summary)}</p>}</div></article>) : <Empty text="还没有足够的经历可供复盘。"/>}</div><section className="conversation-review" aria-label="完整会谈记录"><header><div><small>完整记录</small><h3>人物会谈复盘</h3></div><span>{historyLoading ? "正在加载全部分页…" : `${filteredConversations.length} 场`}</span></header><div className="conversation-filters"><label>人物<select value={npcFilter} onChange={event => setNpcFilter(event.target.value)}><option value="">全部人物</option>{[...npcOptions].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><label>日期<input type="number" min="1" max="90" value={dayFilter} onChange={event => setDayFilter(event.target.value)} placeholder="全部" /></label><label>会谈编号<input value={conversationFilter} onChange={event => setConversationFilter(event.target.value)} placeholder="输入编号筛选" /></label></div>{historyError && <div className="notice">{historyError}</div>}{!historyLoading && !historyError && (filteredConversations.length ? <div className="conversation-history-list">{filteredConversations.map(item => <details key={String(item.conversation_id)}><summary><b>第 {item.story_day || "?"} 日 · {npcOptions.get(String(item.npc_id)) || "相关人员"}</b><span>{item.completion_status === "completed" ? "已完成" : "未完成"}</span></summary><div>{arr(item.transcript).map((turn, index) => <article key={index}><strong>{turn.speaker_type === "player" ? "你" : npcOptions.get(String(item.npc_id)) || "对方"}</strong><p>{playerText(turn.text)}</p><ReferenceAttachments references={turn.references} /></article>)}</div></details>)}</div> : <Empty text="当前筛选条件下没有会谈记录。"/>)}</section><section className="conversation-review" aria-label="治理与多人会谈记录"><h3>治理与多人会谈记录</h3>{otherRecords.map((item, index) => <details key={item.action_instance_id || item.meeting_id || item.conversation_id || index}><summary>第 {item.story_day || "?"} 日 · {item.recordTitle}</summary>{arr(item.transcript).map((turn, turnIndex) => <article key={turnIndex}><strong>{turn.speaker_type === "player" ? "你" : playerText(turn.npc_name, resolveCharacter(String(turn.npc_id || ""))?.name || "现场记录")}</strong><p>{playerText(turn.text)}</p><ReferenceAttachments references={turn.references} /></article>)}</details>)}</section></div>;
}


function PanelSection({ title, items, empty, render }: { title: string; items: Dict[]; empty: string; render: (item: Dict, index: number) => React.ReactNode }) {
  if (title === "已取得档案") {
    const groups = archiveInvestigationGroups(items);
    const renderGroup = (groupTitle: string, groupItems: Dict[], groupEmpty: string, unread: boolean) => <section className="panel-section archive-investigation-group"><h3>{groupTitle}</h3>{groupItems.length ? <div>{groupItems.map((item, index) => <article key={item.archive_id || index}><div className="archive-investigation-summary">{render(item, index)}<small>{unread ? `首次消耗 ${displayValue(item.first_read_cost_action_points, 1)} 点精力 · 预计形成 ${displayValue(item.result_fact_count, 0)} 条权威事实` : "已读档案可免费重读"}</small>{values(item.strategic_uses).length > 0 && <p className="archive-strategic-use">可用于：{values(item.strategic_uses).map(value => playerText(value)).join("；")}</p>}{unread && <p className="archive-read-route">请从“行动—查阅档案”选择一份首次查阅。</p>}</div></article>)}</div> : <p className="section-empty">{groupEmpty}</p>}</section>;
    return <>{renderGroup(`新到未读（${groups.unreadCount}）`, groups.unread as Dict[], "当前没有新到未读档案", true)}{renderGroup("已读可重读", groups.read as Dict[], "尚无已读档案", false)}</>;
  }
  return <section className="panel-section"><h3>{title}</h3>{items.length ? <div>{items.map((item, index) => <article key={item.id || item.title || item.document_id || item.meeting_id || index}>{render(item, index)}</article>)}</div> : <p className="section-empty">{empty}</p>}</section>;
}

function ContextForm({ config, state, api, sessionId, notice, onPerform, onArchivesRead, onOpenProfile }: { config: { kind: string; item?: Dict }; state: Dict; api: GameApi; sessionId: string; notice: string; onPerform: (fn: () => Promise<Dict>, text?: string, rebuildNarrative?: boolean, onResult?: (result: Dict) => void) => Promise<boolean>; onArchivesRead: (result: Dict) => void; onOpenProfile: (character: Character) => void }) {
  const item = config.item || {};
  if (config.kind === "resource" && (item.execution_mode === "governance" || ["household_visit", "cadre_interview", "leadership_meeting", "inspect_archives"].includes(item.action_id))) {
    return <GovernanceActionForm item={item} state={state} api={api} sessionId={sessionId} notice={notice} onPerform={onPerform} onArchivesRead={onArchivesRead} onOpenProfile={onOpenProfile} />;
  }
  if (config.kind === "resource" && (item.action_id || item.submit?.action_id)) {
    return <ResourceActionForm item={item} state={state} api={api} sessionId={sessionId} notice={notice} onPerform={onPerform} onOpenProfile={onOpenProfile} />;
  }
  return <div className="empty-state"><span>缓</span><h3>这项安排尚需完善</h3><p>当前页面还没有足够的信息来安全执行它，请从行动或会谈入口尝试。</p></div>;
}

function ResourceActionForm({ item, state, api, sessionId, notice, onPerform, onOpenProfile }: { item: Dict; state: Dict; api: GameApi; sessionId: string; notice: string; onPerform: (fn: () => Promise<Dict>, text?: string, rebuildNarrative?: boolean, onResult?: (result: Dict) => void) => Promise<boolean>; onOpenProfile: (character: Character) => void }) {
  const actionId = String(item.action_id || item.submit?.action_id || "");
  const parameterSchema = item.parameter_schema || {};
  const properties = parameterSchema.properties || {};
  const required = new Set<string>(Array.isArray(parameterSchema.required) ? (parameterSchema.required as unknown[]).map(String) : []);
  const targetSchema = item.target_schema || {};
  const minTargets = Number(targetSchema.min_items || 0);
  const maxTargets = Number(targetSchema.max_items ?? Math.max(minTargets, 8));
  const targetKind = targetSchema.target_kind || (["field_visit"].includes(actionId) ? "location" : ["cross_validate_clues", "zheng_clue_summary"].includes(actionId) ? "fact" : "npc");
  const [catalogs, setCatalogs] = useState<{ npc: Dict[]; household: Dict[]; fact: Dict[]; location: Dict[] }>({ npc: [], household: [], fact: [], location: [] });
  const [loadError, setLoadError] = useState("");
  const [targets, setTargets] = useState<string[]>(() => actionId === "field_visit" && item.location_id ? [String(item.location_id)] : []);
  const [parameters, setParameters] = useState<Dict>(() => Object.fromEntries(Object.entries(properties).map(([key, raw]) => {
    const spec = raw as Dict;
    if (Array.isArray(spec.enum) && spec.enum.length) return [key, String(spec.enum[0])];
    if (spec.type === "integer") return [key, Number(spec.minimum || 0)];
    return [key, ""];
  })));

  useEffect(() => {
    let active = true;
    Promise.all([
      api.panel(sessionId, "governance"), api.panel(sessionId, "desk"), api.panel(sessionId, "knowledge"), api.panel(sessionId, "map"),
    ]).then(([governanceData, deskData, knowledgeData, mapData]) => {
      if (!active) return;
      const npc = arr(get(governanceData, "target_catalogs.meeting_participants")).map(value => ({ id: value.target_id, label: value.label }));
      const household = arr(deskData.household_registry).map(value => ({ id: value.household_id, label: value.signatory_name || "未命名家庭" }));
      const fact = [...arr(knowledgeData.facts), ...arr(knowledgeData.clues), ...arr(knowledgeData.evidence)].map(value => ({ id: value.fact_id || value.id, label: value.title || value.text || value.name || "已掌握材料" })).filter(value => value.id);
      const location = arr(mapData.locations).filter(value => value.visual_state === "available").map(value => ({ id: value.location_id, label: value.name }));
      setCatalogs({ npc, household, fact, location });
    }).catch(error => { if (active) setLoadError(playerErrorMessage(error)); });
    return () => { active = false; };
  }, [api, sessionId]);

  const authoritativeChoices = arr(item.target_choices).map(value => ({ id: value.target_id || value.id, label: value.label || value.name }));
  const choices = authoritativeChoices.length ? authoritativeChoices : catalogs[targetKind as keyof typeof catalogs] || catalogs.npc;
  const parametersValid = [...required].every(key => {
    const value = parameters[key];
    return typeof value === "number" ? Number.isFinite(value) : String(value || "").trim().length > 0;
  });
  const targetsValid = targets.length >= minTargets && targets.length <= maxTargets;
  const toggleTarget = (id: string) => setTargets(current => {
    if (current.includes(id)) return current.filter(value => value !== id);
    if (maxTargets === 1) return [id];
    if (current.length >= maxTargets) return current;
    return [...current, id];
  });

  return <form className="stack-form resource-action-form" onSubmit={async event => {
    event.preventDefault();
    if (!targetsValid || !parametersValid) return;
    await onPerform(async () => {
      const quote = await api.write(sessionId, "/actions/quote", "POST", { state_version: state.state_version, action_id: actionId, target_ids: targets, parameters });
      return api.action(sessionId, {
        input_mode: "resource_action", client_action_id: api.key("resource-action"), state_version: quote.state_version || state.state_version,
        action_id: actionId, target_ids: targets, parameters, quote_id: quote.quote_id,
      });
    }, `${playerText(item.title || item.name, "现场事务")}已经办理`);
  }}>
    <p>{playerText(item.description || item.narrative, "根据当前情况推进这项工作。")}</p>
    <div className="action-cost-summary"><span>预计消耗</span><strong>{actionPointLabel(item)}</strong>{Number(item.direct_budget_cost || 0) > 0 && <em>另需预算 {item.direct_budget_cost} 万元</em>}</div>
    {maxTargets > 0 && (minTargets > 0 || choices.length > 0) && <fieldset className="choice-fieldset"><legend>{targetKind === "household" ? "选择涉及家庭" : targetKind === "location" ? "选择前往地点" : targetKind === "fact" ? "选择用于核验的材料" : "选择涉及人员"}</legend><div className={targetKind === "npc" ? "choice-grid character-choice-grid" : "choice-grid"}>{choices.map((choice, index) => { const id = String(choice.id); const selected = targets.includes(id); const fallbackName = playerText(choice.label, `对象${chineseIndex(index)}`); if (targetKind === "npc") return <CharacterChoiceCard key={id || index} character={resolveCharacter(id, fallbackName)} fallbackName={fallbackName} inputId={`resource-person-${actionId}-${id}`} type={maxTargets === 1 ? "radio" : "checkbox"} name="resource-targets" value={id} checked={selected} onChange={() => toggleTarget(id)} onOpenProfile={onOpenProfile} />; return <label className={selected ? "choice-card selected" : "choice-card"} key={id || index}><input type={maxTargets === 1 ? "radio" : "checkbox"} checked={selected} onChange={() => toggleTarget(id)} /><span>{fallbackName}</span></label>; })}</div><small>需选择 {minTargets}{maxTargets !== minTargets ? ` 至 ${maxTargets}` : ""} 项 · 当前已选 {targets.length} 项</small>{!choices.length && minTargets > 0 && <div className="blocked-reason">目前没有符合条件的可选对象。</div>}</fieldset>}
    {Object.entries(properties).map(([key, raw]) => { const spec = raw as Dict; const label = PARAMETER_LABELS[key] || "具体说明"; const value = parameters[key]; if (Array.isArray(spec.enum)) return <label key={key}>{label}<select value={String(value)} onChange={event => setParameters(current => ({ ...current, [key]: event.target.value }))}>{spec.enum.map((option: unknown) => <option key={String(option)} value={String(option)}>{playerText(option)}</option>)}</select></label>; if (spec.type === "integer") return <label key={key}>{label}<input type="number" min={spec.minimum} max={spec.maximum} value={Number(value)} onChange={event => setParameters(current => ({ ...current, [key]: Number(event.target.value) }))} required={required.has(key)} /></label>; return <label key={key}>{label}<textarea value={String(value)} onChange={event => setParameters(current => ({ ...current, [key]: event.target.value }))} maxLength={500} required={required.has(key)} placeholder={`请填写${label}`} /></label>; })}
    {loadError && <div className="notice">{loadError}</div>}
    {notice && <div className="notice form-notice" role="status">{notice}</div>}
    <button disabled={!targetsValid || !parametersValid || Boolean(loadError)}>确认办理</button>
  </form>;
}

function ReadArchiveHistory({ archives, api, sessionId, onRead }: { archives: Dict[]; api: GameApi; sessionId: string; onRead: (result: Dict) => void }) {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const pending = useRef(false);
  async function reread(archiveId: string) {
    if (pending.current) return;
    pending.current = true;
    setLoading(archiveId); setError("");
    try {
      const result = await api.archiveDetail(sessionId, archiveId) as Dict;
      if (!result.archive) throw new Error("暂时无法读取档案正文，请重试。");
      onRead({ records: [result.archive] });
    } catch (cause) { setError(playerErrorMessage(cause)); }
    finally { pending.current = false; setLoading(null); }
  }
  return <fieldset className="choice-fieldset" data-testid="read-archive-history">
    <legend>已查阅的档案</legend>
    <p className="field-help">已完成查阅的档案保留在这里，免费重读不消耗精力。</p>
    <div className="choice-grid archive-investigation-choices">{archives.map(archive => <div className="choice-card" key={String(archive.archive_id)}><span><b>{playerText(archive.title, "未命名档案")}</b><small>{friendlyStatus(archive.evidence_level)} · 已查阅</small><button type="button" disabled={loading !== null} onClick={() => void reread(String(archive.archive_id))}>{loading === String(archive.archive_id) ? "正在读取…" : "免费重读"}</button></span></div>)}</div>
    {!archives.length && <p className="field-help">暂时没有已查阅的档案，完成首次查阅后会显示在这里。</p>}
    {error && <p className="field-error" role="alert">{error}</p>}
  </fieldset>;
}

function GovernanceActionForm({ item, state, api, sessionId, notice, onPerform, onArchivesRead, onOpenProfile }: { item: Dict; state: Dict; api: GameApi; sessionId: string; notice: string; onPerform: (fn: () => Promise<Dict>, text?: string, rebuildNarrative?: boolean, onResult?: (result: Dict) => void) => Promise<boolean>; onArchivesRead: (result: Dict) => void; onOpenProfile: (character: Character) => void }) {
  const actionId = String(item.action_id || "");
  const variantId = String(item.variant_id || "");
  const locationChoices = arr(item.location_choices);
  const [overview, setOverview] = useState<Dict | null>(null);
  const [loadError, setLoadError] = useState("");
  const locationId = String(item.preselected_location_id || item.location_id || item.resolved_location_id || locationChoices[0]?.location_id || "");
  const [selectedTargets, setSelectedTargets] = useState<string[]>(() => values(item.preselected_npc_ids).map(String));
  const [selectedArchives, setSelectedArchives] = useState<string[]>(() => values(item.preselected_archive_ids).map(String));
  const presentation = actionPresentation(item);
  const [topic, setTopic] = useState(() => String(item.canonical_topic || (presentation.leadership ? MEETING_TOPICS[0] : presentation.prompt)));
  const [meetingTopicMode, setMeetingTopicMode] = useState<"preset" | "custom">("preset");
  const [customMeetingTopic, setCustomMeetingTopic] = useState("");
  const [documentType, setDocumentType] = useState("");
  const [leadNpcId, setLeadNpcId] = useState("");
  const isMeeting = presentation.leadership;
  const isArchive = actionId === "inspect_archives";
  const isCanonicalOpportunity = Boolean(item.opportunity_id);
  const requiresLead = isMeeting && variantId === "convene_leadership_meeting";

  useEffect(() => {
    let active = true;
    api.panel(sessionId, "governance").then(data => { if (active) setOverview(data); }).catch(error => { if (active) setLoadError(playerErrorMessage(error)); });
    return () => { active = false; };
  }, [api, sessionId]);

  const descriptorTargets = arr(item.target_choices);
  const targetChoices = descriptorTargets.length ? descriptorTargets : arr(get(overview, `target_catalogs.${item.target_kind}`, []));
  const descriptorArchiveIds = new Set(descriptorTargets.map(choice => String(choice.target_id || choice.archive_id)));
  const allArchives = arr(overview?.archives);
  const unreadArchives = archiveInvestigationGroups(allArchives).unread as Dict[];
  const meetingArchives = meetingEvidenceArchives(allArchives) as Dict[];
  const archiveChoices = isArchive && descriptorArchiveIds.size
    ? unreadArchives.filter(choice => descriptorArchiveIds.has(String(choice.archive_id)))
    : unreadArchives;
  const evidenceArchiveChoices = isMeeting ? meetingArchives : archiveChoices;
  const documentTypes = arr(overview?.document_types);
  const minTargets = Number(item.participant_rules?.minimum ?? 1);
  const maxTargets = Number(item.participant_rules?.maximum ?? Math.max(1, minTargets));
  const selectedDocumentRule = documentTypes.find(value => value.document_type === documentType) || null;
  const requiredParticipantIds = values(selectedDocumentRule?.required_countersign_ids).map(String);
  const missingRequiredParticipantIds = requiredParticipantIds.filter(id => !selectedTargets.includes(id));
  const requiredParticipantNames = requiredParticipantIds.map(id => playerText(targetChoices.find(choice => String(choice.target_id || choice.id) === id)?.label, id));
  const requiredEvidenceLevel = String(selectedDocumentRule?.required_evidence_level || "E0");
  const highestSelectedEvidenceRank = Math.max(0, ...selectedArchives.map(id => EVIDENCE_RANK[String(evidenceArchiveChoices.find(choice => String(choice.archive_id) === id)?.evidence_level || "E0")] || 0));
  const documentEvidenceValid = !documentType || highestSelectedEvidenceRank >= (EVIDENCE_RANK[requiredEvidenceLevel] || 0);
  const selectedCountValid = isArchive
    ? selectedArchives.length >= minTargets && selectedArchives.length <= maxTargets
    : selectedTargets.length >= minTargets && selectedTargets.length <= maxTargets;
  const validSelection = Boolean(locationId) && selectedCountValid && missingRequiredParticipantIds.length === 0 && documentEvidenceValid && (!requiresLead || selectedTargets.includes(leadNpcId));
  const effectiveTopic = isMeeting && meetingTopicMode === "custom" ? customMeetingTopic.trim() : topic.trim();
  const topicValid = !isMeeting || effectiveTopic.length > 0;

  const toggleTarget = (targetId: string) => setSelectedTargets(current => {
    if (current.includes(targetId)) {
      if (leadNpcId === targetId) setLeadNpcId("");
      return current.filter(value => value !== targetId);
    }
    if (maxTargets === 1) return [targetId];
    if (current.length >= maxTargets) return current;
    return [...current, targetId];
  });
  const toggleArchive = (archiveId: string) => setSelectedArchives(current => current.includes(archiveId) ? current.filter(value => value !== archiveId) : isArchive ? [archiveId] : [...current, archiveId]);
  const chooseDocumentType = (value: string) => {
    setDocumentType(value);
    if (!value) { setSelectedArchives([]); return; }
    const rule = documentTypes.find(item => item.document_type === value);
    const requiredIds = values(rule?.required_countersign_ids).map(String);
    const minimumRank = EVIDENCE_RANK[String(rule?.required_evidence_level || "E0")] || 0;
    const bestArchive = meetingArchives
      .filter(choice => (EVIDENCE_RANK[String(choice.evidence_level || "E0")] || 0) >= minimumRank)
      .sort((left, right) => (EVIDENCE_RANK[String(right.evidence_level || "E0")] || 0) - (EVIDENCE_RANK[String(left.evidence_level || "E0")] || 0))[0];
    setSelectedTargets(current => {
      const required = new Set(requiredIds);
      return [...requiredIds, ...current.filter(id => !required.has(id))].slice(0, maxTargets);
    });
    setSelectedArchives(current => {
      const currentMeetsRequirement = current.some(id => (EVIDENCE_RANK[String(meetingArchives.find(choice => String(choice.archive_id) === id)?.evidence_level || "E0")] || 0) >= minimumRank);
      return currentMeetsRequirement || !bestArchive ? current : [String(bestArchive.archive_id)];
    });
  };

  if (loadError) return <div className="notice">{loadError}</div>;
  if (!overview) return <div className="form-loading">正在整理可选对象…</div>;

  return <form className="stack-form governance-action-form" onSubmit={async event => {
    event.preventDefault(); if (item.available === false || !validSelection || !topicValid) return;
    await onPerform(() => submitGovernanceAction(api, sessionId, {
      state_version: state.state_version,
      descriptor: item,
      location_id: locationId,
      target_ids: isArchive ? [] : selectedTargets,
      topic: isArchive ? "" : effectiveTopic,
      archive_ids: isArchive || (isMeeting && Boolean(documentType)) ? selectedArchives : [],
      proposed_document_type: isMeeting && documentType ? documentType : null,
      lead_npc_id: requiresLead ? leadNpcId : null,
    }) as Promise<Dict>, isArchive ? "档案正文已经调出并记录查阅" : `${governanceDisplayTitle(item, presentation.title)}已经发起`, false, result => {
      if (isArchive) onArchivesRead({ ...result, records: arr(result.archives) });
    });
  }}>
    <p>{item.description}</p>
    <div data-tutorial-id="form-location" data-tutorial-valid={Boolean(locationId)} className="action-location-readonly" data-testid="action-location"><span>办理地点</span><strong>{actionLocationLabel(item, locationId, locationChoices)}</strong><small>{item.map_entry_id ? "地图入口已确定现场" : item.opportunity_id ? "剧情机会已确定现场" : "当前行动配置已确定现场"}{item.scene_id ? ` · ${playerText(item.scene_id)}` : ""}</small></div>
    {isMeeting && <fieldset data-tutorial-id="form-topic" data-tutorial-valid={topicValid} className="choice-fieldset"><legend>本次会议要解决什么</legend><p className="field-help">发言和最终决议都会围绕这个核心问题展开。</p><div className="choice-grid topic-choices">{MEETING_TOPICS.map(value => <label className={meetingTopicMode === "preset" && topic === value ? "choice-card selected" : "choice-card"} key={value}><input type="radio" name="meeting-topic" value={value} checked={meetingTopicMode === "preset" && topic === value} onChange={() => { setMeetingTopicMode("preset"); setTopic(value); }} /><span>{value}</span></label>)}<label className={meetingTopicMode === "custom" ? "choice-card selected" : "choice-card"}><input type="radio" name="meeting-topic" value={CUSTOM_MEETING_TOPIC} checked={meetingTopicMode === "custom"} onChange={() => setMeetingTopicMode("custom")} /><span><b>自定义会议主题</b><small>输入本次会议需要讨论的具体事项</small></span></label></div>{meetingTopicMode === "custom" && <label className="custom-topic-field">会议主题<input value={customMeetingTopic} onChange={event => setCustomMeetingTopic(event.target.value)} maxLength={200} required autoFocus placeholder="例如：讨论柳林村临时安置点启用与责任分工" /><small>{customMeetingTopic.trim().length} / 200</small></label>}</fieldset>}
    {!isMeeting && !isArchive && <label data-tutorial-id="form-topic" data-tutorial-valid={Boolean(topic.trim())}>{presentation.topic}<textarea value={topic} readOnly={isCanonicalOpportunity} onChange={event => setTopic(event.target.value)} maxLength={500} required placeholder={presentation.prompt} /></label>}
    {!isArchive && <fieldset data-tutorial-id="form-targets" data-tutorial-valid={selectedCountValid} className="choice-fieldset"><legend>{presentation.participants}（{participantCountLabel(minTargets, maxTargets)}）</legend><p className="field-help">{presentation.participantHelp}</p><div className="choice-grid character-choice-grid">{targetChoices.map(choice => { const id = String(choice.target_id || choice.id); const selected = selectedTargets.includes(id); const fallbackName = playerText(choice.label || choice.name, "未命名对象"); return <CharacterChoiceCard key={id} character={resolveCharacter(id, fallbackName)} fallbackName={fallbackName} inputId={`governance-person-${actionId}-${id}`} type={maxTargets === 1 ? "radio" : "checkbox"} name="targets" value={id} checked={selected} disabled={isCanonicalOpportunity} onChange={() => toggleTarget(id)} onOpenProfile={onOpenProfile} />; })}</div><small>已选择 {selectedTargets.length} 人{selectedTargets.length < minTargets ? `，还需选择 ${minTargets - selectedTargets.length} 人` : ""}</small></fieldset>}
    {requiresLead && selectedTargets.length > 0 && <fieldset data-tutorial-id="form-lead" data-tutorial-valid={selectedTargets.includes(leadNpcId)} className="choice-fieldset"><legend>指定分管或牵头领导</legend><p className="field-help">该领导首先汇报议题的事实、依据、方案与风险；其他参会领导随后逐一表态。</p><div className="choice-grid character-choice-grid">{selectedTargets.map(id => { const fallbackName = playerText(targetChoices.find(choice => String(choice.target_id || choice.id) === id)?.label, id); return <CharacterChoiceCard key={`lead-${id}`} character={resolveCharacter(id, fallbackName)} fallbackName={fallbackName} inputId={`meeting-lead-${id}`} type="radio" name="meeting-lead" value={id} checked={leadNpcId === id} onChange={() => setLeadNpcId(id)} onOpenProfile={onOpenProfile} />; })}</div>{!leadNpcId && <span className="field-error">必须确定一名主要汇报人。</span>}</fieldset>}
    {isMeeting && documentType && <fieldset data-tutorial-id="form-evidence" data-tutorial-valid={documentEvidenceValid} className="choice-fieldset"><legend>会议依据（至少达到 {requiredEvidenceLevel}）</legend><p className="field-help">拟形成红头文件时，会议只能引用已经查阅且证据等级足够的材料。</p><div className="choice-grid meeting-evidence-choices">{meetingArchives.map(choice => { const id = String(choice.archive_id); const selected = selectedArchives.includes(id); return <label className={selected ? "choice-card selected" : "choice-card"} key={id}><input type="checkbox" value={id} checked={selected} onChange={() => toggleArchive(id)} /><span><b>{choice.title || "未命名材料"}</b><small>{friendlyStatus(choice.evidence_level)} · {choice.evidence_level || "E0"}</small></span></label>; })}</div>{!meetingArchives.length && <div className="blocked-reason">当前还没有已读、可供会议引用的材料。</div>}{!documentEvidenceValid && <span className="field-error">所选材料尚未达到 {requiredEvidenceLevel}，请改选更高等级材料或仅形成会议纪要。</span>}</fieldset>}
    {isArchive && <fieldset data-tutorial-id="form-archives" data-tutorial-valid={selectedCountValid} className="choice-fieldset"><legend>要查阅的档案（每次选择一份）</legend><p className="field-help">首次查阅会立即扣除标示精力，并把权威事实和用途收入线索页；已读档案保留在下方“已查阅的档案”中，可免费重读。</p><div className="choice-grid archive-investigation-choices">{archiveChoices.map(choice => { const id = String(choice.archive_id); const selected = selectedArchives.includes(id); return <label className={selected ? "choice-card selected" : "choice-card"} key={id}><input type="radio" name="archive-investigation" value={id} checked={selected} onChange={() => toggleArchive(id)} /><span><b>{choice.title || "未命名档案"}</b><small>{friendlyStatus(choice.evidence_level)} · {friendlyStatus(choice.confidentiality)} · 首次 {displayValue(choice.first_read_cost_action_points, actionPointCost(item) ?? 1)} 点精力</small><small>预计形成 {displayValue(choice.result_fact_count, 0)} 条事实</small>{values(choice.strategic_uses).length > 0 && <em>可用于：{values(choice.strategic_uses).map(value => playerText(value)).join("；")}</em>}</span></label>; })}</div>{!archiveChoices.length && <div className="empty-state"><p>目前没有新到未读档案，可在下方免费重读已查阅的档案。</p></div>}</fieldset>}
    {isMeeting && documentTypes.length > 0 && <label data-tutorial-id="form-document">拟形成文件（可选）<select value={documentType} onChange={event => chooseDocumentType(event.target.value)}><option value="">仅形成会议纪要</option>{documentTypes.map(value => <option key={value.document_type} value={value.document_type}>{DOCUMENT_TYPE_LABELS[value.document_type] || "专项治理文件"}</option>)}</select>{requiredParticipantNames.length > 0 && <small className="required-participants">该文件要求 {requiredParticipantNames.join("、")} 参会，选择文件时会自动加入。</small>}{missingRequiredParticipantIds.length > 0 && <span className="field-error">仍缺少必要会签人，请重新选择文件以自动补齐。</span>}</label>}
    {notice && <div className="notice form-notice" role="status">{notice}</div>}
    <button data-tutorial-id="form-submit" disabled={item.available === false || !validSelection || !topicValid}>{presentation.leadership ? "发起班子会议" : presentation.start}</button>
    {isArchive && <ReadArchiveHistory archives={meetingArchives} api={api} sessionId={sessionId} onRead={onArchivesRead} />}
  </form>;
}

function NextStepGuidance({ steps, busy, onOpen }: { steps: unknown; busy: boolean; onOpen: (step: NextStep) => void }) {
  const directions = nextSteps(steps);
  if (!directions.length) return null;
  return <section className="next-step-guidance" aria-label="下一步办理指引"><b>下一步办理</b><ul>{directions.map((step, index) => <li key={`${step.action_id}:${step.archive_id}:${index}`}><span>{step.label}</span>{step.unavailable_reason ? <p>{step.unavailable_reason}</p> : step.action_id && <button type="button" disabled={busy} onClick={() => onOpen(step)}>查看办理安排</button>}</li>)}</ul><small>先核对办理对象、材料与费用，确认后才会执行行动。</small></section>;
}

function Empty({ text }: { text: string }) { return <div className="empty-state"><span>待</span><p>{text}</p></div>; }
