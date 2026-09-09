import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // These cases exercise gameplay; tutorial invitation and interaction are
  // covered separately by tutorial.spec.ts using the same integrated shell.
  await page.addInitScript(() => {
    const account = "sandbox_component_gameplay";
    localStorage.setItem("qingjiang-sandbox-account", account);
    localStorage.setItem(`qingjiang:tutorial:v1:${account}`, JSON.stringify({ version: 1, auto: false, chapters: {} }));
  });
});

test("signed contract updates fiscal balance even when view refresh fails", async ({ page }) => {
  const writes: string[] = [];
  const action = { action_instance_id: "visit-contract", action_kind: "household_visit", status: "active", target_ids: ["npc_yuan_guilan"], topic: "安置协商", transcript: [] };
  const state = { session_id: "contract-ui", status: "active", state_version: 1, story: { day: 10 }, onboarding: { free_action_completed: false }, ledger: { action_points: { remaining: 8, daily_cap: 8 }, budget: { remaining: 7800 }, relocation: { signed: 0, total: 36 } } };
  let contract = { contract_id: "c1", batch_id: "b1", household_id: "YUAN-01", signatory_npc_id: "npc_yuan_guilan", signatory_name: "袁桂兰", status: "rejected", current_version: 2, review_version: 1, review_reason: "请确认扶手。", audit_status: "not_required", contract_text: "搬离日：第83日\n交房日：第83日\n住房已核实设有扶手。", can_review: true, conversation_available: true, term_sheet: { cash_amount: 27, move_out_day: 83, housing_delivery_day: 83, transition_months: 12 } };
  await page.route("**/api/backend/**", async route => {
    const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    let body: unknown = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
    else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
    else if (endpoint.endsWith("/view") && contract.status === "signed") { await route.fulfill({status: 503, body: "refresh unavailable"}); return; }
    else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "opening", story_day: 10, text: "安置会谈正在进行。", block_id: "d10_source_opening", scene_id: "C01_S12" }], cursor: 1 } };
    else if (endpoint.endsWith("/governance")) body = { governance_actions: [action], contracts: [contract], contract_batches: [{ batch_id: "b1", representative_npc_id: "npc_yuan_guilan", status: "confirmed" }], resources: { resource_pools: [], budget_envelopes: { property_land: { available: 100 } } } };
    else if (endpoint.endsWith("/contracts/c1")) body = { contract };
    else if (endpoint.endsWith("/terms")) {
      writes.push(endpoint);
      contract = { ...contract, status: "draft", current_version: 3, term_sheet: { ...contract.term_sheet, cash_amount: 28 }, contract_text: "现金补偿：28万元\n搬离日：第83日\n交房日：第83日" };
      body = { contract, state_version: ++state.state_version };
    } else if (endpoint.endsWith("/review")) {
      writes.push(endpoint);
      expect(route.request().postDataJSON().expected_contract_version).toBe(3);
      contract = { ...contract, status: "signed", review_version: 3, review_reason: "同意签约。", can_review: false };
      state.ledger.budget.remaining = 7772;
      body = { contract, state_version: ++state.state_version, visible_state: state };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  await page.getByRole("button", { name: "继续办理合同", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".contract-body")).toHaveText(contract.contract_text);
  await expect(dialog.locator("textarea")).toHaveCount(0);
  await expect(dialog).not.toContainText("专业审校");
  await expect(dialog.getByText("请确认扶手。", { exact: true })).not.toBeVisible();
  await dialog.getByRole("button", { name: "修改方案", exact: true }).click();
  await dialog.locator('[name="cash_amount"]').fill("28");
  await expect(dialog.getByRole("button", { name: "提交签约", exact: true })).toBeDisabled();
  page.once("dialog", prompt => prompt.dismiss());
  await dialog.getByRole("button", { name: "继续协商", exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[name="cash_amount"]')).toHaveValue("28");
  await dialog.getByRole("button", { name: "保存方案并预览合同", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "提交签约", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "提交签约", exact: true }).click();
  await expect(page.locator('[data-tutorial-id="metrics"]')).toContainText('7772');
  await expect(dialog.locator('.signed-contract-seal')).toBeVisible();
  expect(writes.filter(path => path.endsWith('/review'))).toHaveLength(1);
});
