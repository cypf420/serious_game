import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
for(const width of [1366,1920,390]) test(`relationship reasons after completed event ${width}`,async({page},info)=>{
 const event=JSON.parse(readFileSync('E:/严肃游戏/output/review-followup-20260913/relationship-event.json','utf8'));let phase='before';let reads=0;
 await page.setViewportSize({width,height:width===1920?1080:width===390?844:768});
 await page.addInitScript(()=>{localStorage.setItem('qingjiang-sandbox-account','review32');localStorage.setItem('qingjiang:tutorial:v1:review32',JSON.stringify({version:1,auto:false,chapters:{}}));});
 await page.route('**/api/backend/**',async route=>{
  const path=new URL(route.request().url()).pathname;let body:any={};
  if(path.endsWith('/health/ready'))body={authentication_required:false,model_consent_required:false};
  else if(path.endsWith('/api/ai/config'))body={active:true,mode:'personal',model:'fixture',endpoint:'https://fixture.invalid/v1'};
  else if(path.endsWith('/api/game/session'))body={session_id:'review32'};
  else if(path.endsWith('/view'))body={state:{session_id:'review32',status:'active',state_version:1,story:{day:2},ledger:{action_points:{remaining:8,daily_cap:8}}},commands:{},feed:{cursor:1,items:[{id:'scene',kind:'narration',story_day:2,text:'会谈前后关系核查。'}]}};
  else if(path.endsWith('/opportunities')){body=event[phase];reads++;}
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto('/');await expect(page.locator('.top-status .online')).toHaveCount(1);await page.getByRole('button',{name:'进入游戏',exact:true}).click();await page.getByRole('button',{name:/开始新游戏/}).click();
 const nav=page.locator('.rail [data-tutorial-id="nav-opportunities"]');await nav.click();
 const wu=page.locator('.card-list.people > article').filter({has:page.getByRole('heading',{name:'吴秀英',exact:true})});
 await wu.getByText('近期关系变化依据',{exact:true}).click();await expect(wu).toContainText('尚无直接互动改变态度');
 await page.screenshot({path:info.outputPath('relationship-before.png'),fullPage:true});
 await page.locator('.rail [data-tutorial-id="nav-scene"]').click();phase='after';await nav.click();
 await wu.getByText('近期关系变化依据',{exact:true}).click();await expect(wu).toContainText('回应使对方更愿意合作');await expect(wu).toContainText('缓解了对方');
 await wu.locator('.relationship-reasons p').last().scrollIntoViewIfNeeded();await expect(wu.locator('.relationship-reasons p').last()).toBeInViewport();
 expect(reads).toBeGreaterThanOrEqual(2);await expect(page.locator('.card-list.people')).not.toContainText('顾克明');
 await expect(wu).not.toContainText('trust_score');await page.screenshot({path:info.outputPath('relationship-after.png'),fullPage:true});
});
