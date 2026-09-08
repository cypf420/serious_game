import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// UI transport fixture uses actual package prose. API/action/full-route behavior
// is independently exercised by backend tests; this is not a live-AI run.
const packageRoot = path.resolve('../../backend/content/packages/pkg_gameplay_v3');
const decisions = JSON.parse(fs.readFileSync(path.join(packageRoot, 'decisions.json'), 'utf8')).decisions;
const beats = JSON.parse(fs.readFileSync(path.join(packageRoot, 'story_beats.json'), 'utf8')).beats;

for (const width of [1440,390]) {
  test(`night transition and full consequence survive reading and reload at ${width}`, async ({page}, info) => {
    await page.setViewportSize({width,height:900});
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    const consequence = decisions.find((d: {decision_id:string}) => d.decision_id==='dp1_03').options[1].consequence;
    const night = beats.find((b: {story_day:number}) => b.story_day===46).night_blocks[0].text;
    const nextText = '次日清晨，你接着核对昨日留下的办理材料。';
    let ended = false;
    const state = {session_id:'story-integrity-ui',status:'active',state_version:1,story:{day:46},onboarding:{free_action_completed:true},ledger:{action_points:{remaining:3,daily_cap:3},budget:{available:8000},relocation:{signed:0,total:36}}};
    const all = [
      {cursor:1,story_day:46,kind:'consequence',presentation_phase:'consequence',text:consequence,content_instance_id:'test:consequence',scene_id:'C01_S02'},
      {cursor:2,story_day:46,kind:'night',presentation_phase:'night',text:night,content_instance_id:'test:night',scene_id:'C01_S02'},
      {cursor:3,story_day:47,kind:'narration',presentation_phase:'scene',text:nextText,content_instance_id:'test:next',scene_id:'C01_S02'},
    ];
    await page.route('**/api/backend/**',async route => {
      const url = new URL(route.request().url());
      const ep = url.pathname.replace(/^\/api\/backend/,'');
      let body: Record<string,unknown> = {};
      if(ep==='/health/ready') body={authentication_required:false,model_consent_required:false};
      else if(ep==='/api/ai/config') body={active:true,mode:'personal',model:'explicit-ui-fixture',endpoint:'https://fixture.invalid/v1'};
      else if(ep==='/api/game/session' && route.request().method()==='POST') body={session_id:state.session_id};
      else if(ep==='/api/game/sessions') body={sessions:[{session_id:state.session_id,status:'active',story_day:47,package_status:'published',loadable:true}]};
      else if(ep.endsWith('/end-day')) { ended=true; state.story.day=47;state.state_version++;body={state_version:state.state_version}; }
      else if(ep.endsWith('/view')) body={state,commands:{can_act:true,can_end_day:true},feed:{items:(ended?all:all.slice(0,1)).filter(i=>i.cursor>Number(url.searchParams.get('after')||0)),cursor:ended?3:1}};
      else if(ep.endsWith('/governance')) body={governance_actions:[],contracts:[],meetings:[]};
      else if(ep===`/api/game/session/${state.session_id}`) body={session_id:state.session_id};
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    });
    async function enter(){
      await expect(page.locator('.top-status .online')).toHaveCount(1);
      await page.getByRole('button',{name:'进入游戏',exact:true}).click();
      await page.getByRole('button',{name:/开始新游戏/}).click();
    }
    await page.goto('/');
    await enter();
    const paragraph=page.locator('.gal-dialogue > p');
    await expect(paragraph).toHaveText(consequence);
    await paragraph.scrollIntoViewIfNeeded();
    await page.screenshot({path:info.outputPath('complete-consequence.png'),fullPage:true});
    await page.getByRole('button',{name:'结束今日',exact:true}).first().click();
    await page.getByRole('dialog').getByRole('button',{name:'进入夜间结算',exact:true}).click();
    await expect(paragraph).toHaveText(night);
    await page.screenshot({path:info.outputPath('night-before-morning.png'),fullPage:true});
    await page.getByRole('button',{name:'下一段',exact:true}).click();
    await expect(paragraph).toHaveText(nextText);
    await page.reload();
    await expect(page.locator('.top-status .online')).toHaveCount(1);
    await page.getByRole('button',{name:'进入游戏',exact:true}).click();
    await page.getByRole('button',{name:/查看已有进度/}).click();
    await page.getByRole('button',{name:/进度一.*继续游戏/}).click();
    await expect(paragraph).toHaveText(nextText);
    await page.getByRole('button',{name:'上一段',exact:true}).click();
    await expect(paragraph).toHaveText(night);
    await page.getByRole('button',{name:'下一段',exact:true}).click();
    await expect(paragraph).toHaveText(nextText);
    await page.getByRole('button',{name:'剧情回看',exact:true}).click();
    await expect(page.getByRole('region',{name:'剧情回看'})).toContainText(consequence);
    expect(errors).toEqual([]);
  });
}

for (const width of [1440,390]) {
  test(`long prose and D84 ordering consequence reach their last character at ${width}`,async({page},info)=>{
    await page.setViewportSize({width,height:900});
    const decision=decisions.find((d:{decision_id:string})=>d.decision_id==='dp6_07');
    const longest=beats.flatMap((b:{opening_blocks:{text:string}[]})=>b.opening_blocks).map((b:{text:string})=>b.text).sort((a:string,b:string)=>b.length-a.length)[0];
    const consequence=decision.options.find((o:{option_id:string})=>o.option_id==='b_a_c_d_e').consequence;
    const state:Record<string,unknown> & { state_version: number }={session_id:'story-integrity-long',status:'active',state_version:1,story:{day:84},onboarding:{free_action_completed:true},ledger:{action_points:{remaining:3,daily_cap:3},budget:{available:8000},relocation:{signed:30,total:36}},pending_decision:{...decision,presentation_entry_id:'test:gate'}};
    let submitted=false;
    const feed=[
      {cursor:1,story_day:84,text:longest,kind:'narration',presentation_phase:'scene',content_instance_id:'test:long',scene_id:'C01_S02'},
      {cursor:2,story_day:84,text:decision.prompt,kind:'decision',presentation_phase:'decision',content_instance_id:'test:gate',scene_id:'C01_S02'},
      {cursor:3,story_day:84,text:consequence,kind:'consequence',presentation_phase:'consequence',content_instance_id:'test:sorted',scene_id:'C01_S02'},
    ];
    await page.route('**/api/backend/**',async route=>{
      const url=new URL(route.request().url()),ep=url.pathname.replace(/^\/api\/backend/,'');
      let body:Record<string,unknown>={};
      if(ep==='/health/ready')body={authentication_required:false,model_consent_required:false};
      else if(ep==='/api/ai/config')body={active:true,mode:'personal',model:'explicit-ui-fixture',endpoint:'https://fixture.invalid/v1'};
      else if(ep==='/api/game/session')body={session_id:state.session_id};
      else if(ep.endsWith('/action')){
        expect(route.request().postDataJSON().ordered_option_ids).toEqual(['b','a','c','d','e']);
        submitted=true;state.pending_decision=null;state.state_version++;
        body={state_version:state.state_version};
      }
      else if(ep.endsWith('/view'))body={state,commands:{can_act:true,can_end_day:submitted},feed:{items:feed.slice(0,submitted?3:2).filter(i=>i.cursor>Number(url.searchParams.get('after')||0)),cursor:submitted?3:2}};
      else if(ep.endsWith('/governance'))body={governance_actions:[],contracts:[],meetings:[]};
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.goto('/');
    await expect(page.locator('.top-status .online')).toHaveCount(1);
    await page.getByRole('button',{name:'进入游戏',exact:true}).click();
    await page.getByRole('button',{name:/开始新游戏/}).click();
    const paragraph=page.locator('.gal-dialogue > p');
    await expect(paragraph).toHaveText(longest);
    await paragraph.scrollIntoViewIfNeeded();
    const bottomVisible=await paragraph.evaluate(el=>{
      el.scrollTop=el.scrollHeight;
      const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
      let node:Node|null=null,next:Node|null;
      while((next=walker.nextNode()))node=next;
      if(!node?.textContent)return false;
      const range=document.createRange();range.setStart(node,node.textContent.length-1);range.setEnd(node,node.textContent.length);
      const rect=range.getBoundingClientRect(),box=el.getBoundingClientRect();
      return rect.bottom<=box.bottom+2 && rect.top>=box.top-2;
    });
    expect(bottomVisible).toBe(true);
    await page.screenshot({path:info.outputPath('long-paragraph-last-line.png'),fullPage:true});
    await page.getByRole('button',{name:'下一段',exact:true}).click();
    await page.getByRole('button',{name:'上移第2项',exact:true}).click();
    await page.getByRole('button',{name:'确认优先顺序',exact:true}).click();
    await expect(paragraph).toHaveText(consequence);
    expect(submitted).toBe(true);
    await page.screenshot({path:info.outputPath('d84-complete-order.png'),fullPage:true});
  });
}
