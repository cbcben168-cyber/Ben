async(page)=>{
  const results=[];
  for(const code of ['SPY','QQQ','IWM','SOXX','SMH','SPY']){
    const input=page.getByRole('combobox',{name:'独立窗口观察标的',exact:true});
    if(await input.inputValue()!=='US.'+code){await input.evaluate(e=>e.scrollIntoView({block:'center'}));await input.locator('..').getByRole('button',{name:'Open',exact:true}).click();await page.getByRole('option',{name:'US.'+code,exact:true}).click();}
    await page.getByRole('region',{name:code+' 现在该怎么做',exact:true}).waitFor();
    await page.waitForTimeout(300);await page.getByRole('button',{name:'Stop',exact:true}).waitFor({state:'hidden'});
    await page.waitForFunction(code=>document.querySelectorAll('.st-key-answer-chart .js-plotly-plot').length===1&&document.querySelectorAll('.dash-summary').length===1&&document.querySelector('.st-key-answer-chart .js-plotly-plot')?._fullLayout?.uirevision?.startsWith('US.'+code+'-'),code);
    const result=await page.locator('.st-key-answer-chart .js-plotly-plot').evaluate(p=>({bars:p.data[0].x.length,last:p.data[0].x.at(-1),ema:p.data.filter(t=>t.meta?.kind==='historical_ema').map(t=>({name:t.name,last:t.y.at(-1)}))}));
    if(result.bars!==(code==='SMH'?86:84)||result.ema.length!==4)throw Error(code+' chart incomplete');
    if(!((await page.locator('.dash-summary').innerText()).includes('不能 · 暂无合格买卖点')))throw Error(code+' trading permission changed');
    if(await page.locator('[data-testid=stException]').count())throw Error('Page exception');results.push({symbol:code,...result});
  }
  return {url:page.url(),symbols:results,final_symbol:'SPY'};
}
