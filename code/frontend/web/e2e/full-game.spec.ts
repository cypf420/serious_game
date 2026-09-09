import { expect, test, type Page, type Request, type TestInfo } from "@playwright/test";
import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  assertStableIdentity,
  buildAcceptanceEvidence,
  collectAuditPages,
  collectEvidenceIdentity,
  currentGitIdentity,
  validateLiveServerAuditEvidence,
  type EvidenceOperation,
} from "./acceptance-evidence.js";

type JsonMap = Record<string, unknown>;
type RouteProfile = {
  route_id: string;
  origin_id: string;
  target_main_ending_ids: string[];
  target_sub_ending_ids: string[];
  decision_policy_template_id?: string;
  decision_policy: Record<string, unknown>;
  daily_action_policy?: Array<{ action_kind: string; target_signed_households?: number }>;
  conversation_strategies?: Record<string, unknown>;
  expected_end_day: number;
};

type RouteCatalog = {
  profiles: RouteProfile[];
  decision_policy_templates: Record<string, Record<string, unknown>>;
  main_ending_policy_overrides: Record<string, Record<string, unknown>>;
  sub_ending_policy_overrides: Record<string, Record<string, unknown>>;
  contract_terms: Record<string, JsonMap>;
};

type Decision = {
  decision_id: string;
  options: Array<{ option_id: string; text: string }>;
};

const contentRoot = path.resolve(process.cwd(), "../../backend/content/packages/pkg_gameplay_v3");
const repositoryRoot = path.resolve(process.cwd(), "../../..");
const routeCatalogPath = path.join(contentRoot, "acceptance_route_profiles.json");
const enabled = process.env.RUN_FULL_REAL_E2E === "1";
const shardIndex = Number(process.env.FULL_E2E_SHARD_INDEX || 0);
const shardTotal = Math.max(1, Number(process.env.FULL_E2E_SHARD_TOTAL || 1));
const browserEvidenceRoot = process.env.FULL_ACCEPTANCE_BROWSER_DIR
  ? path.resolve(process.env.FULL_ACCEPTANCE_BROWSER_DIR)
  : path.resolve(process.cwd(), "../../../output/full-acceptance/playwright");
const visualManifest = path.join(browserEvidenceRoot, "browser-state-manifest.jsonl");
const visualViewports = [
  { name: "desktop-1920", width: 1920, height: 1080 },
  { name: "laptop-1366", width: 1366, height: 768 },
  { name: "mobile-390", width: 390, height: 844 },
];
const contractRepresentativeSchedule: Array<[number, string]> = [
  [53, "npc_zhou_dashan"], [53, "npc_tan_laoliu"], [56, "npc_yuan_guilan"],
  [56, "npc_wu_xiuying"], [57, "npc_he_tiezhu"], [57, "npc_yang_bo"],
  [64, "npc_zhou_kuiyuan"], [68, "npc_zhou_mancang"], [71, "npc_ning_dehai"],
  [73, "npc_ma_changshun"], [77, "npc_lao_juetou"], [78, "npc_miao_xiwang"],
  [84, "npc_deng_shouben"],
];
const demandOpportunityById: Record<string, string> = {
  demand_shi_wenbin: "opp_22_shi_wenbin_contact",
  demand_zhou_mancang: "opp_03_zhou_mancang_contact",
  demand_he_tiezhu: "opp_03_he_tiezhu_contact",
  demand_miao_xiwang: "opp_03_miao_xiwang_contact",
  demand_he_xingbang: "opp_46_he_xingbang_contact",
  demand_gu_keming: "opp_59_gu_keming_contact",
};
const peopleAxisDemandIds: Record<string, string[]> = {
  "归心": Object.keys(demandOpportunityById),
  "认可": ["demand_shi_wenbin", "demand_zhou_mancang", "demand_he_tiezhu", "demand_gu_keming"],
};

const readJson = async <T>(file: string): Promise<T> => JSON.parse(await readFile(file, "utf8")) as T;
const asMap = (value: unknown): JsonMap => value && typeof value === "object" && !Array.isArray(value) ? value as JsonMap : {};

async function recordVisualState(
  page: Page,
  testInfo: TestInfo,
  routeId: string,
  state: string,
  variant = "default",
  metadata: JsonMap = {},
) {
  const original = page.viewportSize();
  for (const viewport of visualViewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const layout = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      portraitTextOverlap: (() => {
        const visibleModal = Array.from(document.querySelectorAll<HTMLElement>(".modal"))
          .reverse()
          .find(element => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
          });
        const activeLayer: ParentNode = visibleModal || document;
        const portrait = activeLayer.querySelector(".gal-portrait")?.getBoundingClientRect();
        const text = activeLayer.querySelector(".gal-dialogue p")?.getBoundingClientRect();
        if (!portrait || !text) return 0;
        return Math.max(0, Math.min(portrait.right, text.right) - Math.max(portrait.left, text.left))
          * Math.max(0, Math.min(portrait.bottom, text.bottom) - Math.max(portrait.top, text.top));
      })(),
    }));
    expect(layout.scrollWidth, `${state} must not overflow at ${viewport.name}`).toBeLessThanOrEqual(layout.clientWidth + 1);
    expect(layout.portraitTextOverlap, `${state} portrait must not cover dialogue at ${viewport.name}`).toBe(0);
    const safeName = `${state}-${variant}-${viewport.name}`.replace(/[^a-zA-Z0-9_-]+/g, "-");
    const screenshot = testInfo.outputPath("visual", `${safeName}.png`);
    await mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    await mkdir(browserEvidenceRoot, { recursive: true });
    await appendFile(visualManifest, `${JSON.stringify({
      route_id: routeId, state, variant, viewport: viewport.name, width: viewport.width,
      height: viewport.height, screenshot, layout, ...metadata,
    })}\n`, "utf8");
  }
  if (original) await page.setViewportSize(original);
}

async function dismissBlockingPlayerNotices(page: Page, testInfo: TestInfo, routeId: string) {
  const broadcast = page.locator('[role="dialog"]:has([data-testid="progress-broadcast"])');
  if (!await broadcast.isVisible().catch(() => false)) return;
  const storyDay = Number((await page.locator(".metric-strip").innerText().catch(() => "")).match(/第\s*(\d+)\s*日/)?.[1] || 0);
  await recordVisualState(page, testInfo, routeId, "progress-broadcast", `day-${storyDay || "unknown"}`, { story_day: storyDay });
  const close = broadcast.getByRole("button").filter({ hasText: /^×$/ }).first();
  await expect(close, "progress broadcast must provide a visible close control").toBeVisible();
  await close.click();
  await expect(broadcast).toBeHidden();
}

function mergedPolicy(profile: RouteProfile, catalog: RouteCatalog) {
  return Object.assign(
    {},
    profile.decision_policy_template_id ? catalog.decision_policy_templates[profile.decision_policy_template_id] : {},
    profile.decision_policy,
    ...profile.target_main_ending_ids.map(id => catalog.main_ending_policy_overrides[id] || {}),
    ...profile.target_sub_ending_ids.map(id => catalog.sub_ending_policy_overrides[id] || {}),
  );
}

async function installEvidenceObservers(page: Page, testInfo: TestInfo) {
  const consoleEvents: JsonMap[] = [];
  const networkEvents: JsonMap[] = [];
  page.on("console", message => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleEvents.push({ type: message.type(), text: message.text(), location: message.location() });
    }
  });
  page.on("pageerror", error => consoleEvents.push({ type: "pageerror", text: error.message }));
  page.on("requestfailed", request => networkEvents.push({
    method: request.method(), url: new URL(request.url()).pathname,
    failure: request.failure()?.errorText || "request failed",
  }));
  page.on("response", response => {
    if (response.status() >= 400) networkEvents.push({
      method: response.request().method(), url: new URL(response.url()).pathname, status: response.status(),
    });
  });
  return async (summary: JsonMap) => {
    const folder = testInfo.outputPath("browser-evidence");
    await mkdir(folder, { recursive: true });
    await writeFile(path.join(folder, "console.json"), JSON.stringify(consoleEvents, null, 2));
    await writeFile(path.join(folder, "network.json"), JSON.stringify(networkEvents, null, 2));
    const consoleErrors = consoleEvents.filter(item => item.type === "error" || item.type === "pageerror");
    const networkErrors = networkEvents.filter(item => item.failure || Number(item.status || 0) >= 500);
    const counts = {
      console_unattributed_errors: consoleErrors.length,
      network_unattributed_errors: networkErrors.length,
    };
    await writeFile(path.join(folder, "browser-summary.json"), JSON.stringify({ ...summary, counts }, null, 2));
    expect(consoleErrors, "unattributed browser errors").toEqual([]);
    expect(networkErrors, "unattributed browser network errors").toEqual([]);
    return counts;
  };
}

async function configureAndStart(page: Page, testInfo: TestInfo, routeId: string, routeIndex: number, originId: string) {
  await page.goto("/");
  await page.getByRole("button", { name: /进入游戏/ }).first().click(); // acceptance:login acceptance:api-configuration
  await expect(page.getByRole("heading", { name: "进入云溪县" })).toBeVisible();

  const sessionResponse = page.waitForResponse(response =>
    response.request().method() === "POST" && /\/api\/game\/session$/.test(new URL(response.url()).pathname),
  );
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  const created = asMap(await (await sessionResponse).json());
  const state = asMap(created.visible_state || created.state || created);
  const sessionId = String(created.session_id || state.session_id || "");
  expect(sessionId).not.toBe("");

  const originButton = page.getByRole("button", { name: new RegExp(originId, "i") });
  if (await originButton.isVisible().catch(() => false)) await originButton.click();
  await recordVisualState(page, testInfo, routeId, "today", "day-1", { story_day: 1 });
  return { sessionId, username: "shared-ephemeral-browser-account" };
}

async function readPlayerState(page: Page, sessionId: string) {
  return page.evaluate(async id => {
    const response = await fetch(`/api/backend/api/game/session/${encodeURIComponent(id)}/view?after=999999999`, { credentials: "include" });
    if (!response.ok) throw new Error(`player-safe state read failed: ${response.status}`);
    return response.json();
  }, sessionId) as Promise<JsonMap>;
}

async function readGovernancePanel(page: Page, sessionId: string) {
  return page.evaluate(async id => {
    const response = await fetch(`/api/backend/api/game/session/${encodeURIComponent(id)}/governance`, { credentials: "include" });
    if (!response.ok) throw new Error(`governance panel read failed: ${response.status}`);
    return response.json();
  }, sessionId) as Promise<JsonMap>;
}

async function readAIConfiguration(page: Page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/backend/api/ai/config", { credentials: "include" });
    if (!response.ok) throw new Error(`AI configuration read failed: ${response.status}`);
    return response.json();
  }) as Promise<JsonMap>;
}

async function readAuditPage(page: Page, sessionId: string, cursor: string) {
  return page.evaluate(async ({ id, after }) => {
    const query = new URLSearchParams({ after, limit: "50" });
    const response = await fetch(`/api/backend/api/game/session/${encodeURIComponent(id)}/ai/audits?${query}`, {
      credentials: "include",
    });
    if (!response.ok) throw new Error(`authenticated session audit read failed: ${response.status}`);
    return response.json();
  }, { id: sessionId, after: cursor });
}

function playerStateVersion(payload: JsonMap) {
  return Number(
    payload.state_version
    || asMap(payload.state).state_version
    || asMap(payload.visible_state).state_version
    || 0,
  );
}

function streamErrorCode(body: string) {
  for (const line of body.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const event = JSON.parse(line) as JsonMap;
      if (event.type === "error") return String(event.code || "STREAM_ERROR");
    } catch { /* partial diagnostic lines are ignored */ }
  }
  return "";
}

async function waitForCommittedState(page: Page, sessionId: string, previousVersion: number) {
  let committedVersion = previousVersion;
  await expect.poll(async () => {
    const payload = await readPlayerState(page, sessionId);
    committedVersion = playerStateVersion(payload);
    return committedVersion;
  }, { message: `state must advance beyond v${previousVersion}`, timeout: 600_000 }).toBeGreaterThan(previousVersion);
  await expect(page.locator(".workspace")).toHaveAttribute(
    "data-state-version",
    String(committedVersion),
    { timeout: 60_000 },
  );
}

async function readPlayerActions(page: Page, sessionId: string) {
  return page.evaluate(async id => {
    const response = await fetch(`/api/backend/api/game/session/${encodeURIComponent(id)}/actions`, { credentials: "include" });
    if (!response.ok) throw new Error(`player action catalog read failed: ${response.status}`);
    return response.json();
  }, sessionId) as Promise<JsonMap>;
}

async function readPlayerEndpoint(page: Page, sessionId: string, suffix: string) {
  return page.evaluate(async ({ id, pathSuffix }) => {
    const response = await fetch(`/api/backend/api/game/session/${encodeURIComponent(id)}/${pathSuffix}`, { credentials: "include" });
    if (!response.ok) throw new Error(`player endpoint ${pathSuffix} failed: ${response.status}`);
    return response.json();
  }, { id: sessionId, pathSuffix: suffix }) as Promise<JsonMap>;
}

function visibleState(payload: JsonMap) {
  return asMap(payload.visible_state || payload.state || payload);
}

async function revealCurrentDecision(page: Page, testInfo: TestInfo, routeId: string) {
  for (let count = 0; count < 160; count += 1) {
    await dismissBlockingPlayerNotices(page, testInfo, routeId);
    if (await page.locator(".decision-stage-inline").isVisible().catch(() => false)) return;
    const next = page.getByRole("button", { name: "下一段", exact: true });
    if (await next.isEnabled().catch(() => false)) {
      try {
        await next.click({ timeout: 2_000 });
      } catch (error) {
        const broadcast = page.locator('[role="dialog"]:has([data-testid="progress-broadcast"])');
        if (!await broadcast.isVisible().catch(() => false)) throw error;
        await dismissBlockingPlayerNotices(page, testInfo, routeId);
      }
    }
    else break;
  }
}

async function finishVisibleNarrative(page: Page, testInfo: TestInfo, routeId: string) {
  for (let count = 0; count < 200; count += 1) {
    await dismissBlockingPlayerNotices(page, testInfo, routeId);
    if (await page.locator(".decision-stage-inline").isVisible().catch(() => false)) return;
    const next = page.getByRole("button", { name: "下一段", exact: true });
    if (!await next.isEnabled().catch(() => false)) return;
    try {
      await next.click({ timeout: 2_000 });
    } catch (error) {
      const broadcast = page.locator('[role="dialog"]:has([data-testid="progress-broadcast"])');
      if (!await broadcast.isVisible().catch(() => false)) throw error;
      await dismissBlockingPlayerNotices(page, testInfo, routeId);
    }
  }
  throw new Error("visible narrative did not reach a stable end within 200 steps");
}

async function resolveDecision(page: Page, testInfo: TestInfo, routeId: string, pending: JsonMap, policy: Record<string, unknown>, decisions: Map<string, Decision>) {
  await revealCurrentDecision(page, testInfo, routeId); // acceptance:narrative
  const waitForCommit = () => page.waitForResponse(response =>
    response.request().method() === "POST"
      && /\/api\/game\/session\/[^/]+\/action$/.test(new URL(response.url()).pathname),
  );
  const decisionId = String(pending.decision_id || "");
  const configured = policy[decisionId];
  const inputKind = String(pending.input_kind || "");
  if (inputKind === "sorting") {
    const committed = waitForCommit();
    await page.getByRole("button", { name: "确认优先顺序" }).click();
    expect((await committed).ok(), `${decisionId} sorting decision must commit`).toBe(true);
    return;
  }
  if (inputKind === "allocation") {
    const submit = page.getByRole("button", { name: "确认分配" });
    await expect(submit).toBeEnabled();
    const committed = waitForCommit();
    await submit.click();
    expect((await committed).ok(), `${decisionId} allocation decision must commit`).toBe(true);
    return;
  }
  const definition = decisions.get(decisionId);
  const desiredId = typeof configured === "string" ? configured : String(asMap(configured).option_id || "");
  const desired = definition?.options.find(option => option.option_id === desiredId)
    || definition?.options.find(option => option.option_id.startsWith(`${desiredId}_`))
    || definition?.options[0];
  expect(desired, `decision ${decisionId} has no selectable catalog option`).toBeTruthy();
  const button = page.locator(".decision-option button").filter({ hasText: desired!.text }).first();
  await expect.poll(() => button.isEnabled().catch(() => false), {
    message: `configured choice ${desired!.option_id} must be player-visible`,
  }).toBe(true);
  await button.evaluate(element => element.scrollIntoView({ block: "center", inline: "nearest" }));
  const clickPoint = await button.evaluate(element => {
    const rect = element.getBoundingClientRect();
    for (const yRatio of [0.5, 0.25, 0.75]) {
      for (const xRatio of [0.5, 0.25, 0.75]) {
        const x = rect.left + rect.width * xRatio;
        const y = rect.top + rect.height * yRatio;
        const hit = document.elementFromPoint(x, y);
        if (hit === element || (hit && element.contains(hit))) return { x, y };
      }
    }
    return null;
  });
  expect(clickPoint, `configured choice ${desired!.option_id} must have a player-clickable point`).toBeTruthy();
  const committed = waitForCommit();
  await page.mouse.click(clickPoint!.x, clickPoint!.y);
  expect((await committed).ok(), `${decisionId}/${desired!.option_id} must commit`).toBe(true);
}

function credibleForcedReplies(group: JsonMap) {
  const agenda = String(group.agenda || "");
  const planId = String(group.followup_plan_id || group.plan_id || group.conversation_id || "");
  if (/d40/i.test(planId) || /宗族|迁坟|安置/.test(agenda)) return [
    "宗族协调由渡口镇干部牵头，周氏和散姓各推一名代表共同见证，不能由任何一支单独定规矩。迁坟按择地、择日、起灵、祭祀延续四项旧例逐户确认并书面登记；安置房、医疗和就学分别按公开政策逐户核权，能办和不能办的都写进三日内可复核的清单。",
    "渡口镇干部牵头，周氏和散姓各推一名代表共同见证；迁坟逐户按择地、择日、起灵、祭祀延续四项礼序书面确认。安置房、医疗和就学按公开政策逐户核权，清单由每户本人签字，争议户另列，不拿多数意见替少数户作主；任何节点没做到就保留原记录并公开责任人。",
    "出现分歧时不由周氏、散姓或镇里任何一方单独裁决：镇干部只负责记录，县搬迁专班按公开政策复核；仍无一致意见的就标成争议户继续协商，绝不替住户签字。",
    "每户确认表一式三份，由住户本人、渡口镇和县搬迁专班各留一份；签字只确认陈述和材料已经记录，不代表住户放弃异议。任何更正都保留原版本、日期和经办人。",
    "迁坟礼序由每户自己确认，周氏代表和散姓代表只能见证、不能替别人决定。安置、医疗和就学严格按现行公开政策核权，政策没有依据的事项我不会写成已经承诺。",
    "我给出的不是一句安抚：谁陈述、谁记录、谁复核、谁留存都已明确；少数户的异议单独保留，三日后逐户核对。若我之后改口，你们可以拿三份同文记录直接要求复核。",
  ];
  if (/d55/i.test(planId) || /环保|治疗|复检|取样/.test(agenda)) return [
    "明早由第三方检测机构和县医院分别进场：水样双份封存、编号盲检，儿童按原始名单逐人复检并建立转诊清单。环保局负责公开采样点和原始数据，卫健部门负责治疗与随访，任何一项未落实都按未完成登记。",
    "家属、村民代表和记者可见证封样，检测结果不先交企业改写。治疗名单按儿童本人逐一核对，漏一人就重新复核并追究经办责任。",
  ];
  if (/d70/i.test(planId) || /公开|监督|舆情|记者/.test(agenda)) return [
    "三日内公开台账版本、检测来源和每次更正记录，原始材料与对外口径并列保留。记者可以依法查阅公开材料并采访相关人员，县里不要求撤稿；发现矛盾就标明责任部门、纠正时间和依据。",
    "公开页面保留历史版本，不用新表覆盖旧表。陈默和村民代表都可以按同一目录复核，任何未回答的问题进入公开待办而不是从简报里删掉。",
  ];
  if (/d84/i.test(planId) || /巡察|整改|逾期|自查|终局/.test(agenda)) return [
    "终局汇报按已完成、逾期、证据不足三类逐项列示，不把承诺写成结果。每个逾期项写明责任人、原始记录和下一节点，巡察组可直接抽查底稿；发现自查落空就当场更正并保留旧版本。",
    "我不要求任何部门为达标补签或改口。签约、环保、医疗和资金问题分别附原始依据，缺什么就如实写缺什么，并允许上级继续追责。",
  ];
  if (/d29/i.test(planId) || /材料|保护|证据|交代/.test(agenda)) return [
    "原始材料今晚由两名经手人共同编号封存，制作只读副本并记录交接时间；明早交县纪委指定人员签收。任何人不得私自删除、改写或带走，赵建国若愿意说明情况，可以在律师和纪检人员在场时逐项核对。",
    "封存、复制、移交三步分别留痕，原件与副本哈希对应。若我或专班临时改口，你们可以直接按交接记录向上级复核。",
  ];
  return [
    "我承认当前记录里的差距，不把未完成说成完成。县里和镇里共同负责，明早先核对原始台账，三日内公开责任人、办理节点和可复核记录。",
    "如果节点未完成，就按原记录标注逾期，不要求任何人改口；原始材料和更正记录一并保留，你们可以继续核验。",
  ];
}

async function finishForcedConversation(page: Page, testInfo: TestInfo, routeId: string, sessionId: string, group: JsonMap) {
  // acceptance:night
  const planId = String(group.followup_plan_id || group.plan_id || group.conversation_id || "unknown");
  await expect(page.locator('[data-primary-scene="forced_group_conversation"]')).toBeVisible({ timeout: 60_000 });
  await recordVisualState(page, testInfo, routeId, "forced-conversation", planId, { plan_id: planId });
  let priorHistory = 0;
  let consecutiveRetryableFailures = 0;
  const credibleReplies = credibleForcedReplies(group);
  const priorPlayerTurns = (Array.isArray(group.transcript) ? group.transcript : [])
    .map(asMap)
    .filter(item => String(item.speaker_type) === "player").length;
  for (let turn = 0; turn < 40; turn += 1) {
    const finish = page.getByRole("button", { name: "结束夜间会谈" });
    if (await finish.isVisible().catch(() => false)) {
      const archived = page.waitForResponse(response =>
        response.request().method() === "POST"
          && /\/group-conversation\/finish$/.test(new URL(response.url()).pathname),
      );
      await finish.click();
      expect((await archived).ok(), `${planId} must archive after NPC resolution`).toBe(true);
      return;
    }
    const history = await page.locator('[aria-label="夜间会谈完整记录"] article').count();
    expect(history).toBeGreaterThanOrEqual(priorHistory);
    priorHistory = history;
    await expect(page.getByTestId("forced-group-conversation")).toBeVisible();
    await expect(page.locator("form.conversation-bar.governance-bar")).toHaveCount(0);
    const input = page.locator("form.conversation-bar textarea");
    await expect(input).toBeVisible();
    const selectedReply = credibleReplies[(priorPlayerTurns + turn) % credibleReplies.length];
    await input.fill(selectedReply);
    await expect(input).toHaveValue(selectedReply);
    const beforePayload = await readPlayerState(page, sessionId);
    const beforeVersion = playerStateVersion(beforePayload);
    let governanceTurnRequests = 0;
    const observeGovernanceTurn = (request: Request) => {
      if (request.method() === "POST" && /\/governance\/(?:actions|meetings)\/.*\/turn\/stream$/.test(new URL(request.url()).pathname)) {
        governanceTurnRequests += 1;
      }
    };
    page.on("request", observeGovernanceTurn);
    const answered = page.waitForResponse(response =>
      response.request().method() === "POST"
        && /\/group-conversation\/turn\/stream$/.test(new URL(response.url()).pathname),
    { timeout: 600_000 });
    await page.getByRole("button", { name: "送出回应" }).click();
    await expect(input).toBeDisabled({ timeout: 15_000 });
    await expect(page.getByRole("status").filter({ hasText: "正在" })).toBeVisible({ timeout: 15_000 });
    const answerResponse = await answered;
    page.off("request", observeGovernanceTurn);
    expect(governanceTurnRequests, "forced group input must not submit a governance stream").toBe(0);
    expect(answerResponse.ok(), `${planId} turn ${turn + 1} must start a real-model stream`).toBe(true);
    expect(await answerResponse.finished(), `${planId} turn ${turn + 1} stream must finish cleanly`).toBeNull();
    const errorCode = streamErrorCode(await answerResponse.text());
    if (errorCode) {
      const unchangedVersion = playerStateVersion(await readPlayerState(page, sessionId));
      expect(unchangedVersion, `${errorCode}: retryable stream failure must not change state`).toBe(beforeVersion);
      await expect(input).toBeEnabled({ timeout: 60_000 });
      consecutiveRetryableFailures += 1;
      if (consecutiveRetryableFailures >= 3) {
        throw new Error(`${planId} exhausted retryable real-model stream attempts: ${errorCode}`);
      }
      turn -= 1;
      continue;
    }
    consecutiveRetryableFailures = 0;
    await waitForCommittedState(page, sessionId, beforeVersion);
    await expect.poll(async () =>
      await finish.isVisible().catch(() => false) || await input.isEnabled().catch(() => false),
    { message: `${planId} turn ${turn + 1} must refresh or resolve`, timeout: 600_000 }).toBe(true);
  }
  throw new Error("forced conversation did not resolve after 40 real-model turns");
}

async function finishOpenInteraction(page: Page, playerText = "请围绕当前事项说明你掌握的事实、主要担忧和可以依法推进的下一步。 ") {
  const input = page.locator("form.conversation-bar textarea");
  if (await input.isVisible().catch(() => false)) {
    await input.fill(playerText);
    const answered = page.waitForResponse(response =>
      response.request().method() === "POST" && /\/stream$/.test(new URL(response.url()).pathname),
    { timeout: 600_000 });
    await page.getByRole("button", { name: "送出回应" }).click();
    await expect(input).toBeDisabled({ timeout: 15_000 });
    const answerResponse = await answered;
    expect(answerResponse.ok(), "real-model interaction stream must start successfully").toBe(true);
    expect(await answerResponse.finished(), "real-model interaction stream must finish cleanly").toBeNull();
    await expect(input).toBeEnabled({ timeout: 600_000 });
  }
  const end = page.getByRole("button", { name: /结束本次行动|正式结束会谈/ }).first();
  if (await end.isVisible().catch(() => false)) {
    const finished = page.waitForResponse(response => {
      if (response.request().method() !== "POST") return false;
      const pathname = new URL(response.url()).pathname;
      return /\/governance\/actions\/[^/]+\/finish$/.test(pathname)
        || /\/api\/game\/session\/[^/]+\/action$/.test(pathname);
    });
    await end.click();
    expect((await finished).ok(), "interaction must finish through its player-visible control").toBe(true);
  }
}

async function completeOneOptionalOpportunity(page: Page, testInfo: TestInfo, routeId: string, sessionId: string, allowedIds: Set<string>) {
  const state = visibleState(await readPlayerState(page, sessionId));
  const remaining = Number(asMap(asMap(state.ledger).action_points).remaining || 0);
  const payload = await readPlayerEndpoint(page, sessionId, "opportunities");
  const opportunity = (Array.isArray(payload.opportunities) ? payload.opportunities : []).map(asMap)
    .find(item => allowedIds.has(String(item.opportunity_id))
      && item.cta_available !== false
      && !item.conversation_active
      && Number(item.cost_action_points || 0) <= remaining);
  if (!opportunity) return false;
  const npcId = String(opportunity.npc_id || opportunity.target_npc_id || "");
  await dismissBlockingPlayerNotices(page, testInfo, routeId);
  await page.getByRole("button", { name: /人物/ }).first().click();
  const person = page.locator(`[data-character-id="${npcId}"]`);
  const entry = person.getByRole("button", { name: "进入会谈", exact: true });
  if (!await entry.isEnabled().catch(() => false)) return false;
  await entry.click();
  const actionForm = page.locator("form.governance-action-form");
  await expect(actionForm).toBeVisible();
  const started = page.waitForResponse(response => response.request().method() === "POST"
    && /\/api\/game\/session\/[^/]+\/governance\/actions$/.test(new URL(response.url()).pathname));
  await actionForm.locator('[data-tutorial-id="form-submit"]').click();
  expect((await started).ok(), `${String(opportunity.opportunity_id)} must start through its visible entry`).toBe(true);
  const prompt = String(opportunity.opportunity_id) === "opp_03_zhou_kuiyuan_contact"
    ? "请把迁坟的四件事说清楚：择地、择日、起灵和祭祀延续，我会按村里旧例逐项核对。"
    : String(opportunity.conversation_goal || "请说明你的核心诉求、事实依据和依法可行的处理方式。");
  await finishOpenInteraction(page, prompt);
  return true;
}

async function satisfyMandatoryOpportunity(page: Page) {
  const activeConversation = page.locator("form.conversation-bar textarea");
  if (await activeConversation.isVisible().catch(() => false)) {
    await finishOpenInteraction(page);
    return;
  }
  const actionDialog = page.getByRole("dialog").filter({ hasText: /现场走访|入户走访/ });
  if (!await actionDialog.isVisible().catch(() => false)) {
    await page.getByRole("button", { name: /人物/ }).first().click(); // acceptance:people
    const start = page.getByRole("button", { name: "进入会谈" }).first();
    await expect(start, "mandatory opportunity must expose a player-visible entry").toBeEnabled();
    await start.click();
  }
  await expect(actionDialog).toBeVisible();
  const started = page.waitForResponse(response =>
    response.request().method() === "POST"
      && /\/api\/game\/session\/[^/]+\/governance\/actions$/.test(new URL(response.url()).pathname),
  );
  await actionDialog.locator('[data-tutorial-id="form-submit"]').click();
  expect((await started).ok(), "mandatory opportunity must start through its canonical action").toBe(true);
  await expect(page.locator("form.conversation-bar textarea")).toBeVisible({ timeout: 60_000 });
  await finishOpenInteraction(page);
}

async function inspectAllAvailableArchives(page: Page, testInfo: TestInfo, routeId: string, maxReads: number | null = null) {
  // Mirror the lawful witness driver through the player-visible archive form:
  // one unread file per transaction until the day has no affordable unread file.
  for (let count = 0; count < 20; count += 1) {
    await dismissBlockingPlayerNotices(page, testInfo, routeId);
    const catalogLoaded = page.waitForResponse(response =>
      response.request().method() === "GET"
        && /\/api\/game\/session\/[^/]+\/actions$/.test(new URL(response.url()).pathname),
    );
    await page.getByRole("button", { name: /行动/ }).first().click(); // acceptance:archives
    expect((await catalogLoaded).ok(), "player action catalog must load before archive availability is evaluated").toBe(true);
    await expect(page.locator('.canonical-actions article[data-action-id="inspect_archives"]')).toBeVisible();
    const archiveAction = page.locator(".canonical-actions article").filter({ hasText: "查阅档案" }).first();
    const open = archiveAction.getByRole("button", { name: "填写方案", exact: true }).first();
    if (await open.count() === 0) return;
    if (!await open.isEnabled().catch(() => false)) return;
    await open.click();

    const form = page.locator("form.governance-action-form").filter({ hasText: "要查阅的档案" });
    await expect(form).toBeVisible();
    const choices = form.locator('input[name="archive-investigation"]');
    if (await choices.count() === 0) {
      await page.getByRole("button", { name: "关闭" }).last().click().catch(async () => {
        await page.keyboard.press("Escape");
      });
      return;
    }
    const factProducingChoices = form.locator("label.choice-card").filter({ hasText: /预计形成\s*[1-9]\d*\s*条事实/ });
    if (await factProducingChoices.count() === 0) {
      await page.getByRole("button", { name: "关闭", exact: true }).last().click();
      await expect(form).toBeHidden();
      return;
    }
    await factProducingChoices.first().locator('input[name="archive-investigation"]').check();
    const committed = page.waitForResponse(response =>
      response.request().method() === "POST"
        && /\/api\/game\/session\/[^/]+\/governance\/actions$/.test(new URL(response.url()).pathname),
    );
    await form.getByRole("button", { name: "开始查阅", exact: true }).click();
    const response = await committed;
    if (!response.ok()) {
      if (response.status() === 409) {
        const archiveDialog = page.getByRole("dialog").filter({ hasText: "查阅县级档案" });
        const closeArchive = archiveDialog.getByRole("button", { name: "关闭", exact: true });
        await expect(closeArchive).toBeVisible();
        await closeArchive.click();
        await expect(archiveDialog).toBeHidden();
        return;
      }
      expect(response.ok(), "archive investigation must commit through the player-visible form").toBe(true);
    }
    const reading = page.getByRole("dialog").filter({ hasText: "档案查阅结果" });
    await expect(reading).toBeVisible();
    if (count === 0) await recordVisualState(page, testInfo, routeId, "archive-result", "first-read");
    await reading.getByRole("button").filter({ hasText: /^×$/ }).click();
    await expect(reading).toBeHidden();
    if (maxReads !== null && count + 1 >= maxReads) return;
  }
  throw new Error("archive investigation did not drain within 20 player-visible reads");
}

async function fillContractTerms(form: ReturnType<Page["locator"]>, terms: JsonMap, storyDay: number) {
  const scalar = (name: string, value: unknown) => form.locator(`[name="${name}"]`).fill(String(value));
  await form.locator('[name="policy_document_id"]').selectOption(String(terms.policy_document_id || "doc_compensation_policy_v1"));
  await form.locator('[name="budget_envelope"]').selectOption(String(terms.budget_envelope || "property_land"));
  await scalar("cash_amount", Number(terms.cash_amount || 0));
  await scalar("transition_months", Number(terms.transition_months || 0));
  await scalar("move_out_day", Math.max(storyDay, Number(terms.move_out_day || storyDay)));
  await scalar("housing_delivery_day", Math.max(storyDay, Number(terms.housing_delivery_day || storyDay)));
  await form.locator('[name="housing_resource_id"]').selectOption(String(terms.housing_resource_id || ""));
  for (const [resourceId, amount] of Object.entries(asMap(terms.service_allocations))) {
    const input = form.locator(`[name="service:${resourceId}"]`);
    if (await input.count()) await input.fill(String(amount));
  }
  for (const approvalId of (Array.isArray(terms.approval_document_ids) ? terms.approval_document_ids : [])) {
    const input = form.locator(`[name="approval_document_ids"][value="${String(approvalId)}"]`);
    if (await input.count()) await input.check();
  }
  const checks: Array<[string, boolean]> = [
    ["public_window_reward", storyDay <= 75 && Boolean(terms.public_window_reward)],
  ];
  for (const [name, checked] of checks) {
    const input = form.locator(`[name="${name}"]`);
    if (await input.count() && await input.isEnabled().catch(() => false)) await input.setChecked(checked);
  }
}

async function signContractsTowardTarget(
  page: Page,
  testInfo: TestInfo,
  routeId: string,
  sessionId: string,
  storyDay: number,
  targetSigned: number,
  contractTerms: Record<string, JsonMap>,
  processedRepresentatives: Set<string>,
) {
  let currentState = visibleState(await readPlayerState(page, sessionId));
  let signed = Number(asMap(asMap(currentState.ledger).signed_households).signed || 0);
  if (signed >= targetSigned || Number(asMap(asMap(currentState.ledger).action_points).remaining || 0) < 2) return;
  for (const [availableDay, representative] of contractRepresentativeSchedule) {
    if (signed >= targetSigned) return;
    if (availableDay > storyDay || processedRepresentatives.has(representative)) continue;
    currentState = visibleState(await readPlayerState(page, sessionId));
    if (Number(asMap(asMap(currentState.ledger).action_points).remaining || 0) < 2) return;
    const catalog = await readPlayerActions(page, sessionId);
    const householdAction = (Array.isArray(catalog.actions) ? catalog.actions : []).map(asMap)
      .find(item => String(item.action_id) === "household_visit");
    const variant = (Array.isArray(householdAction?.variants) ? householdAction.variants : []).map(asMap)
      .find(item => item.available !== false && (Array.isArray(item.target_choices) ? item.target_choices : [])
        .map(asMap).some(choice => String(choice.target_id) === representative));
    if (!variant) continue;

    await dismissBlockingPlayerNotices(page, testInfo, routeId);
    await page.getByRole("button", { name: /行动/ }).first().click();
    const variantCard = page.locator(`[data-action-id="household_visit"] [data-variant-id="${String(variant.variant_id)}"]`);
    await variantCard.getByRole("button", { name: "填写方案", exact: true }).click();
    const actionForm = page.locator("form.governance-action-form");
    await expect(actionForm).toBeVisible();
    await actionForm.locator(`[data-target-id="${representative}"] input`).check();
    await actionForm.locator("textarea").fill("逐户合同与正式签约");
    const started = page.waitForResponse(response => response.request().method() === "POST"
      && /\/governance\/actions$/.test(new URL(response.url()).pathname));
    await actionForm.locator('[data-tutorial-id="form-submit"]').click();
    expect((await started).ok(), `contract visit for ${representative} must start`).toBe(true);
    const talk = page.locator("form.conversation-bar textarea");
    await expect(talk).toBeVisible();
    await talk.fill("我正式向你代表的每一户分别发起合同，请逐户核对条款并签约。");
    const answered = page.waitForResponse(response => response.request().method() === "POST"
      && /\/governance\/actions\/[^/]+\/turn\/stream$/.test(new URL(response.url()).pathname), { timeout: 600_000 });
    await page.getByRole("button", { name: "送出回应", exact: true }).click();
    expect((await answered).ok(), `contract intent for ${representative} must reach the real model`).toBe(true);
    const contractEntry = page.getByRole("button", { name: "签订合同", exact: true });
    await expect(contractEntry).toBeVisible({ timeout: 600_000 });
    await contractEntry.click();
    const proposal = page.getByRole("dialog").filter({ hasText: "确认逐户合同提议" });
    await expect(proposal).toBeVisible();
    const confirmed = page.waitForResponse(response => response.request().method() === "POST"
      && /\/governance\/contract-batches\/[^/]+\/confirm$/.test(new URL(response.url()).pathname));
    await proposal.getByRole("button", { name: /建立 \d+ 份逐户合同/ }).click();
    expect((await confirmed).ok(), `contract batch for ${representative} must be established`).toBe(true);

    let contractDialog = page.getByRole("dialog").filter({ hasText: "逐户合同 ·" });
    await expect(contractDialog).toBeVisible();
    if (signed === 0) await recordVisualState(page, testInfo, routeId, "contract-3-stages", "first-contract", { stage_count: 3 });
    while (signed < targetSigned) {
      const householdText = await contractDialog.locator(".contract-status small").innerText();
      const householdId = householdText.split("·")[0].trim();
      const terms = contractTerms[householdId];
      expect(terms, `published lawful terms must exist for ${householdId}`).toBeTruthy();
      const termsForm = contractDialog.locator("form.contract-terms-form");
      if (!await termsForm.isVisible().catch(() => false)) break;
      await fillContractTerms(termsForm, terms!, storyDay);
      const drafted = page.waitForResponse(response => response.request().method() === "PUT"
        && /\/governance\/contracts\/[^/]+\/terms$/.test(new URL(response.url()).pathname));
      await termsForm.getByRole("button", { name: "保存方案并预览合同", exact: true }).click();
      expect((await drafted).ok(), `${householdId} lawful terms must pass`).toBe(true);
      const review = contractDialog.getByRole("button", { name: "提交签约", exact: true });
      await expect(review).toBeEnabled({ timeout: 600_000 });
      const reviewed = page.waitForResponse(response => response.request().method() === "POST"
        && /\/governance\/contracts\/[^/]+\/review$/.test(new URL(response.url()).pathname), { timeout: 600_000 });
      await review.click();
      expect((await reviewed).ok(), `${householdId} must complete real-model household review`).toBe(true);
      await expect(contractDialog.getByText("已签署", { exact: true }).first()).toBeVisible({ timeout: 600_000 });
      signed += 1;
      if (signed >= targetSigned) break;
      const currentHouseholdId = householdId;
      const next = contractDialog.locator('[aria-label="同批次逐户合同"] button:not(.active)').filter({ hasNotText: "已签署" }).first();
      if (!await next.isVisible().catch(() => false)) break;
      const nextHouseholdId = String(await next.locator("small").evaluate(element => element.parentElement?.firstChild?.textContent || "")).trim();
      const detail = page.waitForResponse(response => response.request().method() === "GET"
        && /\/governance\/contracts\/[^/]+$/.test(new URL(response.url()).pathname), { timeout: 600_000 });
      await next.click();
      expect((await detail).ok(), `${nextHouseholdId || "next household"} contract detail must load`).toBe(true);
      contractDialog = page.getByRole("dialog").filter({ hasText: "逐户合同 ·" });
      await expect(contractDialog.locator(".contract-status small")).not.toContainText(currentHouseholdId, { timeout: 600_000 });
      await expect(contractDialog.locator("form.contract-terms-form")).toBeVisible({ timeout: 600_000 });
    }
    const closeContract = contractDialog.getByRole("button", { name: "关闭", exact: true });
    await expect(closeContract).toBeVisible({ timeout: 600_000 });
    await expect(async () => {
      await closeContract.click();
      await expect(contractDialog).toBeHidden({ timeout: 5_000 });
    }).toPass({ timeout: 600_000 });
    const finish = page.getByRole("button", { name: "结束本次行动", exact: true });
    const finished = page.waitForResponse(response => response.request().method() === "POST"
      && /\/governance\/actions\/[^/]+\/finish$/.test(new URL(response.url()).pathname));
    await finish.click();
    expect((await finished).ok(), `contract visit for ${representative} must finish`).toBe(true);
    processedRepresentatives.add(representative);
  }
}

async function endCurrentDay(page: Page, testInfo: TestInfo, routeId: string, sessionId: string, day: number) {
  await finishVisibleNarrative(page, testInfo, routeId);
  const end = page.getByRole("button", { name: "结束今日", exact: true }).last();
  await expect(end).toBeEnabled();
  await end.click();
  const confirmation = page.getByRole("dialog").filter({ hasText: "结束今日工作" });
  await expect(confirmation).toBeVisible();
  const settled = page.waitForResponse(response =>
    response.request().method() === "POST"
      && /\/api\/game\/session\/[^/]+\/end-day$/.test(new URL(response.url()).pathname),
  );
  await confirmation.getByRole("button", { name: "进入夜间结算", exact: true }).click();
  expect((await settled).ok(), `day ${day} night settlement must commit`).toBe(true);
  await expect.poll(async () => {
    const next = visibleState(await readPlayerState(page, sessionId));
    return String(next.status) === "ended"
      || Number(asMap(next.story).day || next.story_day || 0) > day
      || Boolean(next.active_group_conversation);
  }, { message: `day ${day} must advance or enter its forced conversation`, timeout: 60_000 }).toBe(true);
  const morning = page.getByText(/晨间|次晨|简报/).first();
  if (await morning.isVisible().catch(() => false)) {
    await recordVisualState(page, testInfo, routeId, "morning-briefing", `after-day-${day}`, { story_day: day + 1 });
  }
}

async function exercisePlayerPanels(page: Page, testInfo: TestInfo, routeId: string) {
  await page.getByRole("button", { name: /人物/ }).first().click(); // acceptance:people
  await expect(page.locator(".people-relationship-view")).toBeVisible();
  await recordVisualState(page, testInfo, routeId, "people");
  await page.getByRole("button", { name: /治理/ }).first().click(); // acceptance:governance acceptance:contract acceptance:meeting
  await expect(page.locator(".governance-panel")).toBeVisible();
  await recordVisualState(page, testInfo, routeId, "governance");
  const contractStages = await page.locator(".contract-progress span").count();
  if (contractStages === 3) await recordVisualState(page, testInfo, routeId, "contract-3-stages", "overview", { stage_count: 3 });
  await page.getByRole("button", { name: /线索/ }).first().click(); // acceptance:clues
  await expect(page.locator(".knowledge-panel")).toBeVisible();
  await recordVisualState(page, testInfo, routeId, "clues");
  await page.getByRole("button", { name: /地图/ }).first().click(); // acceptance:map
  await expect(page.locator(".map-panel")).toBeVisible();
  const mapLocations = page.locator(".location-list article");
  await expect(mapLocations, "the complete map catalog must finish loading").toHaveCount(8, { timeout: 60_000 });
  await recordVisualState(page, testInfo, routeId, "map-current", "day-1", {
    location_count: await mapLocations.count(),
  });
  await page.getByRole("button", { name: /关键节点/ }).first().click(); // acceptance:save-load
  await expect(page.getByText("五个关键节点")).toBeVisible();
  await recordVisualState(page, testInfo, routeId, "save-load");
  await page.getByRole("button", { name: /行动/ }).first().click(); // acceptance:archives
}

async function captureCompletedPanels(page: Page, testInfo: TestInfo, routeId: string) {
  await page.getByRole("button", { name: /地图/ }).first().click();
  await expect(page.locator(".map-panel")).toBeVisible();
  const mapLocations = page.locator(".location-list article");
  await expect(mapLocations, "completed route must finish loading all eight map locations").toHaveCount(8, { timeout: 60_000 });
  const locationCount = await mapLocations.count();
  expect(locationCount, "completed route must expose all eight map locations").toBe(8);
  await recordVisualState(page, testInfo, routeId, "map-8-locations", "all", { location_count: locationCount });
  await page.getByRole("button", { name: /复盘/ }).first().click();
  await expect(page.locator(".review-panel")).toBeVisible();
  await recordVisualState(page, testInfo, routeId, "review");
}

async function exerciseLeadershipMeeting(
  page: Page,
  testInfo: TestInfo,
  routeId: string,
  sessionId: string,
) {
  await page.getByRole("button", { name: /行动/ }).first().click();
  const variant = page.locator('[data-action-id="leadership_meeting"] [data-variant-id="convene_leadership_meeting"]');
  await expect(variant.getByRole("button", { name: "填写方案", exact: true })).toBeEnabled();
  await variant.getByRole("button", { name: "填写方案", exact: true }).click();
  const form = page.locator("form.governance-action-form");
  await expect(form).toBeVisible();
  const participants = form.locator("fieldset").filter({ hasText: "参会领导" }).locator('input[type="checkbox"]');
  expect(await participants.count()).toBeGreaterThanOrEqual(2);
  await participants.nth(0).check();
  await participants.nth(1).check();
  const documentType = form.getByLabel("拟形成文件（可选）");
  await expect(documentType, "leadership meeting must expose a formal document choice").toBeVisible();
  const formalDocumentType = await documentType.locator("option").nth(1).getAttribute("value");
  expect(formalDocumentType, "at least one formal document type must be available").toBeTruthy();
  await documentType.selectOption(String(formalDocumentType));
  const evidenceFieldset = form.locator("fieldset").filter({ hasText: "会议依据" });
  await expect(evidenceFieldset).toBeVisible();
  const evidenceChoice = evidenceFieldset.locator('input[type="checkbox"]').first();
  await expect(evidenceChoice, "formal document workflow must expose a lawfully read archive").toBeEnabled();
  await evidenceChoice.check();
  const lead = form.locator("fieldset").filter({ hasText: "指定分管或牵头领导" }).locator('input[type="radio"]').first();
  if (await lead.count()) await lead.check();
  const started = page.waitForResponse(response => response.request().method() === "POST"
    && /\/governance\/actions$/.test(new URL(response.url()).pathname));
  await form.getByRole("button", { name: "发起班子会议", exact: true }).click();
  const startResponse = await started;
  expect(startResponse.ok(), "leadership meeting must start through its visible form").toBe(true);
  const startPayload = asMap(await startResponse.json());
  const meeting = asMap(startPayload.meeting);
  const meetingId = String(meeting.meeting_id || "");
  expect(meetingId, "leadership meeting response must identify the persisted meeting").not.toBe("");
  const input = page.locator("form.conversation-bar textarea");
  await expect(input).toBeVisible();
  await input.fill("请各位围绕当前搬迁工作的事实依据、程序风险和下一步责任分工作出明确意见。");
  const answered = page.waitForResponse(response => response.request().method() === "POST"
    && /\/governance\/meetings\/[^/]+\/turn\/stream$/.test(new URL(response.url()).pathname), { timeout: 600_000 });
  await page.getByRole("button", { name: "送出回应", exact: true }).click();
  await expect(input).toBeDisabled({ timeout: 15_000 });
  const answerResponse = await answered;
  expect(answerResponse.ok(), "leadership members must answer through the real model").toBe(true);
  expect(await answerResponse.finished(), "leadership response stream must finish cleanly").toBeNull();
  await expect(input).toBeEnabled({ timeout: 600_000 });
  await recordVisualState(page, testInfo, routeId, "leadership-meeting", "active-discussion");
  await page.getByRole("button", { name: "形成会议决议", exact: true }).click();
  const resolution = page.getByRole("dialog").filter({ hasText: "确认会议决议" });
  await expect(resolution).toBeVisible();
  const resolved = page.waitForResponse(response => response.request().method() === "POST"
    && /\/governance\/meetings\/[^/]+\/resolve$/.test(new URL(response.url()).pathname));
  await resolution.getByRole("button", { name: "末位表态并形成决定", exact: true }).click();
  const resolveResponse = await resolved;
  expect(resolveResponse.ok(), "leadership meeting resolution must commit").toBe(true);
  const resolveRequest = asMap(resolveResponse.request().postDataJSON());
  const resolvedPayload = asMap(await resolveResponse.json());
  const resolvedMeeting = asMap(resolvedPayload.meeting);
  let document = asMap(resolvedPayload.document);
  const documentId = String(document.document_id || "");
  expect(documentId, "resolving a formal meeting must generate a document").not.toBe("");
  expect(String(document.source_meeting_id), "generated document must retain its source meeting").toBe(meetingId);
  const requestedResolution = asMap(resolveRequest.resolution);
  const persistedResolution = asMap(document.resolution_snapshot);
  expect(persistedResolution, "generated document must retain the adopted resolution fields").toMatchObject({
    decision: requestedResolution.decision,
    target_scope: requestedResolution.target_scope,
    resource_mode: requestedResolution.resource_mode,
    resource_authorization_limits: requestedResolution.resources,
    responsible_ids: requestedResolution.responsible_ids,
    deadline_day: requestedResolution.deadline_day,
    public_scope: requestedResolution.public_scope,
    document_title: requestedResolution.document_title,
  });
  expect(String(document.review_status), "generated document must pass the independent review before countersign").toBe("pass");
  await expect(resolution).toBeHidden({ timeout: 600_000 });

  const operations: EvidenceOperation[] = [
    {
      step: "resolve", operation_id: `${meetingId}:resolve`, api_path: new URL(resolveResponse.url()).pathname,
      state_version_before: Number(resolveRequest.state_version), state_version_after: Number(resolvedPayload.state_version),
      status: String(resolvedMeeting.status || "resolved"),
    },
    {
      step: "observe_review", operation_id: `${documentId}:review-observed-in-resolve-response`, api_path: new URL(resolveResponse.url()).pathname,
      state_version_before: Number(resolvedPayload.state_version), state_version_after: Number(resolvedPayload.state_version),
      status: String(document.review_status),
    },
  ];

  await page.getByRole("button", { name: /治理/ }).first().click();
  await expect(page.locator(".governance-panel")).toBeVisible();
  const documentRow = page.locator(".governance-record-row").filter({ hasText: String(document.title) }).first();
  await expect(documentRow, "generated document must be visible in the governance panel").toBeVisible();
  await documentRow.getByRole("button", { name: "查看文件", exact: true }).click();
  const detail = page.getByRole("dialog").filter({ hasText: "决议文件详情" });
  await expect(detail).toBeVisible();
  await expect(detail.getByText(String(asMap(document.resolution_snapshot).decision), { exact: false }),
    "document detail must display the adopted meeting decision").toBeVisible();
  await expect(detail.locator(".document-review")).toContainText(/通过/);

  while (await detail.getByRole("button", { name: "请其会签" }).count()) {
    const signerButton = detail.getByRole("button", { name: "请其会签" }).first();
    await expect(signerButton).toBeEnabled({ timeout: 600_000 });
    let accepted = false;
    for (let attempt = 0; attempt < 3 && !accepted; attempt += 1) {
      const beforePayload = await readPlayerState(page, sessionId);
      const beforeVersion = playerStateVersion(beforePayload);
      const signed = page.waitForRequest(request => request.method() === "POST"
        && new URL(request.url()).pathname.endsWith(`/governance/documents/${documentId}/countersign`), { timeout: 60_000 });
      // The successful request refreshes the detail and can detach the pressed
      // button before Playwright observes mouseup. The response is authoritative;
      // keep the click promise handled without mistaking that refresh for failure.
      const clickAttempt = signerButton.click().catch(() => undefined);
      const signedRequestObject = await signed;
      await Promise.race([clickAttempt, page.waitForTimeout(1_000)]);
      const signedRequest = asMap(signedRequestObject.postDataJSON());
      await expect.poll(async () => playerStateVersion(await readPlayerState(page, sessionId)), {
        message: "countersign request must produce one authoritative state transition", timeout: 60_000,
      }).toBeGreaterThan(beforeVersion);
      const governanceAfterSign = await readGovernancePanel(page, sessionId);
      document = asMap((governanceAfterSign.documents as JsonMap[]).find(item => String(item.document_id) === documentId));
      const signedBy = (document.countersigned_by as string[]) || [];
      accepted = signedBy.includes(String(signedRequest.npc_id));
      operations.push({
        step: "countersign", operation_id: `${documentId}:countersign:${String(signedRequest.npc_id)}:attempt-${attempt + 1}`,
        api_path: new URL(signedRequestObject.url()).pathname,
        state_version_before: Number(signedRequest.state_version), state_version_after: playerStateVersion(await readPlayerState(page, sessionId)),
        status: accepted ? "accepted" : "rejected",
      });
      if (accepted) {
        expect(String(document.status), "accepted countersign must advance the document workflow").toMatch(/pending_countersign|approved/);
      }
    }
    expect(accepted, "required countersigner must accept within three explicit player attempts").toBe(true);
  }
  expect(operations.some(item => item.step === "countersign"), "formal document must record at least one accepted countersign").toBe(true);
  await expect(detail.getByRole("button", { name: "正式印发", exact: true })).toBeVisible();
  const beforeIssuePayload = await readPlayerState(page, sessionId);
  const beforeIssueVersion = playerStateVersion(beforeIssuePayload);
  const issued = page.waitForRequest(request => request.method() === "POST"
    && new URL(request.url()).pathname.endsWith(`/governance/documents/${documentId}/issue`));
  const issueClick = detail.getByRole("button", { name: "正式印发", exact: true }).click().catch(() => undefined);
  const issueRequestObject = await issued;
  await Promise.race([issueClick, page.waitForTimeout(1_000)]);
  const issueRequest = asMap(issueRequestObject.postDataJSON());
  expect(Number(issueRequest.state_version), "issue must use the currently displayed state version").toBe(beforeIssueVersion);
  await expect.poll(async () => {
    const panel = await readGovernancePanel(page, sessionId);
    return String(asMap((panel.documents as JsonMap[]).find(item => String(item.document_id) === documentId)).status);
  }, { message: "issued document must persist in the governance DTO", timeout: 60_000 }).toBe("issued");
  const issuedGovernance = await readGovernancePanel(page, sessionId);
  document = asMap((issuedGovernance.documents as JsonMap[]).find(item => String(item.document_id) === documentId));
  expect(String(document.status)).toBe("issued");
  operations.push({
    step: "issue", operation_id: `${documentId}:issue`, api_path: new URL(issueRequestObject.url()).pathname,
    state_version_before: beforeIssueVersion, state_version_after: playerStateVersion(await readPlayerState(page, sessionId)),
    status: String(document.status),
  });

  const governance = await readGovernancePanel(page, sessionId);
  const persistedDocument = (governance.documents as JsonMap[]).find(item => String(item.document_id) === documentId);
  expect(persistedDocument, "issued document must survive an official governance panel readback").toBeTruthy();
  expect(String(persistedDocument?.source_meeting_id)).toBe(meetingId);
  expect(asMap(persistedDocument?.resolution_snapshot)).toEqual(asMap(document.resolution_snapshot));
  expect(String(persistedDocument?.status)).toBe("issued");
  expect([...((persistedDocument?.countersigned_by as string[]) || [])].sort(),
    "every required signer must be present in the persisted issued document").toEqual(
    [...((persistedDocument?.required_countersign_ids as string[]) || [])].sort(),
  );
  await recordVisualState(page, testInfo, routeId, "leadership-document", "issued", {
    meeting_id: meetingId, document_id: documentId, source_meeting_id: persistedDocument?.source_meeting_id,
  });
  return { meetingId, document: persistedDocument!, operations };
}

async function exerciseMapAction(
  page: Page,
  testInfo: TestInfo,
  routeId: string,
) {
  await page.getByRole("button", { name: /地图/ }).first().click();
  const availableLocation = page.locator(".location-list article").filter({ hasText: "可以前往" }).first();
  const details = availableLocation.locator("details.location-actions");
  await expect(details).toBeVisible();
  if (!await details.getAttribute("open")) await details.locator("summary").click();
  const entries = details.locator("section:not(.unavailable)");
  expect(await entries.count(), "an unlocked map location must expose a lawful action").toBeGreaterThan(0);
  const entry = entries.first();
  const open = entry.getByRole("button", { name: /填写方案|进入会谈/ });
  await expect(open).toBeEnabled();
  await open.click();
  const form = page.locator("form.governance-action-form");
  await expect(form).toBeVisible();
  const location = form.getByLabel("办理地点");
  if (await location.count()) await expect(location).toBeDisabled();
  const targets = form.locator('input[name="targets"]');
  if (await targets.count()) await targets.first().check();
  const started = page.waitForResponse(response => response.request().method() === "POST"
    && /\/governance\/actions$/.test(new URL(response.url()).pathname));
  await form.locator('[data-tutorial-id="form-submit"]').click();
  expect((await started).ok(), "map action must start through its locked player-visible entry").toBe(true);
  await recordVisualState(page, testInfo, routeId, "map-action", "location-locked");
  await finishOpenInteraction(page, "请只围绕这个地点当前已经公开的事实、程序风险和下一步安排作答。");
}

async function exerciseManualSaveLoad(
  page: Page,
  testInfo: TestInfo,
  routeId: string,
  sessionId: string,
  mutate: () => Promise<void>,
) {
  const baseline = visibleState(await readPlayerState(page, sessionId));
  await page.getByRole("button", { name: /关键节点/ }).first().click();
  const savePanel = page.locator(".save-panel");
  await expect(savePanel).toBeVisible();
  await savePanel.getByLabel("节点名称").fill("全量验收关键节点");
  const saved = page.waitForResponse(response => response.request().method() === "POST"
    && /\/manual-saves$/.test(new URL(response.url()).pathname));
  await savePanel.getByRole("button", { name: "保存关键节点", exact: true }).click();
  expect((await saved).ok(), "manual save must commit through the player-visible panel").toBe(true);
  await expect(savePanel.getByText("全量验收关键节点", { exact: true })).toBeVisible();
  await recordVisualState(page, testInfo, routeId, "save-load", "saved");

  await mutate();
  const changed = visibleState(await readPlayerState(page, sessionId));
  expect(Number(changed.state_version)).toBeGreaterThan(Number(baseline.state_version));

  await page.getByRole("button", { name: /关键节点/ }).first().click();
  const load = page.locator(".save-row").filter({ hasText: "全量验收关键节点" }).getByRole("button", { name: "载入", exact: true });
  await load.click();
  const confirmation = page.getByRole("dialog").filter({ hasText: "载入关键节点" });
  await expect(confirmation).toBeVisible();
  const loaded = page.waitForResponse(response => response.request().method() === "POST"
    && /\/load-snapshot$/.test(new URL(response.url()).pathname));
  await confirmation.getByRole("button", { name: "确认载入", exact: true }).click();
  expect((await loaded).ok(), "manual load must restore through its confirmation flow").toBe(true);
  await expect(confirmation).toBeHidden({ timeout: 60_000 });
  const restored = visibleState(await readPlayerState(page, sessionId));
  expect(Number(asMap(restored.story).day)).toBe(Number(asMap(baseline.story).day));
  expect(Number(asMap(asMap(restored.ledger).action_points).remaining)).toBe(
    Number(asMap(asMap(baseline.ledger).action_points).remaining),
  );
  expect(restored.active_governance_action || restored.active_conversation).toBeFalsy();
  await recordVisualState(page, testInfo, routeId, "save-load", "restored");
}

async function playRoute(page: Page, testInfo: TestInfo, sessionId: string, profile: RouteProfile, policy: Record<string, unknown>, decisions: Map<string, Decision>, contractTerms: Record<string, JsonMap>, stopAfterForcedGroup = false) {
  const visited = new Set<number>();
  const processedRepresentatives = new Set<string>();
  const targetSigned = Number(profile.daily_action_policy?.find(item => item.action_kind === "sign_households_through_contracts")?.target_signed_households || 0);
  const peopleAxis = String(profile.conversation_strategies?.people_axis || "route_default");
  const selectedDemandIds = new Set(peopleAxisDemandIds[peopleAxis] || []);
  const optionalOpportunityIds = new Set([
    "opp_d53_tan_laoliu_paid_recovery",
    "opp_d55_yuan_guilan_paid_recovery",
    ...[...selectedDemandIds].map(id => demandOpportunityById[id]),
  ].filter(Boolean));
  if (String(asMap(policy.dp5_03).option_id || policy.dp5_03 || "") === "a") optionalOpportunityIds.add("opp_03_zhou_kuiyuan_contact");
  let guard = 0;
  while (guard < 900) {
    guard += 1;
    await dismissBlockingPlayerNotices(page, testInfo, profile.route_id);
    const payload = await readPlayerState(page, sessionId);
    const state = visibleState(payload);
    await page.waitForTimeout(60);
    await dismissBlockingPlayerNotices(page, testInfo, profile.route_id);
    const story = asMap(state.story);
    const day = Number(story.day || state.story_day || 0);
    if (day) visited.add(day);
    if (String(state.status) === "ended" || state.ending_result) break;
    if (state.active_group_conversation) {
      const group = asMap(state.active_group_conversation);
      await finishForcedConversation(page, testInfo, profile.route_id, sessionId, group);
      if (stopAfterForcedGroup) return state;
      continue;
    }
    if (state.active_conversation || state.active_governance_action) {
      await finishOpenInteraction(page);
      continue;
    }
    const pending = asMap(state.pending_decision);
    if (pending.decision_id) {
      await resolveDecision(page, testInfo, profile.route_id, pending, policy, decisions);
      continue;
    }
    const commands = asMap(payload.commands || state.commands);
    if (commands.mandatory_opportunity_id || commands.can_end_day === false) {
      await satisfyMandatoryOpportunity(page);
      continue;
    }
    if (commands.can_end_day !== false) {
      // A resolved decision can leave a short authoritative follow-up passage unread.
      // Player actions remain intentionally locked until that passage is consumed, so
      // finish it before looking for archives that may be required on the following day.
      await finishVisibleNarrative(page, testInfo, profile.route_id);
      await inspectAllAvailableArchives(page, testInfo, profile.route_id);
      if (await completeOneOptionalOpportunity(page, testInfo, profile.route_id, sessionId, optionalOpportunityIds)) continue;
      if (targetSigned > 0) await signContractsTowardTarget(page, testInfo, profile.route_id, sessionId, day, targetSigned, contractTerms, processedRepresentatives);
      await endCurrentDay(page, testInfo, profile.route_id, sessionId, day);
      continue;
    }
    throw new Error(`route ${profile.route_id} has no legal player-visible progression at day ${day}`);
  }
  expect(guard, "route loop must terminate").toBeLessThan(900);
  const finalPayload = await readPlayerState(page, sessionId);
  const finalState = visibleState(finalPayload);
  expect(Number(asMap(finalState.story).day || finalState.story_day)).toBe(profile.expected_end_day);
  expect([...visited]).toEqual(Array.from({ length: 90 }, (_, index) => index + 1));
  return finalState;
}

const catalog = await readJson<RouteCatalog>(routeCatalogPath);
const decisionDocument = await readJson<{ decisions: Decision[] }>(path.join(contentRoot, "decisions.json"));
const decisions = new Map(decisionDocument.decisions.map(item => [item.decision_id, item]));
const selectedProfiles = catalog.profiles.filter((_, index) => index % shardTotal === shardIndex);

test.describe("full real browser routes", () => {
  test.skip(!enabled, "set RUN_FULL_REAL_E2E=1 only from the final real acceptance entrypoint");
  for (const [index, profile] of selectedProfiles.entries()) {
    test(`${profile.route_id} reaches its witnessed ending through player controls`, async ({ page }, testInfo) => {
      const finishEvidence = await installEvidenceObservers(page, testInfo);
      const { sessionId, username } = await configureAndStart(page, testInfo, profile.route_id, index, profile.origin_id);
      if (index === 0) await exercisePlayerPanels(page, testInfo, profile.route_id);
      const finalState = await playRoute(page, testInfo, sessionId, profile, mergedPolicy(profile, catalog), decisions, catalog.contract_terms);
      if (index === 0) await captureCompletedPanels(page, testInfo, profile.route_id);
      else await page.getByRole("button", { name: /复盘/ }).first().click(); // acceptance:review acceptance:ending
      const ending = page.getByLabel("最终结局");
      await expect(ending).toBeVisible();
      await recordVisualState(page, testInfo, profile.route_id, "main-ending", profile.target_main_ending_ids[0], {
        main_ending_ids: profile.target_main_ending_ids,
        sub_ending_ids: profile.target_sub_ending_ids,
      });
      for (const endingId of profile.target_main_ending_ids) expect(JSON.stringify(finalState)).toContain(endingId);
      for (const endingId of profile.target_sub_ending_ids) expect(JSON.stringify(finalState)).toContain(endingId);
      await finishEvidence({ route_id: profile.route_id, session_id: sessionId, username, story_day: 90, status: "passed" });
    });
  }
  if (process.env.RUN_P0_REAL_D2 === "1" && shardIndex === 0) test("P0 real API D2 checkpoint completes a forced group conversation", async ({ page }, testInfo) => {
    const finishEvidence = await installEvidenceObservers(page, testInfo);
    const profile = catalog.profiles.find(item => item.route_id === "route-ending-01d");
    expect(profile, "route-ending-01d must remain available for the P0 checkpoint").toBeTruthy();
    const { sessionId, username } = await configureAndStart(page, testInfo, "p0-real-d2-checkpoint", catalog.profiles.length + 2, profile!.origin_id);
    const checkpointState = await playRoute(page, testInfo, sessionId, profile!, mergedPolicy(profile!, catalog), decisions, catalog.contract_terms, true);
    expect(checkpointState.active_group_conversation, "checkpoint must stop only after a forced group conversation").toBeTruthy();
    await finishEvidence({ route_id: "p0-real-d2-checkpoint", session_id: sessionId, username, status: "passed", checkpoint: "forced-group-completed" });
  });
  if (shardIndex === 0) test("player-visible meeting resolves, reviews, countersigns, and issues its linked document", async ({ page }, testInfo) => {
    const startIdentity = await collectEvidenceIdentity(
      repositoryRoot, contentRoot, currentGitIdentity, [browserEvidenceRoot],
    );
    const finishEvidence = await installEvidenceObservers(page, testInfo);
    const profile = catalog.profiles[0];
    const { sessionId, username } = await configureAndStart(page, testInfo, "feature-leadership-meeting", catalog.profiles.length + 1, profile.origin_id);
    const initial = visibleState(await readPlayerState(page, sessionId));
    const pending = asMap(initial.pending_decision);
    if (pending.decision_id) await resolveDecision(page, testInfo, "feature-leadership-meeting", pending, mergedPolicy(profile, catalog), decisions);
    await finishVisibleNarrative(page, testInfo, "feature-leadership-meeting");
    await exerciseManualSaveLoad(
      page,
      testInfo,
      "feature-leadership-meeting",
      sessionId,
      () => exerciseMapAction(page, testInfo, "feature-leadership-meeting"),
    );
    await inspectAllAvailableArchives(page, testInfo, "feature-leadership-meeting", 1);
    const aiConfiguration = await readAIConfiguration(page);
    for (const field of ["endpoint", "model", "config_version"] as const) {
      expect(String(aiConfiguration[field] || ""), `active AI configuration must expose ${field}`).not.toBe("");
    }
    const baselinePages = await collectAuditPages(
      cursor => readAuditPage(page, sessionId, cursor), "",
    );
    const initialAuditCursor = baselinePages.at(-1)?.next_cursor || "";
    const auditWindowStartedAt = new Date().toISOString();
    const meetingEvidence = await exerciseLeadershipMeeting(
      page, testInfo, "feature-leadership-meeting", sessionId,
    );
    const liveAuditPages = await collectAuditPages(
      cursor => readAuditPage(page, sessionId, cursor), initialAuditCursor,
    );
    const auditWindowEndedAt = new Date().toISOString();
    const endingAIConfiguration = await readAIConfiguration(page);
    expect(endingAIConfiguration.config_version, "AI configuration must remain frozen during the meeting workflow").toBe(
      aiConfiguration.config_version,
    );
    const serverAudit = validateLiveServerAuditEvidence(liveAuditPages, {
      session_id: sessionId,
      meeting_id: meetingEvidence.meetingId,
      document_id: String(meetingEvidence.document.document_id),
      started_at: auditWindowStartedAt,
      ended_at: auditWindowEndedAt,
      endpoint_host: String(aiConfiguration.endpoint),
      config_version: String(aiConfiguration.config_version),
      model: String(aiConfiguration.model),
      initial_cursor: initialAuditCursor,
    });
    const endIdentity = await collectEvidenceIdentity(
      repositoryRoot, contentRoot, currentGitIdentity, [browserEvidenceRoot],
    );
    assertStableIdentity(startIdentity, endIdentity);
    const observerCounts = await finishEvidence({
      route_id: "feature-leadership-meeting", session_id: sessionId, username, status: "passed",
      ...serverAudit.counts,
      server_audit_source: serverAudit.source,
    });
    const machineEvidence = buildAcceptanceEvidence({
      identity: startIdentity,
      route_id: "feature-leadership-meeting",
      session_id: sessionId,
      meeting_id: meetingEvidence.meetingId,
      document_id: String(meetingEvidence.document.document_id),
      source_meeting_id: String(meetingEvidence.document.source_meeting_id),
      resolution_snapshot: asMap(meetingEvidence.document.resolution_snapshot),
      document_status: String(meetingEvidence.document.status),
      client_steps: meetingEvidence.operations,
      server_audit: serverAudit,
      ...observerCounts,
    });
    const evidenceFolder = testInfo.outputPath("browser-evidence");
    await writeFile(path.join(evidenceFolder, "meeting-document-operation-records.json"), JSON.stringify(machineEvidence, null, 2));
  });
});
