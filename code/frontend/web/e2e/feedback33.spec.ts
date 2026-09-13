import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {dialogueSegments} from '../app/lib/dialogue-segments';

for (const width of [1366,1920,390]) {
  test(`requested panels and decision guidance ${width}`,async({page},info)=>{
    await page.setViewportSize({width,height:width===1920?1080:width===390?844:768});
    await page.addInitScript(()=>{
      localStorage.setItem('qingjiang-sandbox-account','feedback33');
      localStorage.setItem('qingjiang:tutorial:v1:feedback33',JSON.stringify({version:1,auto:false,chapters:{}}));
    });
    const person={npc_id:'npc_liu_san',name:'刘三',contact_state:'known',discovery_state:'encountered'};
    await page.route('**/api/backend/**',async route=>{
      const path=new URL(route.request().url()).pathname;
      let body:unknown={};
      if(path.endsWith('/health/ready'))body={authentication_required:false,model_consent_required:false};
      else if(path.endsWith('/api/ai/config'))body={active:true,mode:'personal',model:'fixture',endpoint:'https://fixture.invalid/v1'};
      else if(path.endsWith('/api/game/session'))body={session_id:'feedback33'};
      else if(path.endsWith('/view'))body={state:{session_id:'feedback33',status:'active',story:{day:34},state_version:1,
        pending_decision:{decision_id:'dp3_03',presentation_entry_id:'gate',options:[{option_id:'a',text:'当场戳破政策口径那一条。',available:false,unavailable_reason:'条件不足'}]},
        ledger:{action_points:{remaining:8,daily_cap:8},budget:{available:7000},relocation:{signed:0,total:36}}},commands:{},feed:{cursor:1,items:[{id:'gate',content_instance_id:'gate',kind:'decision',presentation_phase:'decision',text:'你准备如何处理？',story_day:34}]}};
      else if(path.endsWith('/opportunities'))body={people:[person],person_actions:[{npc_id:person.npc_id,npc_name:person.name,variant_id:'field_visit',action_id:'household_visit',name:'了解本户情况',available:true,cost_action_points:1}],opportunities:[],relationship_edges:[]};
      else if(path.endsWith('/desk'))body={mission:{title:'督办任务',summary:'核对本户材料与办理进度。'.repeat(16)},dossiers:[]};
      else if(path.endsWith('/knowledge'))body={facts:[{title:'核查材料',text:'已经取得的材料正文。'.repeat(35),source_label:'本次查档',use_hint:'核对相关事实'}]};
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.goto('/');await expect(page.locator('.top-status .online')).toHaveCount(1);
    await page.getByRole('button',{name:'进入游戏',exact:true}).click();
    await page.getByRole('button',{name:/开始新游戏/}).click();
    await expect(page.locator('.decision-option')).toContainText('需先取得政策原件或罗健留底材料');
    await expect(page.locator('.decision-option button')).toBeDisabled();
    await page.screenshot({path:info.outputPath('decision.png'),fullPage:true});
    for(const [id,selector,size] of [['opportunities','.person-action > button',0],['desk','.desk-panel p',14],['knowledge','.knowledge-panel p',14]] as const){
      await page.locator(`.rail [data-tutorial-id="nav-${id}"]`).click();
      await expect(page.locator(selector).first()).toBeVisible();
      if(size)expect(await page.locator(selector).first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBe(size);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:info.outputPath(`${id}.png`),fullPage:true});
    }
  });
}

for(const width of [1366,1920,390]) for(const [day,block,speaker] of [[20,'d20_arrival','刘三'],[22,'d22_shi_arrival','石文斌'],[32,'d32_ledger','罗健']] as const){
  test(`source dialogue ${day} ${width}`,async({page},info)=>{
    const prose=JSON.parse(readFileSync('E:/严肃游戏/output/feedback17-33-20260913/restored-prose.json','utf8'));
    const source={id:block,blockId:block,kind:'narration',text:prose[block]};
    const segments=dialogueSegments(source);
    expect(segments.map(s=>s.text).join('')).toBe(source.text);
    await page.setViewportSize({width,height:width===1920?1080:width===390?844:768});
    await page.addInitScript(()=>{localStorage.setItem('qingjiang-sandbox-account','portrait33');localStorage.setItem('qingjiang:tutorial:v1:portrait33',JSON.stringify({version:1,auto:false,chapters:{}}));});
    let writes=0;
    await page.route('**/api/backend/**',async route=>{
      const path=new URL(route.request().url()).pathname;
      let body:unknown={};
      if(path.endsWith('/health/ready'))body={authentication_required:false,model_consent_required:false};
      else if(path.endsWith('/api/ai/config'))body={active:true,mode:'personal',model:'fixture',endpoint:'https://fixture.invalid/v1'};
      else if(path.endsWith('/api/game/session'))body={session_id:'portrait33'};
      else if(path.endsWith('/view'))body={state:{session_id:'portrait33',status:'active',state_version:1,story:{day},pending_decision:{decision_id:'test-gate',presentation_entry_id:'gate',options:[{option_id:'a',text:'测试选择',available:true}]},ledger:{action_points:{remaining:8,daily_cap:8},budget:{available:7000},relocation:{signed:0,total:36}}},commands:{can_end_day:false},feed:{cursor:2,items:[{id:block,content_instance_id:`block:${block}`,block_id:block,kind:'narration',text:source.text,story_day:day},{id:'gate',content_instance_id:'gate',kind:'decision',presentation_phase:'decision',text:'你准备如何处理？',story_day:day}]}};
      else if(route.request().method()!=='GET')writes++;
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.goto('/');await expect(page.locator('.top-status .online')).toHaveCount(1);
    await page.getByRole('button',{name:'进入游戏',exact:true}).click();await page.getByRole('button',{name:/开始新游戏/}).click();
    const next=page.getByRole('button',{name:'下一段',exact:true});
    for(let i=0;i<segments.length;i++){
      await expect(page.locator('.decision-option')).toHaveCount(0);
      const portrait=page.locator('.gal-stage > .gal-portrait');
      if(segments[i].speaker){
        await expect(page.locator('.gal-dialogue > header > span').first()).toHaveText(segments[i].speaker!);
        await expect(page.locator(`.gal-portrait[aria-label="${segments[i].speaker}立绘"]`)).toBeVisible();
        if(segments[i].speaker===speaker)await page.screenshot({path:info.outputPath(`${speaker}.png`),fullPage:true});
      } else await expect(portrait).toHaveCount(0);
      if(i===1){
        await page.getByRole('button',{name:'上一段',exact:true}).click();
        await expect(page.locator('.decision-option')).toHaveCount(0);
        await next.click();
      }
      await next.click();
    }
    await expect(page.locator('.decision-option')).toBeVisible();
    expect(writes).toBe(0);
    await page.screenshot({path:info.outputPath('decision-after-reading.png'),fullPage:true});
  });
}

for(const width of [1366,1920,390]) for(const mode of ['contract','units','restore']) {
 test(`readonly details and reading ${mode} ${width}`,async({page},info)=>{
  await page.setViewportSize({width,height:width===1920?1080:width===390?844:768});
  await page.addInitScript(()=>{localStorage.setItem('qingjiang-sandbox-account','extra33');localStorage.setItem('qingjiang:tutorial:v1:extra33',JSON.stringify({version:1,auto:false,chapters:{}}));});
  const source='第一段旁白。\n刘三：「我来核对本户材料。」\n最后一段旁白。';
  const action={action_instance_id:'a33',action_kind:mode==='units'?'leadership_meeting':'household_visit',status:'active',target_ids:['npc_yuan_guilan'],topic:'核对材料',transcript:[]};
  const contract={contract_id:'c33',batch_id:'b33',household_id:'YUAN-01',signatory_npc_id:'npc_yuan_guilan',signatory_name:'袁桂兰',status:'draft',current_version:2,contract_text:'已保存合同正文。',can_review:true,conversation_available:true,term_sheet:{cash_amount:27,move_out_day:83,housing_delivery_day:83,transition_months:12}};
  const breakdown={source:'受控费率明细',rows:[{label:'合法住宅',quantity:100,unit:'平方米',rate:0.1,amount:10}],rounding_adjustment:0,suggested_base_total:10,saved_base_amount:25,saved_transition_amount:2,saved_total:27,transition_population:2,transition_rate:0.03};
  let writes=0;
  await page.route('**/api/backend/**',async route=>{
   const path=new URL(route.request().url()).pathname;let body:unknown={};
   if(path.endsWith('/health/ready'))body={authentication_required:false,model_consent_required:false};
   else if(path.endsWith('/api/ai/config'))body={active:true,mode:'personal',model:'fixture',endpoint:'https://fixture.invalid/v1'};
   else if(path.endsWith('/api/game/session'))body={session_id:'extra33'};
   else if(path.endsWith('/view'))body={state:{session_id:'extra33',status:'active',state_version:1,story:{day:32},ledger:{action_points:{remaining:8,daily_cap:8},budget:{available:7000},relocation:{signed:0,total:36}}},commands:{can_end_day:true},feed:{cursor:1,items:[{id:'b',block_id:'test',kind:'narration',story_day:32,text:source}]}};
   else if(path.endsWith('/governance'))body={governance_actions:mode==='restore'?[]:[action],contracts:[contract],contract_batches:[{batch_id:'b33',representative_npc_id:'npc_yuan_guilan',status:'confirmed'}],meetings:[{meeting_id:'m33',action_instance_id:'a33',topic:'核对材料',participant_ids:['npc_yuan_guilan'],transcript:[{speaker_type:'npc',npc_id:'npc_yuan_guilan',text:'请明确资源授权。'}]}],resources:{resource_pools:[{resource_id:'service',name:'服务名额',capacity:8,unit:'人次'}],budget_envelopes:{property_land:{available:100,capacity:100}}}};
   else if(path.endsWith('/contracts/c33'))body={contract:{...contract,compensation_breakdown:breakdown}};
   else if(route.request().method()!=='GET')writes++;
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  const enter=async()=>{await page.goto('/');await expect(page.locator('.top-status .online')).toHaveCount(1);await page.getByRole('button',{name:'进入游戏',exact:true}).click();await page.getByRole('button',{name:/开始新游戏/}).click();};
  await enter();
  if(mode==='contract'){
   await page.getByRole('button',{name:'继续办理合同',exact:true}).click();
   await page.locator('.compensation-breakdown summary').click();
   await expect(page.locator('.compensation-breakdown')).toContainText('100 平方米 × 0.1 万元/平方米 = 10.0000 万元');
   await expect(page.locator('.compensation-breakdown')).toContainText('总额 27 万元');
   await page.locator('.compensation-breakdown').scrollIntoViewIfNeeded();
  } else if(mode==='units'){
   await page.locator('[data-tutorial-id="conversation-finish"]').click();
   await expect(page.locator('.resource-limit-input em').filter({hasText:'人次'})).toBeVisible();
   await expect(page.locator('.resource-limit-input em').filter({hasText:'万元'}).first()).toBeVisible();
   const input=page.locator('.resource-limit-input input').first();
   await expect(input).toHaveValue('');await input.fill('0');await expect(input).toHaveValue('0');
   await expect(input).toHaveAttribute('max','8');
   await page.locator('.resolution-resources').scrollIntoViewIfNeeded();
  } else {
   const next=page.getByRole('button',{name:'下一段',exact:true});
   await expect(page.getByRole('button',{name:'结束今日',exact:true})).toHaveCount(0);
   await next.click();await expect(page.locator('.gal-dialogue > header > span').first()).toHaveText('刘三');
   await enter(); // Restore original block position; display sub-position safely restarts.
   await expect(page.locator('.gal-dialogue')).toContainText('第一段旁白。');
   await expect(page.getByRole('button',{name:'结束今日',exact:true})).toHaveCount(0);
   await next.click();await next.click();
   await expect(page.getByRole('button',{name:'结束今日',exact:true}).first()).toBeVisible();
  }
  expect(writes).toBe(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`${mode}.png`),fullPage:true});
 });
}
