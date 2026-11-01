async (page) => {
 const output='output/playwright/';
 for(const other of page.context().pages())if(other!==page&&other.url().startsWith('http://127.0.0.1:8506'))await other.close();
 await page.waitForSelector('.st-key-decision');
 const results=[];
 for(const [name,width,height] of [['landscape',2560,1440],['portrait',1440,2560]]){
  await page.setViewportSize({width,height});
  await page.waitForTimeout(500);
  const result=await page.evaluate(()=>{
   const rect=k=>document.querySelector('.st-key-'+k).getBoundingClientRect().toJSON();
   const plot=document.querySelector('.js-plotly-plot');
   return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
    panels:Object.fromEntries(['radar','chart','decision','plans','alerts'].map(k=>[k,rect(k)])),
    exceptions:document.querySelectorAll('[data-testid=stException]').length,
    overflow:document.documentElement.scrollWidth>innerWidth,
    default1H:document.querySelector('.st-key-chart input[value="1"]')?.checked,
    locked:!!document.querySelector('input[aria-label^="实时ICT"][disabled]:not(:checked)'),
    decision:document.querySelector('.st-key-decision').innerText,
    historicalLayers:plot?.data?.filter(t=>t.name?.includes('历史')).map(t=>({name:t.name,x:t.x,y:t.y}))||[]};
  });
  const p=result.panels;
  if(result.width!==width||result.height!==height||result.exceptions||result.overflow||!result.default1H||!result.locked||!result.historicalLayers.length)throw Error(JSON.stringify(result));
  if(!(p.chart.x<p.decision.x&&Math.abs(p.chart.y-p.decision.y)<2))throw Error('图表与决策未并排');
  if(name==='portrait'&&!(p.radar.bottom<=p.chart.top))throw Error('候选未优先');
  if(!result.decision.includes('独立FVG不推进完整链'))throw Error('独立FVG边界缺失');
  await page.screenshot({path:output+'v04-'+name+'.png',fullPage:true});
  results.push({name,...result});
 }
 const second=await page.context().newPage();await second.goto('http://127.0.0.1:8506');
 await second.waitForSelector('.st-key-decision');
 for(const [i,p] of [page,second].entries()){
  const auto=p.getByRole('checkbox',{name:'自动刷新行情（编辑备注时请关闭）'});
  if(!await auto.isVisible())await p.getByText('设置与数据诊断',{exact:true}).click();
  if(!await auto.isChecked())await p.getByText('自动刷新行情（编辑备注时请关闭）',{exact:true}).click();
  await p.getByText('备注与人工计划编辑（行情自动刷新时保留输入）',{exact:true}).click();
  await p.getByRole('textbox',{name:'人工备注',exact:true}).fill('v04未提交备注窗口'+i);
 }
 return results;
}
