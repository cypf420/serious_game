import { expect, test, type Page } from "@playwright/test";

const matrix = [
  { width: 1366, height: 768, zoom: 1 }, { width: 1920, height: 1080, zoom: 1 },
  { width: 390, height: 844, zoom: 1 }, { width: 1366, height: 768, zoom: 1.25 },
  { width: 1920, height: 1080, zoom: 1.25 },
];

async function enter(page: Page) {
  await page.goto("/");
  await expect(page.locator(".online")).toHaveText("游戏已就绪");
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const account = "sandbox_final_check";
    localStorage.setItem("qingjiang-sandbox-account", account);
    localStorage.setItem(`qingjiang:tutorial:v1:${account}`, JSON.stringify({ version: 1, auto: false, chapters: {} }));
  });
});

for (const size of matrix) test.describe(`${size.width}x${size.height} ${size.zoom * 100}%`, () => {
  // Browser zoom is represented by its effective CSS viewport and device ratio.
  test.use({ viewport: { width: Math.floor(size.width / size.zoom), height: Math.floor(size.height / size.zoom) }, deviceScaleFactor: size.zoom });

  test("server evidence directions preselect the actual archive and keep the decision locked until completion", async ({ page }, testInfo) => {
    const writes: string[] = [];
    const archive = { archive_id: "original", title: "政策原件", read_status: "unread", evidence_level: "E3", confidentiality: "internal", first_read_cost_action_points: 1 };
    const option = { option_id: "a", text: "出示原件", available: false, unavailable_reason: "已查阅两套账，但尚未取得政策原件。", next_steps: [{ label: "查阅本次已追回的政策原件", action_id: "inspect_archives", variant_id: "consult_county_archives", archive_id: "original" }] };
    const state = { session_id: "evidence-ui", status: "active", state_version: 1, story: { day: 34 }, ledger: { action_points: { remaining: 3 }, budget: { available: 8000 } }, pending_decision: { decision_id: "dp3_03", presentation_entry_id: "decision-gate", title: "核对原件", options: [option] } };
    const variant = { variant_id: "consult_county_archives", name: "查阅县级档案", available: true, location_choices: [{ location_id: "county", label: "县级档案室" }], participant_rules: { minimum: 1, maximum: 1 }, target_choices: [archive], cost_action_points: 1 };
    await page.route("**/api/backend/**", async route => {
      const endpoint = new URL(route.request().url()).pathname;
      const method = route.request().method();
      let body: unknown = {};
      if (endpoint.endsWith("/health/ready")) body = { authentication_required: false, model_consent_required: false };
      else if (endpoint.endsWith("/ai/config")) body = { active: true, mode: "personal", model: "controlled-ui-fixture", endpoint: "https://fixture.invalid/v1" };
      else if (endpoint.endsWith("/session")) body = { session_id: state.session_id };
      else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ content_instance_id: "decision-gate", kind: "decision", presentation_phase: "decision", story_day: 34, text: "请核对材料后决定。" }], cursor: 1 } };
      else if (endpoint.endsWith("/governance/actions") && method === "POST") {
        writes.push(endpoint);
        expect(route.request().postDataJSON().archive_ids).toEqual(["original"]);
        option.available = true; option.unavailable_reason = ""; state.state_version++;
        body = { visible_state: state, archives: [{ ...archive, read_status: "read", player_sections: [{ heading: "政策原件", body: "完整原件正文" }] }] };
      } else if (endpoint.endsWith("/actions")) body = { actions: [{ action_id: "inspect_archives", variants: [variant] }] };
      else if (endpoint.endsWith("/governance")) body = { governance_actions: [], meetings: [], archives: [archive] };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await enter(page);
    await expect(page.locator(".decision-option > button")).toBeDisabled();
    await expect(page.locator(".decision-option")).toContainText("尚未取得政策原件");
    await page.screenshot({ path: testInfo.outputPath("evidence-missing.png"), fullPage: true });
    await page.getByRole("button", { name: "查看办理安排", exact: true }).click();
    await expect(page.getByRole("radio", { name: /政策原件/ })).toBeChecked();
    expect(writes).toEqual([]);
    await page.locator('[data-tutorial-id="form-submit"]').click();
    await expect(page.getByRole("dialog")).toContainText("完整原件正文");
    await page.getByRole("dialog").getByRole("button", { name: "关闭", exact: true }).click();
    await expect(page.locator(".decision-option > button")).toBeEnabled();
    expect(writes).toHaveLength(1);
    await page.screenshot({ path: testInfo.outputPath("evidence-ready.png"), fullPage: true });
  });

  test("free-day scene, contract identity, fee and long hearing picker remain readable", async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const state = { session_id: "contract-final", status: "active", state_version: 1, story: { day: 40, beat_id: "beat_d40_m2" }, ledger: { action_points: { remaining: 3 }, budget: { available: 7800 } } };
    const contract = { contract_id: "c-final", batch_id: "batch", household_id: "YUAN-02", signatory_name: "袁丽梅", signatory_npc_id: "npc_yuan_limei", conversation_npc_id: "npc_yuan_guilan", conversation_npc_name: "袁桂兰", status: "rejected", current_version: 3, review_version: 3, review_reason: "请先确认医疗名额。", remaining_conditions: ["本户医疗服务尚未安排。"], review_cost_action_points: 1, review_cost_hint: "有效提交扣1点精力，接受与拒签均计费。", can_review: true, conversation_available: true, contract_text: "本合同属于袁丽梅户的第3版安置方案。\n".repeat(25), term_sheet: { cash_amount: 27 } };
    const action = { action_instance_id: "negotiation", action_kind: "household_visit", variant_id: "contract_negotiation", status: "active", target_ids: ["npc_yuan_guilan"], topic: "逐户安置协商", transcript: [] };
    const documents = Array.from({ length: 12 }, (_, index) => ({ id: `meeting:hearing-${index}`, title: `第${index + 1}次搬迁补偿范围与程序争议公开听证记录`, category: "meeting", status: "resolved", body: "对应本轮听证正文", version: 1, can_reference: true, story_day: 30 + index }));
    await page.route("**/api/backend/**", async route => {
      const endpoint = new URL(route.request().url()).pathname;
      let body: unknown = {};
      if (endpoint.endsWith("/health/ready")) body = { authentication_required: false, model_consent_required: false };
      else if (endpoint.endsWith("/ai/config")) body = { active: true, mode: "personal", model: "controlled-ui-fixture", endpoint: "https://fixture.invalid/v1" };
      else if (endpoint.endsWith("/session")) body = { session_id: state.session_id };
      else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ kind: "day_intro", scene_id: "C03_S03", beat_id: "beat_d40_m2", story_day: 40, text: "今天没有必须处理的主线事项，可以自由安排行动。" }], cursor: 1 } };
      else if (endpoint.endsWith("/reference-documents")) body = { documents };
      else if (endpoint.endsWith("/contracts/c-final")) body = { contract };
      else if (endpoint.endsWith("/governance")) body = { governance_actions: [action], meetings: [], contracts: [contract], contract_batches: [{ batch_id: "batch", representative_npc_id: "npc_yuan_guilan", status: "confirmed" }], resources: { resource_pools: [{ resource_id: "housing-zero", category: "housing", name: "库存耗尽房源", capacity: 1, available: 0 }] } };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await enter(page);
    await expect(page.locator(".story-head h2")).toHaveText("县长办公室");
    await page.getByRole("button", { name: "继续办理合同", exact: true }).click();
    const dialog = page.locator(".contract-modal");
    await expect(dialog.locator(".contract-status")).toContainText("袁丽梅");
    await expect(dialog.locator(".contract-status")).toContainText("当前谈话人：袁桂兰");
    await expect(dialog.locator(".contract-status")).toContainText("第 3 版");
    await page.screenshot({ path: testInfo.outputPath("contract-identity.png"), fullPage: true });
    await dialog.locator(".contract-effort").scrollIntoViewIfNeeded();
    await expect(dialog.locator(".contract-effort")).toContainText("本次提交需 1 点精力");
    await page.screenshot({ path: testInfo.outputPath("contract-cost.png"), fullPage: true });
    await dialog.getByRole("button", { name: "修改方案", exact: true }).click();
    await expect(dialog.locator('option[value="housing-zero"]')).toHaveJSProperty("disabled", true);
    await dialog.getByRole("button", { name: "关闭", exact: true }).click();
    await page.locator('.governance-bar textarea[name="player_text"]').fill("@");
    const picker = page.getByRole("listbox", { name: "选择引用档案" });
    await expect(picker).toContainText("第 30 日");
    await expect(picker).toContainText("第 41 日");
    const input = page.locator('.governance-bar textarea[name="player_text"]');
    for (let index = 0; index < 11; index++) await input.press("ArrowDown");
    await expect(picker.getByRole("option").last()).toBeInViewport();
    expect(await picker.getByRole("option").last().evaluate(node => node.scrollHeight <= node.clientHeight + 1)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath("hearing-picker.png"), fullPage: true });
    await input.press("Enter");
    await expect(page.getByLabel("已引用文件")).toContainText("第12次");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    expect(errors).toEqual([]);
  });
});
