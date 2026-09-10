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

for (const [width, initialStage] of [[1366, "preview"], [390, "preview"], [1366, "feedback"], [390, "legacy"]] as const) test(`contract guide uses ${initialStage} at ${width}px without submitting`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 768 });
  const writes: string[] = [];
  const action = { action_instance_id: "visit-contract", action_kind: "household_visit", status: "active", target_ids: ["npc_yuan_guilan"], topic: "安置协商", transcript: [] };
  const state = { session_id: "contract-ui", status: "active", state_version: 1, story: { day: 10 }, onboarding: { free_action_completed: false }, ledger: { action_points: { remaining: 8, daily_cap: 8 }, budget: { remaining: 7800 }, relocation: { signed: 0, total: 36 } } };
  let contract = { contract_id: "c1", batch_id: "b1", household_id: "YUAN-01", signatory_npc_id: "npc_yuan_guilan", signatory_name: "袁桂兰", status: "rejected", current_version: 2, legacy_draft: initialStage === "legacy", review_version: initialStage === "feedback" ? 2 : 1, review_reason: "请确认扶手。", audit_status: "not_required", contract_text: "搬离日：第83日\n交房日：第83日\n住房已核实设有扶手。", can_review: true, conversation_available: true, term_sheet: { cash_amount: 27, move_out_day: 83, housing_delivery_day: 83, transition_months: 12 } };
  await page.route("**/api/backend/**", async route => {
    const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    let body: unknown = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
    else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
    else if (endpoint.endsWith("/view") && contract.status === "signed") { await route.fulfill({status: 503, body: "refresh unavailable"}); return; }
    else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "opening", story_day: 10, text: "安置会谈正在进行。", block_id: "d10_source_opening", scene_id: "C01_S12" }], cursor: 1 } };
    else if (endpoint.endsWith("/governance")) body = { governance_actions: [action], contracts: [contract], contract_batches: [{ batch_id: "b1", representative_npc_id: "npc_yuan_guilan", status: "confirmed" }], resources: { resource_pools: [{ resource_id: "housing_d1_140", category: "housing", name: "现房140平方米", capacity: 2 }], budget_envelopes: { property_land: { available: 100 } } } };
    else if (endpoint.endsWith("/contracts/c1")) body = { contract };
    else if (endpoint.endsWith("/terms")) {
      writes.push(endpoint);
      contract = { ...contract, status: "draft", legacy_draft: false, current_version: 3, term_sheet: { ...contract.term_sheet, cash_amount: 28 }, contract_text: "现金补偿：28万元\n搬离日：第83日\n交房日：第83日" };
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
  await expect(page.locator(".online")).toHaveText("游戏已就绪");
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  await page.getByRole("button", { name: "继续办理合同", exact: true }).click();
  const dialog = page.locator('.contract-modal');
  async function guide(title: string, count: number) {
    const before = writes.length;
    await dialog.getByRole('button', { name: '合同操作指南', exact: true }).click();
    await page.getByRole('dialog', { name: '赴任指南目录' }).getByRole('button', { name: title, exact: true }).click();
    const card = page.locator('.tutorial-popover');
    for (let index = 0; index < count; index++) {
      await expect(card).toBeVisible();
      await expect(card).not.toContainText('展开说明');
      await expect(async () => {
        const bounds = await card.boundingBox();
        expect(bounds!.y).toBeGreaterThanOrEqual(0);
        expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
      }).toPass();
      const rect = await card.boundingBox();
      expect(rect!.x).toBeGreaterThanOrEqual(0);
      expect(rect!.x + rect!.width).toBeLessThanOrEqual(width + 1);
      if (index === 0) await page.screenshot({ path: `E:/严肃游戏/output/contract-guide-${width}-${title}.png` });
      await card.getByRole('button', { name: index === count - 1 ? '讲解完成，自主操作' : '下一步', exact: true }).click();
    }
    await expect(card).toHaveCount(0);
    expect(writes.length).toBe(before);
  }
  await guide(initialStage === 'legacy' ? '核对旧版草案' : initialStage === 'feedback' ? '阅读签约答复' : '核对并提交合同', initialStage === 'preview' ? 3 : 1);
  if (initialStage !== 'legacy') await dialog.getByRole('button', { name: '修改方案', exact: true }).click();
  await expect(dialog.locator('[name="housing_delivery_day"]')).toHaveCount(0);
  await dialog.locator('[name="housing_resource_id"]').selectOption('housing_d1_140');
  await expect(dialog.locator('[name="housing_delivery_day"], [name="move_out_day"], [name="transition_months"], [name="budget_envelope"]')).toHaveCount(0);
  await dialog.locator('[name="housing_resource_id"]').selectOption('');
  await expect(dialog.locator('[name="housing_delivery_day"]')).toHaveCount(0);
  if (initialStage !== 'legacy') await guide('填写合同方案', 5);
  else await dialog.getByRole('checkbox').check();
  await dialog.locator('[name="cash_amount"]').fill('28');
  await dialog.getByRole('button', { name: '保存方案并预览合同', exact: true }).click();
  await guide('核对并提交合同', 3);
  expect(writes).toHaveLength(1);
  await dialog.getByRole('button', { name: '提交签约', exact: true }).click();
  await guide('查看已签合同', 1);
  expect(writes.filter(path => path.endsWith('/review'))).toHaveLength(1);
});
