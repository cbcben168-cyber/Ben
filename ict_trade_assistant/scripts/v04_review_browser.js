async (page) => {
 await page.waitForSelector('.st-key-decision');
 const results=[];
 for(const [name,width,height] of [['横屏',2560,1440],['竖屏',1440,2560]]){
  await page.setViewportSize({width,height});
  const buttons=page.locator('.st-key-radar button').filter({hasText:/^\d+ ·/});
  const count=await buttons.count();if(count!==4)throw Error('四证券数量异常');
  const rows=[];
  for(let i=0;i<count;i++){
   const text=await buttons.nth(i).innerText();
   const symbol=text.split('·')[1].trim();
   await buttons.nth(i).click();
   await page.waitForTimeout(500);
   const row=await page.evaluate((symbol)=>{
    const radar=document.querySelector('.st-key-radar').innerText;
    const card=document.querySelector('.st-key-decision').innerText;
    const plot=document.querySelector('.js-plotly-plot');
    const chart=document.querySelector('.st-key-chart').getBoundingClientRect();
    const decision=document.querySelector('.st-key-decision').getBoundingClientRect();
    const range=card.match(/下一观察区域：\(([0-9.]+), ([0-9.]+)\)/);
    const rangeMatches=!!range&&range.slice(1).every(v=>plot.layout.shapes.some(s=>Math.abs(s.y0-Number(v))<1e-8));
    return {symbol,card,radar,rangeMatches,exceptions:document.querySelectorAll('[data-testid=stException]').length,
     overflow:document.documentElement.scrollWidth>innerWidth,
     aligned:chart.x<decision.x&&Math.abs(chart.y-decision.y)<2,
     layers:plot.data.filter(t=>t.name?.includes('历史')).map(t=>({name:t.name,x:t.x,y:t.y})),
     locked:!!document.querySelector('input[aria-label^="实时ICT"][disabled]:not(:checked)')};
   },symbol);
   if(!row.card.startsWith(symbol)||row.exceptions||row.overflow||!row.aligned||!row.locked||!row.layers.length||!row.rangeMatches)throw Error(JSON.stringify(row));
   const stage=row.card.match(/当前阶段：[^\n]+/)[0];
   if(!row.radar.includes(stage))throw Error('候选与决策阶段不同步');
   if(!row.card.includes('独立FVG不推进完整链'))throw Error('未关联边界缺失');
   rows.push({candidate:text,stage,...row});
  }
  await page.screenshot({path:'output/playwright/v04-review-'+width+'.png',fullPage:true});
  results.push({name,width,height,rows});
 }
 return results;
}
