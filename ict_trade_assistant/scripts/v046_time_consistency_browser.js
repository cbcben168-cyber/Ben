async (page) => {
  if(new URL(page.url()).port!=='8526')throw new Error('Only isolated preview 8526');
  const result={checks:[],layouts:[]};
  const check=(ok,name)=>{if(!ok)throw new Error(name);result.checks.push(name)};
  const select=async(label,value)=>{
    await page.locator('[data-testid=stMain]').evaluate(e=>e.scrollTop=0);
    const input=page.getByRole('combobox',{name:label,exact:true});
    await input.scrollIntoViewIfNeeded();
    await input.click();await input.fill(value);
    await page.getByRole('option',{name:value,exact:true}).click().catch(e=>{throw new Error(label+' -> '+value+': '+e.message)});
  };
  const cards=()=>page.locator('.dash-candidate').evaluateAll(items=>items.map(e=>({
    code:e.querySelector('h4').textContent.trim(),text:e.innerText,
    daily:e.querySelector('[data-period=daily]').innerText,
    hourly:e.querySelector('[data-period=hourly]').innerText,
    dailyStatus:e.querySelector('[data-period=daily]').dataset.status,
    hourlyStatus:e.querySelector('[data-period=hourly]').dataset.status})));
  const waitDates=async(day,hourStatus)=>page.waitForFunction(({day,hourStatus})=>{
    const items=[...document.querySelectorAll('.dash-candidate')];
    return items.length===15&&items.every(e=>e.querySelector('[data-period=daily]')?.innerText.includes(day)&&
      (['VEA','IEFA','BND'].includes(e.querySelector('h4').textContent.trim())?
       e.querySelector('[data-period=hourly]')?.dataset.status==='REJECTED':
       e.querySelector('[data-period=hourly]')?.dataset.status===hourStatus));
  },{day,hourStatus});
  await page.locator('.dash-candidate').nth(14).waitFor();
  await page.keyboard.press('Escape');
  await page.locator('[data-testid=stMain]').evaluate(e=>e.scrollTop=0);
  await page.getByText('真实归档基线',{exact:true}).click();
  await page.setViewportSize({width:2560,height:1440});
  await waitDates('2026-11-06','PASS');
  result.baseline=await cards();
  for(const item of result.baseline){
    check(item.daily.includes('日K最后完成：2026-11-06'),'baseline '+item.code+' daily date');
    if(item.hourlyStatus==='PASS'){
      check(item.hourly.includes('1H最后完成：2026-11-06')&&item.hourly.includes('2026-11-09'),'baseline '+item.code+' independent hourly basis');
    }else check(item.hourly.includes('60分钟汇总与同批日K不一致'),'baseline '+item.code+' actual rejection');
    check(item.text.includes('价格尺度未获统一认证'),'baseline '+item.code+' cross basis warning');
  }
  await page.locator('.st-key-focus-grid').screenshot({path:'output/playwright/v046-time-consistency/baseline-landscape-cards.png'});
  await page.locator('[data-testid=stMain]').evaluate(e=>e.scrollTop=0);
  await page.getByText('日K合成更新至11月9日',{exact:true}).click();
  await waitDates('2026-11-09','STALE');
  result.mismatch=await cards();
  for(const item of result.mismatch){
    check(item.daily.includes('复权估值日：2026-11-10'),'mismatch '+item.code+' daily valuation');
    if(item.hourlyStatus==='STALE'){
      check(item.hourly.includes('1H最后完成：2026-11-06')&&item.hourly.includes('复权估值日：2026-11-09'),'mismatch '+item.code+' hourly date and valuation');
      check(item.text.includes('1H历史资料已过期')&&!item.text.includes('1H合格'),'mismatch '+item.code+' stale not qualified');
    }else check(item.hourly.includes('60分钟汇总与同批日K不一致'),'mismatch '+item.code+' rejection unchanged');
  }
  await select('数据周期','1小时');
  await page.waitForFunction(()=>{
    const p=document.querySelector('.st-key-answer-chart .js-plotly-plot');
    return document.querySelectorAll('.st-key-answer-chart .js-plotly-plot').length===1&&p?._fullData?.[0]?.name==='1H';
  });
  const main=await page.locator('.dash-summary').innerText();
  check(main.includes('日K最后完成：2026-11-09')&&main.includes('1H最后完成：2026-11-06'),'main shows independent dates');
  check(main.includes('数据太旧不能判断')&&main.includes('1H历史资料已过期'),'main uses selected 1H freshness');
  const traces=await page.locator('.st-key-answer-chart .js-plotly-plot').evaluate(p=>p._fullData.map(t=>({name:t.name,close:t.close?.at?.(-1),points:t.x?.length})));
  check(traces[0].points===630&&traces[0].close===735.29,'real SPY 1H price retained after simulated daily update');
  check(!traces.some(t=>/人工计划|历史入场|历史结构/.test(t.name)),'no cross-basis price overlays');
  check((await page.locator('.dash-action').innerText()).includes('跨周期价格尺度未获统一认证'),'no executable cross-period risk reward');
  for(const [width,height,name,cols,rows] of [[2560,1440,'landscape',5,3],[1440,2560,'portrait',3,5]]){
    await page.setViewportSize({width,height});
    await page.locator('[data-testid=stMain]').evaluate(e=>e.scrollTop=0);
    await page.waitForTimeout(250);
    const layout=await page.evaluate(()=>{
      const items=[...document.querySelectorAll('.dash-candidate')].map(e=>e.getBoundingClientRect());
      return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,scale:visualViewport.scale,zoom:getComputedStyle(document.documentElement).zoom,
        columns:new Set(items.map(r=>Math.round(r.x))).size,rows:new Set(items.map(r=>Math.round(r.y))).size,
        overflow:document.documentElement.scrollWidth>innerWidth,exceptions:document.querySelectorAll('[data-testid=stException]').length};
    });
    check(layout.columns===cols&&layout.rows===rows,name+' grid '+cols+'x'+rows);
    check(layout.dpr===1&&layout.scale===1&&layout.zoom==='1'&&!layout.overflow&&layout.exceptions===0,name+' 100% and no overflow/exceptions');
    result.layouts.push(layout);
    await page.screenshot({path:'output/playwright/v046-time-consistency/'+name+'-simulated-main.png'});
    await page.locator('.st-key-focus-grid').screenshot({path:'output/playwright/v046-time-consistency/'+name+'-simulated-cards.png'});
  }
  await select('数据模式','历史回放');await select('历史交易日期（纽约）','2026-11-06');
  await waitDates('2026-11-06','PASS');
  result.replay=await cards();
  check(result.replay.filter(c=>c.hourlyStatus==='PASS').every(c=>!c.text.includes('1H历史资料已过期')),'replay ignores today and synthetic future daily bar');
  await select('数据周期','日K');
  await page.waitForFunction(()=>document.querySelector('.st-key-answer-chart .js-plotly-plot')?._fullData?.[0]?.name==='1D'&&document.querySelector('.st-key-answer-chart .js-plotly-plot')._fullData[0].x.length===90);
  check(true,'replay excludes synthetic Nov9 candle');
  return result;
}
