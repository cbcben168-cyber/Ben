async (page) => {
 await page.waitForSelector('.st-key-decision',{timeout:30000});
 const results=[];
 for(const [name,width,height] of [['landscape',2560,1440],['portrait',1440,2560]]){
  await page.setViewportSize({width,height});
  await page.waitForTimeout(500);
  const result=await page.evaluate(()=>{
   const rect=k=>document.querySelector('.st-key-'+k)?.getBoundingClientRect().toJSON();
   const panel=Object.fromEntries(['radar','chart','decision','plans','alerts'].map(k=>[k,rect(k)]));
   return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,panels:panel,
    exceptions:document.querySelectorAll('[data-testid=stException]').length,
    overflow:document.documentElement.scrollWidth>innerWidth,
    defaultPeriod:document.querySelector('.st-key-chart input[type=radio][value="1"]')?.checked,
    liveSwitch:[...document.querySelectorAll('input[type=checkbox]')].filter(e=>e.getAttribute('aria-label')?.includes('实时ICT')).map(e=>({checked:e.checked,disabled:e.disabled})),
    decision:document.querySelector('.st-key-decision')?.innerText,
    historicalLayers:document.querySelector('.js-plotly-plot')?.data?.filter(t=>t.name?.includes('历史')).map(t=>t.name)||[]};
  });
  if(result.width!==width||result.height!==height||result.exceptions||result.overflow)throw new Error(JSON.stringify(result));
  if(!result.defaultPeriod)throw new Error('默认图表不是1小时');
  if(result.liveSwitch.length!==1||result.liveSwitch[0].checked||!result.liveSwitch[0].disabled)throw new Error('实时ICT开关未安全关闭');
  if(!result.decision.includes('历史观察')||!result.decision.includes('实时入场建议'))throw new Error('历史边界提示缺失');
  const p=result.panels;
  if(name==='landscape'&&!(p.radar.x<p.chart.x&&p.chart.x<p.decision.x&&Math.abs(p.chart.y-p.decision.y)<2))throw new Error('横屏三栏未保留');
  if(name==='portrait'&&!(p.radar.bottom<=p.chart.top&&Math.abs(p.chart.y-p.decision.y)<2))throw new Error('竖屏候选优先并排未保留');
  await page.screenshot({path:'data/v03_acceptance/'+name+'.png'});
  results.push({name,...result});
 }
 return results;
}
