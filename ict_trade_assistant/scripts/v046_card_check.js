async (page) => {
  if(new URL(page.url()).port!=='8526')throw new Error('Only isolated 8526');
  const items=await page.locator('.dash-candidate').evaluateAll(cards=>cards.map(card=>({
    code:card.querySelector('h4').textContent.trim(),
    close:Number(card.innerText.match(/最近收盘\s+([\d.]+)/)[1]),
    region:card.innerText.match(/历史区域\s+([^\n]+)/)[1],
    hourly:card.innerText.includes('1H合格')
  })));
  if(items.length!==15)throw new Error('15 cards required');
  const results=[];
  for(const item of items){
    await page.getByRole('button',{name:'查看图表 · '+item.code,exact:true}).click();
    await page.waitForFunction(code=>{
      const actions=document.querySelectorAll('.dash-action');
      return actions.length===1&&actions[0].querySelector('h3').textContent.startsWith(code+'｜');
    },item.code).catch(e=>{throw new Error(item.code+' action: '+e.message)});
    if(item.hourly){
      await page.waitForFunction(close=>{
        const plots=document.querySelectorAll('.st-key-answer-chart .js-plotly-plot');
        return plots.length===1&&plots[0]._fullData?.[0]?.name==='1H'&&
          Math.abs(plots[0]._fullData[0].close.at(-1)-close)<1e-8;
      },item.close).catch(e=>{throw new Error(item.code+' hourly close '+item.close+': '+e.message)});
    }else{
      await page.getByText(/尚无已验收1小时历史资料/).first().waitFor();
      await page.waitForFunction(()=>document.querySelectorAll('.st-key-answer-chart .js-plotly-plot').length===0);
    }
    const detail=await page.locator('.dash-action').innerText();
    if(!detail.replace(/\s+/g,'').includes(item.region.replace(/\s+/g,'')))throw new Error(item.code+' region mismatch');
    if(!detail.includes('实时资格关闭')||!detail.includes('合格交易目标 · 未具备条件'))throw new Error('trading lock');
    if(await page.getByRole('combobox',{name:'独立窗口观察标的',exact:true}).inputValue()!=='US.'+item.code)throw new Error('selection mismatch');
    results.push({code:item.code,close:item.close,region:item.region,hourly:item.hourly,selection:true,detail:true});
  }
  await page.getByRole('button',{name:'查看图表 · SMH',exact:true}).click();
  await page.getByRole('region',{name:'SMH 现在怎么看',exact:true}).waitFor();
  return {count:results.length,results};
}
