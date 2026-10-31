async (page) => {
 const pages=page.context().pages().filter(p=>p.url().startsWith('http://127.0.0.1:8501'));
 const rows=[];
 for(let i=0;i<pages.length;i++){
  const p=pages[i];
  await p.waitForSelector('.st-key-decision',{timeout:30000});
  const row=await p.evaluate(()=>({at:new Date().toISOString(),url:location.href,
   exceptions:document.querySelectorAll('[data-testid=stException]').length,
   panels:['radar','chart','decision','plans','alerts'].map(k=>({name:k,present:!!document.querySelector('.st-key-'+k)})),
   title:document.querySelector('.st-key-decision h3')?.textContent,
   auto:document.querySelector('input[aria-label="自动刷新行情（编辑备注时请关闭）"]')?.checked,
   notes:[...document.querySelectorAll('textarea')].map(e=>({value:e.value,label:e.getAttribute('aria-label')})),
   text:document.querySelector('.st-key-decision')?.innerText}));
  rows.push({window:i,...row});
 }
 if(rows.length!==2||rows.some(r=>r.exceptions||r.panels.some(p=>!p.present)))throw new Error(JSON.stringify(rows));
 for(const r of rows){
  if(!r.auto||!r.title.startsWith(r.window===0?'SPY':'QQQ')||!r.notes.some(n=>n.label==='人工备注'&&n.value==='稳定性验收未提交输入窗口'+r.window))throw new Error('跨窗口选择或未提交备注未保持 '+JSON.stringify(r));
 }
 return rows;
}
