import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { ACTION_COPY } from "../app/tutorial/definitions";

const account = "sandbox_web_tutorial_qa";
const session = "tutorial-session";
const shotDir = resolve(process.env.TUTORIAL_QA_DIR || "../../../output/tutorial-reference/qa");
type RecordValue = Record<string, unknown>;
const personChoices = [{ target_id: "npc_sun_qiang", label: "孙强" }, { target_id: "npc_zhao_jianguo", label: "赵建国" }];
const locationChoices = [{ location_id: "county", label: "县政府" }, { location_id: "village", label: "柳林村" }];
const variantIds = Object.keys(ACTION_COPY);
const families = () => ["household_visit", "cadre_interview", "leadership_meeting", "inspect_archives"].map((action_id, familyIndex) => ({
  action_id, name: ["走访", "约谈", "会议", "查档"][familyIndex], variants: variantIds.filter((_, index) => [0, 1, 1, 1, 2, 2, 2, 3, 3][index] === familyIndex).map(variant_id => ({
    variant_id, name: ACTION_COPY[variant_id].title, available: true, description: `${ACTION_COPY[variant_id].title}办理说明`,
    action_point_cost: 2, direct_budget_cost: 3, resource_costs: [{ label: "车辆", amount: 1, unit: "台" }],
    location_choices: locationChoices, target_choices: action_id === "inspect_archives" ? [{ target_id: "archive-unread" }] : personChoices,
    participant_rules: { minimum: action_id === "leadership_meeting" ? 2 : 1, maximum: action_id === "leadership_meeting" ? 8 : 1 },
  })),
}));

async function fixture(page: Page, options: { auto?: boolean; readOnly?: boolean; hidden?: boolean; unavailable?: string; failWrite?: boolean; evidenceDecision?: boolean } = {}) {
  const writes: { path: string; body: RecordValue }[] = [];
  const errors: string[] = [];
  let failWrite = Boolean(options.failWrite);
  const reads: string[] = [];
  const actions = families();
  if (options.hidden) actions[3].variants = actions[3].variants.filter(item => item.variant_id !== "collect_blood_lead_report");
  for (const family of actions) for (const item of family.variants) if (item.variant_id === options.unavailable) Object.assign(item, { available: false, unavailable_reason: "尚缺正式授权材料" });
  const archives = [
    { archive_id: "archive-unread", title: "待查县级档案", evidence_level: "E2", confidentiality: "public", read_status: "unread", first_read_cost_action_points: 2 },
    { archive_id: "archive-read", title: "已核定会议依据", evidence_level: "E3", read_status: "read" },
  ];
  const state = { session_id: session, status: "active", state_version: 1, story: { day: 2 }, ledger: { action_points: { remaining: 3, daily_cap: 3 }, budget: { available: 8000 } } };
  const evidenceOption = { option_id: "a", text: "启动医疗兜底", available: false, unavailable_reason: "需先查阅档案", unlock_requirements: [{ archive_name: "待查县级档案", reason: "需要原始记录确认对象。" }] };
  const decision = { decision_id: "dp4_08", event_instance_id: "same-decision", presentation_entry_id: "decision-entry", title: "医疗处置", text: "请决定救治安排。", options: [evidenceOption], option_ids: [] as string[] };
  if (options.evidenceDecision) Object.assign(state, { pending_decision: decision });
  await page.addInitScript(({ accountId, auto }) => {
    localStorage.setItem("qingjiang-sandbox-account", accountId);
    if (auto === false) localStorage.setItem(`qingjiang:tutorial:v1:${accountId}`, JSON.stringify({ version: 1, auto: false, chapters: {} }));
  }, { accountId: account, auto: options.auto });
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/backend/**", async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    const method = route.request().method();
    let body: RecordValue = {};
    let status = 200;
    if (method !== "GET") writes.push({ path, body: route.request().postDataJSON() || {} });
    if (path === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (path === "/api/ai/config") body = { active: true, mode: "personal", endpoint: "https://fixture.invalid/v1", model: "fixture-model" };
    else if (path === "/api/game/sessions") body = { sessions: [{ session_id: session, story_day: 2, status: "active", review_only: Boolean(options.readOnly) }] };
    else if (path === "/api/game/session" || path === `/api/game/session/${session}`) body = { session_id: session };
    else if (path.endsWith("/view")) {
      if (options.evidenceDecision && archives[0].read_status === "read") { status = 500; body = { message: "状态刷新暂时失败" }; }
      else body = { state, commands: {}, feed: { items: [{ id: "tutorial-line", content_instance_id: "decision-entry", presentation_phase: options.evidenceDecision ? "decision" : "narration", story_day: 2, kind: options.evidenceDecision ? "decision" : "narration", text: "请根据当前情况安排今天的工作。" }], cursor: 1 } };
    }
    else if (path.endsWith("/governance/actions") && method === "POST") {
      if (failWrite) { status = 500; body = { message: "暂时无法办理" }; }
      else {
        if (options.evidenceDecision) { evidenceOption.available = true; evidenceOption.unavailable_reason = ""; decision.option_ids = ["a"]; state.state_version += 1; }
        archives[0].read_status = "read"; actions[3].variants[0].available = false; actions[3].variants[0].target_choices = []; body = { visible_state: state, archives: [{ ...archives[0], player_sections: [{ heading: "档案正文", body: "经核对，县级档案记载了当前公开事实。" }] }], new_facts: [] };
      }
    } else if (path.includes("/governance/archives/")) { reads.push(path); if (failWrite) { status = 500; body = { message: "暂时无法读取档案" }; } else body = { archive: { ...archives.find(a => path.endsWith(a.archive_id)), player_sections: [{ heading: "档案正文", body: "已查阅档案的完整正文。" }] } }; } else if (path.endsWith("/actions")) body = { actions };
    else if (path.endsWith("/governance")) body = { governance_actions: [], meetings: [], archives, document_types: [{ document_type: "implementation_plan", required_evidence_level: "E2", required_countersign_ids: [] }] };
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  return {
    writes, reads, errors, allowWrites: () => { failWrite = false; },
    revealNewAction: () => { actions[3].variants = families()[3].variants; },
  };
}

async function enter(page: Page, kind: "new" | "load" = "new") {
  await page.goto("/");
  // The readiness badge is deliberately hidden in the mobile header.
  await expect(page.getByText("游戏已就绪", { exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  if (kind === "new") await page.getByRole("button", { name: /开始新游戏/ }).click();
  else {
    await page.getByRole("button", { name: /查看已有进度/ }).click();
    await page.locator(".saved-session-list button").click();
  }
  await expect(page.locator('[data-tutorial-id="nav-actions"]')).toBeEnabled();
  await expect(page.locator(".session-actions")).toHaveCount(0);
}

for (const width of [1366, 390]) test(`archive history persists after first read and rereads for free at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 844 });
  const result = await fixture(page, { auto: false });
  await enter(page);
  await page.locator('[data-tutorial-id="nav-actions"]').click();
  const action = page.locator('.canonical-actions [data-variant-id="consult_county_archives"]');
  await action.getByRole('button', { name: '开始查阅', exact: true }).click();
  const history = page.getByTestId('read-archive-history');
  await expect(history).toContainText('已核定会议依据');
  await expect(history).not.toContainText('待查县级档案');
  await page.getByRole('radio', { name: /待查县级档案/ }).check();
  await page.locator('[data-tutorial-id="form-submit"]').click();
  await expect(page.locator('[data-tutorial-id="archive-result"]')).toContainText('经核对');
  await page.locator('.modal-head').getByRole('button', { name: '关闭', exact: true }).last().click();
  await action.getByRole('button', { name: '已查阅的档案', exact: true }).click();
  await expect(history).toContainText('待查县级档案');
  await expect(page.getByRole('radio')).toHaveCount(0);
  await expect(page.locator('[data-tutorial-id="form-submit"]')).toBeDisabled();
  await history.getByRole('button', { name: '免费重读', exact: true }).first().click();
  await expect(page.locator('[data-tutorial-id="archive-result"]')).toContainText('已查阅档案的完整正文');
  await page.locator('.modal-head').getByRole('button', { name: '关闭', exact: true }).last().click();
  await expect(history).toContainText('待查县级档案');
  expect(result.writes.filter(item => item.path.endsWith('/governance/actions'))).toHaveLength(1);
  expect(result.reads).toHaveLength(1);
  expect(result.errors).toEqual([]);
  await mkdir(shotDir, { recursive: true });
  await page.screenshot({ path: `${shotDir}/archive-history-${width}.png` });
});

test('archive result unlocks the pending decision even if the follow-up view fails', async ({ page }) => {
  await fixture(page, { auto: false, evidenceDecision: true });
  await enter(page);
  const choice = page.getByRole('button', { name: /启动医疗兜底/ });
  await expect(choice).toBeDisabled();
  await page.getByRole('button', { name: '前往查档', exact: true }).click();
  await page.locator('.canonical-actions [data-variant-id="consult_county_archives"]').getByRole('button', { name: '开始查阅', exact: true }).click();
  await page.getByRole('radio', { name: /待查县级档案/ }).check();
  await page.locator('[data-tutorial-id="form-submit"]').click();
  await expect(page.locator('[data-tutorial-id="archive-result"]')).toContainText('经核对');
  await page.locator('.modal-head').getByRole('button', { name: '关闭', exact: true }).last().click();
  await expect(choice).toBeEnabled();
  await expect(page.locator('.decision-unlock-guidance')).toHaveCount(0);
});

test('reread failure preserves history and allows retry without writes', async ({ page }) => {
  const result = await fixture(page, { auto: false, failWrite: true });
  await enter(page);
  await page.locator('[data-tutorial-id="nav-actions"]').click();
  await page.locator('.canonical-actions [data-variant-id="consult_county_archives"]').getByRole('button', { name: '已查阅的档案', exact: true }).click();
  const history = page.getByTestId('read-archive-history');
  await history.getByRole('button', { name: '免费重读' }).click();
  await expect(history.getByRole('alert')).toBeVisible();
  await expect(history).toContainText('已核定会议依据');
  result.allowWrites();
  await history.getByRole('button', { name: '免费重读' }).click();
  await expect(page.locator('[data-tutorial-id="archive-result"]')).toContainText('完整正文');
  expect(result.writes.filter(item => item.path !== '/api/game/session')).toEqual([]);
});
