async(page)=>{
  const choose=async(label,value)=>{const input=page.getByRole('combobox',{name:label,exact:true});if(await input.inputValue()===value)return;await page.keyboard.press('Escape');await input.evaluate(e=>e.scrollIntoView({block:'center'}));await input.locator('..').getByRole('button',{name:'Open',exact:true}).click();await page.getByRole('option',{name:value,exact:true}).click();await page.waitForTimeout(400);await page.getByRole('button',{name:'Stop',exact:true}).waitFor({state:'hidden'});};
  await choose('数据模式','历史回放');await choose('历史交易日期（纽约）','2026-10-28');
  await page.waitForFunction(()=>document.querySelector('main').innerText.includes('历史回放 · 富途原生日K归档 · 日K · 数据截至 2026-10-28'));
  const evidence=page.locator('details').filter({has:page.locator('summary').filter({hasText:'详细证据与历史分析图层'})});
  if(await evidence.getAttribute('open')===null)await evidence.locator(':scope > summary').click();
  await page.waitForFunction(()=>[...document.querySelectorAll('.js-plotly-plot')].filter(p=>(p.data||[]).some(t=>t.type==='candlestick')).length>=2);
  const charts=await page.evaluate(()=>[...document.querySelectorAll('.js-plotly-plot')].flatMap(p=>(p.data||[]).filter(t=>t.type==='candlestick').map(t=>({bars:t.x.length,last:[...t.x].map(String).sort().at(-1)}))));
  if(charts.length<2||charts.some(t=>t.last.slice(0,10)>'2026-10-28'))throw Error('Legacy evidence sees future data');
  const history=page.locator('details').filter({has:page.locator('summary').filter({hasText:'历史结构证据与原始时间'})});await history.locator(':scope > summary').click();
  await page.getByText('历史观察与当前交易资格分别检查。',{exact:true}).waitFor();
  await page.screenshot({path:'C:/Users/cbcbe/Documents/ChatGPT/ict_trade_assistant/output/playwright/8506-v0441-accepted-replay-evidence.png',animations:'disabled'});
  await history.locator(':scope > summary').click();await evidence.locator(':scope > summary').click();await choose('数据模式','最新已保存数据');
  await page.getByText('当前使用默认参数，与Baseline一致。',{exact:true}).waitFor();
  const lab=page.locator('details').filter({has:page.locator('summary').filter({hasText:'调整分析因子 · v0.4.4.1'})});await lab.locator(':scope > summary').click();await page.locator('main').evaluate(e=>e.scrollTop=0);
  return {url:page.url(),replay_date:'2026-10-28',legacy_fold:true,historical_fold:true,charts,restored_latest:true};
}
