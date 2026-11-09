async (page) => {
  if (new URL(page.url()).port !== '8526') throw new Error('Only isolated preview 8526');
  const result = {checks:[], symbols:[], layouts:[]};
  const check=(ok,label)=>{if(!ok)throw new Error(label);result.checks.push(label);};
  const select=async(label,value)=>{
    const box=page.getByRole('combobox',{name:label,exact:true});
    if(await box.inputValue()===value)return;
    await box.fill(value);await page.getByRole('option',{name:value,exact:true}).click();
  };
  const chart=()=>page.locator('.st-key-answer-chart .js-plotly-plot').last();
  const traces=()=>chart().evaluate(el=>el._fullData.map(t=>({name:t.name,type:t.type,x:Array.from(t.x||[]),
    y:t.y?Array.from(t.y):null,close:t.close?Array.from(t.close):null,meta:t.meta||null})));
  await page.locator('.dash-candidate').nth(14).waitFor();
  check(await page.locator('.dash-candidate').count()===15,'15 real watch cards');
  await select('数据周期','1小时');
  for(const code of ['SMH','SPY','QQQ','IWM','SOXX']){
    await select('独立窗口观察标的','US.'+code);
    await page.getByRole('region',{name:code+' 现在怎么看',exact:true}).waitFor();
    await page.waitForFunction(()=>{
      const plot=document.querySelector('.st-key-answer-chart .js-plotly-plot');
      return plot?.data?.[0]?.name==='1H'&&plot.data[0].x.length===630;
    });
    await page.getByRole('button',{name:'Stop',exact:true}).waitFor({state:'hidden'});
    const expectedEMA={SMH:474.23055851221784,SPY:743.9551667116001,QQQ:665.4338788743127,IWM:275.52503257433136,SOXX:140.1052615982399};
    await page.waitForFunction(expected=>{
      const plots=document.querySelectorAll('.st-key-answer-chart .js-plotly-plot');
      if(plots.length!==1)return false;
      const trace=plots[0]._fullData?.find(t=>t.name==='实验EMA20');
      return trace&&Math.abs(trace.y.at(-1)-expected)<1e-9;
    },expectedEMA[code]);
    const data=await traces();
    check(data[0].type==='candlestick'&&data[0].x.length===630,code+' native 630 candles');
    check(data.filter(t=>t.meta?.kind==='historical_ema').length===2,code+' hourly EMA20/50');
    check(!data.some(t=>t.name?.startsWith('人工计划')),code+' no unverified plan overlay');
    check((await page.locator('.dash-action').innerText()).includes('合格交易目标 · 未具备条件'),code+' trading lock');
    check((await page.locator('.dash-action').innerText()).includes('前交易日'),code+' independent daily references');
    result.symbols.push({code,traces:data.map(t=>({name:t.name,points:t.x.length,last:t.y?.at(-1),lastClose:t.close?.at(-1)}))});
  }
  await select('独立窗口观察标的','US.BND');
  await page.getByText(/尚无已验收1小时历史资料/).first().waitFor();
  check(await page.getByRole('button',{name:'切换至日K',exact:true}).isVisible(),'failed hourly has explicit daily fallback');
  await page.getByRole('button',{name:'切换至日K',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.st-key-answer-chart .js-plotly-plot')?.data?.[0]?.name==='1D');
  check((await traces())[0].x.length===90,'BND daily survives hourly failure');
  await select('独立窗口观察标的','US.SMH');await select('数据周期','1小时');
  await page.waitForFunction(()=>document.querySelector('.st-key-answer-chart .js-plotly-plot')?.data?.[0]?.name==='1H');
  for(const [width,height,name,cols,rows] of [[2560,1440,'landscape',5,3],[1440,2560,'portrait',3,5]]){
    await page.setViewportSize({width,height});
    await page.locator('[data-testid=stMain]').evaluate(e=>e.scrollTop=0);
    await page.waitForTimeout(350);
    const state=await page.evaluate(()=>{
      const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
      const positions=[...document.querySelectorAll('.dash-candidate')].map(e=>({x:Math.round(e.getBoundingClientRect().x),y:Math.round(e.getBoundingClientRect().y)}));
      return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,scale:visualViewport.scale,zoom:getComputedStyle(document.documentElement).zoom,
        chart:rect('.st-key-answer-chart'),action:rect('.st-key-answer-action'),positions,
        columns:new Set(positions.map(p=>p.x)).size,rows:new Set(positions.map(p=>p.y)).size,
        horizontalOverflow:document.documentElement.scrollWidth>innerWidth,
        exceptions:document.querySelectorAll('[data-testid=stException]').length,
        factorsFolded:![...document.querySelectorAll('details')].find(e=>e.querySelector('summary')?.textContent.includes('调整分析因子'))?.open};
    });
    check(state.dpr===1&&state.scale===1&&state.zoom==='1',name+' exact 100% scale');
    check(state.width===width&&state.height===height,name+' exact viewport');
    check(state.columns===cols&&state.rows===rows,name+' grid '+cols+'x'+rows);
    check(!state.horizontalOverflow&&state.exceptions===0,name+' no overflow or Python exceptions');
    check(state.factorsFolded,name+' factors folded');
    check(state.chart.right<=state.action.x+2&&Math.abs(state.chart.y-state.action.y)<2,name+' chart and details aligned');
    result.layouts.push(state);
    await page.screenshot({path:'output/playwright/v046/'+name+'-main.png'});
    await page.locator('.st-key-focus-grid').screenshot({path:'output/playwright/v046/'+name+'-15-cards.png'});
  }
  return result;
}
