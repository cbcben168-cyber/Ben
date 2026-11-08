async(page)=>{
  const panel=()=>page.locator('details').filter({has:page.locator('summary').filter({hasText:'调整分析因子 · v0.4.4.1'})});
  const slider=label=>page.getByRole('slider',{name:new RegExp(label)});
  const idle=async()=>{await page.waitForTimeout(300);await page.getByRole('button',{name:'Stop',exact:true}).waitFor({state:'hidden'});await page.waitForFunction(()=>['EMA短期周期','EMA长期周期','ATR计算周期','横盘EMA距离阈值','候选关键价距离'].every(label=>document.querySelectorAll('input[aria-label="'+label+'"]').length===1)&&[...document.querySelectorAll('button')].filter(b=>b.textContent.trim()==='恢复默认').length===1&&document.querySelectorAll('table').length===2);};
  const table=()=>panel().locator('table').evaluateAll(tables=>tables.map(t=>Object.fromEntries([...t.querySelectorAll('tr')].slice(1).map(tr=>[...tr.querySelectorAll('th,td')].map(c=>c.textContent.trim())).map(r=>[r[0],r.slice(1)]))));
  const settled=async()=>{await idle();await page.waitForFunction(()=>{
    const plot=document.querySelector('.st-key-answer-chart .js-plotly-plot');const table=[...document.querySelectorAll('table')][1];if(!plot||!table)return false;
    return [['EMA短期周期','短期EMA'],['EMA长期周期','长期EMA']].every(([label,field])=>{
      const span=document.querySelector('input[aria-label="'+label+'"]').value;
      const trace=plot.data.find(t=>t.name==='实验EMA'+span);const row=[...table.querySelectorAll('tr')].find(tr=>tr.firstElementChild?.textContent.trim()===field);
      return trace&&row&&Math.abs(trace.y.at(-1)-Number(row.children[2].textContent.trim()))<1e-6;
    });
  });};
  await idle();
  if(!await slider('EMA短期周期').isVisible())await panel().locator(':scope > summary').click();
  await page.waitForFunction(()=>[...document.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent.includes('调整分析因子'))?.getBoundingClientRect().height>1000);
  const defaults=async()=>{await page.getByRole('button',{name:'恢复默认',exact:true}).click();await page.getByText('当前使用默认参数，与Baseline一致。',{exact:true}).waitFor();await settled();};
  const results=[];
  for(const [label,field,input] of [['EMA短期周期','短期EMA',5],['EMA长期周期','长期EMA',35],['ATR计算周期','ATR',7],['横盘EMA距离阈值','横盘阈值余量（ATR）',.1]]){
    await defaults();const before=await table();
    await slider(label).focus();await slider(label).press('Home');await settled();
    await page.waitForFunction(field=>{const row=[...document.querySelectorAll('table')][1]?.querySelectorAll('tr');const r=[...(row||[])].find(tr=>tr.firstElementChild?.textContent.trim()===field);return r&&r.children[1].textContent!==r.children[2].textContent;},field);
    const after=await table();if(before[1][field][0]===after[1][field][1])throw Error(label+' did not recompute');
    let chart_endpoint=null;
    if(label.startsWith('EMA')){
      const trace=await page.locator('.st-key-answer-chart .js-plotly-plot').evaluate((plot,name)=>{const t=plot.data.find(t=>t.name===name);return t?{name:t.name,last:t.y.at(-1)}:null;},'实验EMA'+input);
      if(!trace||Math.abs(trace.last-Number(after[1][field][1]))>1e-6)throw Error(label+' chart mismatch');chart_endpoint=trace;
    }
    results.push({symbol:'SPY',parameter:label,input,field,original:before[1][field][0],experiment:after[1][field][1],judgments:after[0],chart_endpoint});
    await defaults();const restored=await table();if(JSON.stringify(before)!==JSON.stringify(restored))throw Error(label+' did not restore');
  }
  const data=await page.locator('.st-key-answer-chart .js-plotly-plot').evaluate(p=>p.data.filter(t=>t.meta?.kind==='historical_ema').map(t=>({name:t.name,y:t.y})));
  if(JSON.stringify(data[0].y)!==JSON.stringify(data[2].y)||JSON.stringify(data[1].y)!==JSON.stringify(data[3].y))throw Error('Baseline curves do not overlap');
  if(!((await page.locator('.factor-active').innerText()).includes('Baseline（原始参数）')))throw Error('Wrong active status');
  await panel().screenshot({path:'C:/Users/cbcbe/Documents/ChatGPT/ict_trade_assistant/output/playwright/8506-v0441-accepted-restored-baseline.png',animations:'disabled'});
  return {url:page.url(),factors:results,restored:true};
}
