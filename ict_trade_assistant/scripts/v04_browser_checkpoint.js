async (page) => {
 const pages=page.context().pages().filter(p=>p.url().startsWith('http://127.0.0.1:8506'));
 const results=[];
 for(const [i,p] of pages.entries()){
  const row=await p.evaluate(()=>({at:new Date().toISOString(),exceptions:document.querySelectorAll('[data-testid=stException]').length,
   panels:['radar','chart','decision','plans','alerts'].every(k=>!!document.querySelector('.st-key-'+k)),
   note:document.querySelector('textarea[aria-label="人工备注"]')?.value,
   auto:document.querySelector('input[aria-label="自动刷新行情（编辑备注时请关闭）"]')?.checked,
   locked:!!document.querySelector('input[aria-label^="实时ICT"][disabled]:not(:checked)'),
   stage:document.querySelector('.st-key-decision')?.innerText.match(/当前阶段：[^\n]+/)?.[0]}));
  if(row.exceptions||!row.panels||!row.auto||!row.locked||row.note!=='v04未提交备注窗口'+i)throw Error(JSON.stringify(row));
  results.push(row);
 }
 if(results.length!==2)throw Error('需要两个独立窗口');
 return results;
}
