import {test,expect} from '@playwright/test';
for(const width of [1366,1920,390]) test(`HE02 followup text bounds ${width}`,async({page},info)=>{
 await page.setViewportSize({width,height:width===1920?1080:width===390?844:768});
 await page.addInitScript(()=>{localStorage.setItem('qingjiang-sandbox-account','review28');localStorage.setItem('qingjiang:tutorial:v1:review28',JSON.stringify({version:1,auto:false,chapters:{}}));});
 const contract={contract_id:'c28',batch_id:'b28',household_id:'HE-02',signatory_npc_id:'npc_he_tiezhu',signatory_name:'何铁柱',status:'draft',current_version:1,contract_text:'合同正文保持。',can_review:true,conversation_available:true,term_sheet:{cash_amount:30}};
 await page.route('**/api/backend/**',async route=>{
  const path=new URL(route.request().url()).pathname;let body:unknown={};
  if(path.endsWith('/health/ready'))body={authentication_required:false,model_consent_required:false};
  else if(path.endsWith('/api/ai/config'))body={active:true,mode:'personal',model:'fixture',endpoint:'https://fixture.invalid/v1'};
  else if(path.endsWith('/api/game/session'))body={session_id:'review28'};
  else if(path.endsWith('/view'))body={state:{session_id:'review28',status:'active',state_version:1,story:{day:30},ledger:{action_points:{remaining:8,daily_cap:8}}},commands:{},feed:{cursor:1,items:[{id:'b',kind:'narration',story_day:30,text:'检查附件字数。'}]}};
  else if(path.endsWith('/governance'))body={governance_actions:[{action_instance_id:'a28',action_kind:'household_visit',status:'active',target_ids:['npc_he_tiezhu'],topic:'核对本户合同',transcript:[]}],contracts:[contract],contract_batches:[{batch_id:'b28',representative_npc_id:'npc_he_tiezhu',status:'confirmed'}]};
  else if(path.endsWith('/contracts/c28'))body={contract};
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto('/');await expect(page.locator('.top-status .online')).toHaveCount(1);await page.getByRole('button',{name:'进入游戏',exact:true}).click();await page.getByRole('button',{name:/开始新游戏/}).click();
 await page.getByRole('button',{name:'继续办理合同',exact:true}).click();await page.getByRole('button',{name:'修改方案',exact:true}).click();
 for(const field of ['medical_provider','employment_receiver']){
  const input=page.locator(`[name="${field}"]`);await expect(input).toHaveAttribute('maxlength','120');
  await input.pressSequentially('甲'.repeat(121));await expect(input).toHaveValue('甲'.repeat(120));
 }
 await page.locator('.contract-followup-plan').scrollIntoViewIfNeeded();await page.screenshot({path:info.outputPath('followup-120.png'),fullPage:true});
});
