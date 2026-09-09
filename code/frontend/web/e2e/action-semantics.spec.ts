import { expect, test, type Page } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

type Dict = Record<string, unknown>;
const config = JSON.parse(await readFile(resolve("../../backend/content/packages/pkg_gameplay_v3/governance_config.json"), "utf8"));
const definitions: Dict[] = config.action_variants.filter((item: Dict) => item.enabled === true);
const cases = [
  ["field_visit", "现场走访", "走访对象", "开始走访"],
  ["interview_cadre", "干部约谈", "约谈干部", "开始约谈"],
  ["interview_enterprise", "企业约谈", "企业对象", "开始约谈"],
  ["contact_media", "媒体沟通", "媒体沟通对象", "开始沟通"],
  ["convene_leadership_meeting", "班子会议", "参会领导", "发起班子会议"],
  ["public_hearing", "公开听证", "听证参与人", "发起听证"],
  ["clan_leader_campaign", "宗族议事", "议事参与人", "发起议事"],
  ["consult_county_archives", "查阅县级档案", "", "开始查阅"],
  ["collect_blood_lead_report", "调取血铅材料", "", "调取材料"],
];
const qa = resolve("../../../../output/action-audit-20260909/qa");

async function setup(page: Page, activeVariant?: string) {
  const errors: string[] = [];
  const writes: { path: string; body: Dict }[] = [];
  const state: Dict = { session_id: "action-audit", state_version: 1, status: "active", story: { day: 61 }, ledger: { action_points: { remaining: 8, daily_cap: 8 }, budget: { remaining: 8000 } } };
  const descriptors: Dict[] = definitions.map(item => ({ ...item, available: true, cost_action_points: 3,
    target_choices: item.action_id === "inspect_archives" ? [{ target_id: "sample-material" }] : (item.legal_target_ids as string[]).map(target_id => ({ target_id, label: target_id })),
    resolved_location_id: (item.legal_location_ids as string[])[0],
    location_choices: (item.legal_location_ids as string[]).map(location_id => ({ location_id, label: "当前公开地点" })),
    participant_rules: { minimum: item.action_id === "leadership_meeting" ? 2 : 1, maximum: item.action_id === "leadership_meeting" ? 3 : item.action_id === "cadre_interview" ? 3 : 1 },
  }));
  const actions = ["household_visit", "cadre_interview", "leadership_meeting", "inspect_archives"].map(action_id => ({ action_id, variants: descriptors.filter(item => item.action_id === action_id) }));
  const definition = descriptors.find(item => item.variant_id === activeVariant);
  const ids = definition ? (definition.legal_target_ids as string[]).slice(0, definition.action_id === "leadership_meeting" ? 2 : 1) : [];
  const active: Dict | null = definition ? { action_instance_id: "audit-action", action_kind: definition.action_id, variant_id: activeVariant, display_title: definition.name, target_ids: ids, topic: "核对本次公开事项", story_day: 61, status: "active", cost_status: "committed", transcript: [] } : null;
  const meeting: Dict | null = active ? { meeting_id: "audit-meeting", action_instance_id: "audit-action", participant_ids: ids, topic: active.topic, story_day: 61, status: "discussion", transcript: ids.map(npc_id => ({ speaker_type: "npc", npc_id, npc_name: "本次参与人", text: "我已说明对此事项的意见。" })) } : null;
  const governance = () => ({ governance_actions: active ? [active] : [], meetings: meeting ? [meeting] : [], documents: [],
    archives: [{ archive_id: "sample-material", title: "已公开可调阅材料", evidence_level: "E2", confidentiality: "public", read_at_days: [] }],
    document_types: [{ document_type: "implementation_plan", required_evidence_level: "E2", required_countersign_ids: [] }],
  });
  await page.addInitScript(() => {
    localStorage.setItem("qingjiang-sandbox-account", "sandbox_action_audit");
    localStorage.setItem("qingjiang:tutorial:v1:sandbox_action_audit", JSON.stringify({ version: 1, auto: false, chapters: {} }));
  });
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/backend/**", async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    const method = route.request().method();
    let body: Dict = {};
    if (method !== "GET") writes.push({ path, body: route.request().postDataJSON() || {} });
    if (path === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (path === "/api/ai/config") body = { active: true, mode: "personal", endpoint: "https://fixture.invalid/v1", model: "fixture-model" };
    else if (path === "/api/game/session" || path === "/api/game/session/action-audit") body = { session_id: "action-audit" };
    else if (path.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "audit-line", story_day: 61, text: "核对当前行动与办理记录。" }], cursor: 1 } };
    else if (path.endsWith("/actions")) body = { actions };
    else if (path.endsWith("/governance")) body = governance();
    else if (path.endsWith("/resolve") && active && meeting) {
      const payload = route.request().postDataJSON();
      active.status = "completed"; meeting.status = "resolved"; meeting.resolution = payload.resolution;
      body = { state_version: 2, passed: true, meeting, document: null };
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page).toHaveTitle(/浊流之上/);
  await expect(page.getByText("游戏已就绪", { exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  await expect(page.locator('[data-tutorial-id="nav-actions"]')).toBeEnabled();
  return { writes, errors };
}

for (const [id, name, participantLabel, submitLabel] of cases) test(`${name}: card, form, defaults and tutorial use its own action semantics`, async ({ page }) => {
  const result = await setup(page);
  await page.locator('[data-tutorial-id="nav-actions"]').click();
  const entry = page.locator(`.canonical-actions [data-variant-id="${id}"]`);
  await expect(entry.locator("b").first()).toHaveText(name);
  await entry.getByRole("button").last().click();
  const form = page.locator(".governance-action-form");
  await expect(form.locator('[data-tutorial-id="form-submit"]')).toHaveText(submitLabel);
  if (participantLabel) await expect(form.locator('[data-tutorial-id="form-targets"] legend')).toHaveText(`${participantLabel}（${id === "field_visit" ? "选择 1 人" : id === "convene_leadership_meeting" || id === "public_hearing" || id === "clan_leader_campaign" ? "选择 2 至 3 人" : "选择 1 至 3 人"}）`);
  if (["public_hearing", "clan_leader_campaign"].includes(id)) {
    await expect(form).not.toContainText(/班子|分管|参会领导|拟形成文件/);
    await expect(form.locator('[data-tutorial-id="form-topic"] textarea')).not.toHaveValue(/核实负责事项|临时安置点/);
    await mkdir(qa, { recursive: true });
    await page.screenshot({ path: `${qa}/${id}-form.png` });
    await page.getByRole("button", { name: "填写指南", exact: true }).click();
    await page.getByRole("button", { name: "重新查看本次填写指南" }).click();
    await expect(page.locator(".tutorial-popover")).not.toContainText(/班子|领导/);
    await page.keyboard.press("Escape");
  }
  if (id === "contact_media") await expect(form.locator("textarea")).toHaveValue(/公开口径.*材料来源.*采访边界/);
  if (id === "interview_enterprise") await expect(form.locator("textarea")).toHaveValue(/项目履约.*资金.*环境责任/);
  expect(result.writes.filter(write => write.path !== "/api/game/session")).toEqual([]);
  expect(result.errors).toEqual([]);
});

for (const [id, name, conclusion, record] of [["convene_leadership_meeting", "班子会议", "会议决议", "会议纪要"], ["public_hearing", "公开听证", "听证结论", "听证记录"], ["clan_leader_campaign", "宗族议事", "议事结论", "议事记录"]]) test(`${name}: active scene -> real resolution controls -> returned conclusion`, async ({ page }) => {
  const result = await setup(page, id);
  await expect(page.locator('[data-testid="leadership-meeting-scene"] header small')).toHaveText(`正在进行 · ${name}`);
  if (id === "clan_leader_campaign") {
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('[data-testid="leadership-meeting-scene"]')).toHaveCSS("background-image", /c05-s02.webp/);
  }
  const toolbar = page.locator(".governance-bar");
  if (id !== "convene_leadership_meeting") await expect(toolbar).not.toContainText(/班子|领导|终止会议|会议决议/);
  await toolbar.getByRole("button", { name: `形成${conclusion}`, exact: true }).click();
  const resolution = page.locator(".meeting-resolution-form");
  await expect(page.getByRole("heading", { name: `确认${conclusion}` })).toBeVisible();
  if (id !== "convene_leadership_meeting") await expect(resolution).not.toContainText(/班子|分管领导|主要领导|会议纪要/);
  await resolution.locator("textarea").fill(`${name}本次已核定的实际结论`);
  await resolution.locator('button[type="submit"],button:not([type])').last().click();
  await expect(resolution).toHaveCount(0);
  await page.locator('[data-tutorial-id="nav-governance"]').click();
  await page.getByRole("button", { name: `查看${record}`, exact: true }).click();
  await expect(page.getByRole("heading", { name: record, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "记录阅读指南" })).toBeVisible();
  await expect(page.locator(".governance-record-detail")).toContainText(`${name}本次已核定的实际结论`);
  await expect(page.locator(".record-brief small")).toHaveText(record);
  await mkdir(qa, { recursive: true });
  await page.screenshot({ path: `${qa}/${id}-result.png` });
  expect(result.writes.filter(write => write.path.endsWith("/resolve"))).toHaveLength(1);
  expect(result.errors).toEqual([]);
});
