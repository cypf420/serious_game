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

for (const width of [1433, 1081, 390]) {
  test(`feedback signing entry works without keyword guessing at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 898 });
    const errors: string[] = [];
    const writes: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const state = {
      session_id: "feedback-ui", status: "active", state_version: 1,
      story: { day: 10 }, onboarding: { free_action_completed: false },
      ledger: { action_points: { remaining: 8, daily_cap: 8 }, budget: { available: 7800 }, relocation: { signed: 0, total: 36 } },
    };
    const person = { npc_id: "npc_zhou_dashan", name: "周大山", discovery_state: "encountered", contact_state: "known" };
    const preparation = { available: true, reason: null, household_count: 6 };
    const descriptor = {
      npc_id: person.npc_id, npc_name: person.name, variant_id: "contract_negotiation", action_id: "household_visit", name: "签约协商",
      cost_action_points: 0, resource_cost_mode: "none", resource_costs: [], available: true,
      legal_location_ids: ["loc_liulin_village"], location_choices: [{ location_id: "loc_liulin_village", label: "入村走访" }],
      target_kind: "household_representative", target_choices: [{ target_id: person.npc_id, label: person.name }],
      participant_rules: { minimum: 1, maximum: 1 }, preselected_npc_ids: [person.npc_id], contract_preparation: preparation,
    };
    let active = false;
    let preparationAttempts = 0;
    const action = { action_instance_id: "visit-feedback", action_kind: "household_visit", status: "active", story_day: 10,
      target_ids: [person.npc_id], topic: "核对本户搬迁顾虑", transcript: [] };
    await page.route("**/api/backend/**", async route => {
      const url = new URL(route.request().url());
      const endpoint = url.pathname.replace(/^\/api\/backend/, "");
      const method = route.request().method();
      let body: Record<string, unknown> = {};
      if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
      else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "explicit-ui-fixture", endpoint: "https://fixture.invalid/v1" };
      else if (endpoint === "/api/game/session" && method === "POST") body = { session_id: state.session_id };
      else if (endpoint.endsWith("/view")) body = { state, commands: { can_act: !active, can_end_day: !active },
        feed: { items: [{ id: "day10", story_day: 10, text: "第十日，你站在镇政府院子里。", block_id: "d10_source_opening", scene_id: "C01_S12" }], cursor: 1 } };
      else if (endpoint.endsWith("/opportunities")) body = { people: [person], person_actions: [{ ...descriptor, variant_id: "field_visit", name: "现场走访", cost_action_points: 1 }, descriptor], opportunities: [], relationship_edges: [] };
      else if (endpoint.endsWith("/governance")) body = { governance_actions: active ? [action] : [], meetings: [],
        contracts: [], contract_batches: [], active_contract_preparation: active ? preparation : null };
      else if (endpoint.endsWith("/governance/actions") && method === "POST") {
        writes.push(endpoint);
        expect(route.request().postDataJSON().target_ids).toEqual([person.npc_id]);
        expect(route.request().postDataJSON().variant_id).toBe("contract_negotiation");
        active = true;
        state.state_version++;
        state.ledger.action_points.remaining = 8;
        body = { action, state_version: state.state_version };
      } else if (endpoint.endsWith("/prepare-contracts")) {
        writes.push(endpoint);
        if (++preparationAttempts === 1) {
          await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "ACTION_UNAVAILABLE", message: "测试提示：请先核对住户条款后再准备合同。" } }) });
          return;
        }
        body = { state_version: ++state.state_version, batch: { batch_id: "proposal-feedback", representative_npc_id: person.npc_id,
          household_ids: ["ZDS-01", "ZDS-02", "ZDS-03", "ZDS-04", "ZDS-05", "ZDS-06"], status: "pending_confirmation" } };
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("/");
    if (width >= 700) {
      await expect(page.getByText("游戏已就绪", { exact: true })).toBeVisible();
    } else {
      // The compact header intentionally hides the connection label while
      // retaining the status node and its accessible state for screen readers.
      await expect(page.locator(".top-status .online")).toHaveCount(1);
    }
    await page.getByRole("button", { name: "进入游戏", exact: true }).click();
    await page.getByRole("button", { name: /开始新游戏/ }).click();
    await expect(page.getByText("剧情之外，也能主动安排行动", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "推进签约", exact: true }).click();
    await expect(page.getByText("主动推进签约", { exact: true })).toBeVisible();
    await expect(page.getByText("可主动联系", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "入户协商", exact: true }).click();
    await expect(page.getByRole("radio", { name: /周大山/ })).toBeChecked();
    await page.locator('[data-tutorial-id="form-submit"]').click();
    await page.getByRole("button", { name: "准备逐户合同", exact: true }).click();
    const notice = page.locator(".governance-inline-notice");
    await expect(notice).toContainText("请先核对住户条款");
    await expect(notice).toHaveCSS("color", "rgb(245, 230, 196)");
    await expect(notice).toHaveCSS("background-color", "rgb(41, 37, 30)");
    await page.screenshot({ path: testInfo.outputPath(`notice-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "准备逐户合同", exact: true }).click();
    await expect(page.getByRole("dialog")).toContainText("确认逐户合同提议");
    expect(writes).toHaveLength(3);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`signing-${width}.png`), fullPage: true });
  });
}

test("clicking an earlier NPC timeline entry switches the rendered speaker without a page error", async ({ page }) => {
  const pageErrors: Error[] = [];
  page.on("pageerror", error => pageErrors.push(error));

  const groupConversation = {
    conversation_id: "component-group-1",
    phase: "active",
    agenda: "核对安置与复核安排",
    initiator_npc_id: "npc_yuan_guilan",
    participant_ids: ["npc_sun_qiang", "npc_yuan_guilan"],
    participant_states: [
      { npc_id: "npc_sun_qiang", status: "active", public_summary: "要求明确责任" },
      { npc_id: "npc_yuan_guilan", status: "active", public_summary: "要求核对安置" },
    ],
    transcript: [
      { speaker_type: "npc", npc_id: "npc_sun_qiang", npc_name: "孙强", text: "请先明确责任人与复核节点。" },
      { speaker_type: "npc", npc_id: "npc_yuan_guilan", npc_name: "袁桂兰", text: "我的安置清单还需要逐项核对。" },
    ],
  };
  const state = {
    session_id: "component-session",
    status: "active",
    state_version: 1,
    story: { day: 2 },
    ledger: { action_points: { available: 3, daily_cap: 3 }, budget: { available: 8000 } },
    active_group_conversation: groupConversation,
  };

  await page.route("**/api/backend/**", async route => {
    const url = new URL(route.request().url());
    const backendPath = url.pathname.replace(/^\/api\/backend/, "");
    let body: Record<string, unknown> = {};
    if (backendPath === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (backendPath === "/api/ai/config") body = { active: true, mode: "personal", endpoint: "https://fixture.invalid/v1", model: "fixture-model" };
    else if (backendPath === "/api/game/session" && route.request().method() === "POST") body = { session_id: "component-session" };
    else if (backendPath.includes("/api/game/session/component-session/view")) body = {
      state,
      visible_state: state,
      commands: {},
      feed: { items: [{ id: "fixture-line", story_day: 2, text: "会谈已经开始。" }], cursor: 1 },
    };
    else if (backendPath.endsWith("/governance")) body = { governance_actions: [], meetings: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/");
  await expect(page.getByText("游戏已就绪", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  expect(pageErrors).toEqual([]);
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: /开始新游戏/ }).click();

  const speaker = page.locator(".forced-group-speaker");
  await expect(speaker).toHaveAttribute("aria-label", "袁桂兰立绘");
  await expect(speaker.getByText("袁桂兰", { exact: true })).toBeVisible();
  await expect(speaker.getByText("困难户", { exact: true })).toBeVisible();
  await expect(page.getByText("我的安置清单还需要逐项核对。", { exact: true })).toBeVisible();

  await page.locator(".forced-group-timeline button.npc").filter({ hasText: "孙强" }).click();

  await expect(speaker).toHaveAttribute("aria-label", "孙强立绘");
  await expect(speaker.getByText("孙强", { exact: true })).toBeVisible();
  await expect(speaker.getByText("渡口镇党委书记", { exact: true })).toBeVisible();
  await expect(page.getByText("请先明确责任人与复核节点。", { exact: true })).toBeVisible();
  expect(pageErrors.map(error => error.message)).not.toContainEqual(expect.stringContaining("setSelectedNpcId"));
  expect(pageErrors).toEqual([]);
});

test("long governance timelines preserve scroll position and expose new replies", async ({ page }) => {
  const state = {
    session_id: "timeline-session", status: "active", state_version: 4,
    story: { day: 10 }, onboarding: { free_action_completed: true },
    active_governance_action: { action_instance_id: "timeline-action", action_kind: "household_visit", status: "active", story_day: 10, target_ids: ["npc_zhou_dashan"], topic: "核对安置安排" },
    ledger: { action_points: { remaining: 6, daily_cap: 8 }, budget: { available: 7800 }, relocation: { signed: 8, total: 36 } },
  };
  const transcript = Array.from({ length: 18 }, (_, index) => ({
    speaker_type: index % 3 === 0 ? "player" : "npc",
    npc_id: index % 3 === 0 ? undefined : "npc_zhou_dashan",
    npc_name: index % 3 === 0 ? undefined : "周大山",
    text: `${index % 3 === 0 ? "你" : "周大山"}：关于安置房、补偿核算和签署顺序的第${index + 1}轮说明。`.repeat(3),
    turn_id: `turn-${index}`,
  }));
  const expandedTranscript = [...transcript,
    { speaker_type: "npc", npc_id: "npc_zhou_dashan", npc_name: "周大山", text: "我还要再核对一遍安置房交付节点和户主签字。".repeat(4), turn_id: "turn-18" },
    { speaker_type: "npc", npc_id: "npc_yuan_guilan", npc_name: "袁桂兰", text: "困难户的医疗兜底也请写进安排。".repeat(4), turn_id: "turn-19" },
  ];
  let expanded = false;
  const governancePayload = () => ({ governance_actions: [{ ...state.active_governance_action, transcript: expanded ? expandedTranscript : transcript }], meetings: [], contracts: [], contract_batches: [], target_catalogs: { household_representative: [{ target_id: "npc_zhou_dashan", label: "周大山" }, { target_id: "npc_yuan_guilan", label: "袁桂兰" }] } });
  await page.route("**/api/backend/**", async route => {
    const url = new URL(route.request().url());
    const endpoint = url.pathname.replace(/^\/api\/backend/, "");
    const method = route.request().method();
    let body: Record<string, unknown> = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
    else if (endpoint === "/api/game/session" && method === "POST") body = { session_id: state.session_id };
    else if (endpoint.endsWith("/view")) body = { state, commands: { can_act: false, can_end_day: false }, feed: { items: [{ id: "timeline-opening", story_day: 10, text: "第十日，安置安排进入现场核对。" }], cursor: 1 } };
    else if (endpoint.includes("/governance/actions/") && endpoint.endsWith("/turn/stream")) {
      expanded = true;
      const events = [
        { type: "npc_start", stream_id: "npc_zhou_dashan:turn-18", npc_id: "npc_zhou_dashan", npc_name: "周大山" },
        { type: "npc_delta", stream_id: "npc_zhou_dashan:turn-18", delta: "我还要再核对一遍安置房交付节点和户主签字。".repeat(4) },
        { type: "npc_end", stream_id: "npc_zhou_dashan:turn-18" },
        { type: "complete", result: {} },
      ];
      await route.fulfill({ status: 200, contentType: "application/x-ndjson", body: `${events.map(event => JSON.stringify(event)).join("\n")}\n` });
      return;
    }
    else if (endpoint.endsWith("/governance")) body = governancePayload();
    else if (endpoint.endsWith("/actions")) body = { actions: [], action_variants: [] };
    else if (endpoint.endsWith("/opportunities")) body = { people: [], person_actions: [], opportunities: [], relationship_edges: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/");
  await expect(page.getByText("游戏已就绪", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  const timeline = page.locator(".governance-action-timeline");
  await expect(timeline).toBeVisible();
  const initial = await timeline.evaluate(element => ({ scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }));
  expect(initial.scrollHeight).toBeGreaterThan(initial.clientHeight);
  await timeline.evaluate(element => { element.scrollTop = 0; element.dispatchEvent(new Event("scroll", { bubbles: true })); });
  const input = page.locator('[data-tutorial-id="conversation-input"] textarea');
  await input.fill("请把安置房交付节点和户主签字顺序再说明一遍。");
  await page.getByRole("button", { name: "送出回应", exact: true }).click();
  await expect.poll(() => timeline.evaluate(element => element.scrollHeight)).toBeGreaterThan(initial.scrollHeight);
  expect(await timeline.evaluate(element => element.scrollTop)).toBeLessThan(80);
  await expect(page.getByRole("button", { name: "有新回复", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "有新回复", exact: true }).click();
  await expect.poll(() => timeline.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
  await expect(page.locator(".governance-action-timeline article")).toHaveCount(expandedTranscript.length);
});

test("resolved group conversations keep the input and explicit finish action", async ({ page }) => {
  const groupConversation = {
    conversation_id: "resolved-group", phase: "resolved", agenda: "核对安置与复核安排", initiator_npc_id: "npc_yuan_guilan",
    participant_ids: ["npc_sun_qiang", "npc_yuan_guilan"],
    participant_states: [
      { npc_id: "npc_sun_qiang", status: "settled", public_summary: "暂时接受，仍在旁听" },
      { npc_id: "npc_yuan_guilan", status: "settled", public_summary: "暂时接受，仍在旁听" },
    ],
    transcript: [
      { speaker_type: "npc", npc_id: "npc_sun_qiang", npc_name: "孙强", text: "责任节点已经记下。" },
      { speaker_type: "npc", npc_id: "npc_yuan_guilan", npc_name: "袁桂兰", text: "安置清单也请保留。" },
    ],
    closure_summary: "发起人暂时停止追问。",
  };
  const state = {
    session_id: "resolved-group-session", status: "active", state_version: 2, story: { day: 2 },
    active_group_conversation: groupConversation,
    ledger: { action_points: { remaining: 3, daily_cap: 3 }, budget: { available: 8000 } },
  };
  await page.route("**/api/backend/**", async route => {
    const url = new URL(route.request().url());
    const endpoint = url.pathname.replace(/^\/api\/backend/, "");
    let body: Record<string, unknown> = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", endpoint: "https://fixture.invalid/v1", model: "fixture-model" };
    else if (endpoint === "/api/game/session" && route.request().method() === "POST") body = { session_id: state.session_id };
    else if (endpoint.includes("/api/game/session/resolved-group-session/view")) body = { state, visible_state: state, commands: {}, feed: { items: [{ id: "resolved-line", story_day: 2, text: "会谈已经收束。" }], cursor: 1 } };
    else if (endpoint.endsWith("/governance")) body = { governance_actions: [], meetings: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page.getByText("游戏已就绪", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  await expect(page.getByTestId("forced-group-conversation")).toBeVisible();
  await expect(page.getByText("多人会谈已收束，可继续补充", { exact: true })).toBeVisible();
  const input = page.getByRole("textbox", { name: "回应在场各方" });
  await expect(input).toBeVisible();
  await input.fill("我补充说明复核安排和后续联系人。");
  await expect(page.getByRole("button", { name: "结束夜间会谈", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "送出回应", exact: true })).toBeEnabled();
});

test("contract preview preserves text, prevents dirty submit, and resumes existing discussion", async ({ page }, testInfo) => {
  const writes: string[] = [];
  let saveAttempts = 0;
  const action = { action_instance_id: "visit-contract", action_kind: "household_visit", status: "active", target_ids: ["npc_yuan_guilan"], topic: "安置协商", transcript: [] };
  const state = { session_id: "contract-ui", status: "active", state_version: 1, story: { day: 10 }, onboarding: { free_action_completed: false }, ledger: { action_points: { remaining: 8, daily_cap: 8 }, budget: { available: 7800 }, relocation: { signed: 0, total: 36 } } };
  let contract = { contract_id: "c1", batch_id: "b1", household_id: "YUAN-01", signatory_npc_id: "npc_yuan_guilan", signatory_name: "袁桂兰", status: "rejected", current_version: 2, review_version: 1, review_reason: "请确认扶手。", audit_status: "not_required", contract_text: "搬离日：第83日\n交房日：第83日\n住房已核实设有扶手。", can_review: true, conversation_available: true, term_sheet: { cash_amount: 27, move_out_day: 83, housing_delivery_day: 83, transition_months: 12 } };
  const signed = { ...contract, contract_id: "c2", household_id: "YUAN-02", status: "signed", signed_day: 10, signed_hash: "NEVER_DISPLAY_HASH", contract_text: "原始签署正文 D83\n原始标点 ; unchanged", can_review: false };
  let legacy = { ...contract, contract_id: "c3", household_id: "YUAN-03", legacy_draft: true, can_review: false, legacy_versions: [{ version: 2, text: "旧约定：搬家协助与扶手保障。" }] };
  await page.route("**/api/backend/**", async route => {
    const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    let body: unknown = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
    else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
    else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "opening", story_day: 10, text: "安置会谈正在进行。", block_id: "d10_source_opening", scene_id: "C01_S12" }], cursor: 1 } };
    else if (endpoint.endsWith("/governance")) body = { governance_actions: [action], contracts: [contract, signed, legacy], contract_batches: [{ batch_id: "b1", representative_npc_id: "npc_yuan_guilan", status: "confirmed" }], resources: { resource_pools: [], budget_envelopes: { property_land: { available: 100 } } } };
    else if (endpoint.endsWith("/contracts/c1")) body = { contract };
    else if (endpoint.endsWith("/contracts/c2")) body = { contract: signed };
    else if (endpoint.endsWith("/contracts/c3")) body = { contract: legacy };
    else if (endpoint.endsWith("/contracts/c3/terms")) {
      expect(route.request().postDataJSON().acknowledge_legacy_text).toBe(true);
      legacy = { ...legacy, legacy_draft: false, current_version: 3, contract_text: "新方案：27万元。", can_review: true };
      body = { contract: legacy, state_version: ++state.state_version };
    }
    else if (endpoint.endsWith("/terms")) {
      if (++saveAttempts === 1) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "RESOURCE_INSUFFICIENT", message: "预算不足，请调整现金补偿。", details: { field_errors: { cash_amount: "现金补偿超过可用预算。" } } } }) });
        return;
      }
      if (saveAttempts === 2) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "ACTION_UNAVAILABLE", message: "请先继续本户会谈。", details: {} } }) });
        return;
      }
      writes.push(endpoint);
      contract = { ...contract, status: "draft", current_version: 3, term_sheet: { ...contract.term_sheet, cash_amount: 28 }, contract_text: "现金补偿：28万元\n搬离日：第83日\n交房日：第83日", review_reason: "", review_version: 0, review_history: [{ version: 1, reason: "请确认扶手。" }] } as typeof contract;
      body = { contract, state_version: ++state.state_version };
    } else if (endpoint.endsWith("/review")) {
      writes.push(endpoint);
      expect(route.request().postDataJSON().expected_contract_version).toBe(3);
      contract = { ...contract, status: "explanation_requested", review_version: 3, review_reason: "我想去看看房子。", can_review: false };
      body = { contract, state_version: ++state.state_version };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page.locator(".top-status .online")).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  await page.getByRole("button", { name: "继续办理合同", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".contract-body")).toHaveText(contract.contract_text);
  await expect(dialog.locator("textarea")).toHaveCount(0);
  await expect(dialog).not.toContainText("专业审校");
  await expect(dialog.getByText("请确认扶手。", { exact: true })).not.toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("contract-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("contract-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await dialog.getByRole("button", { name: /YUAN-02/ }).click();
  await expect(dialog.locator(".contract-body")).toHaveText(signed.contract_text);
  await expect(dialog).not.toContainText("NEVER_DISPLAY_HASH");
  await expect(dialog.getByRole("button", { name: "提交签约", exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: /YUAN-03/ }).click();
  await expect(dialog.getByRole("button", { name: "保存方案并预览合同", exact: true })).toBeDisabled();
  await dialog.getByText("旧版正文存档", { exact: true }).click();
  await expect(dialog.locator(".contract-body")).toHaveText(legacy.legacy_versions[0].text);
  await dialog.getByRole("checkbox", { name: /我已核对旧正文/ }).check();
  await expect(dialog.getByRole("button", { name: "保存方案并预览合同", exact: true })).toBeEnabled();
  await expect(dialog.locator('[data-tutorial-id="contract-submit"]')).toBeDisabled();
  await dialog.getByRole("button", { name: "保存方案并预览合同", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "提交签约", exact: true })).toBeEnabled();
  await expect(dialog.getByText("旧版正文存档", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: /YUAN-01/ }).click();
  await dialog.getByRole("button", { name: "修改方案", exact: true }).click();
  await dialog.locator('[name="cash_amount"]').fill("28");
  await dialog.locator('[name="cash_amount"]').fill("-1");
  await dialog.getByRole("button", { name: "保存方案并预览合同", exact: true }).click();
  await expect(dialog.getByRole("alert").filter({ hasText: "请检查方案中的输入" })).toBeVisible();
  expect(saveAttempts).toBe(0);
  await dialog.locator('[name="cash_amount"]').fill("28");
  await expect(dialog.locator('[data-tutorial-id="contract-submit"]')).toBeDisabled();
  page.once("dialog", prompt => prompt.dismiss());
  await dialog.getByRole("button", { name: "继续协商", exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[name="cash_amount"]')).toHaveValue("28");
  await dialog.getByRole("button", { name: "保存方案并预览合同", exact: true }).click();
  await expect(dialog.locator('label').filter({ has: page.locator('[name="cash_amount"]') })).toContainText("现金补偿超过可用预算。");
  await expect(dialog.locator('[name="cash_amount"]')).toHaveValue("28");
  await dialog.getByRole("button", { name: "保存方案并预览合同", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("请先继续本户会谈。");
  await dialog.getByRole("button", { name: "保存方案并预览合同", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "提交签约", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "提交签约", exact: true }).click();
  await expect(dialog).toContainText("对方的签约答复 · 方案第3版");
  await dialog.getByRole("button", { name: "继续协商", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(writes).toHaveLength(2);
});

for (const mode of ["governance", "conversation", "group"]) for (const width of [1366, 390]) test(`archive references and unread end-day guard ${mode} at ${width}`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 });
  let active = false;
  const writes: Record<string, unknown>[] = [];
  const state = { session_id: "references-ui", status: "active", state_version: 1, story: { day: 35 }, ledger: { action_points: { remaining: 8, daily_cap: 8 } } };
  const docs = [{ id: "meeting:hearing-1", title: "谭老六旧案听证记录", category: "meeting", status: "completed", body: "听证已完成，法审处理仍待落实。", version: 1, can_reference: true }, { id: "document:draft-1", title: "旧案处理草案", category: "document", status: "draft", body: "尚未签发。", can_reference: true }];
  await page.route("**/api/backend/**", async route => {
    const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    let body: Record<string, unknown> = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
    else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
    else if (endpoint.endsWith("/view")) body = { state, commands: { can_end_day: true, can_act: true }, feed: { items: [{ id: "opening-34", kind: "night", story_day: 34, text: "昨夜仍有情况需要说明。" }, { id: "opening-35-first", story_day: 35, text: "今天的材料需要先核对。" }, { id: "opening-35", story_day: 35, text: "今天继续核对各户诉求。" }], cursor: 2 } };
    else if (endpoint.endsWith("/reference-documents")) body = { documents: docs };
    else if (endpoint.endsWith("/governance")) body = { governance_actions: active && mode === "governance" ? [{ action_instance_id: "visit-tan", action_kind: "household_visit", status: "active", story_day: 35, target_ids: ["npc_tan_laoliu"], topic: "核对旧案处理", transcript: [] }] : [], meetings: [], archives: [], contracts: [], documents: [] };
    else if (endpoint.endsWith("/turn/stream") || endpoint.endsWith("/action/stream")) {
      writes.push(route.request().postDataJSON());
      await route.fulfill({ status: 200, contentType: "application/x-ndjson", body: '{"type":"complete","result":{}}\n\n' }); return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page.locator(".top-status .online")).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  await expect(page.getByRole("button", { name: "结束今日", exact: true })).toHaveCount(0);
  await expect(page.locator(".story-head")).toContainText("第 35 日");
  await page.getByRole("button", { name: "下一段", exact: true }).click();
  await expect(page.getByRole("button", { name: "结束今日", exact: true })).toHaveCount(2);
  await page.getByRole("button", { name: "上一段", exact: true }).click();
  await expect(page.getByRole("button", { name: "结束今日", exact: true })).toHaveCount(0);
  active = true;
  if (mode === "conversation") Object.assign(state, { active_conversation: { conversation_id: "regular-tan", opportunity_id: "talk-tan", npc_id: "npc_tan_laoliu", npc_name: "谭老六" } });
  if (mode === "group") Object.assign(state, { active_group_conversation: { conversation_id: "night-tan", phase: "active", participant_ids: ["npc_tan_laoliu"], initiator_npc_id: "npc_tan_laoliu", participant_states: [], transcript: [], agenda: "核对听证结果" } });
  await page.locator('[data-tutorial-id="nav-governance"]').click();
  await expect(page.getByRole("region", { name: "档案系统" })).toContainText("谭老六旧案听证记录");
  await page.getByText("谭老六旧案听证记录", { exact: false }).first().click();
  await expect(page.locator(".reference-body").first()).toContainText("法审处理仍待落实");
  await page.screenshot({ path: testInfo.outputPath(`archive-library-${width}.png`), fullPage: true });
  // Reload the session view to enter the active visit without changing any real save.
  await page.reload();
  await expect(page.locator(".top-status .online")).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  const input = page.locator('textarea[name="player_text"]');
  await input.fill("@听证");
  await expect(page.getByRole("option")).toHaveCount(1);
  await input.press("Enter");
  await expect(page.locator(".reference-tags")).toContainText("谭老六旧案听证记录");
  await page.getByRole("button", { name: "移除引用 谭老六旧案听证记录" }).click();
  await expect(page.locator(".reference-tags span")).toHaveCount(0);
  await input.fill("@听证"); await input.press("Enter");
  await input.fill("听证已经完成，还需要处理什么？");
  await page.screenshot({ path: testInfo.outputPath(`reference-selected-${width}.png`), fullPage: true });
  await page.locator('[data-tutorial-id="conversation-send"]').click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].reference_ids).toEqual(["meeting:hearing-1"]);
  await expect(page.locator(".reference-tags span")).toHaveCount(0);
  await input.fill("我继续了解要求。");
  await page.locator('[data-tutorial-id="conversation-send"]').click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).not.toHaveProperty("reference_ids");
  await page.screenshot({ path: testInfo.outputPath(`references-${width}.png`), fullPage: true });
});

test("reference audience refresh and immutable metadata in all conversation reviews", async ({ page }) => {
  let allowed = true;
  let reads = 0;
  const refs = [{ id: "meeting:record", title: "旧案听证记录", version: "old-version", status: "completed" }];
  const turn = { speaker_type: "player", text: "请查阅这份材料。", references: refs };
  const state = { session_id: "reference-review", status: "active", state_version: 1, story: { day: 35 }, ledger: { action_points: { remaining: 8, daily_cap: 8 } } };
  const action = { action_instance_id: "visit-1", action_kind: "household_visit", status: "active", story_day: 35, target_ids: ["npc_tan_laoliu"], topic: "旧案走访", transcript: [turn] };
  await page.route("**/api/backend/**", async route => {
    const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    let body: Record<string, unknown> = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
    else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
    else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "opening", story_day: 35, text: "继续核对各户诉求。" }], cursor: 1 } };
    else if (endpoint.endsWith("/reference-documents")) { reads++; body = { documents: [{ ...refs[0], category: "meeting", version: "new-version", body: "新版正文不应作为旧发言附件展示", can_reference: allowed, reference_unavailable_reason: allowed ? "" : "此文件不能向当前全部参会人披露" }] }; }
    else if (endpoint.endsWith("/governance")) body = { governance_actions: [action], meetings: [{ meeting_id: "old-meeting", story_day: 34, topic: "先前会议", transcript: [turn] }], archives: [], contracts: [], documents: [] };
    else if (endpoint.endsWith("/turn/stream")) { await route.fulfill({ status: 200, contentType: "application/x-ndjson", body: '{"type":"complete","result":{}}\n\n' }); return; }
    else if (endpoint.endsWith("/review")) body = { status: "active", group_conversation_timeline: [{ conversation_id: "old-group", story_day: 33, agenda: "夜间补充", transcript: [turn] }] };
    else if (endpoint.endsWith("/conversations")) body = { items: [{ conversation_id: "ordinary", npc_id: "npc_tan_laoliu", story_day: 32, transcript: [turn] }], next_cursor: null };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page.locator(".top-status .online")).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  await expect(page.locator(".governance-action-timeline .reference-attachments")).toContainText("当时版本 old-version");
  const input = page.locator('textarea[name="player_text"]');
  await input.fill("@旧案");
  await expect(page.getByRole("option")).toBeEnabled();
  const previousReads = reads;
  allowed = false; action.action_instance_id = "visit-2"; action.target_ids = ["npc_zhou_dashan"];
  await input.fill("转交下一场会谈。");
  await page.locator('[data-tutorial-id="conversation-send"]').click();
  await page.locator('[data-tutorial-id="nav-governance"]').click();
  await expect.poll(() => reads).toBeGreaterThan(previousReads);
  await page.locator(".reference-library summary").click();
  await expect(page.getByRole("button", { name: "在当前对话中引用" })).toBeDisabled();
  await expect(page.locator(".reference-library")).toContainText("此文件不能向当前全部参会人披露");
  await page.locator('[data-tutorial-id="nav-scene"]').click();
  await input.fill("@旧案");
  await expect(page.getByRole("option")).toBeDisabled();
  await input.press("Enter");
  await expect(page.locator(".reference-tags span")).toHaveCount(0);
  await page.locator('[data-tutorial-id="nav-review"]').click();
  const review = page.locator(".review-panel");
  for (const summary of await review.locator("details > summary").all()) await summary.click();
  await expect(review.locator(".reference-attachments")).toHaveCount(4);
  await expect(review).toContainText("当时版本 old-version");
  await expect(review).not.toContainText("new-version");
  await expect(review).not.toContainText("新版正文");
});

for (const household of ["HE-02", "YUAN-01"]) test(`contract followup attachment only for ${household}`, async ({ page }) => {
  const writes: Record<string, unknown>[] = [];
  const state = { session_id: "followup-ui", status: "active", state_version: 1, story: { day: 35 }, ledger: { action_points: { remaining: 8, daily_cap: 8 } } };
  const contract = { contract_id: "c1", batch_id: "b1", household_id: household, signatory_npc_id: "npc_he_jianguo", signatory_name: "何建军", status: "awaiting_terms", current_version: 0, conversation_available: true };
  await page.route("**/api/backend/**", async route => {
    const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    let body: Record<string, unknown> = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
    else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
    else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "opening", story_day: 35, text: "核对医疗保障。" }], cursor: 1 } };
    else if (endpoint.endsWith("/governance")) body = { governance_actions: [{ action_instance_id: "visit", action_kind: "household_visit", status: "active", target_ids: ["npc_he_jianguo"], transcript: [] }], contracts: [contract], contract_batches: [{ batch_id: "b1", representative_npc_id: "npc_he_jianguo", status: "confirmed" }], resources: { resource_pools: [] } };
    else if (endpoint.endsWith("/contracts/c1")) body = { contract };
    else if (endpoint.endsWith("/terms")) { writes.push(route.request().postDataJSON()); body = { contract, state_version: ++state.state_version }; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page.locator(".top-status .online")).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  await page.getByRole("button", { name: "继续办理合同", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('[name="cash_amount"]').fill("30");
  if (household === "HE-02") {
    await expect(dialog.locator('[name="medical_provider"]')).toHaveValue("");
    await dialog.locator('[name="medical_provider"]').fill("县医院");
    await dialog.locator('[name="recheck_interval_days"]').fill("30");
    await dialog.locator('[name="employment_receiver"]').fill("县就业服务中心");
    await dialog.locator('[name="medical_fee_arrangement"]').selectOption("allocated_medical_service");
  } else await expect(dialog.locator(".contract-followup-plan")).toHaveCount(0);
  await dialog.getByRole("button", { name: "保存方案并预览合同", exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  if (household === "HE-02") expect(writes[0].followup_plan).toEqual({ medical_provider: "县医院", recheck_interval_days: 30, employment_receiver: "县就业服务中心", medical_fee_arrangement: "allocated_medical_service" });
  else expect(writes[0]).not.toHaveProperty("followup_plan");
});

for (const failure of ["view", "governance", "panel"]) test(`saved operation recovers with reads only after ${failure} failure`, async ({ page }) => {
  let writes = 0;
  let failReads = true;
  let governanceReadsAfterWrite = 0;
  const state = { session_id: "saved-sync-ui", status: "active", state_version: 1, story: { day: 35 }, active_conversation: { conversation_id: "talk", opportunity_id: "op", npc_id: "npc_tan_laoliu", npc_name: "谭老六" }, ledger: { action_points: { remaining: 8, daily_cap: 8 } } };
  await page.route("**/api/backend/**", async route => {
    const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
    let body: Record<string, unknown> = {};
    if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
    else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
    else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
    else if (endpoint.endsWith("/action/stream")) {
      writes++; state.state_version++;
      await route.fulfill({ status: 200, contentType: "application/x-ndjson", body: JSON.stringify({ type: "complete", result: { visible_state: state } }) + "\n\n" }); return;
    }
    else if (endpoint.endsWith("/view")) {
      if (writes && failReads && failure === "view") { await route.fulfill({ status: 503, contentType: "application/json", body: '{"message":"视图暂不可用"}' }); return; }
      body = { state, commands: {}, feed: { items: [{ id: "opening", story_day: 35, text: "继续核对情况。" }], cursor: 1 } };
    }
    else if (endpoint.endsWith("/governance")) {
      if (writes) governanceReadsAfterWrite++;
      if (writes && failReads && (failure === "governance" || (failure === "panel" && governanceReadsAfterWrite >= 2))) { await route.fulfill({ status: 503, contentType: "application/json", body: '{"message":"治理面板暂不可用"}' }); return; }
      body = { governance_actions: [], meetings: [], archives: [], contracts: [], documents: [] };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page.locator(".top-status .online")).toHaveCount(1);
  await page.getByRole("button", { name: "进入游戏", exact: true }).click();
  await page.getByRole("button", { name: /开始新游戏/ }).click();
  if (failure === "panel") await page.locator('[data-tutorial-id="nav-governance"]').click();
  const input = page.locator('textarea[name="player_text"]');
  await input.fill("保存这一次明确回复。");
  await page.locator('[data-tutorial-id="conversation-send"]').click();
  await expect(page.locator(".saved-sync-recovery")).toContainText("操作已保存");
  await expect(page.getByRole("button", { name: "重新同步现场", exact: true })).toBeEnabled();
  await expect(input).toHaveValue("");
  expect(writes).toBe(1);
  await input.fill("同步前的新回复应保留。");
  await page.locator('[data-tutorial-id="conversation-send"]').click();
  await expect(input).toHaveValue("同步前的新回复应保留。");
  expect(writes).toBe(1);
  await page.getByRole("button", { name: "重新同步现场", exact: true }).click();
  await expect(page.getByRole("button", { name: "重新同步现场", exact: true })).toBeEnabled();
  expect(writes).toBe(1);
  failReads = false;
  await page.getByRole("button", { name: "重新同步现场", exact: true }).click();
  await expect(page.locator(".saved-sync-recovery")).toHaveCount(0);
  await expect(input).toHaveValue("同步前的新回复应保留。");
  expect(writes).toBe(1);
  await page.locator('[data-tutorial-id="conversation-send"]').click();
  await expect.poll(() => writes).toBe(2);
  await expect(input).toHaveValue("");
  await expect(page.locator(".saved-sync-recovery")).toHaveCount(0);
});
