async (page) => {
  const result={url:page.url(),checks:[],ema:[],layouts:[]};
  const out='C:/Users/cbcbe/Documents/ChatGPT/ict_trade_assistant/output/playwright/v0441-';
  const check=(ok,message)=>{if(!ok)throw Error(message);result.checks.push(message);};
  const panel=()=>page.locator('details').filter({has:page.locator('summary').filter({hasText:'调整分析因子 · v0.4.4.1'})});
  const idle=async()=>{await page.waitForTimeout(300);await page.getByRole('button',{name:'Stop',exact:true}).waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelectorAll('input[aria-label="EMA短期周期"]').length<=1&&document.querySelectorAll('input[aria-label="ATR计算周期"]').length<=1);check(await page.locator('[data-testid=stException]').count()===0,'无页面Python异常');};
  const select=async(label,value)=>{
    const input=page.getByRole('combobox',{name:label,exact:true});
    if(await input.inputValue()===value)return;
    await page.keyboard.press('Escape');await input.evaluate(el=>el.scrollIntoView({block:'center'}));
    await input.locator('..').getByRole('button',{name:'Open',exact:true}).click();
    await page.getByRole('option',{name:value,exact:true}).click();await idle();
  };
  const open=async()=>{
    if(!await panel().getByRole('slider',{name:/EMA短期周期/}).isVisible())await panel().locator(':scope > summary').click();
    await page.waitForFunction(()=>[...document.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent.includes('调整分析因子'))?.getBoundingClientRect().height>1000);
  };
  const close=async()=>{
    if(await panel().getByRole('slider',{name:/EMA短期周期/}).isVisible())await panel().locator(':scope > summary').click();
    await page.waitForFunction(()=>[...document.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent.includes('调整分析因子'))?.getBoundingClientRect().height<100);
  };
  const status=()=>page.locator('.factor-active').innerText();
  const slider=label=>page.getByRole('slider',{name:new RegExp(label)});
  const values=async()=>{await idle();const labels=['EMA短期周期','EMA长期周期','ATR计算周期','横盘EMA距离阈值','候选关键价距离'];return Promise.all(labels.map(async label=>Number(await slider(label).inputValue())));};
  const table=()=>panel().locator('table').evaluateAll(tables=>tables.map(t=>Object.fromEntries([...t.querySelectorAll('tr')].slice(1).map(tr=>[...tr.querySelectorAll('th,td')].map(c=>c.textContent.trim())).map(r=>[r[0],r.slice(1)]))));
  const traces=()=>page.locator('.st-key-answer-chart .js-plotly-plot').evaluate(el=>el.data.map(t=>({name:t.name,type:t.type,x:t.x,y:t.y,line:t.line,opacity:t.opacity,meta:t.meta})));
  const eq=async()=>{
    const data=await traces(),tables=await table(),params=await values();
    for(const [basis,col] of [['baseline',0],['experiment',1]])for(const [span,field] of [['short','短期EMA'],['long','长期EMA']]){
      const name=(basis==='baseline'?'原始':'实验')+'EMA'+(span==='short'?(basis==='baseline'?20:params[0]):(basis==='baseline'?50:params[1]));
      const t=data.find(t=>t.meta?.basis===basis&&t.name===name);
      if(t)check(Math.abs(t.y.at(-1)-Number(tables[1][field][col]))<1e-6,basis+' '+field+'图表末值等于比较表');
    }
    return {traces:data.filter(t=>t.meta?.kind==='historical_ema').map(t=>({name:t.name,last:t.y.at(-1),count:t.y.length,dash:t.line.dash,opacity:t.opacity})),tables};
  };
  const defaults=async()=>{await page.getByRole('button',{name:'恢复默认',exact:true}).click();await page.getByText('当前使用默认参数，与Baseline一致。',{exact:true}).waitFor();await idle();check((await status()).includes('Baseline（原始参数）'),'恢复默认显示真正生效Baseline');check(JSON.stringify(await values())==='[20,50,14,0.5,0.25]','五个滑块恢复默认');};
  const symbol=async code=>{await select('独立窗口观察标的','US.'+code);await page.getByRole('region',{name:code+' 现在怎么看',exact:true}).waitFor();await page.getByRole('region',{name:code+' 现在该怎么做',exact:true}).waitFor();await open();await idle();};
  try {
  check(new URL(page.url()).port==='8521','使用真实8521隔离环境');
  await page.reload();await page.getByText('重点观察的5只证券（固定顺序）',{exact:true}).waitFor();await open();await defaults();
  check((await status()).includes('Baseline'),'初始参数状态Baseline');
  const legacy='8506验收_EMA5_20261107';
  await select('选择准备载入的组合',legacy);
  check((await status()).includes('Baseline')&&(await values())[0]===20,'选择准备载入的旧组合不改变生效参数');
  await page.getByRole('button',{name:'载入组合',exact:true}).click();await page.getByText('已载入：'+legacy+'（版本 v0.4.4）。',{exact:true}).waitFor();
  check((await status()).includes(legacy)&&(await values())[0]===5,'旧v0.4.4组合可载入且名称与实际值一致');
  await defaults();await symbol('SPY');await select('指标图层','对比原始EMA与实验EMA');
  const original=await eq();check(original.traces.length===4,'原始与实验四条EMA同图对比');
  let ts=await traces();check(JSON.stringify(ts[1].y)===JSON.stringify(ts[3].y)&&JSON.stringify(ts[2].y)===JSON.stringify(ts[4].y),'默认参数原始与实验曲线完全重合');
  const t0=Date.now();await slider('EMA短期周期').focus();await slider('EMA短期周期').press('Home');
  await page.waitForFunction(()=>document.querySelector('.st-key-answer-chart .js-plotly-plot')?.data.some(t=>t.name==='实验EMA5'));
  check((await status()).includes('自定义参数（未保存）'),'改动EMA立即显示未保存');
  const changed=await eq();result.ema.push({symbol:'SPY',original,changed,rerender_ms:Date.now()-t0});
  check(changed.traces.find(t=>t.name==='实验EMA5').last!==original.traces.find(t=>t.name==='实验EMA20').last,'EMA20改5实际图线数值改变');
  check(changed.traces.filter(t=>t.name.startsWith('原始')).every(t=>t.dash==='dash'&&t.opacity===0.4),'原始EMA半透明虚线');
  check(changed.traces.filter(t=>t.name.startsWith('实验')).every(t=>t.dash==='solid'&&t.opacity===1),'实验EMA醒目实线');
  await close();await page.locator('main').evaluate(el=>el.scrollTop=0);await page.screenshot({path:out+'ema-compare-landscape.png',animations:'disabled'});
  await open();const profile='v0441验收_EMA5';await page.getByRole('textbox',{name:'实验组合名称',exact:true}).fill(profile);
  await page.getByRole('button',{name:'保存组合',exact:true}).click();await page.getByText('保存成功：'+profile+'（版本 v0.4.4.1）。刷新后仍可载入。',{exact:true}).waitFor();
  check((await status()).includes(profile),'保存成功显示名称和v0.4.4.1版本');
  await panel().screenshot({path:out+'active-saved.png',animations:'disabled'});
  await slider('ATR计算周期').focus();await slider('ATR计算周期').press('Home');await page.getByText('未保存修改',{exact:true}).waitFor();
  check((await status()).includes('未保存'),'修改ATR也立即成为未保存状态');
  await page.getByRole('button',{name:'载入组合',exact:true}).click();await page.getByText('已载入：'+profile+'（版本 v0.4.4.1）。',{exact:true}).waitFor();
  check(JSON.stringify(await values())==='[5,50,14,0.5,0.25]','重新载入五个滑块与保存值完全一致');
  await symbol('QQQ');check((await values())[0]===5&&(await status()).includes(profile),'切换证券不更换生效参数');
  await defaults();const qBefore=(await table())[0]['候选距离资格'][1];await slider('候选关键价距离').focus();await slider('候选关键价距离').press('Home');
  await page.waitForFunction(()=>document.querySelector('main').innerText.includes('超出观察距离'));
  const qAfter=(await table())[0]['候选距离资格'][1];check(qBefore==='进入历史观察'&&qAfter==='超出观察距离','QQQ候选距离0.25到0.05改变历史资格');
  check((await page.locator('.dash-summary').innerText()).includes('不能 · 暂无合格买卖点'),'QQQ实验不授予实时交易许可');result.qqq={before:qBefore,after:qAfter};
  await symbol('SMH');check((await values())[4]===0.05,'观察证券切换保留候选参数');await defaults();
  const smh=await eq();check(smh.traces.length===4,'SMH合格日K显示历史EMA');result.ema.push({symbol:'SMH',...smh});
  await select('数据周期','1小时');await page.getByText('历史资料不足，暂时无法画出可靠的指标',{exact:true}).waitFor();
  check(await page.locator('.st-key-answer-chart .js-plotly-plot').count()===0,'SMH缺分钟资料无1H图线及资格');
  await select('数据周期','日K');await symbol('SPY');await select('选择准备载入的组合',profile);await page.getByRole('button',{name:'载入组合',exact:true}).click();await idle();
  await select('数据模式','历史回放');await select('历史交易日期（纽约）','2026-10-28');
  await page.waitForFunction(()=>document.querySelector('main').innerText.includes('历史回放 · 富途原生日K归档 · 日K · 数据截至 2026-10-28'));
  check((await values())[0]===5&&(await status()).includes(profile),'日期切换不改变生效组合');
  ts=await traces();check(ts.every(t=>[...t.x].every(x=>String(x).slice(0,10)<='2026-10-28')),'历史回放K线和全部EMA均不画未来');result.replay={date:'2026-10-28',traces:ts.map(t=>({name:t.name,last_date:t.x.at(-1),bars:t.x.length}))};await eq();
  await select('数据模式','最新已保存数据');await page.reload();await page.getByText('重点观察的5只证券（固定顺序）',{exact:true}).waitFor();await open();
  check((await status()).includes('Baseline'),'刷新后生效状态准确显示初始Baseline');await select('选择准备载入的组合',profile);await page.getByRole('button',{name:'载入组合',exact:true}).click();await page.getByText('已载入：'+profile+'（版本 v0.4.4.1）。',{exact:true}).waitFor();
  check(JSON.stringify(await values())==='[5,50,14,0.5,0.25]'&&(await status()).includes(profile),'刷新后保存组合仍在并精确载入');
  await page.getByRole('textbox',{name:'实验组合名称',exact:true}).fill('Baseline');await page.getByRole('button',{name:'保存组合',exact:true}).click();await page.getByText('请使用1–60字的实验名称；Baseline不可覆盖。',{exact:true}).waitFor();check(true,'Baseline不可覆盖');await defaults();
  await select('指标图层','对比原始EMA与实验EMA');ts=await traces();check(JSON.stringify(ts[1].y)===JSON.stringify(ts[3].y)&&JSON.stringify(ts[2].y)===JSON.stringify(ts[4].y),'恢复默认图表与Baseline完全重合');
  await select('指标图层','不显示指标');await page.getByText('叠加用户计划价格（待人工复核）',{exact:true}).click();await idle();ts=await traces();check(ts.some(t=>t.name.startsWith('人工计划'))&&!ts.some(t=>t.meta?.kind==='historical_ema'),'人工计划线可独立于EMA开关');
  await page.getByText('叠加用户计划价格（待人工复核）',{exact:true}).click();await select('指标图层','显示当前实验EMA');
  await page.getByRole('button',{name:'查看图表 · QQQ',exact:true}).click();await page.getByRole('region',{name:'QQQ 现在该怎么做',exact:true}).waitFor();check(true,'固定观察卡点击后图表与行动卡同步');
  await symbol('SPY');await defaults();await close();
  const cards=await page.locator('.dash-candidate').allInnerTexts();check(cards.length===5&&cards[4].includes('2026-11-02')&&cards[0].includes('2026-10-29'),'五张固定观察卡逐证券显示不同数据日期');result.cards=cards;
  await page.getByText('重点观察的5只证券（固定顺序）',{exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:out+'fixed-watch-cards.png',animations:'disabled'});
  if(await page.getByRole('button',{name:'Expand sidebar',exact:true}).isVisible())await page.getByRole('button',{name:'Expand sidebar',exact:true}).click();
  for(const [width,height,label] of [[2560,1440,'landscape'],[1440,2560,'portrait']]){
    await page.setViewportSize({width,height});await page.locator('main').evaluate(el=>el.scrollTop=0);
    const geometry=await page.evaluate(()=>{const box=s=>document.querySelector(s).getBoundingClientRect().toJSON(),main=document.querySelector('main');return{width:innerWidth,height:innerHeight,scale:visualViewport.scale,chart:box('.st-key-answer-chart'),action:box('.st-key-answer-action'),main_overflow:main.scrollWidth>main.clientWidth+1,document_overflow:document.documentElement.scrollWidth>innerWidth};});
    check(geometry.width===width&&geometry.height===height&&geometry.scale===1,label+'100%缩放指定尺寸');check(geometry.chart.width>0&&geometry.action.width>0&&geometry.chart.right<=geometry.action.left+1&&geometry.chart.bottom<height&&geometry.action.bottom<height,label+'首屏主图及行动卡完整且无重叠');check(!geometry.main_overflow&&!geometry.document_overflow,label+'主区无横向溢出');
    await page.screenshot({path:out+label+'-main.png',animations:'disabled'});await open();await panel().screenshot({path:out+label+'-factors.png',animations:'disabled'});check((await panel().boundingBox()).height>1000,label+'展开因子区控件可操作');await close();result.layouts.push(geometry);
  }
  await page.setViewportSize({width:2560,height:1440});await open();await select('指标图层','对比原始EMA与实验EMA');await slider('EMA短期周期').focus();await slider('EMA短期周期').press('Home');await page.getByText('未保存修改',{exact:true}).waitFor();await panel().screenshot({path:out+'active-unsaved.png',animations:'disabled'});await close();await page.locator('main').evaluate(el=>el.scrollTop=0);await page.screenshot({path:out+'final-ema-compare.png',animations:'disabled'});
  result.storage={profile,version:'v0.4.4.1',reloaded:true,baseline_locked:true};await idle();
  } catch(error) {result.error=String(error);}
  return result;
}
