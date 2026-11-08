async (page)=>{
  const out='C:/Users/cbcbe/Documents/ChatGPT/ict_trade_assistant/output/playwright/v0441-';
  const layouts=[];
  for(const [width,height,name] of [[2560,1440,'landscape'],[1440,2560,'portrait']]){
    await page.setViewportSize({width,height});
    await page.waitForTimeout(700);
    await page.waitForFunction(()=>{const p=document.querySelector('.st-key-answer-chart .js-plotly-plot');return p&&Math.abs(p._fullLayout.width-p.getBoundingClientRect().width)<2;});
    await page.locator('main').evaluate(el=>el.scrollTop=0);
    const state=await page.evaluate(()=>{const p=document.querySelector('.st-key-answer-chart .js-plotly-plot'),c=document.querySelector('.st-key-answer-chart'),a=document.querySelector('.st-key-answer-action'),box=e=>e.getBoundingClientRect().toJSON();return{width:innerWidth,height:innerHeight,scale:visualViewport.scale,chart:box(c),action:box(a),plot:box(p),plot_layout_width:p._fullLayout.width,main_overflow:document.querySelector('main').scrollWidth>document.querySelector('main').clientWidth+1,axis_ticks:[...p.querySelectorAll('.ytick')].map(e=>({text:e.textContent,box:box(e)})),ema:p.data.filter(t=>t.meta?.kind==='historical_ema').map(t=>({name:t.name,last:t.y.at(-1)}))};});
    if(state.main_overflow||state.chart.right>state.action.left+1||state.action.bottom>height||state.chart.bottom>height||state.scale!==1)throw Error('Layout failure '+name);
    if(!state.axis_ticks.length||state.axis_ticks.some(t=>t.box.right>state.chart.right))throw Error('Chart price axis clipped '+name);
    await page.screenshot({path:out+name+'-ema-compare.png',animations:'disabled'});
    const panel=page.locator('details').filter({has:page.locator('summary').filter({hasText:'调整分析因子 · v0.4.4.1'})});
    await panel.locator(':scope > summary').click();await page.waitForTimeout(500);
    const link=page.getByRole('link',{name:'查看同步更新的主图',exact:true});state.chart_link=await link.evaluate(e=>({href:e.getAttribute('href'),target:e.getAttribute('target')}));
    await panel.screenshot({path:out+name+'-factors.png',animations:'disabled'});
    await panel.locator(':scope > summary').click();await page.waitForTimeout(400);layouts.push(state);
  }
  return layouts;
}
