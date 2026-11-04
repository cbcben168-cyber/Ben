/* 独立无头浏览器；只操作本程序的两个会话，不提交任何用户表单。 */
const fs = require('fs');
const path = require('path');
const [out, deadlineText, modulePath, executablePath, openTimestamp] = process.argv.slice(2);
const { chromium } = require(modulePath);
const deadline = Number(deadlineText) * 1000;
const log = value => fs.appendFileSync(path.join(out, 'browser.jsonl'), JSON.stringify({at:new Date().toISOString(), ...value})+'\n');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
let browser;
let stopping = false;
const stop = () => Date.now() >= deadline || fs.existsSync(path.join(out,'STOP'));
const watchdog = setTimeout(() => { stopping=true; browser?.close().finally(()=>process.exit(0)); }, Math.max(1, deadline-Date.now()+5000));

async function observe(page, symbol, portrait) {
  await page.locator('.st-key-decision').waitFor({timeout:25000});
  const value = await page.evaluate(() => {
    const rect = k => document.querySelector('.st-key-'+k)?.getBoundingClientRect().toJSON();
    const live = [...document.querySelectorAll('input[type=checkbox]')].filter(e=>e.getAttribute('aria-label')?.includes('实时ICT'));
    return {clock:document.body.innerText.match(/◈ ICT 交易工作台 V2 · [^\n]+/)?.[0],
      title:document.querySelector('.st-key-decision h3')?.textContent,
      exceptions:document.querySelectorAll('[data-testid=stException]').length,
      overflow:document.documentElement.scrollWidth>innerWidth,
      panels:Object.fromEntries(['radar','chart','decision','plans','alerts'].map(k=>[k,rect(k)])),
      auto:document.querySelector('input[aria-label="自动刷新行情（编辑备注时请关闭）"]')?.checked,
      liveViolation:live.length!==1 || live.some(e=>e.checked||!e.disabled),
      period1H:document.querySelector('.st-key-chart input[type=radio][value="1"]')?.checked,
      candidateLabels:[...document.querySelectorAll('.st-key-radar button')].map(e=>e.innerText).filter(t=>/^\d · /.test(t)),
      decision:document.querySelector('.st-key-decision')?.innerText,
      health:document.querySelector('input[aria-label="独立窗口观察标的"]')?.value,
      width:innerWidth,height:innerHeight};
  });
  const p=value.panels;
  const layout=Object.values(p).every(Boolean) && (portrait
    ? p.radar.bottom<=p.chart.top+2 && Math.abs(p.chart.y-p.decision.y)<3
    : p.radar.x<p.chart.x && p.chart.x<p.decision.x && Math.abs(p.chart.y-p.decision.y)<3);
  const symbols=value.candidateLabels.map(t=>t.split(' · ')[1]);
  value.topUnique=new Set(symbols).size===symbols.length && symbols.length<=4;
  value.ok=!!(value.title?.startsWith(symbol) && !value.exceptions && !value.overflow && !value.liveViolation && value.auto && value.period1H && layout && value.topUnique);
  value.layoutQualified=layout;
  return value;
}

async function checkCandidate(page,symbol){
  const candidate=page.locator('.st-key-radar button').filter({hasText:new RegExp('^\\d · '+symbol+' · ')}).first();
  if(!(await candidate.count()))return {candidateChecked:false,candidateViolation:false};
  const text=await candidate.innerText();
  await candidate.focus();await candidate.press('Enter');
  await page.waitForTimeout(750);
  const decision=await page.locator('.st-key-decision').innerText();
  return {candidateChecked:true,candidateViolation:!decision.includes(text.split(' · ')[2].replace(/（[^）]*历史）/g,''))};
}

(async()=>{
  browser=await chromium.launch({headless:true,executablePath});
  const pages=[];
  for(const [symbol,width,height] of [['SPY',2560,1440],['QQQ',1440,2560]]){
    const context=await browser.newContext({viewport:{width,height}, timezoneId:'America/New_York'});
    const page=await context.newPage();
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://127.0.0.1:8501',{waitUntil:'domcontentloaded',timeout:20000});
    await page.locator('.st-key-decision').waitFor({timeout:30000});
    // 用本页面实测可访问标签定位，无跨会话共享选股。
    const settings=page.getByText('设置与数据诊断',{exact:true});
    await settings.click();
    const select=page.getByRole('combobox',{name:'独立窗口观察标的',exact:true});
    if(symbol!=='SPY'){
      await select.focus();
      await select.press('Control+A');
      await select.pressSequentially('US.'+symbol,{delay:80});
      await select.press('ArrowDown');
      await select.press('Enter');
      await page.locator('.st-key-decision h3').filter({hasText:symbol+' · '}).waitFor({timeout:10000});
    }
    const auto=page.getByRole('checkbox',{name:'自动刷新行情（编辑备注时请关闭）',exact:true});
    if(!(await auto.isChecked())){await auto.focus();await auto.press('Space');}
    await page.waitForTimeout(1000);
    // 候选点击仅改变会话选择，不提交备注/计划/参数。
    pages.push({page,symbol,portrait:width<height,errors,initialClock:null,previousClock:null,refreshProven:false});
  }
  let index=0;
  while(!stop()){
    for(const item of pages){
      try{
        const candidateResult=await checkCandidate(item.page,item.symbol);
        const value=await observe(item.page,item.symbol,item.portrait);
        item.initialClock??=value.clock;
        if(item.initialClock && value.clock && item.initialClock!==value.clock)item.refreshProven=true;
        const screenshot=path.join(out,`browser-${String(index).padStart(3,'0')}-${item.symbol}.png`);
        await item.page.screenshot({path:screenshot,fullPage:true,timeout:10000});
        const dom=path.join(out,`browser-${String(index).padStart(3,'0')}-${item.symbol}.txt`);
        fs.writeFileSync(dom,await item.page.locator('body').innerText());
        log({...value, symbol:item.symbol,screenshot,dom,errors:item.errors,
          ...candidateResult,
          refreshProven:item.refreshProven,ok:value.ok && !item.errors.length && !candidateResult.candidateViolation});
      }catch(error){log({ok:false,symbol:item.symbol,error:error.message});}
    }
    index++;
    // 开盘后前5分钟每15秒，其余每5分钟；预检阶段也保存一次60秒刷新证据。
    const epoch=Date.now();
    const open=Number(openTimestamp)*1000;
    const interval=(epoch>=open && epoch<=open+300000)?15000:(index===1?65000:300000);
    const until=Date.now()+interval;
    while(!stop()&&Date.now()<until)await wait(Math.min(1000,until-Date.now()));
  }
})().catch(error=>{if(!stopping){log({ok:false,error:error.stack});process.exitCode=2;}}).finally(async()=>{
  clearTimeout(watchdog);
  await browser?.close();
});
