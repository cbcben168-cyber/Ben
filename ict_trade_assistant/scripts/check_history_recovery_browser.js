async (page) => {
  const result={url:page.url(),checks:[],symbols:[],layouts:[]};
  const out='output/playwright/history-recovery-';
  const check=(ok,message)=>{if(!ok)throw Error(message);result.checks.push(message);};
  const panel=()=>page.locator('details').filter({has:page.locator('summary').filter({hasText:'调整分析因子 · v0.4.4.1'})});
  const idle=async()=>{
    await page.waitForTimeout(300);
    await page.getByRole('button',{name:'Stop',exact:true}).waitFor({state:'hidden',timeout:60000});
    check(await page.locator('[data-testid=stException]').count()===0,'无页面Python异常');
  };
  const open=async()=>{
    await page.keyboard.press('Escape');
    for(let attempt=0;attempt<3;attempt++){
      if(await panel().evaluate(el=>el.open)&&await panel().getByRole('slider',{name:/EMA短期周期/}).isVisible())return;
      if(!await panel().evaluate(el=>el.open))await panel().locator(':scope > summary').click();
      await page.waitForTimeout(400);
    }
    await panel().getByRole('slider',{name:/EMA短期周期/}).waitFor({state:'visible',timeout:10000});
  };
  const select=async(label,value)=>{
    const input=page.getByRole('combobox',{name:label,exact:true});
    if(await input.inputValue()===value)return;
    await page.keyboard.press('Escape');await input.scrollIntoViewIfNeeded();
    await input.locator('..').getByRole('button',{name:'Open',exact:true}).click();
    if(await page.getByRole('option',{name:value,exact:true}).count()===0)await input.fill(value);
    await page.getByRole('option',{name:value,exact:true}).click();await idle();
  };
  const source=async value=>{await open();await panel().getByText(value,{exact:true}).click();await idle();};
  const traces=async()=>{
    const handle=await page.waitForFunction(()=>{
      const data=document.querySelector('.st-key-answer-chart .js-plotly-plot')?._fullData;
      return data?.length ? data.map(t=>({name:t.name,type:t.type,x:Array.from(t.x||[]),y:Array.from(t.y||[]),close:Array.from(t.close||[]),meta:t.meta})) : false;
    });
    return handle.jsonValue();
  };
  const top=()=>page.locator('[data-testid=stMain]').evaluate(el=>el.scrollTop=0);
  const symbol=async code=>{
    await select('独立窗口观察标的','US.'+code);
    await page.getByRole('region',{name:code+' 现在怎么看',exact:true}).waitFor();await open();await idle();
  };
  const table=()=>panel().locator('table').evaluateAll(tables=>tables.map(t=>Object.fromEntries([...t.querySelectorAll('tr')].slice(1).map(tr=>[...tr.querySelectorAll('th,td')].map(c=>c.textContent.trim())).map(r=>[r[0],r.slice(1)]))));
  const eq=async()=>{
    const ts=await traces(),tables=await table();
    for(const t of ts.filter(t=>t.meta?.kind==='historical_ema')){
      const label=t.name.includes('EMA50')?'长期EMA':t.name.includes('EMA35')?'长期EMA':'短期EMA';
      const col=t.meta.basis==='baseline'?0:1;
      check(Math.abs(t.y.at(-1)-Number(tables[1][label][col]))<1e-6,t.name+'曲线末值等于比较表');
    }
    return ts;
  };
  const layout=async(width,height,name)=>{
    await page.setViewportSize({width,height});
    if(await page.getByRole('button',{name:'Expand sidebar',exact:true}).isVisible())await page.getByRole('button',{name:'Expand sidebar',exact:true}).click();
    if(await panel().evaluate(el=>el.open))await panel().locator(':scope > summary').click();
    await panel().getByRole('slider',{name:/EMA短期周期/}).waitFor({state:'hidden'});
    await top();await page.waitForTimeout(350);
    const state=await page.evaluate(()=>{
      const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom,right:r.right};};
      return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,scale:visualViewport.scale,cssZoom:getComputedStyle(document.documentElement).zoom,
        chart:rect('.st-key-answer-chart'),action:rect('.st-key-answer-action'),summary:rect('.dash-summary'),cards:document.querySelectorAll('.dash-candidate').length,
        horizontalOverflow:document.documentElement.scrollWidth>innerWidth};
    });
    check(state.width===width&&state.height===height&&state.dpr===1&&state.scale===1&&state.cssZoom==='1','100%缩放 '+width+'×'+height);
    check(Math.abs(state.chart.y-state.action.y)<2&&state.chart.right<=state.action.x+2,'主图与行动卡并排');
    check(state.chart.bottom<height&&state.action.bottom<height&&!state.horizontalOverflow&&state.cards===5,'主图行动卡与固定五只观察正常');
    result.layouts.push(state);
    await page.screenshot({path:out+name+'.png'});
  };
  try {
    check(new URL(page.url()).port==='8522','仅操作隔离8522预览');await idle();await open();
    check(await panel().getByRole('radio',{name:'最新Futu历史日K',exact:true}).isChecked(),'默认使用独立Futu历史日K');
    await select('数据模式','最新已保存数据');await select('数据周期','日K');
    await page.getByRole('button',{name:'恢复默认',exact:true}).click();await idle();
    const symbols=['SPY','QQQ','IWM','SOXX','SMH','VOO','IVV','VTI','VEA','VUG','IEFA','VTV','SPYM','BND','VXUS','IEMG','VGT','GLD','AGG','IWF','IJH','VWO','XLK'];
    for(const code of symbols){
      await symbol(code);const ts=await eq(),candles=ts.find(t=>t.type==='candlestick');
      check(candles.x.length===90&&candles.x.at(-1).startsWith('2026-11-06'),'真实页面 '+code+' 90根截至11月6日');
      check(ts.filter(t=>t.meta?.kind==='historical_ema').every(t=>t.y.length===41),'真实页面 '+code+' EMA41点');
      check(!ts.some(t=>t.name.startsWith('人工计划')),'前复权图无未核实人工计划叠加');
      result.symbols.push({symbol:code,candles:candles.x.length,last:candles.x.at(-1),ema:ts.filter(t=>t.meta?.kind==='historical_ema').map(t=>({name:t.name,last:t.y.at(-1),points:t.y.length}))});
    }
    await symbol('SPY');
    check((await page.locator('.dash-action').innerText()).includes('暂停叠加与风险回报计算'),'行动卡阻断未知计划价格尺度');
    check((await page.locator('.dash-action').innerText()).includes('暂无可计算数据'),'无可执行风险回报');
    await layout(2560,1440,'landscape-latest-spy');
    await layout(1440,2560,'portrait-latest-spy');
    await open();await select('指标图层','对比原始EMA与实验EMA');
    await panel().getByRole('slider',{name:/EMA短期周期/}).focus();await page.keyboard.press('Home');await idle();
    await page.waitForFunction(()=>document.querySelector('.st-key-answer-chart .js-plotly-plot')?.data.some(t=>t.name==='实验EMA5'));
    const changed=await eq();check(changed.filter(t=>t.meta?.kind==='historical_ema').length===4,'基准与实验四条曲线');
    check(JSON.stringify(changed.find(t=>t.name==='原始EMA20').y)!==JSON.stringify(changed.find(t=>t.name==='实验EMA5').y),'EMA5参数实际改变计算');
    await panel().scrollIntoViewIfNeeded();await page.screenshot({path:out+'portrait-factor-comparison.png'});
    await panel().getByRole('textbox',{name:'实验组合名称',exact:true}).fill('历史恢复隔离验收_EMA5');
    await page.getByRole('button',{name:'保存组合',exact:true}).click();await idle();
    check((await page.locator('.factor-active').innerText()).includes('历史恢复隔离验收_EMA5'),'隔离实验组合保存');
    await page.getByRole('button',{name:'恢复默认',exact:true}).click();await idle();
    await select('选择准备载入的组合','历史恢复隔离验收_EMA5');await page.getByRole('button',{name:'载入组合',exact:true}).click();await idle();
    check(Number(await panel().getByRole('slider',{name:/EMA短期周期/}).inputValue())===5,'隔离组合重新载入');
    await page.getByRole('button',{name:'恢复默认',exact:true}).click();await idle();
    const restored=await eq();check(JSON.stringify(restored.find(t=>t.name==='原始EMA20').y)===JSON.stringify(restored.find(t=>t.name==='实验EMA20').y),'恢复Baseline后曲线完全重合');
    await symbol('SOXX');const soxx=(await traces()).find(t=>t.type==='candlestick');
    const index=soxx.x.findIndex(x=>x.startsWith('2026-11-04'));
    check(Math.abs(soxx.close[index]-450.41/3)<1e-6&&soxx.close[index+1]===131.9,'SOXX拆股前后图表价格一致');
    await select('数据模式','历史回放');await select('历史交易日期（纽约）','2026-11-04');
    await page.waitForFunction(()=>document.querySelector('.st-key-answer-chart .js-plotly-plot')?._fullData?.find(t=>t.type==='candlestick')?.x?.at(-1)?.startsWith('2026-11-04'));
    let replay=(await traces()).find(t=>t.type==='candlestick');
    check(replay.x.length===88&&replay.x.every(x=>x.slice(0,10)<='2026-11-04'),'SOXX回放只含所选日期已完成K线');
    await layout(2560,1440,'landscape-soxx-replay-1104');await open();
    await select('历史交易日期（纽约）','2026-08-27');
    await page.waitForFunction(()=>document.querySelector('.st-key-answer-chart .js-plotly-plot')?._fullData?.find(t=>t.type==='candlestick')?.x?.at(-1)?.startsWith('2026-08-27'));
    check(!(await traces()).some(t=>t.meta?.kind==='historical_ema'),'不足50根不画EMA');
    check((await page.locator('body').innerText()).includes('资料不足'),'不足样本明确提示');
    await select('数据模式','最新已保存数据');await select('数据周期','1小时');
    await page.locator('.st-key-answer-chart .js-plotly-plot').waitFor({state:'detached'});
    check(await page.locator('.st-key-answer-chart .js-plotly-plot').count()===0,'独立日K不产生1H图表或ICT');
    await select('数据周期','日K');await symbol('SMH');await source('原历史档案');
    await page.waitForFunction(()=>document.querySelector('.st-key-answer-chart .js-plotly-plot')?._fullData?.find(t=>t.type==='candlestick')?.x?.length===86);
    const old=(await traces()).find(t=>t.type==='candlestick');
    check(old.x.length===86&&old.x.at(-1).startsWith('2026-11-02'),'原Alpaca归档保留独立86根');
    await layout(2560,1440,'landscape-original-smh');await open();await source('最新Futu历史日K');
    await symbol('SPY');await layout(2560,1440,'landscape-final');
    result.status='PASS';result.browser=await page.context().browser().version();return result;
  } catch(error) {result.status='FAIL';result.error=String(error);await page.screenshot({path:out+'failure.png'});return result;}
}
