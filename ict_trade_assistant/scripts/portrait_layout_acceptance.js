async (page) => {
 await page.locator('.js-plotly-plot').waitFor();
 const results=[];
 for (const [name,w,h] of [['portrait100',1440,2560],['landscape100',2560,1440],['portrait125',1152,2048],['portrait150',960,1707],['landscape125',2048,1152],['landscape150',1707,960]]) {
  await page.setViewportSize({width:w,height:h});await page.waitForTimeout(300);
  await page.evaluate(()=>document.querySelector('[data-testid=stMain]').scrollTo(0,0));
  const m=await page.evaluate(()=>{
   const rect=e=>e?e.getBoundingClientRect().toJSON():null;
   const panels=Object.fromEntries(['radar','chart','decision','plans','alerts'].map(k=>[k,rect(document.querySelector('.st-key-'+k))]));
   const main=document.querySelector('.block-container');const sidebar=document.querySelector('[data-testid=stSidebar]');
   const important=[...document.querySelectorAll('.st-key-decision p')].filter(e=>/下一触发|候选入场|失效价|目标区|风险回报/.test(e.textContent)&&e.innerText.trim()&&e.getBoundingClientRect().height>0).map(e=>({text:e.innerText,width:e.clientWidth,scrollWidth:e.scrollWidth,font:getComputedStyle(e).fontSize,rect:rect(e)}));
   return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,main:rect(main),sidebar:rect(sidebar),sidebarCollapsed:sidebar?.getAttribute('data-collapsed'),panels,overflow:document.documentElement.scrollWidth>innerWidth,important,visibleModules:Object.entries(panels).filter(([k,r])=>r.top<innerHeight&&r.bottom>0).map(([k])=>k),plotWidth:document.querySelector('.js-plotly-plot')?._fullLayout?._size?.w,legend:document.querySelector('.js-plotly-plot')?._fullLayout?.showlegend,exceptions:document.querySelectorAll('[data-testid=stException]').length};
  });
  if(m.overflow||m.exceptions)throw new Error(name+' 溢出或页面异常');
  if(m.important.length<5||m.important.some(x=>x.scrollWidth>x.width+2||parseFloat(x.font)<16))throw new Error(name+' 关键字段截断');
  if(name==='portrait100'){
   if(m.sidebar.width>1||m.main.width<1400)throw new Error('折叠导航仍占位');
   if(Math.abs(m.panels.chart.y-m.panels.decision.y)>2)throw new Error('竖屏未并排');
   if(m.panels.radar.bottom>m.panels.chart.top)throw new Error('竖屏不是候选优先');
   const ratio=m.panels.chart.width/m.panels.decision.width;
   if(ratio<1.45||ratio>1.55)throw new Error('不是约60/40');
   if(!(m.plotWidth>=700))throw new Error('绘图区过窄');
  }
  if(name==='landscape100'&&!(m.panels.radar.x<m.panels.chart.x&&m.panels.chart.x<m.panels.decision.x&&Math.abs(m.panels.chart.y-m.panels.decision.y)<2))throw new Error('横屏三栏退化');
  await page.screenshot({path:'data/portrait_fix/after_'+name+'.png'});
  results.push({name,...m});
 }
 return results;
}
