async (page) => {
 const began=Date.now();let previous=began;const checks=[];
 while(true){
  if(Date.now()-previous>30000)throw Error('采样间隔超过30秒；宿主暂停或时钟跳变，不能计作连续稳定性');
  previous=Date.now();
  const pages=page.context().pages().filter(p=>p.url().startsWith('http://127.0.0.1:8506'));
  const windows=[];
  for(const [i,p] of pages.entries()){
   const row=await p.evaluate(()=>({at:new Date().toISOString(),exceptions:document.querySelectorAll('[data-testid=stException]').length,
    panels:['radar','chart','decision','plans','alerts'].every(k=>!!document.querySelector('.st-key-'+k)),
    note:document.querySelector('textarea[aria-label="人工备注"]')?.value,
    auto:document.querySelector('input[aria-label="自动刷新行情（编辑备注时请关闭）"]')?.checked,
    locked:!!document.querySelector('input[aria-label^="实时ICT"][disabled]:not(:checked)'),
    stage:document.querySelector('.st-key-decision')?.innerText.match(/当前阶段：[^\n]+/)?.[0]}));
   if(row.exceptions||!row.panels||!row.auto||!row.locked||row.note!=='v04未提交备注窗口'+i)throw Error(JSON.stringify(row));
   windows.push(row);
  }
  if(windows.length!==2)throw Error('需要两个独立窗口');
  const response=await page.request.get('http://127.0.0.1:8506/_stcore/health');
  if(!response.ok())throw Error('隔离服务健康检查失败');
  checks.push({elapsed:(Date.now()-began)/1000,windows,health:await response.text()});
  if(Date.now()-began>=180000)break;
  await page.waitForTimeout(10000);
 }
 return {seconds:(Date.now()-began)/1000,passed:true,checks,boundary:'离线历史快照；不证明真实RTH或数小时稳定性'};
}
