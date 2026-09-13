import { expect, test } from "@playwright/test";

// Isolated UI fixtures: no real saves or model calls.
for (const viewport of [{ width: 1366, height: 768 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }]) {
  for (const [npcId, npcName] of [["npc_wu_xiuying", "吴秀英"], ["npc_yuan_guilan", "袁桂兰"]]) {
    test(`${npcName} full dialogue and references ${viewport.width}`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      await page.addInitScript(() => {
        const account = "sandbox_feedback16";
        localStorage.setItem("qingjiang-sandbox-account", account);
        localStorage.setItem(`qingjiang:tutorial:v1:${account}`, JSON.stringify({ version: 1, auto: false, chapters: {} }));
      });
      const errors: string[] = [];
      page.on("pageerror", error => errors.push(error.message));
      const state = {
        session_id: "feedback16", status: "active", state_version: 1, story: { day: 10 },
        onboarding: { free_action_completed: true },
        active_governance_action: { action_instance_id: "talk", action_kind: "household_visit", status: "active", story_day: 10, target_ids: [npcId], topic: "逐户核对已保存合同、补偿和安置安排" },
        ledger: { action_points: { remaining: 6, daily_cap: 8 }, budget: { available: 7800 }, relocation: { signed: 8, total: 36 } },
      };
      const transcript = Array.from({ length: 20 }, (_, index) => ({
        speaker_type: index % 3 === 0 ? "player" : "npc", npc_id: npcId, npc_name: npcName, turn_id: `turn-${index}`,
        text: `第${index + 1}轮首行。` + "请逐项核对补偿方案、安置房交付节点和保障条款，保存合同后再交由本人决定。".repeat(8) + `第${index + 1}轮末行。`,
        references: index === 0 ? [{ id: "document:fixture", title: "柳林村搬迁补偿及困难户安置保障方案的完整引用标题", version: 3, status: "published" }] : [],
      }));
      await page.route("**/api/backend/**", async route => {
        const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
        let body: unknown = {};
        if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
        else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
        else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
        else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "fixture", story_day: 10, text: "会谈进行中。" }], cursor: 1 } };
        else if (endpoint.endsWith("/governance")) body = { governance_actions: [{ ...state.active_governance_action, transcript }], meetings: [], contracts: [], contract_batches: [] };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      });
      await page.goto("/");
      await expect(page.locator(".top-status .online")).toHaveCount(1);
      await page.getByRole("button", { name: "进入游戏", exact: true }).click();
      await page.getByRole("button", { name: /开始新游戏/ }).click();
      const timeline = page.locator(".governance-action-timeline");
      await expect(timeline).toBeVisible();
      if (!process.env.FEEDBACK16_BASELINE) {
        expect(await page.locator(".metric-strip strong").evaluateAll(elements => elements.every(el => el.scrollWidth <= el.clientWidth))).toBe(true);
      }
      const measure = () => page.evaluate(() => {
        const box = (selector: string) => { const r = document.querySelector(selector)!.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height, width: r.width }; };
        return { meta: box(".gal-scene-meta"), timeline: box(".governance-action-timeline"), input: box(".governance-bar"), stage: box(".governance-gal-stage"), reference: box(".reference-attachments"), article: box(".governance-action-timeline article") };
      });
      await timeline.evaluate(element => { element.scrollTo({ top: 0, behavior: "instant" }); });
      await page.screenshot({ path: testInfo.outputPath("first-line.png"), fullPage: true, animations: "disabled" });
      const first = await measure();
      await timeline.evaluate(element => {
        const reference = element.querySelector(".reference-attachments")!;
        element.scrollTo({ top: reference.getBoundingClientRect().top - element.getBoundingClientRect().top + element.scrollTop, behavior: "instant" });
      });
      await page.screenshot({ path: testInfo.outputPath("references.png"), fullPage: true, animations: "disabled" });
      if (!process.env.FEEDBACK16_BASELINE) {
        const reference = await measure();
        expect(reference.reference.top).toBeGreaterThanOrEqual(reference.timeline.top - 1);
        expect(reference.reference.bottom).toBeLessThanOrEqual(reference.timeline.bottom);
      }
      await timeline.evaluate(element => { element.scrollTo({ top: element.scrollHeight, behavior: "instant" }); });
      await page.screenshot({ path: testInfo.outputPath("last-line.png"), fullPage: true, animations: "disabled" });
      await testInfo.attach("geometry", { body: JSON.stringify({ viewport, first, last: await measure() }, null, 2), contentType: "application/json" });
      if (!process.env.FEEDBACK16_BASELINE) {
        expect(first.timeline.top).toBeGreaterThanOrEqual(first.meta.bottom);
        expect(first.timeline.bottom).toBeLessThanOrEqual(first.input.top);
        expect(first.timeline.bottom).toBeLessThanOrEqual(first.stage.bottom);
        const lineHeight = await timeline.locator("article p").first().evaluate(el => parseFloat(getComputedStyle(el).lineHeight));
        expect(first.timeline.height).toBeGreaterThan(2 * lineHeight);
        expect(first.reference.width).toBeGreaterThan(first.article.width * .65);
        expect(await timeline.locator("article").count()).toBe(20);
        expect(await timeline.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(2);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(errors).toEqual([]);
        const portrait = await page.locator(".governance-gal-stage .gal-portrait").boundingBox();
        expect(portrait!.height).toBeGreaterThan(50);
        await page.addStyleTag({ content: ".governance-action-timeline article p { font-size: 18px; } .governance-gal-stage .gal-scene-meta strong { font-size: 20px; }" });
        await timeline.evaluate(el => { el.scrollTo({ top: el.scrollHeight, behavior: "instant" }); });
        const enlarged = await measure();
        expect(enlarged.timeline.top).toBeGreaterThanOrEqual(enlarged.meta.bottom);
        expect(enlarged.timeline.bottom).toBeLessThanOrEqual(enlarged.input.top);
        expect(await timeline.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(2);
        await page.screenshot({ path: testInfo.outputPath("enlarged-last-line.png"), fullPage: true, animations: "disabled" });
      }
    });
  }
}

for (const viewport of [{ width: 1366, height: 768 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }]) {
  test(`guide invitation and currency explanation ${viewport.width}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.addInitScript(() => localStorage.setItem("qingjiang-sandbox-account", "sandbox_feedback16_guide"));
    const state = { session_id: "feedback16-guide", status: "active", state_version: 1, story: { day: 2 },
      ledger: { action_points: { remaining: 8, daily_cap: 8 }, budget: { available: 8000 } },
      onboarding: { free_action_completed: false } };
    await page.route("**/api/backend/**", async route => {
      const endpoint = new URL(route.request().url()).pathname.replace(/^\/api\/backend/, "");
      let body: unknown = {};
      if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
      else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
      else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
      else if (endpoint.endsWith("/view")) body = { state, commands: { can_act: true }, feed: { items: [{ id: "fixture", story_day: 2, text: "今日工作已开放。" }], cursor: 1 } };
      else if (endpoint.endsWith("/governance")) body = { governance_actions: [], meetings: [], contracts: [] };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("/");
    await expect(page.locator(".top-status .online")).toHaveCount(1);
    await page.getByRole("button", { name: "进入游戏", exact: true }).click();
    await page.getByRole("button", { name: /开始新游戏/ }).click();
    const invitation = page.getByRole("complementary", { name: "赴任指南邀请" });
    await expect(invitation).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("guide-invitation.png"), animations: "disabled" });
    if (!process.env.FEEDBACK16_BASELINE) {
      await expect(invitation).toHaveCSS("background-color", "rgb(41, 37, 30)");
      const buttons = await invitation.locator("button").all();
      const left = (await buttons[0].boundingBox())!, right = (await buttons[1].boundingBox())!;
      expect(Math.abs(left.y - right.y)).toBeLessThan(1);
      expect(left.height).toBe(right.height);
      const title = (await invitation.locator("b").boundingBox())!;
      expect(title.y + title.height).toBeLessThan(left.y);
    }
    await invitation.getByRole("button", { name: "开始赴任指南" }).click();
    const card = page.locator(".tutorial-popover");
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "下一步", exact: true }).click();
    await card.getByRole("button", { name: "下一步", exact: true }).click();
    await expect(card).toContainText("日期、阶段与精力");
    if (!process.env.FEEDBACK16_BASELINE) {
      await card.locator("summary").click();
      await expect(card).toContainText("开放时间、兑换范围和具体规则以百晓生网站公告为准");
      await expect.poll(async () => { const box = (await card.boundingBox())!; return box.y + box.height; }).toBeLessThanOrEqual(viewport.height);
    }
    await page.screenshot({ path: testInfo.outputPath("guide-metrics.png"), animations: "disabled" });
  });
}
