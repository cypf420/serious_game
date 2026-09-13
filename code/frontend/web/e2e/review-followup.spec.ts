import { expect, test } from "@playwright/test";

// Isolated UI fixtures: no real saves or model calls.
for (const viewport of [{ width: 1366, height: 768 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }]) {
  for (const hasContract of [false, true]) for (const [npcId, npcName] of [["npc_wu_xiuying", "吴秀英"], ["npc_yuan_guilan", "袁桂兰"]]) {
    test(`${npcName} full dialogue and references ${viewport.width} contract=${hasContract}`, async ({ page }, testInfo) => {
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
        if(endpoint.endsWith('/turn/stream')) {
          if(route.request().postDataJSON().player_text==='测试错误提示'){
            await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:{code:'RESOURCE_INSUFFICIENT',message:'测试提示：请核对已经保存的本户合同。'}})});return;
          }
          transcript.push({speaker_type:'npc',npc_id:npcId,npc_name:npcName,turn_id:`turn-${transcript.length}`,text:'新增回复首行。'+'完整新增说明。'.repeat(80)+'新增回复末行。',references:[]});state.state_version++;
          await route.fulfill({status:200,contentType:'application/x-ndjson',body:JSON.stringify({type:'complete',result:{state_version:state.state_version}})+'\n'});return;
        }
        let body: unknown = {};
        if (endpoint === "/health/ready") body = { authentication_required: false, model_consent_required: false };
        else if (endpoint === "/api/ai/config") body = { active: true, mode: "personal", model: "fixture", endpoint: "https://fixture.invalid/v1" };
        else if (endpoint === "/api/game/session") body = { session_id: state.session_id };
        else if (endpoint.endsWith("/view")) body = { state, commands: {}, feed: { items: [{ id: "fixture", story_day: 10, text: "会谈进行中。" }], cursor: 1 } };
        else if(endpoint.endsWith('/reference-documents')) body={documents:[{id:'document:fixture',title:'柳林村补偿与安置完整核对材料',category:'document',status:'published',body:'完整正文。'.repeat(100),version:3,can_reference:true}]};
        else if (endpoint.endsWith("/governance")) body = { governance_actions: [{ ...state.active_governance_action, transcript }], meetings: [], contracts: hasContract ? [{contract_id:"c",batch_id:"b",household_id:"H-01",signatory_npc_id:npcId,status:"draft",current_version:1}] : [], contract_batches: hasContract ? [{batch_id:"b",representative_npc_id:npcId,status:"confirmed"}] : [] };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      });
      await page.goto("/");
      await expect(page.locator(".top-status .online")).toHaveCount(1);
      await page.getByRole("button", { name: "进入游戏", exact: true }).click();
      await page.getByRole("button", { name: /开始新游戏/ }).click();
      await expect(page.locator('.rail')).toBeVisible();
      await expect(page.locator('.governance-action-timeline')).toBeVisible();
      if(viewport.width > 780) {
        const nav=await page.locator('.rail').evaluate(el=>{
          const r=el.getBoundingClientRect().toJSON();const buttons=[...el.querySelectorAll('button')].map(b=>b.getBoundingClientRect().toJSON());
          return {height:r.height,topGap:buttons[0].top-r.top,bottomGap:r.bottom-buttons.at(-1)!.bottom,width:r.width,buttonWidth:buttons[0].width,occupied:buttons.reduce((n,b)=>n+b.height,0)};
        });
        await testInfo.attach('navigation-raw',{body:JSON.stringify(nav),contentType:'application/json'});
        expect(nav.topGap).toBeLessThanOrEqual(6);expect(nav.bottomGap).toBeLessThanOrEqual(6);
        expect(nav.occupied/nav.height).toBeGreaterThan(.93);expect(nav.buttonWidth/nav.width).toBeGreaterThan(.90);
        await page.locator('.rail button').last().focus();await expect(page.locator('.rail button').last()).toBeFocused();
        await testInfo.attach('navigation',{body:JSON.stringify(nav),contentType:'application/json'});
      }
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
      for(const button of await page.locator('.governance-bar > div > button').all()) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      if(viewport.width>780){
        expect(first.input.height).toBeLessThanOrEqual(90);
        const oldHeight=viewport.width===1366?124.8125:431.8125;
        expect(first.timeline.height-oldHeight).toBeGreaterThanOrEqual(45);
        await testInfo.attach('composer-gain',{body:JSON.stringify({input:first.input.height,output:first.timeline.height,baselineOutput:oldHeight,gain:first.timeline.height-oldHeight}),contentType:'application/json'});
      }
      const input=page.locator('.governance-bar textarea');
      await input.fill('核对'.repeat(500));await expect(input).toHaveValue('核对'.repeat(500));
      await expect(input).toBeFocused();
      await input.fill('@');
      await expect(page.locator('.reference-candidates')).toBeVisible();
      await page.screenshot({path:testInfo.outputPath('reference-picker.png'),fullPage:true});
      const withPicker=await measure();
      if(viewport.width>780)expect(withPicker.input.height).toBeLessThanOrEqual(90);
      await input.press('Enter');
      await expect(page.locator('.reference-tags')).toContainText('柳林村补偿与安置完整核对材料');
      await page.screenshot({path:testInfo.outputPath('selected-reference.png'),fullPage:true});
      await page.getByRole('button',{name:'移除引用 柳林村补偿与安置完整核对材料'}).click();
      await input.fill('');
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
        await timeline.evaluate(el=>el.scrollTo({top:0,behavior:'instant'}));
        await expect.poll(()=>timeline.evaluate(el=>el.scrollTop)).toBeLessThan(1);
        await input.fill('测试新增回复');await page.locator('[data-tutorial-id="conversation-send"]').click();
        await expect(timeline.locator('article')).toHaveCount(21);
        await expect.poll(()=>timeline.evaluate(el=>el.scrollTop)).toBeLessThan(1);
        await page.screenshot({path:testInfo.outputPath('history-not-jumped.png'),fullPage:true});
        await page.getByRole('button',{name:'有新回复',exact:true}).click();
        await expect.poll(()=>timeline.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(2);
        await input.fill('测试底部跟随');await page.locator('[data-tutorial-id="conversation-send"]').click();
        await expect(timeline.locator('article')).toHaveCount(22);
        await expect.poll(()=>timeline.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(2);
        await timeline.evaluate(el=>el.scrollTo({top:0,behavior:'instant'}));
        await expect.poll(()=>timeline.evaluate(el=>el.scrollTop)).toBeLessThan(1);
        await timeline.evaluate(el=>new Promise<void>(resolve=>{
          el.addEventListener('scroll',()=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())),{once:true});
          el.scrollTo({top:el.scrollHeight,behavior:'instant'});
        }));
        await expect.poll(()=>timeline.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(2);
        await input.fill('测试手动到底跟随');await page.locator('[data-tutorial-id="conversation-send"]').click();
        await expect(timeline.locator('article')).toHaveCount(23);
        await expect.poll(()=>timeline.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(2);
        if(hasContract){
          await input.fill('测试错误提示');await page.locator('[data-tutorial-id="conversation-send"]').click();
          await expect(page.locator('.governance-inline-notice')).toContainText('测试提示');
          await expect(page.getByRole('button',{name:'继续办理合同',exact:true})).toBeVisible();
          const noticed=await measure();expect(noticed.timeline.height).toBeGreaterThan(60);
          expect(noticed.timeline.bottom).toBeLessThanOrEqual(noticed.input.top);
          await page.screenshot({path:testInfo.outputPath('contract-notice.png'),fullPage:true});
        }

      }
    });
  }
}
