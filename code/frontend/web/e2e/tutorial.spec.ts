import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { governanceActionButtonLabel } from "../app/lib/player-ui";
import { ACTION_COPY, BASIC_TUTORIAL } from "../app/tutorial/definitions";

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

async function fixture(page: Page, options: { auto?: boolean; readOnly?: boolean; hidden?: boolean; unavailable?: string; failWrite?: boolean } = {}) {
  const writes: { path: string; body: RecordValue }[] = [];
  const errors: string[] = [];
  let failWrite = Boolean(options.failWrite);
  const actions = families();
  if (options.hidden) actions[3].variants = actions[3].variants.filter(item => item.variant_id !== "collect_blood_lead_report");
  for (const family of actions) for (const item of family.variants) if (item.variant_id === options.unavailable) Object.assign(item, { available: false, unavailable_reason: "尚缺正式授权材料" });
  const archives = [
    { archive_id: "archive-unread", title: "待查县级档案", evidence_level: "E2", confidentiality: "public", read_status: "unread", first_read_cost_action_points: 2 },
    { archive_id: "archive-read", title: "已核定会议依据", evidence_level: "E3", read_status: "read" },
  ];
  const state = { session_id: session, status: "active", state_version: 1, story: { day: 2 }, ledger: { action_points: { remaining: 3, daily_cap: 3 }, budget: { available: 8000 } } };
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
    else if (path.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "tutorial-line", story_day: 2, text: "请根据当前情况安排今天的工作。" }], cursor: 1 } };
    else if (path.endsWith("/governance/actions") && method === "POST") {
      if (failWrite) { status = 500; body = { message: "暂时无法办理" }; }
      else body = { archives: [{ ...archives[0], body: "经核对，县级档案记载了当前公开事实。" }], new_facts: [] };
    } else if (path.endsWith("/actions")) body = { actions };
    else if (path.endsWith("/governance")) body = { governance_actions: [], meetings: [], archives, document_types: [{ document_type: "implementation_plan", required_evidence_level: "E2", required_countersign_ids: [] }] };
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  return {
    writes, errors, allowWrites: () => { failWrite = false; },
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
const card = (page: Page) => page.locator(".tutorial-popover");
const target = (page: Page, id: string) => page.locator(`[data-tutorial-id="${id}"]`);
async function next(page: Page) {
  const count = card(page).locator(".tutorial-step-count");
  const previous = await count.innerText();
  await card(page).getByRole("button", { name: "下一步", exact: true }).click();
  await expect(count).not.toHaveText(previous);
}
async function expectCardInViewport(page: Page) {
  await expect(async () => {
    const bounds = await card(page).boundingBox();
    const viewport = page.viewportSize()!;
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width + 1);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height + 1);
  }).toPass();
}
async function actionsPage(page: Page) {
  await target(page, "nav-actions").click();
  await expect(page.locator(".canonical-actions [data-variant-id]")).toHaveCount(9);
}
async function guideForm(page: Page, variant: string) {
  await page.locator(`.canonical-actions [data-variant-id="${variant}"]`).getByRole("button", { name: governanceActionButtonLabel({ action_id: families().find(family => family.variants.some(item => item.variant_id === variant))?.action_id, variant_id: variant }) }).click();
  await expect(target(page, "form-submit")).toBeVisible();
  await page.getByRole("button", { name: "填写指南", exact: true }).click();
  await page.getByRole("button", { name: "重新查看本次填写指南" }).click();
  await expect(card(page).getByRole("heading", { name: "核对办理地点" })).toBeVisible();
}
function gameplayWrites(result: Awaited<ReturnType<typeof fixture>>) { return result.writes.filter(item => item.path !== "/api/game/session"); }

test("new game invites eight-step basic tour, skip/replay/next do not write game state", async ({ page }) => {
  const result = await fixture(page);
  await enter(page);
  await expect(page.getByRole("complementary", { name: "游戏导航" }).locator("small")).toHaveCount(0);
  await page.getByRole("button", { name: "开始赴任指南" }).click();
  for (let index = 0; index < BASIC_TUTORIAL.steps.length; index++) {
    await expect(card(page).getByRole("heading", { name: BASIC_TUTORIAL.steps[index].title, exact: true })).toBeVisible();
    await expect(card(page).locator(".tutorial-step-count")).toHaveText(`第 ${index + 1} / 8 步`);
    if (BASIC_TUTORIAL.steps[index].id === "advance-signing") {
      await expect(target(page, "advance-signing")).toHaveText("推进签约");
      await expect(card(page)).toContainText("准备逐户合同");
      await mkdir(shotDir, { recursive: true });
      await page.screenshot({ path: `${shotDir}/advance-signing-guide.png` });
    }
    if (index < BASIC_TUTORIAL.steps.length - 1) await next(page);
  }
  await card(page).getByRole("button", { name: "完成本节" }).click();
  await expect(card(page)).toHaveCount(0);
  await page.getByRole("button", { name: "赴任指南", exact: true }).click();
  await page.getByRole("button", { name: "重新查看基础导览" }).click();
  await card(page).getByRole("button", { name: "跳过本节" }).click();
  expect(result.writes).toHaveLength(1);
  expect(gameplayWrites(result)).toEqual([]);
  expect(result.errors).toEqual([]);
});

test("paused basic chapter resumes its saved step after reload without inviting again", async ({ page }) => {
  const result = await fixture(page);
  await enter(page);
  await page.getByRole("button", { name: "开始赴任指南" }).click();
  await next(page); await next(page); await next(page);
  await expect(card(page).getByRole("heading", { name: "阅读与推进" })).toBeVisible();
  await card(page).getByRole("button", { name: "暂停，稍后继续" }).click();
  await enter(page, "load");
  await expect(page.getByRole("button", { name: "开始赴任指南" })).toHaveCount(0);
  await page.getByRole("button", { name: "赴任指南", exact: true }).click();
  await page.getByRole("button", { name: "继续上次学习" }).click();
  await expect(card(page).getByRole("heading", { name: "阅读与推进" })).toBeVisible();
  await expect(card(page).locator(".tutorial-step-count")).toHaveText("第 4 / 8 步");
  expect(gameplayWrites(result)).toEqual([]);
  expect(result.errors).toEqual([]);
});

test("first actual form automatically guides once; reopening allows manual replay", async ({ page }) => {
  const result = await fixture(page);
  await enter(page);
  await page.getByRole("complementary", { name: "赴任指南邀请" }).getByRole("button", { name: "稍后再看" }).click();
  await actionsPage(page);
  const open = () => page.locator('.canonical-actions [data-variant-id="field_visit"]').getByRole("button", { name: "开始走访" }).click();
  await open();
  await expect(card(page).getByRole("heading", { name: "核对办理地点" })).toBeVisible();
  await card(page).getByRole("button", { name: "跳过本节" }).click();
  await page.locator(".modal-head").getByRole("button", { name: "关闭", exact: true }).click();
  await open();
  await expect(target(page, "form-submit")).toBeVisible();
  await page.getByRole("button", { name: "填写指南", exact: true }).click();
  await expect(card(page)).toHaveCount(0);
  await page.getByRole("button", { name: "重新查看本次填写指南" }).click();
  await expect(card(page).getByRole("heading", { name: "核对办理地点" })).toBeVisible();
  expect(gameplayWrites(result)).toEqual([]);
  expect(result.errors).toEqual([]);
});

for (const readOnly of [false, true]) test(`loaded ${readOnly ? "read-only" : "playable"} save does not invite basic tour`, async ({ page }) => {
  const result = await fixture(page, { readOnly });
  await enter(page, "load");
  if (readOnly) await expect(page.locator(".review-panel")).toBeVisible();
  else await expect(page.getByText("请根据当前情况安排今天的工作。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始赴任指南" })).toHaveCount(0);
  await page.getByRole("button", { name: "赴任指南", exact: true }).click();
  if (readOnly) {
    await expect(page.getByText("当前为只读复盘。可执行教程在可游玩的存档中提供。")).toBeVisible();
    await expect(page.getByRole("button", { name: "重新查看基础导览" })).toHaveCount(0);
  } else await expect(page.getByRole("button", { name: "重新查看基础导览" })).toBeEnabled();
  expect(result.writes).toEqual([]);
  expect(result.errors).toEqual([]);
});

test("all nine actual action cards have individual help and current cost details", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const result = await fixture(page, { auto: false });
  await enter(page); await actionsPage(page);
  await expect(page.locator(".canonical-actions").getByRole("button", { name: "填写方案", exact: true })).toHaveCount(0);
  for (const id of variantIds) {
    await page.locator(`.canonical-actions [data-variant-id="${id}"]`).getByRole("button", { name: "了解此行动" }).click();
    await expect(card(page).getByRole("heading", { name: ACTION_COPY[id].title, exact: true })).toBeVisible();
    await card(page).getByText("展开说明", { exact: true }).click();
    await expect(card(page)).toContainText("预算 3 万元");
    await expect(card(page)).toContainText("车辆 1台");
    await expect(card(page)).toContainText("办理结果：");
    await expectCardInViewport(page);
    await mkdir(shotDir, { recursive: true });
    await page.screenshot({ path: `${shotDir}/action-${id}-1920.png` });
    await card(page).getByRole("button", { name: "完成本节" }).click();
  }
  await expect(page.locator(".tutorial-action-intro")).toHaveCount(0);
  await target(page, "nav-scene").click();
  await page.getByRole("button", { name: "赴任指南", exact: true }).click();
  await page.getByRole("dialog", { name: "赴任指南目录" }).getByRole("button", { name: /^现场走访/ }).click();
  await expect(card(page).getByRole("heading", { name: "现场走访", exact: true })).toBeVisible();
  await card(page).getByRole("button", { name: "完成本节" }).click();
  expect(gameplayWrites(result)).toEqual([]);
  expect(result.errors).toEqual([]);
});

test("unavailable action help gives blocking reason; unreturned action never enters directory", async ({ page }) => {
  const result = await fixture(page, { auto: false, hidden: true, unavailable: "contact_media" });
  await enter(page); await target(page, "nav-actions").click();
  const unavailable = page.locator('.canonical-actions [data-variant-id="contact_media"]');
  await unavailable.getByRole("button", { name: "了解此行动" }).click();
  await card(page).getByText("展开说明", { exact: true }).click();
  await expect(card(page)).toContainText("当前不可用：尚缺正式授权材料");
  await card(page).getByRole("button", { name: "完成本节" }).click();
  await expect(unavailable.getByRole("button", { name: "条件不足" })).toBeDisabled();
  await page.getByRole("button", { name: "赴任指南", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "赴任指南目录" })).not.toContainText("调取血铅材料");
  expect(gameplayWrites(result)).toEqual([]);
});

test("action intro card stays removed while individual guides remain available", async ({ page }) => {
  const result = await fixture(page, { hidden: true });
  await enter(page);
  await page.getByRole("complementary", { name: "赴任指南邀请" }).getByRole("button", { name: "稍后再看" }).click();
  await target(page, "nav-actions").click();
  await expect(page.locator(".canonical-actions [data-variant-id]")).toHaveCount(8);
  await expect(page.locator(".tutorial-action-intro")).toHaveCount(0);
  result.revealNewAction();
  await target(page, "nav-scene").click(); await target(page, "nav-actions").click();
  await expect(page.locator(".canonical-actions [data-variant-id]")).toHaveCount(9);
  await expect(page.locator(".tutorial-action-intro")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "了解此行动", exact: true })).toHaveCount(9);
  expect(gameplayWrites(result)).toEqual([]);
  expect(result.errors).toEqual([]);
});

test("actual form validation blocks next and Enter; finish focuses submit; failed write retains form", async ({ page }) => {
  const result = await fixture(page, { auto: false, failWrite: true });
  await enter(page); await actionsPage(page); await guideForm(page, "field_visit");
  await expect(target(page, "form-location").locator("select")).toHaveCount(0);
  await expect(target(page, "form-location")).toContainText("县政府");
  await next(page);
  await expect(card(page).getByRole("heading", { name: "写明本次重点", exact: true })).toBeVisible();
  await target(page, "form-topic").locator("textarea").fill("");
  await expect(target(page, "form-topic").locator("textarea")).toHaveValue("");
  await expect(target(page, "form-topic")).toHaveAttribute("data-tutorial-valid", "false");
  await expect(card(page).getByRole("button", { name: "下一步", exact: true })).toBeDisabled();
  await target(page, "form-topic").locator("textarea").fill("核实搬迁安排");
  await target(page, "form-topic").locator("textarea").press("Enter");
  await next(page);
  await expect(card(page).getByRole("button", { name: "下一步", exact: true })).toBeDisabled();
  await target(page, "form-targets").locator('input[name="targets"]').first().check();
  await target(page, "form-targets").getByRole("button", { name: "查看孙强人物介绍" }).click();
  const profile = page.locator(".modal-backdrop").filter({ has: page.getByRole("heading", { name: "人物介绍", exact: true }) });
  await expect(profile).toBeVisible();
  await expect(card(page)).toHaveCount(0);
  await profile.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(card(page).getByRole("heading", { name: "选择当前可参与对象" })).toBeVisible();
  await expect(target(page, "form-targets").locator('input[name="targets"]').first()).toBeChecked();
  await next(page);
  await expect(card(page).getByRole("heading", { name: "确认前再核对一次" })).toBeVisible();
  expect(gameplayWrites(result)).toEqual([]);
  await card(page).getByRole("button", { name: "讲解完成，自主操作" }).click();
  await expect(target(page, "form-submit")).toBeFocused();
  await target(page, "form-submit").click();
  await expect(page.locator(".governance-action-form .form-notice")).toContainText("游戏服务暂时没有响应");
  await expect(target(page, "form-topic").locator("textarea")).toHaveValue("核实搬迁安排");
  await expect(page.getByText("现场走访已经发起", { exact: true })).toHaveCount(0);
  expect(gameplayWrites(result)).toHaveLength(1);
  expect(gameplayWrites(result)[0].body).toMatchObject({ variant_id: "field_visit", location_id: "county", target_ids: ["npc_sun_qiang"], topic: "核实搬迁安排" });
  result.allowWrites();
  await target(page, "form-submit").click();
  await expect(page.locator(".governance-action-form")).toHaveCount(0);
  await expect(page.getByText("现场走访已经发起", { exact: true })).toBeVisible();
  expect(gameplayWrites(result)).toHaveLength(2);
  expect(result.errors).toEqual([]);
});

test("meeting guide finds lead and evidence controls revealed by real preceding choices", async ({ page }) => {
  const result = await fixture(page, { auto: false });
  await enter(page); await actionsPage(page); await guideForm(page, "convene_leadership_meeting");
  await expect(target(page, "form-lead")).toHaveCount(0);
  await expect(target(page, "form-evidence")).toHaveCount(0);
  await next(page); await next(page);
  await target(page, "form-targets").locator('input[name="targets"]').nth(0).check();
  await target(page, "form-targets").locator('input[name="targets"]').nth(1).check();
  await next(page);
  await expect(card(page).getByRole("heading", { name: "指定主要汇报人" })).toBeVisible();
  await expect(card(page).getByRole("button", { name: "下一步", exact: true })).toBeDisabled();
  await target(page, "form-lead").locator('input[name="meeting-lead"]').first().check();
  await next(page);
  await expect(card(page).getByRole("heading", { name: "选择是否拟形成文件" })).toBeVisible();
  await target(page, "form-document").locator("select").selectOption("implementation_plan");
  await next(page);
  await expect(card(page).getByRole("heading", { name: "核对会议依据" })).toBeVisible();
  await expect(target(page, "form-evidence")).toContainText("已核定会议依据");
  await target(page, "form-evidence").locator('input[type="checkbox"]').uncheck();
  await expect(card(page).getByRole("button", { name: "下一步", exact: true })).toBeDisabled();
  await target(page, "form-evidence").locator('input[type="checkbox"]').check();
  await next(page);
  await card(page).getByRole("button", { name: "讲解完成，自主操作" }).click();
  await expect(target(page, "form-submit")).toBeFocused();
  expect(gameplayWrites(result)).toEqual([]);
  expect(result.errors).toEqual([]);
});

for (const viewport of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
  test(`real participant controls remain operable with tutorial at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const result = await fixture(page, { auto: false });
    await enter(page); await actionsPage(page);
    await page.locator('.canonical-actions [data-variant-id="field_visit"]').getByRole("button", { name: "了解此行动" }).click();
    await expect(card(page).getByRole("heading", { name: "现场走访", exact: true })).toBeVisible();
    await expectCardInViewport(page);
    if (viewport.width === 390) await expect(async () => {
      const hole = page.locator('.tutorial-mask mask rect[fill="black"]');
      const bottom = Number(await hole.getAttribute("y")) + Number(await hole.getAttribute("height"));
      const popover = await card(page).boundingBox();
      expect(bottom).toBeLessThanOrEqual(popover!.y);
    }).toPass();
    await mkdir(shotDir, { recursive: true });
    await page.screenshot({ path: `${shotDir}/action-overview-${viewport.width}.png` });
    await card(page).getByRole("button", { name: "完成本节" }).click();
    await guideForm(page, "field_visit");
    await next(page); await next(page);
    await expect(card(page).getByRole("heading", { name: "选择当前可参与对象" })).toBeVisible();
    await target(page, "form-targets").locator('input[name="targets"]').first().check();
    await expect(card(page).getByRole("button", { name: "下一步", exact: true })).toBeEnabled();
    await expectCardInViewport(page);
    await mkdir(shotDir, { recursive: true });
    await page.screenshot({ path: `${shotDir}/form-targets-${viewport.width}.png` });
    await next(page);
    await card(page).getByRole("button", { name: "讲解完成，自主操作" }).click();
    await expect(target(page, "form-submit")).toBeFocused();
    expect(gameplayWrites(result)).toEqual([]);
    expect(result.errors).toEqual([]);
  });
}

test("archive tutorial finishes without reading; user submits exactly once and sees actual result", async ({ page }) => {
  const result = await fixture(page, { auto: false });
  await enter(page); await actionsPage(page); await guideForm(page, "consult_county_archives");
  await next(page);
  await expect(card(page).getByRole("button", { name: "下一步", exact: true })).toBeDisabled();
  await target(page, "form-archives").getByRole("radio").check();
  await next(page);
  await card(page).getByRole("button", { name: "讲解完成，自主操作" }).click();
  await expect(target(page, "form-submit")).toBeFocused();
  expect(gameplayWrites(result)).toEqual([]);
  await target(page, "form-submit").click();
  await expect(page.getByRole("heading", { name: "档案查阅结果" })).toBeVisible();
  await expect(page.locator(".archive-reading-modal")).toContainText("待查县级档案");
  expect(gameplayWrites(result)).toHaveLength(1);
  expect(gameplayWrites(result)[0].body).toMatchObject({ archive_ids: ["archive-unread"] });
  expect(result.errors).toEqual([]);
});

test("spotlight remains on current target during desktop/mobile resize and captures references", async ({ page }) => {
  const result = await fixture(page);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await enter(page); await page.getByRole("button", { name: "开始赴任指南" }).click();
  await next(page); // 玩法概述 → 今日案头
  await next(page); // 今日案头 → 状态栏
  await mkdir(shotDir, { recursive: true });
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await expect(card(page).getByRole("heading", { name: "日期、阶段与精力" })).toBeVisible();
    await expect(async () => {
      const bounds = await target(page, "metrics").boundingBox();
      const hole = page.locator('.tutorial-mask mask rect[fill="black"]');
      const holeX = Number(await hole.getAttribute("x"));
      const holeY = Number(await hole.getAttribute("y"));
      expect(bounds).not.toBeNull();
      expect(Math.abs(holeX - Math.max(5, bounds!.x - 6))).toBeLessThan(10);
      expect(Math.abs(holeY - Math.max(5, bounds!.y - 6))).toBeLessThan(10);
      const box = await card(page).boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1);
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1);
    }).toPass();
    await page.screenshot({ path: `${shotDir}/basic-metrics-${viewport.width}.png` });
  }
  expect(gameplayWrites(result)).toEqual([]);
  expect(result.errors).toEqual([]);
});
