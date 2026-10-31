async (page) => {
 const measure=()=>page.evaluate(()=>{
  const r=k=>document.querySelector('.st-key-'+k).getBoundingClientRect().toJSON();
  return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,chart:r('chart'),decision:r('decision'),alerts:r('alerts'),plans:r('plans'),radar:r('radar'),sidebar:document.querySelector('[data-testid=stSidebar]').getBoundingClientRect().toJSON(),gap:r('alerts').top-r('decision').bottom,overflow:document.documentElement.scrollWidth>innerWidth,exceptions:document.querySelectorAll('[data-testid=stException]').length};
 });
 await page.setViewportSize({width:1440,height:2560});await page.locator('.js-plotly-plot').waitFor();
 const collapsed=await measure();
 if(Math.abs(collapsed.radar.width-collapsed.chart.width-collapsed.decision.width-16)>2)throw new Error('候选区未占满顶部');
 if(Math.abs(collapsed.gap-16)>1)throw new Error('右栏卡片间距不是16px');
 if(Math.abs(collapsed.alerts.x-collapsed.decision.x)>1)throw new Error('两张右卡不在同列');
 if(Math.abs(collapsed.plans.top-collapsed.chart.bottom-16)>1)throw new Error('左列没有自然堆叠');
 await page.screenshot({path:'data/right_gap_fix/portrait_collapsed.png'});
 await page.getByText('SOP 详细检查与评估依据',{exact:true}).click();await page.waitForTimeout(300);
 const expandedSOP=await measure();
 if(Math.abs(expandedSOP.gap-16)>1||expandedSOP.decision.height<=collapsed.decision.height)throw new Error('SOP展开时堆叠失败');
 await page.getByText('SOP 详细检查与评估依据',{exact:true}).click();
 await page.getByRole('button',{name:'Expand sidebar',exact:true}).click();await page.waitForTimeout(350);
 const expandedSidebar=await measure();
 await page.screenshot({path:'data/right_gap_fix/portrait_expanded.png'});
 await page.getByRole('button',{name:'Collapse sidebar',exact:true}).click();await page.waitForTimeout(350);
 await page.setViewportSize({width:2560,height:1440});await page.waitForTimeout(300);
 const landscape=await measure();
 if(!(landscape.radar.x<landscape.chart.x&&landscape.chart.x<landscape.decision.x)||Math.abs(landscape.chart.top-landscape.decision.top)>1)throw new Error('横屏三栏退化');
 await page.screenshot({path:'data/right_gap_fix/landscape.png'});
 for(const m of [collapsed,expandedSOP,expandedSidebar,landscape])if(m.overflow||m.exceptions)throw new Error('出现溢出或页面异常');
 return {collapsed,expandedSOP,expandedSidebar,landscape};
}
