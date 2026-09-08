import {expect,test} from '@playwright/test';

// Genuine game HTTP API on an isolated in-memory server; only AI setup display
// is stubbed. Narrative/view/action/history are never intercepted or fabricated.
for(const width of [1440,390])for(const [day,did,oid] of [[5,'dp1_03','b'],[10,'ev1_03','a'],[31,'dp3_01','d'],[56,'dp4_07','a'],[58,'dp4_09','a'],[84,'dp6_07','a_b_c_d_e']] as const){
  test(`real API D${day} full consequence and reload at ${width}`,async({page,request},info)=>{
    await page.setViewportSize({width,height:900});
    const broadcast=page.getByRole('dialog').filter({has:page.getByRole('heading',{name:'云溪县十日督办播报',exact:true})});
    await page.addLocatorHandler(broadcast,async()=>{await broadcast.getByRole('button',{name:'关闭',exact:true}).click();});
    const account=`story-real-${day}-${width}`,headers={'X-Account-ID':account};
    await page.addInitScript(id=>localStorage.setItem('qingjiang-sandbox-account',id),account);
    await page.route('**/api/backend/api/ai/config',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({active:true,mode:'personal',model:'offline-test-double',endpoint:'https://fixture.invalid/v1'})}));
    const listed=await request.get('http://127.0.0.1:8107/api/game/sessions',{headers});
    expect(listed.ok()).toBe(true);
    const sid=(await listed.json()).sessions[0].session_id;
    const before=await(await request.get(`http://127.0.0.1:8107/api/game/session/${sid}/view`,{headers})).json();
    expect(before.state.pending_decision.decision_id).toBe(did);
    await page.goto('/');
    await expect(page.locator('.top-status .online')).toHaveCount(1);
    await page.getByRole('button',{name:'进入游戏',exact:true}).click();
    await page.getByRole('button',{name:/查看已有进度/}).click();
    await page.getByRole('button',{name:/进度一.*继续游戏/}).click();
    const gate=day===84?page.getByRole('button',{name:'确认优先顺序',exact:true}):page.locator('.decision-options button').filter({hasText:before.state.pending_decision.options.find((o:{option_id:string})=>o.option_id===oid).text});
    for(let i=0;i<30 && !(await gate.count());i++)await page.getByRole('button',{name:'下一段',exact:true}).click();
    await expect(gate).toBeVisible();
    const actionResponse=page.waitForResponse(r=>r.url().endsWith('/action')&&r.request().method()==='POST');
    await gate.click();
    const completed=await actionResponse;
    expect(completed.status(),await completed.text()).toBe(200);
    const paragraph=page.locator('.gal-dialogue > p');
    const after=await(await request.get(`http://127.0.0.1:8107/api/game/session/${sid}/view?after=${before.feed.cursor}`,{headers})).json();
    const outcome=after.feed.items.find((i:{kind:string,decision_id:string})=>i.kind==='consequence'&&i.decision_id===did);
    expect(outcome).toBeTruthy();
    await expect(paragraph).toHaveText(outcome.text);
    await paragraph.scrollIntoViewIfNeeded();
    await page.screenshot({path:info.outputPath('actual-api-consequence.png'),fullPage:true});
    await page.reload();
    await expect(page.locator('.top-status .online')).toHaveCount(1);
    await page.getByRole('button',{name:'进入游戏',exact:true}).click();
    await page.getByRole('button',{name:/查看已有进度/}).click();
    await page.getByRole('button',{name:/进度一.*继续游戏/}).click();
    await expect(paragraph).toHaveText(outcome.text);
  });
}
