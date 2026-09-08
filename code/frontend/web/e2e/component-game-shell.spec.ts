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
      npc_id: person.npc_id, npc_name: person.name, variant_id: "field_visit", action_id: "household_visit", name: "现场走访",
      cost_action_points: 1, resource_cost_mode: "none", resource_costs: [], available: true,
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
      else if (endpoint.endsWith("/opportunities")) body = { people: [person], person_actions: [descriptor], opportunities: [], relationship_edges: [] };
      else if (endpoint.endsWith("/governance")) body = { governance_actions: active ? [action] : [], meetings: [],
        contracts: [], contract_batches: [], active_contract_preparation: active ? preparation : null };
      else if (endpoint.endsWith("/governance/actions") && method === "POST") {
        writes.push(endpoint);
        expect(route.request().postDataJSON().target_ids).toEqual([person.npc_id]);
        expect(route.request().postDataJSON().variant_id).toBe("field_visit");
        active = true;
        state.state_version++;
        state.ledger.action_points.remaining = 7;
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
    await page.getByRole("button", { name: "发起行动", exact: true }).click();
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
  const input = page.getByRole("textbox", { name: "继续询问或说明" });
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
